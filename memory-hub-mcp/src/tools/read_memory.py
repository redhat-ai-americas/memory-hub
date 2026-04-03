"""Retrieve a memory by ID with optional branch depth expansion."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.tools._deps import get_db_session, release_db_session

from memoryhub.services.exceptions import MemoryNotFoundError
from memoryhub.services.memory import get_memory_history, read_memory as _read_memory


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def read_memory(
    memory_id: Annotated[
        str,
        Field(description="The UUID of the memory to read."),
    ],
    depth: Annotated[
        int,
        Field(
            description=(
                "How many levels of branches to include. "
                "0 = just this node, 1 = include direct children. "
                "Rarely need more than 1."
            ),
        ),
    ] = 0,
    include_versions: Annotated[
        bool,
        Field(
            description=(
                "If true, includes version history alongside the current content. "
                "Useful for understanding how a memory evolved."
            ),
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Retrieve a memory by ID with optional branch depth expansion.

    At depth 0, returns just the node. At depth 1, includes all direct child
    branches (rationale, provenance, etc.) with their full content. Use
    include_versions=true to see how the memory evolved over time.
    """
    if ctx:
        await ctx.info(f"Reading memory {memory_id}")

    # Parse memory_id to UUID
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        return {"error": True, "message": f"Invalid memory_id format: '{memory_id}'. Must be a valid UUID."}

    session = None
    gen = None
    try:
        session, gen = await get_db_session()

        node = await _read_memory(parsed_id, session, depth=depth)
        result = node.model_dump(mode="json")

        # Include version history if requested and we're at the node level
        if include_versions and depth == 0:
            history = await get_memory_history(parsed_id, session)
            result["version_history"] = [v.model_dump(mode="json") for v in history]

        return result

    except MemoryNotFoundError:
        return {
            "error": True,
            "message": (
                f"Memory {memory_id} not found. It may have been deleted, "
                "or you may not have access to this memory's scope."
            ),
        }
    except Exception as exc:
        return {"error": True, "message": f"Failed to read memory: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
