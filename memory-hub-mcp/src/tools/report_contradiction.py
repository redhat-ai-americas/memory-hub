"""Signal that observed behavior contradicts a stored memory."""

import uuid
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import (
    read_memory as _read_memory,
    report_contradiction as _report_contradiction,
)

CONTRADICTION_THRESHOLD = 5


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def report_contradiction(
    memory_id: Annotated[
        str,
        Field(
            description="The ID of the memory that appears to be contradicted.",
        ),
    ],
    observed_behavior: Annotated[
        str,
        Field(
            description=(
                "Description of what was observed that conflicts with the "
                "memory. Be specific: 'User created a Docker Compose project "
                "with 12 services' not just 'used Docker'."
            ),
        ),
    ],
    confidence: Annotated[
        float,
        Field(
            default=0.7,
            ge=0.0,
            le=1.0,
            description=(
                "How confident the agent is that this is a real contradiction "
                "(0.0-1.0). Temporary exceptions warrant lower confidence. "
                "Repeated, consistent contradictions warrant higher."
            ),
        ),
    ] = 0.7,
    ctx: Context = None,
) -> dict:
    """Signal that observed behavior contradicts a stored memory.

    When an agent notices the user doing something that conflicts with a stored
    preference (e.g., using Docker when the memory says "prefers Podman"), it
    reports the contradiction. The curator agent aggregates these signals and
    may trigger a memory revision prompt after enough contradictions accumulate.
    """
    if ctx:
        await ctx.info(
            f"Reporting contradiction against memory {memory_id} "
            f"(confidence: {confidence})"
        )

    if not observed_behavior.strip():
        raise ToolError(
            "observed_behavior cannot be empty. Describe what was observed "
            "that conflicts with the memory."
        )

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. "
            "Provide a valid UUID (e.g., '550e8400-e29b-41d4-a716-446655440000')."
        )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))
    reporter = claims["sub"]
    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        # Verify caller can see the memory being contradicted. The tenant
        # filter makes a cross-tenant ID indistinguishable from a
        # nonexistent row.
        target_memory = await _read_memory(parsed_id, session, tenant_id=tenant)
        if not authorize_read(claims, target_memory):
            raise ToolError(f"Not authorized to access memory {memory_id}.")

        contradiction_count = await _report_contradiction(
            memory_id=parsed_id,
            observed_behavior=observed_behavior,
            confidence=confidence,
            reporter=reporter,
            session=session,
        )

        revision_triggered = contradiction_count >= CONTRADICTION_THRESHOLD

        if revision_triggered:
            message = (
                f"Contradiction recorded ({contradiction_count} of "
                f"{CONTRADICTION_THRESHOLD} threshold). A revision prompt "
                "will be triggered — the user will be asked to review this memory."
            )
        else:
            message = (
                f"Contradiction recorded ({contradiction_count} of "
                f"{CONTRADICTION_THRESHOLD} threshold). "
                f"{CONTRADICTION_THRESHOLD - contradiction_count} more "
                "before a revision prompt is triggered."
            )

        return {
            "memory_id": memory_id,
            "contradiction_count": contradiction_count,
            "threshold": CONTRADICTION_THRESHOLD,
            "revision_triggered": revision_triggered,
            "message": message,
        }

    except MemoryNotFoundError:
        raise ToolError(
            f"Memory {memory_id} not found. "
            "It may have been deleted, or you may not have access to this "
            "memory's scope."
        )
    finally:
        await release_db_session(gen)
