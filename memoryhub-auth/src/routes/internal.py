import hashlib
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.models import ApiKey, OAuthClient
from src.schemas import ValidateApiKeyRequest, ValidateApiKeyResponse
from src.usage import mark_client_used, mark_key_used

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
    if client is not None:
        due = mark_key_used(client, "api_key_last_used_at")
    else:
        # A named key (#721): active client, key not revoked.
        row = (await session.execute(
            select(ApiKey, OAuthClient).join(OAuthClient, OAuthClient.client_id == ApiKey.client_id).where(
                ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None), OAuthClient.active,
            )
        )).first()
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        key, client = row
        due = mark_key_used(key)
    if mark_client_used(client, "api_key") or due:
        await session.commit()
    return ValidateApiKeyResponse(
        user_id=client.client_id,
        name=client.client_name,
        identity_type=client.identity_type,
        tenant_id=client.tenant_id,
        scopes=client.default_scopes,
    )
