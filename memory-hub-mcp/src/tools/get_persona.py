"""Get the compiled persona synopsis for a user — WRIG-1483.

Always-inject path: agents call this at session start BEFORE search_memory.
The synopsis is scope=user, source=persona_compiler, weight=1.0.

Staleness: when the synopsis is stale (new dreaming facts since last compile),
the response includes is_stale=True and a hint to recompile. The stale profile
is still returned — it is better than nothing.

Usage pattern in a SessionStart hook:
  1. get_persona() → inject result first (always-include, unconditional)
  2. search_memory(query=<task>) → inject search hits after
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.persona import get_current_synopsis, get_persona_status
from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context
from src.tools._deps import get_db_session, release_db_session

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_persona(
    user_id: Annotated[
        str | None,
        Field(
            description=(
                "User ID to retrieve the persona for. Defaults to the "
                "authenticated session user when omitted."
            )
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Scope the lookup to a specific project. "
                "When omitted, returns the global user-level synopsis."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Retrieve the compiled persona synopsis for a user.

    Returns the standing profile compiled from behavioral dreaming facts:
    preferences, working style, values, constraints, communication patterns,
    and current focus. Profile is ~400 tokens, weight=1.0.

    Always inject this BEFORE search_memory results. The synopsis loads
    unconditionally — it is not subject to search scoring.

    When is_stale=True, the profile reflects facts from before the most recent
    dreaming extraction. Call compile_persona() to refresh, then retry.

    Returns synopsis=None when no profile has been compiled yet.
    Run: memoryhub persona compile --user <id>
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    resolved_user_id = user_id or claims.get("sub")
    if not resolved_user_id:
        raise ToolError("Could not resolve user_id from session. Pass user_id explicitly.")

    tenant_id = claims.get("tenant_id", "default")

    gen = None
    try:
        session, gen = await get_db_session()
        node = await get_current_synopsis(
            resolved_user_id, tenant_id, session, project_id=project_id
        )
        status = await get_persona_status(
            resolved_user_id, tenant_id, session, project_id=project_id
        )
    finally:
        if gen is not None:
            await release_db_session(gen)

    if node is None:
        return {
            "synopsis": None,
            "user_id": resolved_user_id,
            "project_id": project_id,
            "is_stale": True,
            "stale_reason": "no synopsis compiled yet",
            "source_fact_count": status.get("source_fact_count", 0),
            "message": (
                f"No persona synopsis found for '{resolved_user_id}'. "
                "Run compile_persona() or 'memoryhub persona compile --user <id>'."
            ),
        }

    meta = node.metadata_ or {}
    is_stale = meta.get("stale", False)

    result: dict[str, Any] = {
        "synopsis": {
            "id": str(node.id),
            "content": node.content,
            "weight": node.weight,
            "scope": node.scope,
            "version": node.version,
            "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        },
        "user_id": resolved_user_id,
        "project_id": project_id,
        "is_stale": is_stale,
        "source_fact_count": status.get("source_fact_count", 0),
        "compiled_fact_count": meta.get("source_fact_count"),
        "inject_hint": (
            "Always inject this profile BEFORE search_memory results. "
            "It captures standing user preferences and patterns that apply every session."
        ),
    }

    if is_stale:
        result["stale_reason"] = "new dreaming facts since last compile"
        result["stale_hint"] = (
            "Call compile_persona() to refresh the profile with the latest facts."
        )

    return result
