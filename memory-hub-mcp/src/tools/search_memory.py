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
from memoryhub.services.memory import count_search_matches, search_memories
from src.core.app import mcp
from src.core.authz import (
    get_claims_from_context,
    build_authorized_scopes,
    AuthenticationError,
)
from src.tools._deps import (
    get_db_session,
    get_embedding_service,
    release_db_session,
)

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
            description=(
                "Filter to a specific owner's memories (user ID or project identifier). "
                "Omit to default to your authenticated user_id (requires register_session). "
                "Pass an empty string to search across all owners without filtering."
            )
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

    Response fields:
      - results: the page of ranked matches (size <= max_results).
      - total_matching: total count of memories matching the filter set
        (scope/owner/current_only/RBAC), independent of max_results. Use this
        to display "showing N of M" or to gauge whether to broaden the query.
      - has_more: true when total_matching > len(results); indicates that
        narrowing filters or paging would reveal additional matches.
    """
    if not query.strip():
        raise ToolError(
            "Query cannot be empty. Provide a natural language search query."
        )

    # Resolve caller identity via JWT or session fallback.
    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))

    # Build RBAC visibility filter
    authorized = build_authorized_scopes(claims)

    # Resolve owner_id: default to authenticated user when not explicitly set.
    # An empty string signals "no filter" (search all accessible owners).
    if owner_id is None:
        owner_id = claims["sub"]
    elif owner_id == "":
        owner_id = None

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
            authorized_scopes=authorized,
        )

        # Count all matching memories under the same filter set so the agent
        # can tell whether more matches exist beyond this page.
        total_matching = await count_search_matches(
            session=session,
            scope=scope,
            owner_id=owner_id,
            current_only=current_only,
            authorized_scopes=authorized,
        )

        if not results:
            return {
                "results": [],
                "total_matching": total_matching,
                "has_more": False,
                "message": (
                    "No memories found matching your query. "
                    "Try broader search terms or remove scope/owner filters."
                ),
            }

        formatted = []
        for item, relevance_score in results:
            entry = item.model_dump(mode="json")
            if isinstance(item, MemoryNodeRead):
                entry["result_type"] = "full"
            elif isinstance(item, MemoryNodeStub):
                entry["result_type"] = "stub"
            else:
                entry["result_type"] = "unknown"
            entry["relevance_score"] = round(relevance_score, 4)
            formatted.append(entry)

        return {
            "results": formatted,
            "total_matching": total_matching,
            "has_more": total_matching > len(formatted),
        }

    finally:
        await release_db_session(gen)
