"""Return paged similar memories for a given memory ID."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.tools._deps import get_db_session, release_db_session
from src.tools.auth import require_auth

from memoryhub.services.curation.similarity import get_similar_memories as _get_similar_memories
from memoryhub.services.exceptions import MemoryNotFoundError


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_similar_memories(
    memory_id: Annotated[
        str,
        Field(description="UUID of the memory to find similar memories for."),
    ],
    threshold: Annotated[
        float,
        Field(description="Minimum cosine similarity (0.0-1.0). Default: 0.80.", ge=0.0, le=1.0),
    ] = 0.80,
    max_results: Annotated[
        int,
        Field(description="Maximum results per page. Default: 10.", ge=1, le=50),
    ] = 10,
    offset: Annotated[
        int,
        Field(description="Pagination offset. Default: 0.", ge=0),
    ] = 0,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get memories similar to a given memory, with similarity scores.

    Use this to investigate when write_memory reports similar_count > 0. Returns
    paged results to avoid context bloat — start with a small page and increase
    if needed. Each result includes the memory stub and a similarity score.
    """
    if ctx:
        await ctx.info(f"Finding memories similar to {memory_id!r} (threshold={threshold})")

    try:
        require_auth()
    except RuntimeError as exc:
        return {"error": True, "message": str(exc)}

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid memory_id format: {memory_id!r}. Must be a valid UUID.",
        }

    session = None
    gen = None
    try:
        session, gen = await get_db_session()
        result = await _get_similar_memories(
            memory_id=parsed_id,
            session=session,
            threshold=threshold,
            max_results=max_results,
            offset=offset,
        )
        # Normalise UUIDs to strings for JSON serialisation
        for item in result.get("results", []):
            if "id" in item and isinstance(item["id"], uuid.UUID):
                item["id"] = str(item["id"])
        return result

    except MemoryNotFoundError as exc:
        return {
            "error": True,
            "message": (
                f"Memory {exc.memory_id} not found. "
                "Verify the memory_id refers to an existing memory node."
            ),
        }
    except Exception as exc:
        return {"error": True, "message": f"Failed to fetch similar memories: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
