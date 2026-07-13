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
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.config import AppSettings
from memoryhub_core.services.project import get_projects_for_user, list_projects_for_tenant
from memoryhub_core.services.push_subscriber import (
    ensure_memoryhub_subscriber_running,
    stop_memoryhub_subscriber,
)
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from src.core.app import mcp
from src.core.audit import record_event
from src.core.authz import get_tenant_filter
from src.tools._deps import get_db_session, release_db_session
from src.tools.auth import (
    DEFAULT_TENANT_ID,
    AuthServiceUnavailableError,
    authenticate,
    authenticate_remote,
    set_default_driver_id,
    set_session,
    set_session_id,
)

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


async def _resolve_project_memberships(
    user: dict[str, Any],
) -> list[str]:
    """Merge ConfigMap-declared and DB-enrolled project memberships.

    The ConfigMap provides a static bootstrap list; the DB has the
    authoritative runtime state (including auto-enrollments from
    write_memory). Returns the sorted union so the session carries
    the fullest membership snapshot available at registration time.

    Non-fatal: returns ConfigMap memberships alone if the DB is
    unreachable, so registration is never blocked.
    """
    configmap_projects = set(user.get("project_memberships", []))

    gen = None
    try:
        session, gen = await get_db_session()
        db_projects = await get_projects_for_user(session, user["user_id"])
        merged = configmap_projects | db_projects
        return sorted(merged)
    except Exception as exc:
        logger.debug(
            "Failed to resolve DB project memberships for %s: %s",
            user.get("user_id", "?"),
            exc,
        )
        return sorted(configmap_projects)
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
    default_driver_id: Annotated[
        str | None,
        Field(
            description=(
                "Identity of the upstream human or system on whose behalf the "
                "agent is acting. When set, every write in this session records "
                "this as the driver_id unless overridden per-call. Omit when "
                "the agent is acting autonomously (driver_id defaults to the "
                "authenticated actor_id)."
            ),
        ),
    ] = None,
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
        user_id = jwt_claims.get("sub", token.client_id)
        session_id = str(uuid.uuid4())
        set_session_id(session_id)
        set_default_driver_id(default_driver_id)
        tenant = get_tenant_filter(jwt_claims)
        await _start_push_for_session(session_id, ctx)
        projects = await _fetch_user_projects(user_id, tenant)

        # Resolve project memberships from DB for JWT users.
        jwt_user_stub = {
            "user_id": user_id,
            "project_memberships": jwt_claims.get("project_memberships", []),
        }
        project_memberships = await _resolve_project_memberships(jwt_user_stub)

        record_event(
            event_type="session.registered",
            actor_id=user_id,
            driver_id=default_driver_id or user_id,
            scope="session",
            owner_id=user_id,
            memory_id=None,
            decision="allowed",
            metadata={"auth_method": "jwt", "session_id": session_id},
        )
        return {
            "session_id": session_id,
            "user_id": user_id,
            "name": jwt_claims.get("name", user_id),
            "scopes": list(token.scopes),
            "project_memberships": project_memberships,
            "auth_method": "jwt",
            "default_driver_id": default_driver_id,
            "projects": projects,
            "quick_start": _QUICK_START,
            "message": (
                f"JWT authentication active for {user_id}. "
                f"Session {session_id} registered."
            ),
        }

    user = authenticate(api_key)
    if user is None:
        try:
            user = await authenticate_remote(api_key)
        except AuthServiceUnavailableError as exc:
            raise ToolError(
                "Could not reach authentication service to validate your API key. "
                f"The service may be temporarily unavailable: {exc}. "
                "Retry in a moment, or contact your system administrator."
            ) from exc

    if user is None:
        record_event(
            event_type="session.denied",
            actor_id="unknown",
            driver_id="unknown",
            scope="session",
            owner_id="unknown",
            memory_id=None,
            decision="denied",
            metadata={"auth_method": "api_key"},
        )
        raise ToolError(
            "Invalid API key. Contact your system administrator for a valid key. "
            "Keys follow the format: mh-dev-<hex>."
        )

    # Resolve project memberships: merge ConfigMap bootstrap with DB state.
    # This must happen before set_session() so the session user dict
    # carries project_memberships for get_claims_from_context() to extract.
    user["project_memberships"] = await _resolve_project_memberships(user)

    app_settings = AppSettings()
    ttl = app_settings.session_ttl_seconds
    expires_at = set_session(user, ttl_seconds=ttl)
    session_id = str(uuid.uuid4())
    set_session_id(session_id)
    set_default_driver_id(default_driver_id)
    await _start_push_for_session(session_id, ctx)

    if ctx:
        await ctx.info(f"Session {session_id} registered for user: {user['user_id']}")

    tenant = get_tenant_filter(
        {"sub": user["user_id"], "tenant_id": user.get("tenant_id", DEFAULT_TENANT_ID)}
    )
    projects = await _fetch_user_projects(user["user_id"], tenant)

    record_event(
        event_type="session.registered",
        actor_id=user["user_id"],
        driver_id=default_driver_id or user["user_id"],
        scope="session",
        owner_id=user["user_id"],
        memory_id=None,
        decision="allowed",
        metadata={"auth_method": "api_key", "session_id": session_id},
    )

    return {
        "session_id": session_id,
        "user_id": user["user_id"],
        "name": user["name"],
        "scopes": user["scopes"],
        "project_memberships": user["project_memberships"],
        "expires_at": expires_at.isoformat(),
        "session_ttl_seconds": ttl,
        "default_driver_id": default_driver_id,
        "projects": projects,
        "quick_start": _QUICK_START,
        "message": (
            f"Session {session_id} registered for {user['name']} ({user['user_id']}). "
            f"Accessible scopes: {', '.join(user['scopes'])}. "
            f"Session expires in {ttl}s (auto-extends on activity)."
        ),
    }
