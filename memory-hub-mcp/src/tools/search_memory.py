"""Semantic search across accessible memories via pgvector.

The primary discovery mechanism for agents -- no need to know memory IDs
upfront. Results are returned in cache-optimized order by default (stable
ordering for KV cache efficiency), with a ``raw_results`` flag to opt into
legacy similarity-ranked output. Result detail is a mix of full content
(high-weight matches) and stubs (lower-weight matches), keeping responses
token-efficient.
"""

import json
import logging
import uuid as uuid_mod
from typing import Annotated, Any, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub, MemoryScope
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.compilation import (
    CompilationEpoch,
    apply_compilation,
    compile_memory_set,
    should_recompile,
)
from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.memory import (
    _build_search_filters,
    _bulk_branch_flags,
    count_search_matches,
    node_to_read,
    search_memories,
    search_memories_with_focus,
)
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    PROJECT_ISOLATION_ENABLED,
    ROLE_ISOLATION_ENABLED,
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

logger = logging.getLogger(__name__)

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
        created_at=read.created_at,
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
    # Guide agents from chunk hits to the parent memory's full content
    if item.branch_type == "chunk" and item.parent_id is not None:
        entry["parent_hint"] = (
            f"This is a chunk of a larger memory. Call "
            f"read_memory('{item.parent_id}', hydrate=true) for full content."
        )
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


def _format_entry_cached(
    item: MemoryNodeRead | MemoryNodeStub,
    nested_branches: list[tuple[MemoryNodeRead | MemoryNodeStub, float]],
    is_appendix: bool = False,
) -> tuple[dict[str, Any], int]:
    """Build cache-optimized entry -- no relevance_score, adds is_appendix."""
    entry = item.model_dump(mode="json")
    entry["result_type"] = "full" if isinstance(item, MemoryNodeRead) else "stub"
    entry["is_appendix"] = is_appendix
    if item.branch_type == "chunk" and item.parent_id is not None:
        entry["parent_hint"] = (
            f"This is a chunk of a larger memory. Call "
            f"read_memory('{item.parent_id}', hydrate=true) for full content."
        )
    if nested_branches:
        branch_entries: list[dict[str, Any]] = []
        for branch_item, _score in nested_branches:
            branch_entry = branch_item.model_dump(mode="json")
            branch_entry["result_type"] = (
                "full" if isinstance(branch_item, MemoryNodeRead) else "stub"
            )
            branch_entries.append(branch_entry)
        entry["branches"] = branch_entries
    return entry, _estimate_tokens(entry)


async def _apply_cache_optimized_ordering(
    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]],
    tenant_id: str,
    owner_id: str,
) -> dict[str, Any] | None:
    """Apply compilation-epoch ordering for cache-stable responses.

    Returns a dict with:
      - ordered_results: list of (item, score, is_appendix) triples
      - compilation_hash: str
      - compilation_epoch: int
      - appendix_count: int

    Returns None if results are empty. Falls back to deterministic sort
    (no Valkey state) if Valkey is unavailable.
    """
    if not results:
        return None

    valkey = get_valkey_client()

    try:
        existing_data = await valkey.read_compilation(tenant_id, owner_id)
    except ValkeyUnavailableError:
        logger.warning("Valkey unavailable; falling back to deterministic sort")
        existing_data = None

    if existing_data is not None:
        epoch = CompilationEpoch.from_dict(existing_data)
        compiled, appendix = apply_compilation(results, epoch)

        if should_recompile(len(compiled), len(appendix)):
            new_epoch = compile_memory_set(results, epoch=epoch.epoch + 1)
            try:
                await valkey.write_compilation(
                    tenant_id, owner_id, new_epoch.to_dict()
                )
            except ValkeyUnavailableError:
                logger.warning("Valkey unavailable; recompile not persisted")
            ordered = [(item, score, False) for item, score in results]
            id_order = {mid: i for i, mid in enumerate(new_epoch.ordered_ids)}
            ordered.sort(key=lambda t: id_order.get(str(t[0].id), len(id_order)))
            return {
                "ordered_results": ordered,
                "compilation_hash": new_epoch.compilation_hash,
                "compilation_epoch": new_epoch.epoch,
                "appendix_count": 0,
            }

        # Normal case: compiled in epoch order, appendix at end
        ordered = [(item, score, False) for item, score in compiled]
        ordered.extend((item, score, True) for item, score in appendix)
        return {
            "ordered_results": ordered,
            "compilation_hash": epoch.compilation_hash,
            "compilation_epoch": epoch.epoch,
            "appendix_count": len(appendix),
        }

    # No existing compilation -- create the first one
    new_epoch = compile_memory_set(results, epoch=1)
    try:
        await valkey.write_compilation(tenant_id, owner_id, new_epoch.to_dict())
    except ValkeyUnavailableError:
        logger.warning("Valkey unavailable; initial compilation not persisted")

    ordered = [(item, score, False) for item, score in results]
    id_order = {mid: i for i, mid in enumerate(new_epoch.ordered_ids)}
    ordered.sort(key=lambda t: id_order.get(str(t[0].id), len(id_order)))
    return {
        "ordered_results": ordered,
        "compilation_hash": new_epoch.compilation_hash,
        "compilation_epoch": new_epoch.epoch,
        "appendix_count": 0,
    }


async def _backfill_compiled_entries(
    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]],
    session: Any,
    tenant_id: str,
    owner_id: str,
    weight_threshold: float,
    scope: str | None = None,
    authorized_scopes: dict[str, str | None] | None = None,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
    current_only: bool = True,
) -> list[tuple[MemoryNodeRead | MemoryNodeStub, float]]:
    """Ensure compiled entries are present in the result set.

    The similarity search limits results to max_results by cosine score,
    which can exclude compiled entries that rank lower by similarity but
    belong in the cache-stable prefix. This function:

    1. Peeks at the current compilation epoch from Valkey
    2. Finds epoch IDs missing from the similarity results
    3. Loads those from the database applying the same scope/project filters
       as the main search, so backfilled entries are always in-scope
    4. Appends them to the results so _apply_cache_optimized_ordering
       can place them in their correct epoch positions

    Returns the (possibly extended) results list. No-op if Valkey is
    unavailable or no epoch exists.
    """
    compilation_owner = owner_id if owner_id is not None else "*"
    valkey = get_valkey_client()

    try:
        existing_data = await valkey.read_compilation(tenant_id, compilation_owner)
    except ValkeyUnavailableError:
        return results

    if existing_data is None:
        return results

    epoch = CompilationEpoch.from_dict(existing_data)
    if not epoch.ordered_ids:
        return results

    # Find compiled IDs missing from the similarity results.
    result_ids = {str(item.id) for item, _ in results}
    missing_ids = [
        mid for mid in epoch.ordered_ids if mid not in result_ids
    ]
    if not missing_ids:
        return results

    # Load missing memories from DB, filtered by tenant.
    from sqlalchemy import select

    missing_uuids = []
    for mid in missing_ids:
        try:
            missing_uuids.append(uuid_mod.UUID(mid))
        except ValueError:
            continue

    if not missing_uuids:
        return results

    # Build the same scope/project filters used by the main search so
    # backfilled entries are always within the caller's authorized view.
    # _build_search_filters returns None when authorized_scopes is non-None
    # but empty — that means the caller can see nothing, so bail out.
    scope_filters = _build_search_filters(
        scope=scope,
        owner_id=owner_id,
        current_only=current_only,
        authorized_scopes=authorized_scopes,
        tenant_id=tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
    )
    if scope_filters is None:
        return results

    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.id.in_(missing_uuids),
            *scope_filters,
        )
    )
    db_result = await session.execute(stmt)
    nodes = db_result.scalars().all()

    if not nodes:
        return results

    # Build MemoryNodeRead/Stub entries for the backfilled items.
    node_ids = [n.id for n in nodes]
    branch_flags = await _bulk_branch_flags(node_ids, session)

    backfilled: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for node in nodes:
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        # Score 0.0: these weren't in the similarity results; the
        # compilation ordering ignores scores for compiled entries.
        if node.weight >= weight_threshold:
            backfilled.append((
                node_to_read(
                    node,
                    has_children=has_children,
                    has_rationale=has_rationale,
                    branch_count=branch_count,
                ),
                0.0,
            ))
        else:
            backfilled.append((
                MemoryNodeStub(
                    id=node.id,
                    parent_id=node.parent_id,
                    stub=node.stub,
                    scope=node.scope,
                    weight=node.weight,
                    branch_type=node.branch_type,
                    has_children=has_children,
                    has_rationale=has_rationale,
                    created_at=node.created_at,
                ),
                0.0,
            ))

    logger.debug(
        "Backfilled %d compiled entries missing from similarity results",
        len(backfilled),
    )
    return results + backfilled


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
                "(Advanced) Filter to a specific owner's memories. "
                "Omit to default to your user_id. "
                "Pass empty string to search across all owners."
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
                "(Advanced) Memories with weight below this value return as stubs "
                "instead of full content. Default 0.0 (all full)."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.0,
    current_only: Annotated[
        bool,
        Field(
            description="(Advanced) If true, only returns current versions. Set false for forensic searches."
        ),
    ] = True,
    mode: Annotated[
        Literal["full", "index", "full_only"],
        Field(
            description=(
                "(Advanced) Result detail mode. 'full' (default): full content "
                "for high-weight matches, stubs for low. 'index': stubs only "
                "(for exploratory searches). 'full_only': always full content."
            ),
        ),
    ] = "full",
    max_response_tokens: Annotated[
        int,
        Field(
            description=(
                "(Advanced) Soft cap on total response tokens. Past this cap, "
                "remaining results degrade to stubs. Default 4000."
            ),
            ge=100,
            le=20000,
        ),
    ] = 4000,
    include_branches: Annotated[
        bool,
        Field(
            description=(
                "(Advanced) If true, nest branch memories (rationale, provenance) "
                "under their parent. Default false omits them — use read_memory "
                "to drill in when has_rationale or has_children is flagged."
            ),
        ),
    ] = False,
    focus: Annotated[
        str | None,
        Field(
            description=(
                "(Advanced) Session focus string (e.g., 'OpenShift deployment'). "
                "Biases retrieval toward memories matching this focus in addition "
                "to the query. Pass on every call (stateless)."
            ),
        ),
    ] = None,
    session_focus_weight: Annotated[
        float,
        Field(
            description=(
                "(Advanced) Focus bias strength (0.0-1.0). Default 0.4. "
                "Higher values favor on-focus recall. Ignored when focus is None."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.4,
    domain_boost_weight: Annotated[
        float,
        Field(
            description=(
                "(Advanced) Domain boost strength (0.0-1.0). Default 0.3. "
                "Ignored when domains is not set."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.3,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Restricts project-scoped results to "
                "this project only. Also resolves campaign-scoped memories for "
                "campaigns this project is enrolled in. Omit to include project "
                "memories from ALL projects you belong to."
            ),
        ),
    ] = None,
    domains: Annotated[
        list[str] | None,
        Field(
            description=(
                "(Advanced) Domain tags to boost in results (e.g., ['React']). "
                "Matching results rank higher. Non-matching still appear."
            ),
        ),
    ] = None,
    graph_depth: Annotated[
        int,
        Field(
            description=(
                "(Advanced) Hop depth for graph-enhanced retrieval. "
                "When > 0, follows relationships from vector search results to "
                "surface connected memories. 0 (default) disables graph traversal. Max 3."
            ),
            ge=0,
            le=3,
        ),
    ] = 0,
    graph_relationship_types: Annotated[
        list[str] | None,
        Field(
            description=(
                "(Advanced) Limit graph traversal to these relationship types "
                "(e.g., ['derived_from', 'related_to']). Null means all types. "
                "Only used when graph_depth > 0."
            ),
        ),
    ] = None,
    graph_boost_weight: Annotated[
        float,
        Field(
            description=(
                "(Advanced) Graph proximity boost strength (0.0-1.0). Default 0.2. "
                "Higher values favor graph-connected memories. "
                "Ignored when graph_depth is 0."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.2,
    raw_results: Annotated[
        bool,
        Field(
            description=(
                "(Advanced) When True, return results ranked by similarity "
                "score instead of cache-optimized stable ordering. Default False."
            ),
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Search memories using semantic similarity.

    Quick start — simplest call:
      search_memory(query="deployment preferences")
    With project filter:
      search_memory(query="deployment preferences", project_id="my-project")

    By default, results are returned in cache-optimized order: a stable,
    deterministic ordering driven by compilation epochs (#175) that maximizes
    KV cache hit rates when the response is injected into prompts. New
    memories since the last compilation appear in an appendix section
    (is_appendix=True). Set raw_results=True to revert to legacy
    similarity-ranked output with relevance_score per entry.

    Response fields:
      - results: the page of matches (size <= max_results, possibly less
        when branches were omitted by the default branch-handling rule).
        In cache-optimized mode (default), each entry has result_type
        ('full' or 'stub') and is_appendix (bool). In raw mode, each
        entry has result_type and relevance_score (float). Both modes
        support 'branches' (when include_branches=True).
      - total_matching: total count of memories matching the filter set
        (scope/owner/current_only/RBAC), independent of max_results and of any
        in-memory branch omission. Use this to display "showing N of M".
      - has_more: true when total_matching > len(results); indicates that
        narrowing filters or paging would reveal additional matches.
      - compilation_hash (cache-optimized mode only): SHA-256 of the
        compilation epoch's ordered ID list; stable across calls until
        recompilation.
      - compilation_epoch (cache-optimized mode only): integer epoch
        counter; increments on recompilation.
      - appendix_count (cache-optimized mode only): number of results
        that are new since the last compilation.
      - pivot_suggested (only when 'focus' was set): true if the immediate
        query embedding sits far from the session focus vector, indicating
        the user has likely pivoted off-topic. Agents should consider
        re-issuing search_memory with a fresh focus when this flag fires.
      - pivot_reason (only when 'focus' was set): human-readable explanation
        of the pivot signal -- query-to-focus distance and the threshold.
      - graph_neighbors_added (int, only when graph_depth > 0): count of
        unique nodes surfaced by graph traversal beyond the vector results.
      - graph_fallback_reason (str, only when graph_depth > 0 and traversal
        was skipped): human-readable reason graph traversal was not performed.

    Sizing controls:
      - mode controls full-vs-stub detail per result.
      - max_response_tokens caps total response size; results past the budget
        degrade to stubs in similarity order (raw) or compilation order
        (cache-optimized).
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

    # Resolve project memberships for the caller.
    # When PROJECT_ISOLATION_ENABLED is False, skip resolution — the
    # search filter's generic branch handles project scope without
    # scope_id filtering, and authorize_read returns True.
    #
    # When a specific project_id is given, restrict results to THAT
    # project only.  Without project_id, include all projects the
    # caller belongs to so project-scoped memories stay discoverable.
    project_ids: set[str] | None = None
    if PROJECT_ISOLATION_ENABLED:
        if project_id:
            project_ids = {project_id}
        else:
            session_for_project, gen_for_project = await get_db_session()
            try:
                project_ids = await get_projects_for_user(
                    session_for_project, claims["sub"],
                )
            finally:
                await release_db_session(gen_for_project)

    # Resolve role assignments for the caller (table + JWT claims).
    role_names: set[str] | None = None
    if ROLE_ISOLATION_ENABLED:
        session_for_roles, gen_for_roles = await get_db_session()
        try:
            role_names = await get_roles_for_user(
                session_for_roles, claims["sub"], tenant, claims=claims,
            )
        finally:
            await release_db_session(gen_for_roles)

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
        graph_bundle = None
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
                project_ids=project_ids,
                role_names=role_names,
                domains=domains,
                domain_boost_weight=domain_boost_weight,
                graph_depth=graph_depth,
                graph_relationship_types=graph_relationship_types,
                graph_boost_weight=graph_boost_weight,
            )
            graph_bundle = bundle
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
                project_ids=project_ids,
                role_names=role_names,
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
            project_ids=project_ids,
            role_names=role_names,
        )

        # Apply post-retrieval domain boost only on the non-focus path.
        # The focus path handles domains via RRF integration in the
        # service layer — applying it here too would double-boost.
        used_focus_path = focus and focus.strip()
        if domains and results and not used_focus_path:
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

        # --- Backfill compiled entries (#188) ---
        # The similarity search limits results to max_results by cosine
        # score, which can exclude compiled entries that belong in the
        # cache-stable prefix. Backfill them before compilation ordering
        # so compiled entries are never displaced by high-similarity
        # appendix entries.
        cache_optimized = not raw_results
        if cache_optimized and results:
            results = await _backfill_compiled_entries(
                results, session, tenant,
                owner_id=owner_id,
                weight_threshold=effective_weight_threshold,
                scope=scope,
                authorized_scopes=authorized,
                campaign_ids=campaign_ids,
                project_ids=project_ids,
                role_names=role_names,
                current_only=current_only,
            )

        # --- Cache-optimized assembly (default, #175) ---
        # When raw_results is False (the default), reorder results by
        # compilation epoch for cache-stable prompt injection. Runs after
        # mode='index' so stubs are used in the compilation ordering.
        compilation_meta: dict[str, Any] | None = None
        if cache_optimized and results:
            # owner_id for compilation scope: the effective owner from the
            # tool parameter (already resolved above — None means "all
            # owners", which we key as "*" for the compilation hash).
            compilation_owner = owner_id if owner_id is not None else "*"
            compilation_meta = await _apply_cache_optimized_ordering(
                results, tenant, compilation_owner
            )

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

        # Filter branches from compilation-ordered results so they aren't
        # duplicated as both nested and top-level.
        if compilation_meta is not None:
            branch_ids = result_id_set - {str(item.id) for item, _ in top_level}
            compilation_meta["ordered_results"] = [
                (item, score, is_app)
                for item, score, is_app in compilation_meta["ordered_results"]
                if str(item.id) not in branch_ids
            ]

        # Token-budget packing. Walk results in order; full-form entries
        # that exceed the remaining budget (and everything after them)
        # are degraded to stub form. Stubs are always included so the
        # agent never silently misses a match.
        budget = max_response_tokens
        budget_exhausted = False
        formatted: list[dict[str, Any]] = []

        if compilation_meta is not None:
            # Cache-optimized: iterate compilation-ordered results
            for item, _score, is_appendix in compilation_meta["ordered_results"]:
                child_branches = nested_by_parent.get(str(item.id), [])

                if budget_exhausted:
                    output_item = (
                        _to_stub(item) if isinstance(item, MemoryNodeRead) else item
                    )
                    output_branches = [
                        ((_to_stub(b) if isinstance(b, MemoryNodeRead) else b), s)
                        for b, s in child_branches
                    ]
                    entry, cost = _format_entry_cached(
                        output_item, output_branches, is_appendix
                    )
                    formatted.append(entry)
                    budget = max(0, budget - cost)
                    continue

                entry, cost = _format_entry_cached(item, child_branches, is_appendix)
                if isinstance(item, MemoryNodeStub) or cost <= budget:
                    formatted.append(entry)
                    budget = max(0, budget - cost)
                else:
                    budget_exhausted = True
                    stub_item = _to_stub(item)
                    stub_branches = [
                        ((_to_stub(b) if isinstance(b, MemoryNodeRead) else b), s)
                        for b, s in child_branches
                    ]
                    stub_entry, stub_cost = _format_entry_cached(
                        stub_item, stub_branches, is_appendix
                    )
                    formatted.append(stub_entry)
                    budget = max(0, budget - stub_cost)
        else:
            # Raw results: existing similarity-ranked behavior
            for item, relevance_score in top_level:
                child_branches = nested_by_parent.get(str(item.id), [])

                if budget_exhausted:
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
                    formatted.append(entry)
                    budget = max(0, budget - cost)
                else:
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
        if compilation_meta is not None:
            response["compilation_hash"] = compilation_meta["compilation_hash"]
            response["compilation_epoch"] = compilation_meta["compilation_epoch"]
            response["appendix_count"] = compilation_meta["appendix_count"]
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
        if graph_depth > 0 and graph_bundle is not None:
            response["graph_neighbors_added"] = graph_bundle.graph_neighbors_added
            if graph_bundle.graph_fallback_reason:
                response["graph_fallback_reason"] = graph_bundle.graph_fallback_reason
        return response

    except EmbeddingContentTooLargeError as exc:
        raise ToolError(
            f"Invalid query size: {exc.content_length} characters exceeds the "
            "embedding model's input limit. Use a shorter, more focused search query."
        ) from exc
    except EmbeddingServiceUnavailableError as exc:
        raise ToolError(
            f"Embedding service is unavailable: {exc.reason}."
            " Search requires embeddings to function."
            " Retry after the embedding service recovers."
        ) from exc
    except EmbeddingServiceError as exc:
        raise ToolError(
            f"Search failed due to embedding error: {exc}."
            " Retry or contact an administrator."
        ) from exc
    finally:
        await release_db_session(gen)
