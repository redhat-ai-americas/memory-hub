import base64
import hashlib
import logging
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.errors import OAuthError
from src.models import AuthSession, OAuthClient, RefreshToken
from src.tokens import create_access_token, create_refresh_token

log = logging.getLogger("memoryhub-auth.routes.token")

router = APIRouter()


async def _authenticate_client(
    client_id: str, client_secret: str, session: AsyncSession
) -> OAuthClient:
    """Validate client credentials against the database."""
    result = await session.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.active == True,  # noqa: E712
        )
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise OAuthError(401, "invalid_client", "Unknown or inactive client")

    if not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash.encode()):
        raise OAuthError(401, "invalid_client", "Invalid client secret")

    return client


async def _lookup_client(client_id: str, session: AsyncSession) -> OAuthClient:
    """Look up an active client without secret validation (for public clients)."""
    result = await session.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.active == True,  # noqa: E712
        )
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise OAuthError(401, "invalid_client", "Unknown or inactive client")
    return client


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify PKCE S256: base64url(SHA256(verifier)) == challenge."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge


def _resolve_scopes(requested: str | None, client: OAuthClient) -> list[str]:
    """Resolve requested scopes against client's allowed scopes."""
    allowed = set(client.default_scopes)
    if not requested:
        return sorted(allowed)
    requested_set = set(requested.split())
    invalid = requested_set - allowed
    if invalid:
        raise OAuthError(
            400,
            "invalid_scope",
            f"Client not authorized for scopes: {' '.join(sorted(invalid))}",
        )
    return sorted(requested_set)


@router.post("/token")
async def token_endpoint(
    grant_type: str = Form(...),
    client_id: str = Form(default=None),
    client_secret: str = Form(default=None),
    scope: str = Form(default=None),
    refresh_token: str = Form(default=None),
    code: str = Form(default=None),
    redirect_uri: str = Form(default=None),
    code_verifier: str = Form(default=None),
    session: AsyncSession = Depends(get_session),
):
    """OAuth 2.1 token endpoint."""

    if grant_type == "client_credentials":
        return await _handle_client_credentials(
            client_id, client_secret, scope, session
        )
    elif grant_type == "refresh_token":
        return await _handle_refresh_token(
            client_id, client_secret, refresh_token, session
        )
    elif grant_type == "authorization_code":
        return await _handle_authorization_code(
            client_id, client_secret, code, redirect_uri, code_verifier, session
        )
    else:
        raise OAuthError(
            400,
            "unsupported_grant_type",
            f"Grant type '{grant_type}' is not supported. "
            "Supported: client_credentials, refresh_token, authorization_code",
        )


async def _handle_client_credentials(
    client_id: str | None,
    client_secret: str | None,
    scope: str | None,
    session: AsyncSession,
) -> dict:
    if not client_id or not client_secret:
        raise OAuthError(
            400, "invalid_request", "client_id and client_secret are required"
        )

    client = await _authenticate_client(client_id, client_secret, session)
    scopes = _resolve_scopes(scope, client)

    access_token = create_access_token(
        subject=client.client_id,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        scopes=scopes,
    )

    raw_refresh, refresh_hash = create_refresh_token()
    rt = RefreshToken(
        token_hash=refresh_hash,
        client_id=client.client_id,
        subject=client.client_id,
        scopes=scopes,
        tenant_id=client.tenant_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.refresh_token_ttl),
    )
    session.add(rt)
    await session.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl,
        "refresh_token": raw_refresh,
        "scope": " ".join(scopes),
    }


async def _handle_refresh_token(
    client_id: str | None,
    client_secret: str | None,
    refresh_token: str | None,
    session: AsyncSession,
) -> dict:
    if not client_id:
        raise OAuthError(400, "invalid_request", "client_id is required for refresh_token grant")
    if not refresh_token:
        raise OAuthError(400, "invalid_request", "refresh_token is required")

    # Public clients: skip secret validation, rely on refresh token binding.
    # Confidential clients: require client_secret.
    client = await _lookup_client(client_id, session)
    if not client.public:
        if not client_secret:
            raise OAuthError(
                400, "invalid_request", "client_secret is required for confidential clients"
            )
        if not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash.encode()):
            raise OAuthError(401, "invalid_client", "Invalid client secret")

    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    result = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,  # noqa: E712
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    stored_rt = result.scalar_one_or_none()
    if stored_rt is None:
        raise OAuthError(
            401, "invalid_grant", "Invalid, expired, or revoked refresh token"
        )

    # Verify the refresh token belongs to the authenticated client
    if stored_rt.client_id != client.client_id:
        raise OAuthError(401, "invalid_grant", "Refresh token does not belong to this client")

    # Revoke old token, issue new pair — single transaction
    stored_rt.revoked = True
    stored_rt.revoked_at = datetime.now(timezone.utc)

    scopes = stored_rt.scopes
    access_token = create_access_token(
        subject=stored_rt.subject,
        identity_type=client.identity_type,
        tenant_id=stored_rt.tenant_id,
        scopes=scopes,
    )

    raw_refresh_new, refresh_hash_new = create_refresh_token()
    new_rt = RefreshToken(
        token_hash=refresh_hash_new,
        client_id=client.client_id,
        subject=stored_rt.subject,
        scopes=scopes,
        tenant_id=stored_rt.tenant_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.refresh_token_ttl),
    )
    session.add(new_rt)
    await session.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl,
        "refresh_token": raw_refresh_new,
        "scope": " ".join(scopes),
    }


async def _handle_authorization_code(
    client_id: str | None,
    client_secret: str | None,
    code: str | None,
    redirect_uri: str | None,
    code_verifier: str | None,
    session: AsyncSession,
) -> dict:
    if not client_id:
        raise OAuthError(400, "invalid_request", "client_id is required")
    if not code:
        raise OAuthError(400, "invalid_request", "code is required")
    if not redirect_uri:
        raise OAuthError(400, "invalid_request", "redirect_uri is required")
    if not code_verifier:
        raise OAuthError(400, "invalid_request", "code_verifier is required")

    # Authenticate client — public clients skip secret validation
    client = await _lookup_client(client_id, session)
    if not client.public:
        if not client_secret:
            raise OAuthError(
                400, "invalid_request", "client_secret is required for confidential clients"
            )
        if not bcrypt.checkpw(client_secret.encode(), client.client_secret_hash.encode()):
            raise OAuthError(401, "invalid_client", "Invalid client secret")

    # Look up the authorization code
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    result = await session.execute(
        select(AuthSession).where(
            AuthSession.code_hash == code_hash,
            AuthSession.status == "ready",
        )
    )
    auth_session = result.scalar_one_or_none()
    if auth_session is None:
        raise OAuthError(400, "invalid_grant", "Invalid or expired authorization code")

    # Check expiry (naive-safe for SQLite tests)
    expires = auth_session.expires_at.replace(tzinfo=None)
    if expires < datetime.utcnow():
        raise OAuthError(400, "invalid_grant", "Authorization code has expired")

    # Verify client_id matches
    if auth_session.client_id != client_id:
        raise OAuthError(400, "invalid_grant", "client_id mismatch")

    # Verify redirect_uri matches
    if auth_session.client_redirect_uri != redirect_uri:
        raise OAuthError(400, "invalid_grant", "redirect_uri mismatch")

    # PKCE verification
    if not _verify_pkce(code_verifier, auth_session.code_challenge):
        raise OAuthError(400, "invalid_grant", "PKCE code_verifier mismatch")

    # Mark used in same transaction as token issuance (replay protection)
    auth_session.status = "used"
    auth_session.used_at = datetime.now(timezone.utc)

    scopes = auth_session.scopes or []
    access_token = create_access_token(
        subject=auth_session.subject,
        identity_type=auth_session.identity_type,
        tenant_id=auth_session.tenant_id,
        scopes=scopes,
    )

    raw_refresh, refresh_hash = create_refresh_token()
    rt = RefreshToken(
        token_hash=refresh_hash,
        client_id=client_id,
        subject=auth_session.subject,
        scopes=scopes,
        tenant_id=auth_session.tenant_id,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.refresh_token_ttl),
    )
    session.add(rt)
    await session.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl,
        "refresh_token": raw_refresh,
        "scope": " ".join(scopes),
    }
