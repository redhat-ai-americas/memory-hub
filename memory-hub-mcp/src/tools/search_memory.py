"""Semantic search across accessible memories via pgvector.

The primary discovery mechanism for agents -- no need to know memory IDs
upfront. Results are a mix of full content (high-weight matches) and stubs
(lower-weight matches), keeping responses token-efficient.
"""

import json
from typing import Annotated, Any, Literal

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

# Rough chars-per-token heuristic for budgeting. Conservative -- it
# over-estimates a bit (real ratios for English JSON are closer to 3.5)
# so the actual response stays under the cap.
_CHARS_PER_TOKEN = 4


def _to_stub(read: MemoryNodeRead) -> MemoryNodeStub:
    """Project a MemoryNodeRead down to its stub form, preserving parent_id
    so branch handling continues to work after a full→stub degradation."""
    return MemoryNodeStub(
        id=read.id,
        parent_id=read.parent_id,
        stub=read.stub,
        scope=read.scope,
        weight=read.weight,
        branch_type=read.branch_type,
        has_children=read.has_children,
        has_rationale=read.has_rationale,
    )


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Estimate the token cost of a serialized result entry."""
    return max(1, len(json.dumps(payload, default=str)) // _CHARS_PER_TOKEN)


def _format_entry(
    item: MemoryNodeRead | MemoryNodeStub,
    relevance_score: float,
    nested_branches: list[tuple[MemoryNodeRead | MemoryNodeStub, float]],
) -> tuple[dict[str, Any], int]:
    """Build the JSON-ready dict for one result entry and estimate its cost.

    nested_branches is the list of branch results (with their scores) that
    should appear under this entry's "branches" field. Pass an empty list
    when not nesting.
    """
    entry = item.model_dump(mode="json")
    entry["result_type"] = "full" if isinstance(item, MemoryNodeRead) else "stub"
    entry["relevance_score"] = round(relevance_score, 4)
    if nested_branches:
        branch_entries: list[dict[str, Any]] = []
        for branch_item, branch_score in nested_branches:
            branch_entry = branch_item.model_dump(mode="json")
            branch_entry["result_type"] = (
                "full" if isinstance(branch_item, MemoryNodeRead) else "stub"
            )
            branch_entry["relevance_score"] = round(branch_score, 4)
            branch_entries.append(branch_entry)
        entry["branches"] = branch_entries
    return entry, _estimate_tokens(entry)


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
            description=(
                "Memories with weight below this value return as stubs instead of full "
                "content. Set to 0.8 to stub low-priority matches. Ignored when mode='full_only'."
            ),
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
    mode: Annotated[
        Literal["full", "index", "full_only"],
        Field(
            description=(
                "Result detail mode. 'full' (default) returns full content for "
                "weight >= weight_threshold and stubs below it. 'index' returns "
                "stubs for everything regardless of weight (use for exploratory "
                "'what's in here?' or audit searches). 'full_only' ignores "
                "weight_threshold so weight alone never causes stubbing (use for "
                "specific-question answering when zero round-trips matters). Note "
                "that max_response_tokens can still degrade entries to stubs once "
                "the budget is hit -- to guarantee full content end-to-end, raise "
                "max_response_tokens or lower max_results in addition to setting "
                "mode='full_only'."
            ),
        ),
    ] = "full",
    max_response_tokens: Annotated[
        int,
        Field(
            description=(
                "Soft cap on the total response token cost. Results are packed in "
                "similarity order; once the cap is reached, remaining matches degrade "
                "to stubs. Stubs are always included regardless of cap so the agent "
                "never silently misses a ranked match. Default 4000."
            ),
            ge=100,
            le=20000,
        ),
    ] = 4000,
    include_branches: Annotated[
        bool,
        Field(
            description=(
                "Branch handling. Default false omits branches (rationale, provenance, "
                "etc.) whose parent is already in the result set -- the agent can drill "
                "in via read_memory using has_rationale/has_children flags. Set true to "
                "receive those branches nested under their parent in a 'branches' field. "
                "Branches whose parent is NOT in the result set are always returned as "
                "top-level entries regardless of this flag."
            ),
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Search memories using semantic similarity. Returns ranked results as a mix of
    full content (high-weight) and lightweight stubs (lower-weight). Use read_memory
    to expand stubs that look interesting.

    Response fields:
      - results: the page of ranked matches (size <= max_results, possibly less
        when branches were omitted by the default branch-handling rule). Each
        entry has result_type ('full' or 'stub'), relevance_score, and -- when
        include_branches=True -- a 'branches' list of nested branch entries.
      - total_matching: total count of memories matching the filter set
        (scope/owner/current_only/RBAC), independent of max_results and of any
        in-memory branch omission. Use this to display "showing N of M".
      - has_more: true when total_matching > len(results); indicates that
        narrowing filters or paging would reveal additional matches.

    Sizing controls:
      - mode controls full-vs-stub detail per result.
      - max_response_tokens caps total response size; results past the budget
        degrade to stubs in similarity order.
      - include_branches controls whether branches whose parent is also in the
        result set are dropped (default) or nested under their parent.
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

    # mode='full_only' overrides weight_threshold so the service never stubs.
    effective_weight_threshold = 0.0 if mode == "full_only" else weight_threshold

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
            weight_threshold=effective_weight_threshold,
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

        # mode='index' degrades every full result to stub form. Done before
        # branch handling so nested branches are also stubs in this mode.
        if mode == "index":
            results = [
                ((_to_stub(item) if isinstance(item, MemoryNodeRead) else item), score)
                for item, score in results
            ]

        # Branch handling: identify branches whose parent is also in the result
        # set. Default behavior drops them; include_branches=True nests them
        # under the parent in a 'branches' field.
        result_id_set = {str(item.id) for item, _ in results}
        top_level: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
        nested_by_parent: dict[
            str, list[tuple[MemoryNodeRead | MemoryNodeStub, float]]
        ] = {}
        for item, score in results:
            parent_id = getattr(item, "parent_id", None)
            if parent_id is not None and str(parent_id) in result_id_set:
                if include_branches:
                    nested_by_parent.setdefault(str(parent_id), []).append((item, score))
                # else: drop the branch; the parent's has_rationale/has_children
                # flags tell the agent it can drill in via read_memory.
            else:
                top_level.append((item, score))

        # Token-budget packing. Walk results in similarity order; full-form
        # entries that exceed the remaining budget (and everything after them)
        # are degraded to stub form. Stubs are still included so the agent
        # never silently misses a match.
        budget = max_response_tokens
        budget_exhausted = False
        formatted: list[dict[str, Any]] = []
        for item, relevance_score in top_level:
            child_branches = nested_by_parent.get(str(item.id), [])

            if budget_exhausted:
                # Already over budget -- everything from here on is stub form.
                output_item = (
                    _to_stub(item) if isinstance(item, MemoryNodeRead) else item
                )
                output_branches = [
                    (
                        (_to_stub(b) if isinstance(b, MemoryNodeRead) else b),
                        s,
                    )
                    for b, s in child_branches
                ]
                entry, cost = _format_entry(
                    output_item, relevance_score, output_branches
                )
                formatted.append(entry)
                budget = max(0, budget - cost)
                continue

            # Try the full form first.
            entry, cost = _format_entry(item, relevance_score, child_branches)
            if isinstance(item, MemoryNodeStub) or cost <= budget:
                # Either it's already a stub (no degradation possible) or it
                # fits the budget. Either way, include as-is.
                formatted.append(entry)
                budget = max(0, budget - cost)
            else:
                # Too expensive: degrade this entry and switch to exhausted mode
                # so subsequent entries are also stubbed.
                budget_exhausted = True
                stub_item = _to_stub(item)
                stub_branches = [
                    (
                        (_to_stub(b) if isinstance(b, MemoryNodeRead) else b),
                        s,
                    )
                    for b, s in child_branches
                ]
                stub_entry, stub_cost = _format_entry(
                    stub_item, relevance_score, stub_branches
                )
                formatted.append(stub_entry)
                budget = max(0, budget - stub_cost)

        return {
            "results": formatted,
            "total_matching": total_matching,
            "has_more": total_matching > len(formatted),
        }

    finally:
        await release_db_session(gen)
