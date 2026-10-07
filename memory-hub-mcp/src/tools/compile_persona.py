"""Compile a standing persona synopsis from behavioral dreaming facts — WRIG-1483.

Triggered on-demand (CLI or agent call). Dreaming automatically marks the
synopsis stale when new behavioral facts land — call compile_persona to refresh.

The compiler:
  1. Queries scope=user, source=dreaming, content_type=behavioral, is_current=True
  2. Prepends user-declared pins (immutable, labeled [PINNED] in prompt)
  3. Calls the extraction LLM with a synthesis prompt (400-token cap)
  4. Retires the old synopsis (is_current=False) — preserves version chain
  5. Stores the new synopsis (source=persona_compiler, weight=1.0, embedded)
  6. Creates derived_from provenance edges to source fact nodes
  7. Clears the stale flag
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.persona import compile_persona_synopsis
from src.core.app import mcp
from src.core.authz import get_claims_from_context
from src.tools._deps import get_db_session, get_embedding_service, release_db_session

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def compile_persona(
    user_id: Annotated[
        str | None,
        Field(
            description=(
                "User ID to compile persona for. Defaults to the authenticated "
                "session user when omitted."
            )
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Scope compilation to a specific project's behavioral facts. "
                "When omitted, compiles from all user-scoped facts."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Compile a standing persona profile from behavioral dreaming facts.

    Reads all current behavioral dreaming facts for the user, synthesizes them
    into a ~400-token standing profile, and stores the result as a versioned
    synopsis node. User-declared pins (added via edit_persona) are preserved
    and take precedence over inferred facts.

    Requires MEMORYHUB_CONV_EXTRACTION_MODEL and MEMORYHUB_CONV_EXTRACTION_MODEL_URL
    (same endpoint as dreaming extraction).

    Call get_persona() to check whether a recompile is needed (is_stale=True).

    Returns: synopsis content, version, fact count, pin count, and provenance metadata.
    """
    claims = get_claims_from_context(ctx)
    if claims is None:
        raise ToolError("Not authenticated. Call register_session first.")

    resolved_user_id = user_id or claims.get("sub")
    if not resolved_user_id:
        raise ToolError("Could not resolve user_id from session. Pass user_id explicitly.")

    tenant_id = claims.get("tenant_id", "default")
    embedding_service = get_embedding_service()

    gen = None
    try:
        session, gen = await get_db_session()
        try:
            result = await compile_persona_synopsis(
                resolved_user_id,
                tenant_id,
                session,
                project_id=project_id,
                embedding_service=embedding_service,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)

    return result
