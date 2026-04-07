"""Retrieve a memory by ID, with optional version history."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.core.authz import get_claims_from_context, authorize_read, AuthenticationError
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import get_memory_history, read_memory as _read_memory


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
    """Retrieve a memory by ID.

    Returns the node with branch_count set to the number of direct child
    branches. Branch contents are not loaded inline -- to inspect them, use
    search_memory or follow up with read_memory on a specific child ID. Use
    include_versions=true to see how the memory evolved over time.
    """
    if ctx:
        await ctx.info(f"Reading memory {memory_id}")

    # Parse memory_id to UUID
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid memory_id format: '{memory_id}'. Must be a valid UUID.",
        }

    session = None
    gen = None
    try:
        session, gen = await get_db_session()

        node = await _read_memory(parsed_id, session)

        try:
            claims = get_claims_from_context()
        except AuthenticationError as exc:
            return {"error": True, "message": str(exc)}

        if not authorize_read(claims, node):
            return {
                "error": True,
                "message": f"Not authorized to read memory {memory_id}.",
            }

        result = node.model_dump(mode="json")

        if include_versions:
            # get_memory_history returns a dict with a "versions" list plus
            # pagination metadata; embed both so callers see total_versions
            # and has_more without a follow-up call.
            history = await get_memory_history(parsed_id, session)
            result["version_history"] = {
                "versions": [v.model_dump(mode="json") for v in history["versions"]],
                "total_versions": history["total_versions"],
                "has_more": history["has_more"],
                "offset": history["offset"],
            }

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
