"""Suggest that two memories should be merged into one."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.core.authz import get_claims_from_context, authorize_read, AuthenticationError
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.models.schemas import RelationshipCreate
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship as create_relationship_service
from memoryhub_core.services.memory import read_memory as _read_memory


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def suggest_merge(
    memory_a_id: Annotated[
        str,
        Field(description="UUID of the first memory."),
    ],
    memory_b_id: Annotated[
        str,
        Field(description="UUID of the second memory."),
    ],
    reasoning: Annotated[
        str,
        Field(description="Why these memories should be merged. Be specific."),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Suggest that two memories should be merged into one.

    Use this when you discover duplicate or overlapping memories. The suggestion
    is recorded as a 'conflicts_with' relationship between the two memories, with
    merge reasoning stored in the relationship metadata. Use get_relationships to
    find pending merge suggestions.

    You must have read access to both memories (RBAC-scoped).
    """
    if ctx:
        await ctx.info(f"Suggesting merge: {memory_a_id} + {memory_b_id}")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        return {"error": True, "message": str(exc)}

    try:
        parsed_a = uuid.UUID(memory_a_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid memory_a_id format: {memory_a_id!r}. Must be a valid UUID.",
        }

    try:
        parsed_b = uuid.UUID(memory_b_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid memory_b_id format: {memory_b_id!r}. Must be a valid UUID.",
        }

    if parsed_a == parsed_b:
        return {
            "error": True,
            "message": "memory_a_id and memory_b_id must be different.",
        }

    if not reasoning or not reasoning.strip():
        return {
            "error": True,
            "message": "reasoning cannot be empty.",
        }

    gen = None
    try:
        session, gen = await get_db_session()

        # Verify read access to both memories
        for mid, label in [(parsed_a, "memory_a_id"), (parsed_b, "memory_b_id")]:
            try:
                mem = await _read_memory(mid, session)
            except MemoryNotFoundError:
                return {"error": True, "message": f"Memory {mid} not found."}
            if not authorize_read(claims, mem):
                return {"error": True, "message": f"Not authorized to access {label} ({mid})."}

        rel_create = RelationshipCreate(
            source_id=parsed_a,
            target_id=parsed_b,
            relationship_type="conflicts_with",
            created_by=claims["sub"],
            metadata={
                "merge_suggested": True,
                "reasoning": reasoning.strip(),
                "suggested_by": claims["sub"],
            },
        )
        result = await create_relationship_service(rel_create, session)

        return {
            "relationship": result.model_dump(mode="json"),
            "message": (
                f"Merge suggestion recorded between {memory_a_id} and {memory_b_id}. "
                "Use get_relationships to find pending merge suggestions."
            ),
        }

    except MemoryNotFoundError as exc:
        return {
            "error": True,
            "message": f"Memory node {exc.memory_id} not found.",
        }
    except ValueError as exc:
        return {"error": True, "message": str(exc)}
    except Exception as exc:
        return {"error": True, "message": f"Failed to suggest merge: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
