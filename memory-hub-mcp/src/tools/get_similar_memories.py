"""Get memories similar to a given memory, with similarity scores."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.tools._deps import get_db_session, release_db_session
from src.tools.auth import require_auth

from memoryhub.services.curation.similarity import get_similar_memories as get_similar_memories_service
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
        Field(
            description="Minimum cosine similarity (0.0-1.0). Default: 0.80.",
            ge=0.0,
            le=1.0,
        ),
    ] = 0.80,
    max_results: Annotated[
        int,
        Field(
            description="Maximum results per page. Default: 10.",
            ge=1,
            le=50,
        ),
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
        await ctx.info(f"Finding memories similar to {memory_id}")

    try:
        require_auth()
    except RuntimeError as exc:
        return {"error": True, "message": str(exc)}

    try:
        parsed_memory_id = uuid.UUID(memory_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid memory_id format: {memory_id!r}. Must be a valid UUID.",
        }

    gen = None
    try:
        session, gen = await get_db_session()
        result = await get_similar_memories_service(
            parsed_memory_id,
            session,
            threshold=threshold,
            max_results=max_results,
            offset=offset,
        )

        # Serialize UUIDs in results for JSON
        for item in result.get("results", []):
            if "id" in item:
                item["id"] = str(item["id"])

        return result

    except MemoryNotFoundError as exc:
        return {
            "error": True,
            "message": f"Memory {exc.memory_id} not found.",
        }
    except Exception as exc:
        return {"error": True, "message": f"Failed to get similar memories: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
