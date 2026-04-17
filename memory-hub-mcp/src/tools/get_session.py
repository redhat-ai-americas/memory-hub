"""Return the current session state without re-authenticating.

Lightweight 'whoami' tool for agents to verify their identity and
check whether a session is still active after errors or reconnects.
"""

import logging
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context, get_tenant_filter
from src.tools._deps import get_db_session, release_db_session
from src.tools.auth import get_current_user, get_session_expiry

from memoryhub_core.services.project import list_projects_for_tenant

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_session(
    ctx: Context = None,
) -> dict[str, Any]:
    """Check your current session state.

    Returns your user_id, name, accessible scopes, session expiry info,
    and project memberships. Raises an error if no session is registered
    or if the session has expired — call register_session to fix.
    """
    # Check expiry before claims resolution so expired API-key sessions
    # get a clear "expired" error rather than a generic "no session" error.
    expiry = get_session_expiry()
    if expiry is not None and expiry["expired"]:
        raise ToolError(
            "Session expired. Call register_session(api_key=...) to "
            "re-authenticate. Sessions auto-extend on activity but expire "
            f"after {expiry['ttl_seconds']}s of inactivity."
        ) from None

    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No active session. Call register_session(api_key=...) first."
        ) from None

    # Prefer the display name from the session user dict (set by
    # register_session) over the claims sub, which is the login ID.
    session_user = get_current_user()
    display_name = (
        session_user.get("name", claims["sub"]) if session_user
        else claims.get("name", claims["sub"])
    )

    # Session TTL info (None for JWT-authenticated sessions).
    expiry_info = get_session_expiry()

    # Fetch project memberships (non-fatal).
    projects: list[dict[str, Any]] = []
    tenant = get_tenant_filter(claims)
    gen = None
    try:
        session, gen = await get_db_session()
        raw = await list_projects_for_tenant(
            session, tenant_id=tenant, user_id=claims["sub"],
        )
        projects = [
            {
                "project_id": p["name"],
                "description": p.get("description", ""),
                "memory_count": p.get("memory_count", 0),
            }
            for p in raw
        ]
    except Exception as exc:
        logger.debug("Failed to fetch projects for get_session: %s", exc)
    finally:
        if gen is not None:
            await release_db_session(gen)

    result: dict[str, Any] = {
        "user_id": claims["sub"],
        "name": display_name,
        "scopes": claims.get("scopes", []),
        "projects": projects,
        "authenticated": True,
    }
    if expiry_info:
        result["expires_at"] = expiry_info["expires_at"]
        result["remaining_seconds"] = expiry_info["remaining_seconds"]
        result["session_ttl_seconds"] = expiry_info["ttl_seconds"]

    return result
