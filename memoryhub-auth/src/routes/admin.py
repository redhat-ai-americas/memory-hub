import hashlib
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.entitlements import EntitlementUnavailableError
from src.models import AgentOwnerBinding, HumanIdentity, OAuthClient, RefreshToken
from src.people import IdentityChanged, current_uid
from src.routes.token import revoke_person_sessions, revoke_tokens
from src.schemas import (
    ApiKeyRotatedResponse,
    ClientCreatedResponse,
    ClientResponse,
    CreateClientRequest,
    EndSessionsRequest,
    EndSessionsResponse,
    SecretRotatedResponse,
    UpdateClientRequest,
)

log = logging.getLogger("memoryhub-auth.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin_key(
    x_admin_key: str | None = Header(default=None),
) -> None:
    """Validate the admin API key from the X-Admin-Key header."""
    admin_key = os.environ.get("AUTH_ADMIN_KEY", "")
    if not admin_key or not x_admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid or missing admin key")


def _client_to_response(client: OAuthClient) -> ClientResponse:
    return ClientResponse(
        client_id=client.client_id,
        client_name=client.client_name,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        default_scopes=client.default_scopes,
        redirect_uris=client.redirect_uris,
        public=client.public,
        active=client.active,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def _with_owner_binding(stmt, owner: str | None):
    """Apply the dashboard owner check in the same DB query as the operation."""
    if owner is None:
        return stmt
    return stmt.join(
        AgentOwnerBinding,
        and_(
            AgentOwnerBinding.tenant_id == OAuthClient.tenant_id,
            AgentOwnerBinding.client_id == OAuthClient.client_id,
        ),
    ).where(AgentOwnerBinding.owner == owner)


@router.get("/clients", dependencies=[Depends(require_admin_key)])
async def list_clients(
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    owner: str | None = Query(default=None, description="Filter by owner binding"),
    session: AsyncSession = Depends(get_session),
) -> list[ClientResponse]:
    stmt = _with_owner_binding(select(OAuthClient), owner)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    clients = result.scalars().all()
    return [_client_to_response(c) for c in clients]


@router.post(
    "/clients",
    status_code=201,
    dependencies=[Depends(require_admin_key)],
)
async def create_client(
    body: CreateClientRequest,
    session: AsyncSession = Depends(get_session),
) -> ClientCreatedResponse:
    # Check for duplicate client_id
    existing = await session.execute(
        select(OAuthClient).where(OAuthClient.client_id == body.client_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Client with client_id '{body.client_id}' already exists",
        )

    plaintext_secret = secrets.token_urlsafe(32)
    secret_hash = bcrypt.hashpw(
        plaintext_secret.encode(), bcrypt.gensalt()
    ).decode()

    api_key = "mh-dev-" + secrets.token_hex(8)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    now = datetime.now(UTC)
    client = OAuthClient(
        client_id=body.client_id,
        client_secret_hash=secret_hash,
        client_name=body.client_name,
        identity_type=body.identity_type,
        tenant_id=body.tenant_id,
        default_scopes=body.default_scopes,
        redirect_uris=body.redirect_uris,
        public=body.public,
        active=True,
        created_at=now,
        updated_at=now,
        api_key_hash=api_key_hash,
    )
    session.add(client)
    if body.owner is not None:
        session.add(AgentOwnerBinding(
            tenant_id=body.tenant_id, client_id=body.client_id, owner=body.owner,
        ))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Client or owner binding already exists") from exc
    await session.refresh(client)

    log.info("Created client %s (tenant=%s)", body.client_id, body.tenant_id)

    return ClientCreatedResponse(
        client_id=client.client_id,
        client_name=client.client_name,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        default_scopes=client.default_scopes,
        redirect_uris=client.redirect_uris,
        public=client.public,
        active=client.active,
        created_at=client.created_at,
        updated_at=client.updated_at,
        client_secret=plaintext_secret,
        api_key=api_key,
    )


@router.get("/clients/{client_id}", dependencies=[Depends(require_admin_key)])
async def get_client(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    owner: str | None = Query(default=None, description="Filter by owner binding"),
    session: AsyncSession = Depends(get_session),
) -> ClientResponse:
    stmt = _with_owner_binding(select(OAuthClient).where(OAuthClient.client_id == client_id), owner)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
    return _client_to_response(client)


@router.patch("/clients/{client_id}", dependencies=[Depends(require_admin_key)])
async def update_client(
    client_id: str,
    body: UpdateClientRequest,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    owner: str | None = Query(default=None, description="Filter by owner binding"),
    session: AsyncSession = Depends(get_session),
) -> ClientResponse:
    stmt = _with_owner_binding(select(OAuthClient).where(OAuthClient.client_id == client_id), owner)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    if body.client_name is not None:
        client.client_name = body.client_name
    if body.active is not None:
        client.active = body.active
    if body.default_scopes is not None:
        client.default_scopes = body.default_scopes
    if body.redirect_uris is not None:
        client.redirect_uris = body.redirect_uris
    if body.public is not None:
        client.public = body.public

    client.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(client)

    log.info("Updated client %s", client_id)
    return _client_to_response(client)


@router.post(
    "/clients/{client_id}/rotate-secret",
    dependencies=[Depends(require_admin_key)],
)
async def rotate_secret(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    owner: str | None = Query(default=None, description="Filter by owner binding"),
    session: AsyncSession = Depends(get_session),
) -> SecretRotatedResponse:
    stmt = _with_owner_binding(select(OAuthClient).where(OAuthClient.client_id == client_id), owner)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    plaintext_secret = secrets.token_urlsafe(32)
    client.client_secret_hash = bcrypt.hashpw(
        plaintext_secret.encode(), bcrypt.gensalt()
    ).decode()
    api_key = "mh-dev-" + secrets.token_hex(8)
    client.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    client.updated_at = datetime.now(UTC)
    await session.commit()

    log.info("Rotated secret and API key for client %s", client_id)
    return SecretRotatedResponse(
        client_id=client.client_id,
        client_secret=plaintext_secret,
        api_key=api_key,
    )


@router.post(
    "/clients/{client_id}/rotate-api-key",
    dependencies=[Depends(require_admin_key)],
)
async def rotate_api_key(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    owner: str | None = Query(default=None, description="Filter by owner binding"),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyRotatedResponse:
    stmt = _with_owner_binding(select(OAuthClient).where(OAuthClient.client_id == client_id), owner)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")

    api_key = "mh-dev-" + secrets.token_hex(8)
    client.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    client.updated_at = datetime.now(UTC)
    await session.commit()

    log.info("Rotated API key for client %s", client_id)
    return ApiKeyRotatedResponse(client_id=client.client_id, api_key=api_key)


# --- People: explicit end of sessions and blocking (#744) -------------------


@router.post("/people/{username}/end-sessions", response_model=EndSessionsResponse,
             dependencies=[Depends(require_admin_key)])
async def end_sessions(username: str, body: EndSessionsRequest,
                       session: AsyncSession = Depends(get_session)) -> EndSessionsResponse:
    """Revoke a person's refresh-token families; optionally their agents' and block them.

    Revocation is final: a new sign-in is required even if access is later
    restored. Access tokens already issued stay valid until they expire
    (AUTH_ACCESS_TOKEN_TTL).
    """
    sessions = await revoke_person_sessions(session, body.tenant_id, username)
    agents = 0
    if body.include_agents:
        owned = select(AgentOwnerBinding.client_id).where(
            AgentOwnerBinding.tenant_id == body.tenant_id, AgentOwnerBinding.owner == username)
        agents = await revoke_tokens(session, RefreshToken.client_id.in_(owned))
    profile = (await session.execute(select(HumanIdentity).where(
        HumanIdentity.tenant_id == body.tenant_id, HumanIdentity.username == username,
    ))).scalar_one_or_none()
    disabled = False
    if body.disable:
        if profile is None:
            # Never signed in: record a blocked profile for the current account.
            try:
                uid = await current_uid(username)
            except (IdentityChanged, EntitlementUnavailableError):
                uid = None
            if uid:
                profile = HumanIdentity(id=str(uuid.uuid4()), tenant_id=body.tenant_id,
                                        issuer=settings.verified_issuer(), subject=uid, username=username)
                session.add(profile)
        if profile is not None:
            profile.disabled_at = datetime.now(UTC)
            disabled = True
    await session.commit()
    log.warning("Sessions of %r ended by admin (%s): %d session token(s), %d agent token(s), disabled=%s",
                username, body.reason, sessions, agents, disabled)
    return EndSessionsResponse(username=username, sessions_revoked=sessions, agent_tokens_revoked=agents,
                               disabled=disabled, profile_found=profile is not None)


@router.post("/people/{username}/enable", dependencies=[Depends(require_admin_key)])
async def enable_person(username: str, tenant_id: str = Query(...),
                        session: AsyncSession = Depends(get_session)) -> dict:
    """Lift a block. Revoked sessions stay revoked: the person signs in again."""
    profile = (await session.execute(select(HumanIdentity).where(
        HumanIdentity.tenant_id == tenant_id, HumanIdentity.username == username,
    ))).scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile for this username")
    profile.disabled_at = None
    await session.commit()
    log.warning("Profile of %r re-enabled by admin", username)
    return {"username": username, "disabled": False}
