import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Admin principals
#
# AUTH_ADMIN_KEY is the platform operator key: it may manage clients of any
# tenant. AUTH_TENANT_ADMIN_KEYS (JSON object {"tenant-id": "key"}) holds one key
# per tenant dashboard. A tenant key is bound to its tenant: every route forces
# that tenant, a different tenant in the body or query string is refused (403),
# and tenant keys can never grant cross-tenant scopes. The BFF is not trusted to
# pick the tenant; the key it holds decides it.
# ---------------------------------------------------------------------------

_SCOPE_RE = re.compile(
    r"^(memory:(read|write)(:(user|project|campaign|role|organizational|enterprise))?"
    r"|memory:approve:(organizational|enterprise)"
    r"|memory:admin(:(super|cross_tenant|sanitized_audit))?"
    r"|project:admin)$"
)
PLATFORM_ONLY_SCOPES = frozenset({"memory:admin:cross_tenant"})


@dataclass(frozen=True)
class AdminPrincipal:
    kind: str  # "platform" | "tenant"
    tenant_id: str | None = None

    def tenant_for(self, requested: str | None) -> str | None:
        """Return the tenant this request may touch; refuse foreign tenants."""
        if self.kind == "platform":
            return requested
        if requested is not None and requested != self.tenant_id:
            log.warning("Refused tenant override: key for %s asked for %s", self.tenant_id, requested)
            raise HTTPException(status_code=403, detail="This admin key cannot act on another tenant")
        return self.tenant_id


def _tenant_keys() -> dict[str, str]:
    raw = os.environ.get("AUTH_TENANT_ADMIN_KEYS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        log.error("AUTH_TENANT_ADMIN_KEYS is not valid JSON; tenant admin keys disabled")
        return {}
    return {str(t): str(k) for t, k in data.items() if t and k} if isinstance(data, dict) else {}


async def require_admin_key(
    x_admin_key: str | None = Header(default=None),
) -> AdminPrincipal:
    """Resolve the X-Admin-Key header to a platform or tenant-bound principal."""
    if x_admin_key:
        platform = os.environ.get("AUTH_ADMIN_KEY", "")
        if platform and hmac.compare_digest(x_admin_key.encode(), platform.encode()):
            return AdminPrincipal(kind="platform")
        for tenant, key in _tenant_keys().items():
            if hmac.compare_digest(x_admin_key.encode(), key.encode()):
                return AdminPrincipal(kind="tenant", tenant_id=tenant)
    raise HTTPException(status_code=401, detail="Invalid or missing admin key")


def _validate_scopes(principal: AdminPrincipal, scopes: list[str] | None) -> None:
    if scopes is None:
        return
    unknown = sorted({s for s in scopes if not isinstance(s, str) or not _SCOPE_RE.match(s)})
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown scopes: {', '.join(map(str, unknown))}")
    if principal.kind != "platform" and PLATFORM_ONLY_SCOPES.intersection(scopes):
        raise HTTPException(
            status_code=403, detail="Cross-tenant scopes can only be granted with the platform admin key"
        )


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


@router.get("/clients")
async def list_clients(
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> list[ClientResponse]:
    tenant_id = principal.tenant_for(tenant_id)
    stmt = select(OAuthClient)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    clients = result.scalars().all()
    return [_client_to_response(c) for c in clients]


@router.post("/clients", status_code=201)
async def create_client(
    body: CreateClientRequest,
    tenant_id: str | None = Query(default=None, description="Must match body.tenant_id when given"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> ClientCreatedResponse:
    if tenant_id is not None and tenant_id != body.tenant_id:
        raise HTTPException(status_code=403, detail="Conflicting tenant in query string and body")
    principal.tenant_for(body.tenant_id)
    _validate_scopes(principal, body.default_scopes)
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

    log.info("Created client %s (tenant=%s, by=%s)", body.client_id, body.tenant_id, principal.kind)

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


@router.get("/clients/{client_id}")
async def get_client(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> ClientResponse:
    tenant_id = principal.tenant_for(tenant_id)
    stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
    if tenant_id is not None:
        stmt = stmt.where(OAuthClient.tenant_id == tenant_id)
    result = await session.execute(stmt)
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found")
    return _client_to_response(client)


@router.patch("/clients/{client_id}")
async def update_client(
    client_id: str,
    body: UpdateClientRequest,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> ClientResponse:
    tenant_id = principal.tenant_for(tenant_id)
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
        _validate_scopes(principal, body.default_scopes)
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
)
async def rotate_secret(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> SecretRotatedResponse:
    tenant_id = principal.tenant_for(tenant_id)
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
)
async def rotate_api_key(
    client_id: str,
    tenant_id: str | None = Query(default=None, description="Filter by tenant"),
    session: AsyncSession = Depends(get_session),
    principal: AdminPrincipal = Depends(require_admin_key),
) -> ApiKeyRotatedResponse:
    tenant_id = principal.tenant_for(tenant_id)
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
