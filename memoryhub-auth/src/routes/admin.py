import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import OAuthClient
from src.schemas import (
    ApiKeyRotatedResponse,
    ClientCreatedResponse,
    ClientResponse,
    CreateClientRequest,
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


@router.get("/clients", dependencies=[Depends(require_admin_key)])
async def list_clients(
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
) -> list[ClientResponse]:
    stmt = select(OAuthClient)
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
    await session.commit()
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
    session: AsyncSession = Depends(get_session),
) -> ClientResponse:
    stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
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
    session: AsyncSession = Depends(get_session),
) -> ClientResponse:
    stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
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
    session: AsyncSession = Depends(get_session),
) -> SecretRotatedResponse:
    stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
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
    session: AsyncSession = Depends(get_session),
) -> ApiKeyRotatedResponse:
    stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
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
