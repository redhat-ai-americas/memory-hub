import hashlib
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import OAuthClient
from src.schemas import ValidateApiKeyRequest, ValidateApiKeyResponse

log = logging.getLogger("memoryhub-auth.routes.internal")

router = APIRouter(prefix="/internal", tags=["internal"])


async def require_service_key(
    x_service_key: str | None = Header(default=None),
) -> None:
    service_key = os.environ.get("AUTH_INTERNAL_SERVICE_KEY", "")
    if not service_key or not x_service_key or x_service_key != service_key:
        raise HTTPException(status_code=401, detail="Invalid or missing service key")


@router.post(
    "/validate-api-key",
    dependencies=[Depends(require_service_key)],
)
async def validate_api_key(
    body: ValidateApiKeyRequest,
    session: AsyncSession = Depends(get_session),
) -> ValidateApiKeyResponse:
    key_hash = hashlib.sha256(body.api_key.encode()).hexdigest()
    result = await session.execute(
        select(OAuthClient).where(
            OAuthClient.api_key_hash == key_hash,
            OAuthClient.active,
        )
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return ValidateApiKeyResponse(
        user_id=client.client_id,
        name=client.client_name,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        scopes=client.default_scopes,
    )


@router.get(
    "/clients/{client_id}/status",
    dependencies=[Depends(require_service_key)],
)
async def client_status(
    client_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Current state of an OAuth client, for resource servers re-checking bearer tokens.

    Unknown and revoked clients are both 404, so the answer reveals nothing beyond
    "this client may not be used now" (QA 2026-11-09 RT2-CL-05).
    """
    result = await session.execute(select(OAuthClient).where(OAuthClient.client_id == client_id, OAuthClient.active))
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not active")
    return {"client_id": client.client_id, "tenant_id": client.tenant_id, "scopes": list(client.default_scopes or [])}
