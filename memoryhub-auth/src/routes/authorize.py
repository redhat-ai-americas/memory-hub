"""GET /authorize — OAuth 2.1 authorization endpoint with PKCE.

Validates the client, PKCE challenge, and redirect URI, persists a pending
auth session, then 302s the user to OpenShift's OAuth server.
"""

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.errors import OAuthError
from src.models import AuthSession, OAuthClient

log = logging.getLogger("memoryhub-auth.routes.authorize")

router = APIRouter()

# base64url alphabet (RFC 4648 §5) — no padding required
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_code_challenge(value: str) -> None:
    """Ensure code_challenge is non-empty, valid base64url."""
    if not value or not _BASE64URL_RE.match(value):
        raise OAuthError(
            400,
            "invalid_request",
            "code_challenge must be a non-empty base64url string",
        )


@router.get("/authorize")
async def authorize_endpoint(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(...),
    state: str = Query(...),
    scope: str = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """OAuth 2.1 authorization endpoint — initiates the PKCE broker flow."""

    # --- response_type ---
    if response_type != "code":
        raise OAuthError(
            400,
            "unsupported_response_type",
            "Only response_type=code is supported",
        )

    # --- code_challenge_method ---
    if code_challenge_method != "S256":
        raise OAuthError(
            400,
            "invalid_request",
            "Only code_challenge_method=S256 is supported (plain is not allowed)",
        )

    # --- code_challenge ---
    _validate_code_challenge(code_challenge)

    # --- client lookup ---
    result = await session.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.active == True,  # noqa: E712
        )
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise OAuthError(400, "invalid_request", "Unknown or inactive client_id")

    # --- redirect_uri exact match ---
    registered = client.redirect_uris or []
    if redirect_uri not in registered:
        raise OAuthError(
            400,
            "invalid_request",
            "redirect_uri does not match any registered URI for this client",
        )

    # --- broker must be configured ---
    if not settings.openshift_oauth_authorize_url:
        raise OAuthError(
            503,
            "temporarily_unavailable",
            "OpenShift OAuth broker is not configured",
        )

    # --- persist pending session ---
    session_id = secrets.token_hex(32)  # 256-bit
    auth_session = AuthSession(
        session_id=session_id,
        client_id=client_id,
        client_redirect_uri=redirect_uri,
        client_state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        status="pending",
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.auth_session_pending_ttl),
    )
    session.add(auth_session)
    await session.commit()

    log.info("Created auth session %s for client %s", session_id[:8], client_id)

    # --- 302 to OpenShift OAuth ---
    broker_callback = f"{settings.issuer}/oauth/openshift/callback"
    qs = urlencode(
        {
            "response_type": "code",
            "client_id": settings.openshift_oauth_client_id,
            "redirect_uri": broker_callback,
            "state": session_id,
        }
    )
    return RedirectResponse(
        url=f"{settings.openshift_oauth_authorize_url}?{qs}",
        status_code=302,
    )
