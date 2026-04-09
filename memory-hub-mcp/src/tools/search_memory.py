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

from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub, MemoryScope
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.memory import (
    count_search_matches,
    search_memories,
    search_memories_with_focus,
)
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    build_authorized_scopes,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import (
    get_db_session,
    get_embedding_service,
    get_reranker_service,
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
        domains=read.domains,
    )


_DOMAIN_BOOST_PER_MATCH = 0.15  # 15% score boost per matching domain
_DOMAIN_BOOST_CAP = 0.30  # max 30% total boost


def _apply_domain_boost(
    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]],
    query_domains: list[str],
) -> list[tuple[MemoryNodeRead | MemoryNodeStub, float]]:
    """Boost results whose domain tags overlap with the query domains.

    Non-matching results keep their original score — this is a boost,
    not a filter. Results are re-sorted by boosted score.
    """
    query_set = {d.lower() for d in query_domains}
    boosted = []
    for item, score in results:
        item_domains = {d.lower() for d in (getattr(item, "domains", None) or [])}
        overlap = len(item_domains & query_set)
        if overlap > 0:
            boost = min(overlap * _DOMAIN_BOOST_PER_MATCH, _DOMAIN_BOOST_CAP)
            score = min(1.0, score * (1.0 + boost))
        boosted.append((item, score))
    boosted.sort(key=lambda x: x[1], reverse=True)
    return boosted


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
                "Filter to a specific scope: user, project, campaign, role, "
                "organizational, enterprise. Omit to search all accessible scopes."
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
    focus: Annotated[
        str | None,
        Field(
            description=(
                "Optional session focus string (e.g., 'OpenShift deployment' or "
                "'OAuth token validation'). When provided, retrieval is biased toward "
                "memories whose content matches the focus, in addition to the immediate "
                "query. Out-of-focus memories are down-weighted but not excluded -- a "
                "strong query match still surfaces them. The focus string is embedded "
                "and combined with the query via reciprocal-rank fusion (NEW-1 from "
                "the two-vector retrieval research). Pass per call rather than via "
                "register_session: stateless makes scaling and concurrency simpler."
            ),
        ),
    ] = None,
    session_focus_weight: Annotated[
        float,
        Field(
            description=(
                "Strength of the focus bias when 'focus' is set, on a 0.0 to 1.0 "
                "scale. 0.0 collapses to plain query-cosine retrieval (focus has no "
                "effect). 0.4 (the default) follows the project config schema and "
                "produced the best gain/loss ratio in benchmarking. Values above 0.6 "
                "tank cross-topic recall. Ignored when focus is None."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.4,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. When provided, campaign-scoped memories "
                "for campaigns your project is enrolled in are included in results. "
                "Omit to exclude campaign memories from search."
            ),
        ),
    ] = None,
    domains: Annotated[
        list[str] | None,
        Field(
            description=(
                "Domain tags to boost in results (e.g., ['React', 'Spring Boot']). "
                "Results with matching domains are ranked higher. Non-matching "
                "results still appear — this is a boost, not a filter."
            ),
        ),
    ] = None,
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
      - pivot_suggested (only when 'focus' was set): true if the immediate
        query embedding sits far from the session focus vector, indicating
        the user has likely pivoted off-topic. Agents should consider
        re-issuing search_memory with a fresh focus when this flag fires.
      - pivot_reason (only when 'focus' was set): human-readable explanation
        of the pivot signal -- query-to-focus distance and the threshold.

    Sizing controls:
      - mode controls full-vs-stub detail per result.
      - max_response_tokens caps total response size; results past the budget
        degrade to stubs in similarity order.
      - include_branches controls whether branches whose parent is also in the
        result set are dropped (default) or nested under their parent.

    Session focus (#58):
      - Pass 'focus' on every call (stateless). When set, retrieval uses
        two-vector NEW-1: pgvector cosine recall, cross-encoder rerank by
        query, RRF blend with focus cosine ranks. The reranker is optional
        -- when MEMORYHUB_RERANKER_URL is unset or unreachable, the path
        gracefully degrades to a cosine-rank blend.
      - session_focus_weight controls the bias strength. Default 0.4 lifts
        on-focus recall by ~10% over cosine baseline at the cost of ~10% on
        cross-topic queries. Lower (0.2) for conservative focus, higher
        (0.6) for aggressive bias.
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

    # Build RBAC visibility filter + resolve caller tenant for SQL-level
    # isolation. Tenant filter is ALWAYS applied, independent of scopes.
    authorized = build_authorized_scopes(claims)
    tenant = get_tenant_filter(claims)

    # Resolve campaign membership when project_id is provided. The
    # campaign_ids set feeds into _build_search_filters so campaign-scoped
    # memories for enrolled campaigns appear in results.
    campaign_ids: set[str] | None = None
    if project_id:
        session_for_campaign, gen_for_campaign = await get_db_session()
        try:
            campaign_ids = await get_campaigns_for_project(
                session_for_campaign, project_id, tenant,
            )
        finally:
            await release_db_session(gen_for_campaign)

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

        # Route to the focused path when a focus is declared; otherwise
        # the original cosine-only path stays on the hot code path.
        focus_meta: dict[str, Any] | None = None
        if focus and focus.strip():
            reranker = get_reranker_service()
            bundle = await search_memories_with_focus(
                query=query,
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant,
                focus_string=focus.strip(),
                session_focus_weight=session_focus_weight,
                reranker=reranker,
                scope=scope,
                owner_id=owner_id,
                weight_threshold=effective_weight_threshold,
                max_results=max_results,
                current_only=current_only,
                authorized_scopes=authorized,
                campaign_ids=campaign_ids,
            )
            results = bundle.results
            focus_meta = {
                "pivot_suggested": bundle.pivot_suggested,
                "pivot_distance": bundle.pivot_distance,
                "pivot_threshold": bundle.pivot_threshold,
                "pivot_reason": bundle.pivot_reason,
                "used_reranker": bundle.used_reranker,
                "fallback_reason": bundle.fallback_reason,
            }
        else:
            results = await search_memories(
                query=query,
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant,
                scope=scope,
                owner_id=owner_id,
                weight_threshold=effective_weight_threshold,
                max_results=max_results,
                current_only=current_only,
                authorized_scopes=authorized,
                campaign_ids=campaign_ids,
            )

        # Count all matching memories under the same filter set so the agent
        # can tell whether more matches exist beyond this page.
        total_matching = await count_search_matches(
            session=session,
            tenant_id=tenant,
            scope=scope,
            owner_id=owner_id,
            current_only=current_only,
            authorized_scopes=authorized,
            campaign_ids=campaign_ids,
        )

        # Apply domain boost before branch handling and budget packing.
        if domains and results:
            results = _apply_domain_boost(results, domains)

        if not results:
            response: dict[str, Any] = {
                "results": [],
                "total_matching": total_matching,
                "has_more": False,
                "message": (
                    "No memories found matching your query. "
                    "Try broader search terms or remove scope/owner filters."
                ),
            }
            if focus_meta is not None:
                response["pivot_suggested"] = focus_meta["pivot_suggested"]
                response["pivot_reason"] = focus_meta["pivot_reason"]
            return response

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

        response = {
            "results": formatted,
            "total_matching": total_matching,
            "has_more": total_matching > len(formatted),
        }
        if focus_meta is not None:
            # Surface only the agent-facing pivot fields by default. The
            # internal `used_reranker` and `fallback_reason` are useful
            # for operator debugging but noisy for the agent surface;
            # they are still exposed when the rerank fell back so an
            # operator can grep response logs.
            response["pivot_suggested"] = focus_meta["pivot_suggested"]
            response["pivot_reason"] = focus_meta["pivot_reason"]
            if focus_meta["fallback_reason"]:
                response["focus_fallback_reason"] = focus_meta["fallback_reason"]
        return response

    finally:
        await release_db_session(gen)
