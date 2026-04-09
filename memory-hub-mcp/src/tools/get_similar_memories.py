"""Get memories similar to a given memory, with similarity scores."""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

logger = logging.getLogger(__name__)

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.services.curation.similarity import get_similar_memories as get_similar_memories_service
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import read_memory as read_memory_service


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
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc
    tenant = get_tenant_filter(claims)

    try:
        parsed_memory_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: {memory_id!r}. Must be a valid UUID."
        )

    gen = None
    try:
        session, gen = await get_db_session()

        # Authorize the caller against the source memory. The similarity
        # service restricts results to (owner_id, scope, tenant_id) of the
        # source, so once the caller is allowed to read the source, every
        # returned item is in the same authorization domain. The tenant_id
        # filter in both calls makes a cross-tenant source ID indistinguishable
        # from a nonexistent row.
        source = await read_memory_service(
            parsed_memory_id, session, tenant_id=tenant
        )
        if not authorize_read(claims, source):
            raise ToolError(f"Not authorized to read memory {memory_id}.")

        result = await get_similar_memories_service(
            parsed_memory_id,
            session,
            tenant_id=tenant,
            threshold=threshold,
            max_results=max_results,
            offset=offset,
        )

        # Serialize UUIDs in results for JSON
        for item in result.get("results", []):
            if "id" in item:
                item["id"] = str(item["id"])

        return result

    except ToolError:
        raise
    except MemoryNotFoundError as exc:
        raise ToolError(f"Memory {exc.memory_id} not found.")
    except Exception as exc:
        logger.error("Failed to get similar memories for %s: %s", memory_id, exc, exc_info=True)
        raise ToolError(
            f"Failed to get similar memories for {memory_id}. See server logs for details."
        ) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
