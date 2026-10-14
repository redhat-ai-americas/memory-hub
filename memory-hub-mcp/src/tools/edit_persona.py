"""Add user-declared facts that survive persona recompilation — WRIG-1483.

User pins are stored as branch_type="fact", source="user" children of the
current synopsis node. On every recompile, pins are prepended to the LLM
prompt as [PINNED] facts with higher authority than dreaming-inferred facts.

Use this when the user explicitly states something they want permanently
reflected in their persona (e.g. "I'm switching to Rust", "I now prefer
pair programming over async reviews").
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.persona import add_user_pin, get_current_synopsis, get_user_pins
from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context
from src.tools._deps import get_db_session, release_db_session

logger = logging.getLogger(__name__)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def edit_persona(
    action: Annotated[
        str,
        Field(description="Action: 'add_pin' to add a user-declared fact, 'list_pins' to view existing pins."),
    ],
    content: Annotated[
        str | None,
        Field(
            description=(
                "The fact to pin (required for action='add_pin'). "
                "State it as a self-contained sentence: "
                "'I prefer Rust over Python for systems code.' "
                "Pins are labeled [PINNED] and take precedence over inferred facts."
            )
        ),
    ] = None,
    user_id: Annotated[
        str | None,
        Field(description="User ID. Defaults to authenticated session user."),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Add or list user-declared persona facts that survive recompilation.

    Actions:
      add_pin  — Store a user-declared fact. Pinned facts are prepended to
                 every future persona compile as authoritative [PINNED] facts
                 that override any conflicting inferred fact.
      list_pins — Return all currently pinned facts for the user.

    After adding a pin, the current synopsis is not automatically recompiled.
    Call compile_persona() to incorporate it immediately, or wait for the
    next scheduled compile.
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    resolved_user_id = user_id or claims.get("sub")
    if not resolved_user_id:
        raise ToolError("Could not resolve user_id. Pass user_id explicitly.")

    tenant_id = claims.get("tenant_id", "default")

    if action not in ("add_pin", "list_pins"):
        raise ToolError(f"Unknown action '{action}'. Use 'add_pin' or 'list_pins'.")

    gen = None
    try:
        session, gen = await get_db_session()

        if action == "list_pins":
            current = await get_current_synopsis(resolved_user_id, tenant_id, session)
            synopsis_id = current.id if current is not None else None
            pins = await get_user_pins(resolved_user_id, tenant_id, session, synopsis_id=synopsis_id)
            return {
                "pins": pins,
                "user_id": resolved_user_id,
                "synopsis_id": str(synopsis_id) if synopsis_id else None,
                "count": len(pins),
            }

        # add_pin
        if not content or not content.strip():
            raise ToolError("content is required for action='add_pin'.")

        result = await add_user_pin(
            resolved_user_id, tenant_id, content.strip(), session
        )
        return result

    finally:
        if gen is not None:
            await release_db_session(gen)
