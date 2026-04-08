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
from pydantic import Field

from memoryhub_core.services.push_subscriber import (
    ensure_memoryhub_subscriber_running,
    stop_memoryhub_subscriber,
)
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from src.core.app import mcp
from src.tools.auth import authenticate, set_session

logger = logging.getLogger(__name__)


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
                "Format: mh-dev-<username>-<year>."
            ),
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Register this session with your API key.

    Call this once at the start of every conversation to establish your identity.
    After registration, write_memory and search_memory will automatically scope
    operations to your user_id. Returns your identity and accessible memory scopes.
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
        await _start_push_for_session(session_id, ctx)
        return {
            "user_id": session_id,
            "name": jwt_claims.get("name", session_id),
            "scopes": list(token.scopes),
            "auth_method": "jwt",
            "message": (
                f"JWT authentication active for {session_id}. "
                "Session registration is not needed when using JWT auth."
            ),
        }

    user = authenticate(api_key)

    if user is None:
        return {
            "error": True,
            "message": (
                "Invalid API key. Contact your system administrator for a valid key. "
                "Keys follow the format: mh-dev-<username>-<year>."
            ),
        }

    set_session(user)
    await _start_push_for_session(user["user_id"], ctx)

    if ctx:
        await ctx.info(f"Session registered for user: {user['user_id']}")

    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "scopes": user["scopes"],
        "message": (
            f"Session registered for {user['name']} ({user['user_id']}). "
            f"Accessible scopes: {', '.join(user['scopes'])}."
        ),
    }
