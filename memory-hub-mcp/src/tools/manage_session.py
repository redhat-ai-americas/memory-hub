"""Consolidated session management tool (#166 pattern).

Replaces three separate tools — get_session, set_session_focus, and
get_focus_history — with a single action-dispatch interface. Each action
maps directly to the original tool's logic; this is a tool-layer
consolidation only (service calls are unchanged).

Actions:
- ``status``       — Lightweight session check (replaces get_session).
- ``set_focus``    — Declare this session's focus topic (replaces set_session_focus).
- ``focus_history``— Per-project focus histogram (replaces get_focus_history).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)
from memoryhub_core.services.project import list_projects_for_tenant
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context, get_tenant_filter
from src.tools._deps import get_db_session, get_embedding_service, release_db_session
from src.tools.auth import get_current_user, get_session_expiry

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {"status", "set_focus", "focus_history"}
_ACTIONS_REQUIRING_FOCUS = {"set_focus"}
_ACTIONS_REQUIRING_PROJECT = {"set_focus", "focus_history"}

_DEFAULT_WINDOW_DAYS = 30


def _require_param(action: str, name: str, value: str | None) -> str:
    """Validate that a required string parameter is present for the given action."""
    if not value or not value.strip():
        raise ToolError(
            f"action='{action}' requires '{name}'. "
            f"Example: manage_session(action='{action}', {name}='...')"
        )
    return value.strip()


def _parse_iso_date(label: str, value: str | None) -> date | None:
    """Parse an optional YYYY-MM-DD string into a date.

    ``label`` is the parameter name used in error messages. Returns None if the
    input is None or empty.
    """
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ToolError(
            f"Invalid {label} format: {value!r}. Expected ISO format YYYY-MM-DD."
        ) from exc


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def manage_session(
    action: Annotated[
        str,
        Field(
            description=(
                "The operation to perform. One of: "
                "'status' (check your current session identity and project memberships), "
                "'set_focus' (declare the session's focus topic for history and broadcast filtering), "
                "'focus_history' (retrieve a per-project histogram of recent session focus declarations)."
            ),
        ),
    ],
    focus: Annotated[
        str | None,
        Field(
            description=(
                "Required for action='set_focus'. A short natural-language topic "
                "describing this session's current focus. 5-10 words work best. "
                "Examples: 'deployment', 'MCP tool design for session focus', "
                "'UI panel for curation rules'. The SDK normally infers this from "
                "working directory or first user turn, but agents can declare "
                "explicitly or update mid-session when the conversation pivots."
            ),
        ),
    ] = None,
    project: Annotated[
        str | None,
        Field(
            description=(
                "Required for action='set_focus' and action='focus_history'. "
                "The project identifier this session belongs to. Typically matches "
                "the `project` field of project-scope memories and the `project` "
                "value in `.memoryhub.yaml`. Required so history aggregation can "
                "scope per-project."
            ),
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(
            description=(
                "Used with action='focus_history'. Start of the date range, "
                "inclusive, in ISO format YYYY-MM-DD. "
                "Defaults to 30 days before end_date."
            ),
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            description=(
                "Used with action='focus_history'. End of the date range, "
                "inclusive, in ISO format YYYY-MM-DD. Defaults to today (UTC)."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Manage your session: check status, set focus topic, or query focus history.

    Use action='status' as a lightweight whoami — it returns your user_id, name,
    scopes, session expiry, and project memberships without re-authenticating.

    Use action='set_focus' to declare the current session's topic. This writes
    to two Valkey keys: an active-session hash (for broadcast filtering) and a
    per-project per-day history list (for the focus histogram).

    Use action='focus_history' to retrieve a sorted histogram of focus
    declarations for a project over a date window. This is advisory-only: it
    does not auto-tune memory weights or affect retrieval ranking.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    if action == "status":
        return await _handle_status()

    if action == "set_focus":
        focus = _require_param(action, "focus", focus)
        project = _require_param(action, "project", project)
        return await _handle_set_focus(focus, project, ctx)

    # action == "focus_history"
    project = _require_param(action, "project", project)
    return await _handle_focus_history(project, start_date, end_date, ctx)


async def _handle_status() -> dict[str, Any]:
    """Return current session identity, scopes, expiry, and project memberships."""
    # Check expiry before claims resolution so expired API-key sessions get a
    # clear "expired" error rather than a generic "no session" error.
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

    # Prefer the display name from the session user dict (set by register_session)
    # over the claims sub, which is the login ID.
    session_user = get_current_user()
    display_name = (
        session_user.get("name", claims["sub"]) if session_user
        else claims.get("name", claims["sub"])
    )

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
        logger.debug("Failed to fetch projects for manage_session status: %s", exc)
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


async def _handle_set_focus(
    focus: str, project: str, ctx: Context | None,
) -> dict[str, Any]:
    """Embed the focus string and write it to the active-session hash and history list."""
    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, or "
            "provide a JWT in the Authorization header."
        ) from None

    user_id = claims["sub"]
    session_id = user_id  # interim: one session per user; see set_session_focus module docstring

    embedding_service = get_embedding_service()
    try:
        focus_vector = await embedding_service.embed(focus)
    except EmbeddingContentTooLargeError as exc:
        raise ToolError(
            f"Invalid focus text: {exc.content_length} characters exceeds the "
            "embedding model's input limit. Use a shorter focus description "
            "(5-10 words recommended)."
        ) from exc
    except EmbeddingServiceUnavailableError as exc:
        raise ToolError(
            f"Embedding service is unavailable: {exc.reason}. Session focus was "
            "not set. Retry after the embedding service recovers."
        ) from exc
    except EmbeddingServiceError as exc:
        raise ToolError(
            f"Failed to embed focus text: {exc}. Session focus was not set."
        ) from exc

    valkey = get_valkey_client()
    try:
        result = await valkey.write_session_focus(
            session_id=session_id,
            focus=focus,
            focus_vector=focus_vector,
            user_id=user_id,
            project=project,
        )
    except ValkeyUnavailableError as exc:
        raise ToolError(
            f"Session focus store is unavailable: {exc}. Focus was not recorded; "
            "retry after the backend recovers."
        ) from exc

    if ctx is not None:
        await ctx.info(
            f"Session focus recorded for {user_id} in project {project}: {focus!r}"
        )

    return {
        "session_id": session_id,
        "user_id": user_id,
        "project": project,
        "focus": focus,
        "expires_at": result["expires_at"],
        "message": (
            f"Session focus recorded for {user_id} in project {project}. "
            f"Active-session record expires at {result['expires_at']}."
        ),
    }


async def _handle_focus_history(
    project: str,
    start_date: str | None,
    end_date: str | None,
    ctx: Context | None,
) -> dict[str, Any]:
    """Aggregate per-project focus declarations into a sorted histogram."""
    try:
        get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, or "
            "provide a JWT in the Authorization header."
        ) from None

    parsed_end = _parse_iso_date("end_date", end_date)
    parsed_start = _parse_iso_date("start_date", start_date)

    if parsed_end is None:
        parsed_end = datetime.now(timezone.utc).date()
    if parsed_start is None:
        parsed_start = parsed_end - timedelta(days=_DEFAULT_WINDOW_DAYS)

    if parsed_start > parsed_end:
        raise ToolError(
            f"start_date ({parsed_start.isoformat()}) is after end_date "
            f"({parsed_end.isoformat()}). Provide dates as YYYY-MM-DD where "
            "start_date <= end_date."
        )

    valkey = get_valkey_client()
    try:
        entries = await valkey.read_focus_history(
            project=project,
            start_date=parsed_start,
            end_date=parsed_end,
        )
    except ValkeyUnavailableError as exc:
        raise ToolError(
            f"Session focus store is unavailable: {exc}. Histogram data cannot "
            "be retrieved until the backend recovers."
        ) from exc

    counts: dict[str, int] = {}
    for entry in entries:
        focus_val = entry.get("focus")
        if not isinstance(focus_val, str) or not focus_val:
            continue
        counts[focus_val] = counts.get(focus_val, 0) + 1

    # Sort by count descending, then alphabetically by focus for stable ordering.
    histogram = [
        {"focus": f, "count": c}
        for f, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    if ctx is not None:
        await ctx.info(
            f"Focus history query for {project}: {len(entries)} declarations, "
            f"{len(histogram)} distinct topics over "
            f"{parsed_start.isoformat()}..{parsed_end.isoformat()}"
        )

    return {
        "project": project,
        "start_date": parsed_start.isoformat(),
        "end_date": parsed_end.isoformat(),
        "total_sessions": len(entries),
        "histogram": histogram,
    }
