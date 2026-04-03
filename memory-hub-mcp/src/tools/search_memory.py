"""Semantic search across accessible memories via pgvector.

The primary discovery mechanism for agents -- no need to know memory IDs
upfront. Results are a mix of full content (high-weight matches) and stubs
(lower-weight matches), keeping responses token-efficient.
"""

from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub.models.schemas import MemoryNodeRead, MemoryNodeStub, MemoryScope
from memoryhub.services.memory import search_memories
from src.core.app import mcp
from src.tools._deps import get_db_session, get_embedding_service, release_db_session

VALID_SCOPES = {s.value for s in MemoryScope}


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def search_memory(
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language search query. Be specific -- "
                "'container runtime preferences' works better than 'containers'. "
                "The query is embedded and compared via cosine similarity."
            ),
        ),
    ],
    scope: Annotated[
        str | None,
        Field(
            description=(
                "Filter to a specific scope: user, project, role, organizational, enterprise. "
                "Omit to search all accessible scopes."
            ),
        ),
    ] = None,
    owner_id: Annotated[
        str | None,
        Field(
            description="Filter to a specific owner's memories (user ID or project identifier)."
        ),
    ] = None,
    max_results: Annotated[
        int,
        Field(
            description="Maximum results to return (1-50). Keep low (5-15) to avoid context bloat.",
            ge=1,
            le=50,
        ),
    ] = 10,
    weight_threshold: Annotated[
        float,
        Field(
            description="Only return memories with weight >= this value. Set to 0.8 for high-priority only.",
            ge=0.0,
            le=1.0,
        ),
    ] = 0.0,
    current_only: Annotated[
        bool,
        Field(
            description="If true, only returns current versions. Set false for forensic searches."
        ),
    ] = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """Search memories using semantic similarity. Returns ranked results as a mix of
    full content (high-weight) and lightweight stubs (lower-weight). Use read_memory
    to expand stubs that look interesting.
    """
    if not query.strip():
        raise ToolError(
            "Query cannot be empty. Provide a natural language search query."
        )

    if scope is not None and scope not in VALID_SCOPES:
        raise ToolError(
            f"Invalid scope filter: '{scope}'. "
            f"Valid scopes: {', '.join(sorted(VALID_SCOPES))}."
        )

    session, gen = await get_db_session()
    try:
        if ctx:
            await ctx.info(f"Searching memories: '{query}'")

        embedding_service = get_embedding_service()
        results = await search_memories(
            query=query,
            session=session,
            embedding_service=embedding_service,
            scope=scope,
            owner_id=owner_id,
            weight_threshold=weight_threshold,
            max_results=max_results,
            current_only=current_only,
        )

        if not results:
            return {
                "results": [],
                "total_accessible": 0,
                "message": (
                    "No memories found matching your query. "
                    "Try broader search terms or remove scope/owner filters."
                ),
            }

        formatted = []
        for item in results:
            entry = item.model_dump(mode="json")
            if isinstance(item, MemoryNodeRead):
                entry["result_type"] = "full"
            elif isinstance(item, MemoryNodeStub):
                entry["result_type"] = "stub"
            else:
                entry["result_type"] = "unknown"
            # Relevance score not yet available from the service layer;
            # placeholder until pgvector distance is surfaced.
            entry["relevance_score"] = None
            formatted.append(entry)

        return {
            "results": formatted,
            "total_accessible": len(formatted),
        }

    finally:
        await release_db_session(gen)
