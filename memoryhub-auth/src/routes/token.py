import base64
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, Form
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.entitlements import EntitlementUnavailableError, subject_may_use
from src.entitlements import enabled as entitlements_enabled
from src.errors import OAuthError
from src.models import AgentOwnerBinding, AuthSession, OAuthClient, RefreshToken
from src.people import IdentityChanged, verify_person
from src.token_exchange import (
    lookup_exchange_client,
    parse_service_account,
    resolve_tenant,
    validate_subject_token,
)
from src.tokens import create_access_token, create_refresh_token

log = logging.getLogger("memoryhub-auth.routes.token")

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; PostgreSQL keeps it."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _new_refresh(*, client_id: str, subject: str, scopes: list, tenant_id: str, origin: str,
                 family_id: str | None = None, family_started_at: datetime | None = None,
                 subject_uid: str | None = None) -> tuple[str, RefreshToken]:
    """A refresh token in a rotation family that never outlives session_max_age."""
    raw, digest = create_refresh_token()
    now = _now()
    started = _aware(family_started_at) if family_started_at else now
    expires = min(now + timedelta(seconds=settings.refresh_token_ttl),
                  started + timedelta(seconds=settings.session_max_age))
    return raw, RefreshToken(
        token_hash=digest, client_id=client_id, subject=subject, scopes=scopes, tenant_id=tenant_id,
        origin=origin, family_id=family_id or str(uuid.uuid4()), family_started_at=started,
        subject_uid=subject_uid, expires_at=expires,
    )


async def revoke_tokens(session: AsyncSession, *conditions) -> int:
    """Revoke every live refresh token matching ``conditions``; caller commits."""
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.revoked == False, *conditions)  # noqa: E712
        .values(revoked=True, revoked_at=_now())
    )
    return result.rowcount or 0


async def revoke_person_sessions(session: AsyncSession, tenant_id: str, username: str) -> int:
    return await revoke_tokens(session, RefreshToken.tenant_id == tenant_id,
                               RefreshToken.subject == username, RefreshToken.origin == "broker")


async def _owner_of(client: OAuthClient, session: AsyncSession) -> str | None:
    """The person a personal agent acts for, if any (dashboard owner binding)."""
    result = await session.execute(select(AgentOwnerBinding.owner).where(
        AgentOwnerBinding.tenant_id == client.tenant_id,
        AgentOwnerBinding.client_id == client.client_id,
    ))
    return result.scalar_one_or_none()


def _unavailable() -> OAuthError:
    # OpenShift could not be asked: a temporary error. Nothing is revoked.
    return OAuthError(503, "temporarily_unavailable", "Access to MemoryHub cannot be verified right now")


async def _verify_person_session(session: AsyncSession, rt: RefreshToken) -> None:
    """Refresh of a person's own session (origin "broker").

    Identity changed (User deleted or recreated, username taken by another
    account, renamed, profile disabled) or a session from before identity
    binding: every session of the username is revoked. Role missing: refused,
    or revoked with AUTH_ENTITLEMENT_DENIAL=revoke.
    """
    try:
        if not rt.subject_uid:
            raise IdentityChanged(rt.subject, "session predates identity binding")
        await verify_person(session, rt.tenant_id, rt.subject, expected_uid=rt.subject_uid,
                            require_profile=True, create_profile=False)
        allowed = await subject_may_use(rt.subject)
    except EntitlementUnavailableError:
        raise _unavailable() from None
    except IdentityChanged as changed:
        revoked = await revoke_person_sessions(session, rt.tenant_id, rt.subject)
        await session.commit()
        log.warning("Sessions of %r revoked (%d): %s", rt.subject, revoked, changed.reason)
        raise OAuthError(401, "invalid_grant", "Session ended; sign in again") from None
    if not allowed:
        if settings.entitlement_denial == "revoke":
            revoked = await revoke_person_sessions(session, rt.tenant_id, rt.subject)
            await session.commit()
            log.warning("Sessions of %r revoked (%d): no MemoryHub role", rt.subject, revoked)
        else:
            log.warning("Refresh refused: %r may no longer use MemoryHub", rt.subject)
        raise OAuthError(401, "invalid_grant", "Access to MemoryHub has been revoked")


async def _require_responsible_person(client: OAuthClient, session: AsyncSession) -> None:
    """Every token for an agent needs a responsible party.

    ``service`` clients are team-owned and created only through the admin
    API (the dashboard lets only Admins create them). Every other client is
    personal: it must have an owner binding, and the owner must still be the
    same verified, entitled person. A missing binding is refused, so a person
    cannot escape offboarding through a client without an owner.
    """
    if not entitlements_enabled() or client.identity_type == "service":
        return
    owner = await _owner_of(client, session)
    if not owner:
        log.warning("Token refused: personal client %r has no owner binding", client.client_id)
        raise OAuthError(403, "access_denied", "This personal agent has no verified owner; "
                                               "an administrator must bind it or make it a service agent")
    try:
        await verify_person(session, client.tenant_id, owner, expected_uid=None,
                            require_profile=True, create_profile=False)
        allowed = await subject_may_use(owner)
    except EntitlementUnavailableError:
        raise _unavailable() from None
    except IdentityChanged as changed:
        revoked = await revoke_tokens(session, RefreshToken.client_id == client.client_id)
        await session.commit()
        log.warning("Agent %r refused, %d token(s) revoked: owner %s", client.client_id, revoked, changed)
        raise OAuthError(403, "access_denied", "The owner of this agent is no longer a verified MemoryHub user") \
            from None
    if not allowed:
        if settings.entitlement_denial == "revoke":
            await revoke_tokens(session, RefreshToken.client_id == client.client_id)
            await session.commit()
        log.warning("Token refused: owner %r of agent %r may no longer use MemoryHub", owner, client.client_id)
        raise OAuthError(403, "access_denied", "The owner of this agent may no longer use MemoryHub")


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
    try:
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    except UnicodeEncodeError:
        return False  # RFC 7636 §4.1: verifier is unreserved ASCII only
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
    subject_token: str = Form(default=None),
    subject_token_type: str = Form(default=None),
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
    elif grant_type == "urn:ietf:params:oauth:grant-type:token-exchange":
        return await _handle_token_exchange(
            client_id, subject_token, subject_token_type, scope, session
        )
    else:
        raise OAuthError(
            400,
            "unsupported_grant_type",
            f"Grant type '{grant_type}' is not supported. "
            "Supported: client_credentials, refresh_token, "
            "authorization_code, urn:ietf:params:oauth:grant-type:token-exchange",
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
    await _require_responsible_person(client, session)

    access_token = create_access_token(
        subject=client.client_id,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        scopes=scopes,
    )

    raw_refresh, rt = _new_refresh(client_id=client.client_id, subject=client.client_id, scopes=scopes,
                                   tenant_id=client.tenant_id, origin="client")
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
    stored_rt = (await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )).scalar_one_or_none()
    if stored_rt is None or stored_rt.client_id != client.client_id:
        raise OAuthError(401, "invalid_grant", "Invalid, expired, or revoked refresh token")

    if stored_rt.revoked:
        # Reuse of a rotated or revoked token (RFC 9700 4.14): someone else may
        # hold this family. End the whole family; the owner signs in again.
        revoked = await revoke_tokens(session, RefreshToken.family_id == stored_rt.family_id)
        await session.commit()
        log.warning("Refresh token reuse: family %s of client %s (subject %r) revoked, %d live token(s)",
                    stored_rt.family_id, client.client_id, stored_rt.subject, revoked)
        raise OAuthError(401, "invalid_grant", "Invalid, expired, or revoked refresh token")

    now = _now()
    if _aware(stored_rt.expires_at) <= now:
        raise OAuthError(401, "invalid_grant", "Invalid, expired, or revoked refresh token")
    if _aware(stored_rt.family_started_at) + timedelta(seconds=settings.session_max_age) <= now:
        raise OAuthError(401, "invalid_grant", "Session reached its maximum age; sign in again")

    # The person behind this token must still be the same, allowed person.
    if entitlements_enabled():
        if stored_rt.origin == "broker":
            await _verify_person_session(session, stored_rt)
        else:
            await _require_responsible_person(client, session)

    # Revoke old token, issue new pair — single transaction
    stored_rt.revoked = True
    stored_rt.revoked_at = now

    scopes = stored_rt.scopes
    access_token = create_access_token(
        subject=stored_rt.subject,
        identity_type=client.identity_type,
        tenant_id=stored_rt.tenant_id,
        scopes=scopes,
    )

    raw_refresh_new, new_rt = _new_refresh(
        client_id=client.client_id, subject=stored_rt.subject, scopes=scopes, tenant_id=stored_rt.tenant_id,
        origin=stored_rt.origin, family_id=stored_rt.family_id, family_started_at=stored_rt.family_started_at,
        subject_uid=stored_rt.subject_uid,
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

    # Atomically claim the authorization code — prevents TOCTOU replay.
    # UPDATE ... WHERE status='ready' returns the row only if we won the race.
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    now = datetime.now(UTC)
    result = await session.execute(
        update(AuthSession)
        .where(
            AuthSession.code_hash == code_hash,
            AuthSession.status == "ready",
        )
        .values(status="used", used_at=now)
        .returning(AuthSession)
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

    scopes = auth_session.scopes or []
    access_token = create_access_token(
        subject=auth_session.subject,
        identity_type=auth_session.identity_type,
        tenant_id=auth_session.tenant_id,
        scopes=scopes,
    )

    raw_refresh, rt = _new_refresh(client_id=client_id, subject=auth_session.subject, scopes=scopes,
                                   tenant_id=auth_session.tenant_id, origin="broker",
                                   subject_uid=auth_session.subject_uid)
    session.add(rt)
    await session.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl,
        "refresh_token": raw_refresh,
        "scope": " ".join(scopes),
    }


async def _handle_token_exchange(
    client_id: str | None,
    subject_token: str | None,
    subject_token_type: str | None,
    scope: str | None,
    session: AsyncSession,
) -> dict:
    if not settings.token_exchange_enabled:
        raise OAuthError(
            400,
            "unsupported_grant_type",
            "Token exchange is not enabled in this deployment",
        )
    if not client_id:
        raise OAuthError(400, "invalid_request", "client_id is required")
    if not subject_token:
        raise OAuthError(400, "invalid_request", "subject_token is required")

    if subject_token_type and subject_token_type != "urn:ietf:params:oauth:token-type:jwt":
        raise OAuthError(
            400,
            "invalid_request",
            f"Unsupported subject_token_type: {subject_token_type}",
        )

    token_info = await validate_subject_token(subject_token)
    namespace, sa_name = parse_service_account(token_info["username"])
    tenant_id = await resolve_tenant(namespace)

    client = await lookup_exchange_client(client_id, session)
    scopes = _resolve_scopes(scope, client)
    await _require_responsible_person(client, session)

    subject = token_info["username"]
    access_token = create_access_token(
        subject=subject,
        identity_type=client.identity_type,
        tenant_id=tenant_id,
        scopes=scopes,
    )

    log.info(
        "Token exchange: sa=%s namespace=%s tenant=%s client=%s",
        sa_name, namespace, tenant_id, client_id,
    )

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": settings.access_token_ttl,
        "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "scope": " ".join(scopes),
    }
