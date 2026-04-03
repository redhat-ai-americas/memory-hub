"""Get the full version history of a memory."""

import uuid
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.tools._deps import get_db_session, release_db_session

from memoryhub.services.exceptions import MemoryNotFoundError
from memoryhub.services.memory import get_memory_history as _get_memory_history


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_memory_history(
    memory_id: Annotated[
        str,
        Field(
            description=(
                "The ID of any version of the memory (current or historical). "
                "The tool traces the full version chain regardless of which "
                "version ID you provide."
            ),
        ),
    ],
    ctx: Context = None,
) -> dict:
    """Get the full version history of a memory.

    Shows how the memory evolved over time: what changed, when, and what the
    previous content was. Supports forensics ("what did the agent believe on
    March 15th?") and helps agents understand context drift.

    Returns versions ordered newest-first with full content for each version.
    """
    if ctx:
        await ctx.info(f"Fetching version history for memory {memory_id}")

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. "
            "Provide a valid UUID (e.g., '550e8400-e29b-41d4-a716-446655440000')."
        )

    session, gen = await get_db_session()
    try:
        history = await _get_memory_history(parsed_id, session)

        versions = [
            {
                "version": v.version,
                "content": v.stub,  # MemoryVersionInfo carries stub
                "stub": v.stub,
                "is_current": v.is_current,
                "created_at": v.created_at.isoformat(),
                "id": str(v.id),
            }
            for v in history
        ]

        if len(versions) == 1:
            message = (
                "This memory has no version history "
                f"(version {versions[0]['version']}, never updated)."
            )
        else:
            current = next((v for v in versions if v["is_current"]), versions[0])
            message = (
                f"{len(versions)} versions found. "
                f"Current is version {current['version']}."
            )

        return {
            "memory_id": memory_id,
            "versions": versions,
            "total_versions": len(versions),
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
