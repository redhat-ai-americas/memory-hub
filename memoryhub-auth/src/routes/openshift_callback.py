"""GET /oauth/openshift/callback — broker callback from OpenShift OAuth.

Receives an authorization code from OpenShift, exchanges it for an opaque
token, resolves the OpenShift username, mints a MemoryHub authorization code,
and redirects the user back to the original client (e.g., LibreChat).
"""

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_session
from src.errors import OAuthError
from src.models import AuthSession

log = logging.getLogger("memoryhub-auth.routes.openshift_callback")

router = APIRouter()


def _openshift_tls_verify() -> bool | str:
    """Resolve TLS verification setting for OpenShift HTTP calls.

    Returns the cluster CA bundle path if it exists, True for system CAs,
    or False only when explicitly disabled via config.
    """
    if not settings.openshift_tls_verify:
        log.warning("TLS verification DISABLED for OpenShift calls — do not use in production")
        return False
    ca = settings.openshift_ca_bundle
    if ca and os.path.isfile(ca):
        return ca
    return True


async def _exchange_openshift_code(code: str) -> str:
    """Exchange an OpenShift authorization code for an opaque access token.

    Returns the opaque token. Raises OAuthError on failure.
    """
    broker_callback = f"{settings.issuer}/oauth/openshift/callback"
    async with httpx.AsyncClient(verify=_openshift_tls_verify(), timeout=10.0) as client:
        resp = await client.post(
            settings.openshift_oauth_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": broker_callback,
                "client_id": settings.openshift_oauth_client_id,
                "client_secret": settings.openshift_oauth_client_secret,
            },
        )
    if resp.status_code != 200:
        log.error(
            "OpenShift token exchange failed: status=%d body=%s",
            resp.status_code,
            resp.text[:200],
        )
        raise OAuthError(
            502,
            "server_error",
            "Failed to exchange authorization code with identity provider",
        )

    data = resp.json()
    token = data.get("access_token")
    if not token:
        log.error("OpenShift token response missing access_token")
        raise OAuthError(502, "server_error", "Identity provider returned invalid response")

    return token


async def _resolve_openshift_user(opaque_token: str) -> str:
    """Call OpenShift user-info API to get the username.

    The opaque token is used only for this call and NEVER persisted.
    Returns the OpenShift username (metadata.name).
    """
    async with httpx.AsyncClient(verify=_openshift_tls_verify(), timeout=10.0) as client:
        resp = await client.get(
            settings.openshift_user_info_url,
            headers={"Authorization": f"Bearer {opaque_token}"},
        )
    if resp.status_code != 200:
        log.error(
            "OpenShift user-info call failed: status=%d body=%s",
            resp.status_code,
            resp.text[:200],
        )
        raise OAuthError(
            502, "server_error", "Failed to resolve user identity from identity provider"
        )

    data = resp.json()
    username = data.get("metadata", {}).get("name")
    if not username:
        log.error("OpenShift user-info response missing metadata.name: %s", data)
        raise OAuthError(502, "server_error", "Identity provider returned invalid user info")

    return username


def _decode_group_member(entry: str) -> str:
    """Decode an OpenShift group member entry.

    OpenShift encodes usernames containing ':' with a ``b64:`` prefix in
    the Group ``.users`` list (e.g. ``b64:a3ViZTphZG1pbg==`` for
    ``kube:admin``).  Plain usernames are returned as-is.
    """
    if entry.startswith("b64:"):
        try:
            return base64.b64decode(entry[4:]).decode("utf-8")
        except Exception:
            return entry
    return entry


def _user_in_group_members(username: str, members: list[str]) -> bool:
    """Check if *username* appears in *members*, decoding b64-prefixed entries."""
    return any(_decode_group_member(m) == username for m in members)


async def _check_group_membership(opaque_token: str, username: str) -> None:
    """Verify the user belongs to the required OpenShift group.

    If ``settings.openshift_allowed_group`` is empty the check is skipped
    (all authenticated users are allowed).  Otherwise the OpenShift Groups
    API is queried with the user's opaque token and the username must appear
    in the group's ``.users`` list.
    """
    group_name = settings.openshift_allowed_group
    if not group_name:
        return

    groups_url = (
        f"https://kubernetes.default.svc/apis/user.openshift.io/v1/groups/{group_name}"
    )
    try:
        async with httpx.AsyncClient(verify=_openshift_tls_verify(), timeout=10.0) as client:
            resp = await client.get(
                groups_url,
                headers={"Authorization": f"Bearer {opaque_token}"},
            )
    except httpx.RequestError as exc:
        log.error("OpenShift group lookup network error: group=%s err=%s", group_name, exc)
        raise OAuthError(502, "server_error", "Failed to verify group membership")

    if resp.status_code != 200:
        log.error(
            "OpenShift group lookup failed: group=%s status=%d body=%s",
            group_name,
            resp.status_code,
            resp.text[:200],
        )
        raise OAuthError(502, "server_error", "Failed to verify group membership")

    members = resp.json().get("users") or []
    if not _user_in_group_members(username, members):
        log.warning(
            "User %s is not a member of required group %s", username, group_name
        )
        raise OAuthError(403, "access_denied", "User is not a member of the required group")

    log.info("Group check passed: %s is member of %s", username, group_name)


@router.get("/oauth/openshift/callback")
async def openshift_callback(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Broker callback — exchanges OpenShift code and redirects to the client."""

    # --- look up session by state (which is our session_id) ---
    result = await session.execute(
        select(AuthSession).where(
            AuthSession.session_id == state,
            AuthSession.status == "pending",
        )
    )
    auth_session = result.scalar_one_or_none()
    if auth_session is None:
        raise OAuthError(400, "invalid_request", "Unknown or expired session")

    # --- check expiry ---
    # Compare as naive UTC — SQLite strips tzinfo, PostgreSQL preserves it.
    expires = auth_session.expires_at.replace(tzinfo=None)
    if expires < datetime.utcnow():
        raise OAuthError(400, "invalid_request", "Authorization session has expired")

    # --- exchange OpenShift code for opaque token ---
    opaque_token = await _exchange_openshift_code(code)

    # --- resolve OpenShift username ---
    username = await _resolve_openshift_user(opaque_token)

    log.info("Resolved OpenShift user: %s for session %s", username, state[:8])

    # --- enforce group membership (if configured) ---
    await _check_group_membership(opaque_token, username)
    # opaque_token goes out of scope here — NEVER persisted

    # --- mint MemoryHub authorization code ---
    raw_code = secrets.token_urlsafe(32)  # 256-bit
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()

    # --- update session to ready ---
    auth_session.code_hash = code_hash
    auth_session.subject = username
    auth_session.identity_type = "user"
    auth_session.tenant_id = settings.default_tenant_id
    auth_session.scopes = settings.default_human_scopes
    auth_session.status = "ready"
    auth_session.expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.auth_session_ready_ttl
    )
    await session.commit()

    # --- redirect back to client ---
    qs = urlencode({"code": raw_code, "state": auth_session.client_state})
    return RedirectResponse(
        url=f"{auth_session.client_redirect_uri}?{qs}",
        status_code=302,
    )
