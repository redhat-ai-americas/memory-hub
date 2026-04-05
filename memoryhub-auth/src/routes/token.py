import hashlib
import logging
from datetime import datetime, timezone, timedelta

import bcrypt
from fastapi import APIRouter, Depends, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.errors import OAuthError
from src.models import OAuthClient, RefreshToken
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
    else:
        raise OAuthError(
            400,
            "unsupported_grant_type",
            f"Grant type '{grant_type}' is not supported. "
            "Supported: client_credentials, refresh_token",
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
    # OAuth 2.1 requires client authentication on refresh
    if not client_id or not client_secret:
        raise OAuthError(
            400,
            "invalid_request",
            "client_id and client_secret are required for refresh_token grant",
        )
    if not refresh_token:
        raise OAuthError(400, "invalid_request", "refresh_token is required")

    client = await _authenticate_client(client_id, client_secret, session)

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
