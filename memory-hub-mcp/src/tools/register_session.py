"""Register an authenticated session using an API key.

Agents must call this tool once at the start of every conversation to
establish identity. The authenticated user_id is then used automatically
by write_memory and search_memory when no explicit owner_id is supplied.

In addition to authenticating the session, this tool starts the #62
Pattern E push subscriber for pure-listener agents. A per-session asyncio
Task is spawned that BRPOPs from the session's broadcast queue and
forwards notifications to the client. The subscriber is cleaned up
automatically when the session's FastMCP ``_exit_stack`` unwinds on
disconnect. Push infrastructure failures are non-fatal — if Valkey is
unreachable or the session lifecycle hook is missing, registration still
succeeds and the agent falls back to pull-only memory loading.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.project import list_projects_for_tenant
from memoryhub_core.services.push_subscriber import (
    ensure_memoryhub_subscriber_running,
    stop_memoryhub_subscriber,
)
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from memoryhub_core.config import AppSettings
from src.core.app import mcp
from src.core.authz import get_tenant_filter
from src.tools._deps import get_db_session, release_db_session
from src.tools.auth import authenticate, set_session

logger = logging.getLogger(__name__)

_QUICK_START = [
    "Call search_memory(query='...') to load context relevant to your task.",
    "Pass project_id='<name>' in search_memory and write_memory to scope "
    "memories to a project.",
    "Writing to a project you haven't joined? Auto-enrollment handles it.",
]


async def _start_push_for_session(session_id: str, ctx: Context | None) -> None:
    """Wire a session into the #62 push broadcast pipeline.

    Steps (each independently failure-tolerant):
      1. SADD the session_id to ``memoryhub:active_sessions`` so broadcast
         writers can enumerate targets.
      2. Spawn the subscriber task via ``ensure_memoryhub_subscriber_running``
         so the client receives pushed notifications without polling.
      3. Register a cleanup callback on the FastMCP session ``_exit_stack``
         that undoes both on disconnect.

    Non-fatal throughout. If the backend is down, the session still registers
    and the agent degrades gracefully to pull-only memory loading.
    """
    try:
        valkey_client = get_valkey_client()
        await valkey_client.register_active_session(session_id)
    except ValkeyUnavailableError as exc:
        logger.debug(
            "Skipping push wiring for %s: Valkey unavailable (%s)", session_id, exc
        )
        return

    if ctx is None:
        logger.debug(
            "No context for session %s; active-session registered but "
            "subscriber loop not started",
            session_id,
        )
        return

    try:
        session = ctx.session
    except RuntimeError:
        # No established session (on_initialize or background task without
        # stored session). The SADD above succeeded; the subscriber will be
        # started on a subsequent register_session call that has a session.
        return

    try:
        await ensure_memoryhub_subscriber_running(
            session_id, session, valkey_client
        )
    except Exception as exc:
        logger.debug(
            "Failed to start memoryhub subscriber for %s: %s", session_id, exc
        )
        return

    # Register session-close cleanup exactly once per session. FastMCP's
    # ``_exit_stack`` unwinds when the streamable-http connection closes,
    # calling our callback which cancels the subscriber task and removes
    # the session from the active set.
    exit_stack = getattr(session, "_exit_stack", None)
    if exit_stack is None:
        logger.debug(
            "Session for %s lacks _exit_stack; subscriber cleanup will "
            "rely on weakref GC on next ensure_running call",
            session_id,
        )
        return

    if getattr(session, "_memoryhub_push_cleanup_registered", False):
        return

    async def _cleanup_memoryhub_push() -> None:
        try:
            await stop_memoryhub_subscriber(session_id)
        except Exception as exc:
            logger.debug(
                "stop_memoryhub_subscriber failed for %s: %s", session_id, exc
            )
        try:
            await valkey_client.deregister_active_session(session_id)
        except ValkeyUnavailableError as exc:
            logger.debug(
                "deregister_active_session failed for %s: %s", session_id, exc
            )

    exit_stack.push_async_callback(_cleanup_memoryhub_push)
    session._memoryhub_push_cleanup_registered = True


async def _fetch_user_projects(
    user_id: str, tenant_id: str,
) -> list[dict[str, Any]]:
    """Fetch the user's projects for the registration response.

    Returns a lightweight list of project summaries. Non-fatal: returns
    an empty list on any failure so registration is never blocked.
    """
    gen = None
    try:
        session, gen = await get_db_session()
        projects = await list_projects_for_tenant(
            session, tenant_id=tenant_id, user_id=user_id,
        )
        return [
            {
                "project_id": p["name"],
                "description": p.get("description", ""),
                "memory_count": p.get("memory_count", 0),
            }
            for p in projects
        ]
    except Exception as exc:
        logger.debug("Failed to fetch projects for %s: %s", user_id, exc)
        return []
    finally:
        if gen is not None:
            await release_db_session(gen)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def register_session(
    api_key: Annotated[
        str,
        Field(
            description=(
                "Your MemoryHub API key. Provided by the system administrator. "
                "Format: mh-dev-<hex>."
            ),
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Register this session with your API key.

    Call this once at the start of every conversation to establish your identity.
    After registration, write_memory and search_memory will automatically scope
    operations to your user_id.

    Sessions have a configurable TTL (default 1 hour) and auto-extend on
    activity — active agents never hit expiry. Check remaining time with
    get_session.

    Returns your identity, accessible scopes, session expiry, project
    memberships (with memory counts), and quick-start hints.
    """
    # When JWT auth is active, session registration is unnecessary
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
    except Exception:
        token = None

    if token is not None:
        jwt_claims = token.claims
        session_id = jwt_claims.get("sub", token.client_id)
        tenant = get_tenant_filter(jwt_claims)
        await _start_push_for_session(session_id, ctx)
        projects = await _fetch_user_projects(session_id, tenant)
        return {
            "user_id": session_id,
            "name": jwt_claims.get("name", session_id),
            "scopes": list(token.scopes),
            "auth_method": "jwt",
            "projects": projects,
            "quick_start": _QUICK_START,
            "message": (
                f"JWT authentication active for {session_id}. "
                "Session registration is not needed when using JWT auth."
            ),
        }

    user = authenticate(api_key)

    if user is None:
        raise ToolError(
            "Invalid API key. Contact your system administrator for a valid key. "
            "Keys follow the format: mh-dev-<hex>."
        )

    app_settings = AppSettings()
    ttl = app_settings.session_ttl_seconds
    expires_at = set_session(user, ttl_seconds=ttl)
    await _start_push_for_session(user["user_id"], ctx)

    if ctx:
        await ctx.info(f"Session registered for user: {user['user_id']}")

    tenant = get_tenant_filter(
        {"sub": user["user_id"], "tenant_id": user.get("tenant_id", "default")}
    )
    projects = await _fetch_user_projects(user["user_id"], tenant)

    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "scopes": user["scopes"],
        "expires_at": expires_at.isoformat(),
        "session_ttl_seconds": ttl,
        "projects": projects,
        "quick_start": _QUICK_START,
        "message": (
            f"Session registered for {user['name']} ({user['user_id']}). "
            f"Accessible scopes: {', '.join(user['scopes'])}. "
            f"Session expires in {ttl}s (auto-extends on activity)."
        ),
    }
