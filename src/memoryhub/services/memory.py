"""Core memory service — CRUD, versioning, search, and contradiction reporting.

This module sits between the MCP tools and the database. All methods are async
and receive an explicit AsyncSession (no hidden global state).
"""

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub.config import AppSettings
from memoryhub.models.contradiction import ContradictionReport
from memoryhub.models.memory import MemoryNode
from memoryhub.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryVersionInfo,
)
from memoryhub.models.utils import generate_stub
from memoryhub.services.curation.pipeline import run_curation_pipeline
from memoryhub.services.embeddings import EmbeddingService
from memoryhub.services.exceptions import (
    ContradictionNotFoundError,
    MemoryAlreadyDeletedError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
)
from memoryhub.services.rerank import RERANK_MAX_BATCH, RerankerService

logger = logging.getLogger(__name__)


# Default RRF constant -- standard "k=60" from the original RRF paper.
# Used by both the production search path and the benchmark harness so
# the empirical and production behaviors stay aligned.
RRF_K = 60

# Default cosine distance threshold for the pivot signal. Cosine
# distance ranges 0..2; the design's research file recommended 0.55
# as a starting threshold. Surfaced as a parameter on
# search_memories_with_focus so callers can tune empirically without
# touching service code.
DEFAULT_PIVOT_THRESHOLD = 0.55


async def create_memory(
    data: MemoryNodeCreate,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    skip_curation: bool = False,
) -> tuple[MemoryNodeRead | None, dict]:
    """Create a new memory node.

    Generates the stub and embedding, runs the curation pipeline, and (if
    allowed) persists the node. Returns a ``(memory, curation_result)`` tuple:

    - If curation blocks the write: ``memory`` is ``None`` and
      ``curation_result["blocked"]`` is ``True``.
    - If the write is allowed: ``memory`` is the created ``MemoryNodeRead`` and
      ``curation_result["blocked"]`` is ``False``.

    Set ``skip_curation=True`` to bypass the pipeline entirely (used for
    downstream writes from merge operations).
    """
    embedding = await embedding_service.embed(data.content)
    stub = generate_stub(
        content=data.content,
        scope=data.scope,
        weight=data.weight,
        branch_count=0,
        has_rationale=False,
    )

    if not skip_curation:
        curation_result = await run_curation_pipeline(
            content=data.content,
            embedding=embedding,
            owner_id=data.owner_id,
            scope=data.scope,
            session=session,
        )
        if curation_result["blocked"]:
            return None, curation_result
    else:
        curation_result = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }

    now = datetime.now(UTC)
    node = MemoryNode(
        id=uuid.uuid4(),
        content=data.content,
        stub=stub,
        scope=data.scope,
        weight=data.weight,
        owner_id=data.owner_id,
        parent_id=data.parent_id,
        branch_type=data.branch_type,
        metadata_=data.metadata,
        embedding=embedding,
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    )

    session.add(node)
    await session.commit()
    await session.refresh(node)

    memory = node_to_read(node, has_children=False, has_rationale=False)
    return memory, curation_result


async def read_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
) -> MemoryNodeRead:
    """Read a memory node by ID.

    Returns the node with branch_count populated via a single COUNT query.
    Branches are no longer loaded inline -- callers that need branch contents
    should query them explicitly via search_memory or follow-up read_memory
    calls. When the requested node is a historical (non-current) version,
    populates current_version_id by walking the version chain forward, so
    callers can pivot to the live version in a single round-trip.
    Raises MemoryNotFoundError if the node does not exist.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id, MemoryNode.deleted_at.is_(None)
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    has_children, has_rationale, branch_count = await _compute_branch_flags(node, session)

    current_version_id: uuid.UUID | None = None
    if not node.is_current:
        # Walk the full chain (both directions) and pick the current node.
        # _walk_version_chain is the same helper used by get_memory_history
        # and delete_memory; it handles the case where the caller passed a
        # middle version ID. There is at most one is_current=true node in a
        # well-formed chain; if none exists (e.g., the chain has been fully
        # superseded but not yet pruned), leave the pointer as None.
        chain = await _walk_version_chain(node, session)
        for n in chain:
            if n.is_current and n.deleted_at is None:
                current_version_id = n.id
                break

    return node_to_read(
        node,
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=branch_count,
        current_version_id=current_version_id,
    )


async def update_memory(
    memory_id: uuid.UUID,
    data: MemoryNodeUpdate,
    session: AsyncSession,
    embedding_service: EmbeddingService,
) -> MemoryNodeRead:
    """Create a new version of a memory node.

    Marks the old version as not-current and creates a new node with
    incremented version and previous_version_id pointing to the old.
    Raises MemoryNotFoundError or MemoryNotCurrentError as appropriate.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    old_node = result.scalar_one_or_none()

    if old_node is None:
        raise MemoryNotFoundError(memory_id)

    if not old_node.is_current:
        # Find the current version to include in the error
        current_stmt = (
            select(MemoryNode)
            .where(
                MemoryNode.owner_id == old_node.owner_id,
                MemoryNode.scope == old_node.scope,
                MemoryNode.is_current.is_(True),
            )
            .where(
                # Walk the version chain: the current node should share
                # the same root. For simplicity, report old_node.id as both.
                MemoryNode.id != memory_id,
            )
        )
        current_result = await session.execute(current_stmt)
        current_node = current_result.scalars().first()
        current_id = current_node.id if current_node else memory_id
        raise MemoryNotCurrentError(memory_id, current_id)

    # Apply updates
    new_content = data.content if data.content is not None else old_node.content
    new_weight = data.weight if data.weight is not None else old_node.weight
    new_metadata = data.metadata if data.metadata is not None else old_node.metadata_

    embedding = await embedding_service.embed(new_content)
    stub = generate_stub(
        content=new_content,
        scope=old_node.scope,
        weight=new_weight,
        branch_count=0,
        has_rationale=False,
    )

    now = datetime.now(UTC)
    new_node = MemoryNode(
        id=uuid.uuid4(),
        content=new_content,
        stub=stub,
        scope=old_node.scope,
        weight=new_weight,
        owner_id=old_node.owner_id,
        parent_id=old_node.parent_id,
        branch_type=old_node.branch_type,
        metadata_=new_metadata,
        embedding=embedding,
        is_current=True,
        version=old_node.version + 1,
        previous_version_id=old_node.id,
        storage_type=old_node.storage_type,
        content_ref=old_node.content_ref,
        created_at=now,
        updated_at=now,
    )

    # Set TTL on the old version
    app_settings = AppSettings()
    old_node.is_current = False
    old_node.expires_at = now + timedelta(days=app_settings.version_retention_days)

    session.add(new_node)

    # Deep-copy one level of child branches from old node to new node
    children_stmt = select(MemoryNode).where(MemoryNode.parent_id == old_node.id)
    children_result = await session.execute(children_stmt)
    old_children = children_result.scalars().all()

    for child in old_children:
        # Deep copy branch to new parent
        copied_child = MemoryNode(
            id=uuid.uuid4(),
            content=child.content,
            stub=child.stub,
            scope=child.scope,
            weight=child.weight,
            owner_id=child.owner_id,
            parent_id=new_node.id,
            branch_type=child.branch_type,
            metadata_=child.metadata_,
            embedding=list(child.embedding) if child.embedding is not None else None,
            is_current=True,
            version=child.version,
            previous_version_id=None,
            storage_type=child.storage_type,
            content_ref=child.content_ref,
            created_at=child.created_at,
            updated_at=now,
        )
        session.add(copied_child)

        # Retire old branch — deep copy is the canonical version now
        child.is_current = False
        child.expires_at = now + timedelta(days=app_settings.version_retention_days)

    await session.commit()
    await session.refresh(new_node)

    has_children = len(old_children) > 0
    has_rationale = any(c.branch_type == "rationale" for c in old_children)
    return node_to_read(
        new_node,
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=len(old_children),
    )


async def delete_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
) -> dict:
    """Soft-delete a memory and its entire version chain.

    Marks the target node and all nodes in its version chain with
    deleted_at = now. Relationships are left intact (they reference
    deleted nodes, which are filtered from queries). Returns a summary
    dict with the count of deleted versions.

    Raises MemoryNotFoundError if the node doesn't exist, or
    MemoryAlreadyDeletedError if already soft-deleted.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    if node.deleted_at is not None:
        raise MemoryAlreadyDeletedError(memory_id)

    now = datetime.now(UTC)

    chain_nodes = await _walk_version_chain(node, session)
    version_ids: set[uuid.UUID] = {n.id for n in chain_nodes}

    # Also delete child branches of all versions in the chain
    child_stmt = select(MemoryNode).where(MemoryNode.parent_id.in_(list(version_ids)))
    child_result = await session.execute(child_stmt)
    child_ids = {child.id for child in child_result.scalars().all()}
    all_ids = version_ids | child_ids

    # Bulk soft-delete
    await session.execute(
        update(MemoryNode)
        .where(MemoryNode.id.in_(list(all_ids)))
        .values(deleted_at=now, is_current=False)
    )

    await session.commit()

    return {
        "deleted_id": str(memory_id),
        "versions_deleted": len(version_ids),
        "branches_deleted": len(child_ids),
        "total_deleted": len(all_ids),
    }


def _build_search_filters(
    scope: str | None,
    owner_id: str | None,
    current_only: bool,
    authorized_scopes: dict[str, str | None] | None,
) -> list | None:
    """Build the SQL filter list shared by search_memories and count_search_matches.

    Returns None if authorized_scopes was provided but empty (callers should
    short-circuit to "no results"). This avoids duplicating the filter logic
    between the search query and the count query that backs has_more.
    """
    filters = [MemoryNode.deleted_at.is_(None)]
    if current_only:
        filters.append(MemoryNode.is_current.is_(True))
    if scope is not None:
        filters.append(MemoryNode.scope == scope)
    if owner_id is not None:
        filters.append(MemoryNode.owner_id == owner_id)

    if authorized_scopes is not None:
        if not authorized_scopes:
            return None  # no authorized scopes → no results
        scope_conditions = []
        for scope_name, required_owner in authorized_scopes.items():
            if required_owner is not None:
                scope_conditions.append(
                    and_(
                        MemoryNode.scope == scope_name,
                        MemoryNode.owner_id == required_owner,
                    )
                )
            else:
                scope_conditions.append(MemoryNode.scope == scope_name)
        filters.append(or_(*scope_conditions))

    return filters


async def count_search_matches(
    session: AsyncSession,
    scope: str | None = None,
    owner_id: str | None = None,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
) -> int:
    """Count memories matching the same filter set used by search_memories.

    Used by the search_memory tool to compute has_more for pagination, since
    search_memories itself only returns a single page of results. The query
    parameter and weight_threshold are intentionally absent: total_matching
    is independent of the embedding similarity ranking.
    """
    filters = _build_search_filters(scope, owner_id, current_only, authorized_scopes)
    if filters is None:
        return 0
    stmt = select(func.count()).select_from(MemoryNode).where(*filters)
    return (await session.execute(stmt)).scalar() or 0


async def search_memories(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    scope: str | None = None,
    owner_id: str | None = None,
    weight_threshold: float = 0.8,
    max_results: int = 20,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
) -> list[tuple[MemoryNodeRead | MemoryNodeStub, float]]:
    """Search memories using pgvector cosine similarity.

    Returns a list of (result, relevance_score) tuples. High-weight results
    are MemoryNodeRead, low-weight results are MemoryNodeStub. The relevance
    score is 1.0 - cosine_distance (range 0-1 for normalized vectors).

    Falls back to weight-based ordering with synthetic scores when pgvector
    is not available (e.g., SQLite in tests).

    When authorized_scopes is provided, results are filtered to only include
    memories the caller is authorized to read. The dict maps scope names to
    required owner_id values (None means no owner filter for that scope).
    """
    query_embedding = await embedding_service.embed(query)

    filters = _build_search_filters(scope, owner_id, current_only, authorized_scopes)
    if filters is None:
        return []

    use_pgvector = True
    try:
        # pgvector cosine distance: smaller = more similar
        distance_expr = MemoryNode.embedding.cosine_distance(query_embedding)
        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(*filters)
            .order_by(distance_expr)
            .limit(max_results)
        )
    except Exception:
        # Fallback for non-pgvector backends (e.g., SQLite in tests)
        use_pgvector = False
        stmt = select(MemoryNode).where(*filters).order_by(MemoryNode.weight.desc()).limit(max_results)

    result = await session.execute(stmt)

    if use_pgvector:
        rows = result.all()  # list of (MemoryNode, distance)
        nodes_with_distance = [(row[0], float(row[1])) for row in rows]
    else:
        nodes = result.scalars().all()
        total = len(nodes) if nodes else 1
        # Synthetic scores: rank-based descending from 1.0
        nodes_with_distance = [(node, i / total) for i, node in enumerate(nodes)]

    if not nodes_with_distance:
        return []

    # Bulk-query branch flags for all result nodes
    node_ids = [n.id for n, _ in nodes_with_distance]
    branch_flags = await _bulk_branch_flags(node_ids, session)

    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for node, distance in nodes_with_distance:
        relevance_score = max(0.0, 1.0 - distance)
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        if node.weight >= weight_threshold:
            results.append(
                (
                    node_to_read(
                        node,
                        has_children=has_children,
                        has_rationale=has_rationale,
                        branch_count=branch_count,
                    ),
                    relevance_score,
                )
            )
        else:
            results.append(
                (
                    MemoryNodeStub(
                        id=node.id,
                        parent_id=node.parent_id,
                        stub=node.stub,
                        scope=node.scope,
                        weight=node.weight,
                        branch_type=node.branch_type,
                        has_children=has_children,
                        has_rationale=has_rationale,
                    ),
                    relevance_score,
                )
            )
    return results


# ---- Two-vector retrieval (#58, NEW-1 RRF blend) -----------------------


@dataclass
class FocusedSearchResult:
    """Output of search_memories_with_focus.

    The `results` list has the same shape as search_memories' return
    value (list of (item, relevance_score) tuples) so MCP tool code
    can format both paths uniformly. The pivot_* fields surface the
    embedding distance from the query to the focus vector and a
    boolean threshold flag; only set when a focus was provided.
    """

    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = field(
        default_factory=list
    )
    pivot_suggested: bool = False
    pivot_distance: float | None = None
    pivot_threshold: float | None = None
    pivot_reason: str | None = None
    used_reranker: bool = False
    fallback_reason: str | None = None


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance for two vectors. Range [0, 2]; 0 = identical.

    Always returns a Python float, even when the input lists contain
    numpy.float32 elements (pgvector returns numpy arrays in production).
    pydantic_core.to_jsonable_python rejects numpy scalars, so any numpy
    leakage into the response dict breaks FastMCP's structured-output
    serialization with a confusing "outputSchema defined but no structured
    output returned" error.
    """
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 1.0
    sim = dot / (math.sqrt(na) * math.sqrt(nb))
    # Clamp to handle floating-point drift outside [-1, 1].
    sim = max(-1.0, min(1.0, sim))
    return float(1.0 - sim)


async def search_memories_with_focus(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    focus_string: str,
    session_focus_weight: float = 0.4,
    reranker: RerankerService | None = None,
    pivot_threshold: float = DEFAULT_PIVOT_THRESHOLD,
    scope: str | None = None,
    owner_id: str | None = None,
    weight_threshold: float = 0.8,
    max_results: int = 20,
    current_only: bool = True,
    authorized_scopes: dict[str, str | None] | None = None,
) -> FocusedSearchResult:
    """Two-vector retrieval with session focus bias.

    Pipeline (NEW-1 from research/two-vector-retrieval.md):

        pgvector cosine recall (top-K_recall by query)
            ↓
        cross-encoder rerank by query.text (when reranker available)
            ↓
        RRF blend (rerank ranks, focus cosine ranks)
            ↓
        top max_results

    The focus string is embedded once per call and used both as the
    bias vector for the RRF blend and as the basis for pivot detection.

    When `session_focus_weight <= 0` or `focus_string` is empty, this
    function falls through to the same code path as `search_memories`
    -- it accepts the call shape for caller convenience but does no
    additional work.

    When the reranker is None, not configured, or fails at call time,
    the rerank stage is skipped and the RRF blend operates on cosine
    ranks instead. The fallback path is logged via the returned
    ``fallback_reason`` so the MCP tool can surface it for debugging.

    Returns a FocusedSearchResult dataclass; see its docstring for
    field semantics.
    """
    if not focus_string or session_focus_weight <= 0.0:
        # No-focus short-circuit. Skips both the focus embed and the
        # rerank network call. Mirrors the production-tuning rule
        # from the benchmark: when there's no focus signal, the
        # cross-encoder doesn't help, so don't pay for it.
        plain = await search_memories(
            query=query,
            session=session,
            embedding_service=embedding_service,
            scope=scope,
            owner_id=owner_id,
            weight_threshold=weight_threshold,
            max_results=max_results,
            current_only=current_only,
            authorized_scopes=authorized_scopes,
        )
        return FocusedSearchResult(results=plain)

    query_embedding = await embedding_service.embed(query)
    focus_embedding = await embedding_service.embed(focus_string)

    pivot_distance = _cosine_distance(query_embedding, focus_embedding)
    pivot_suggested = pivot_distance > pivot_threshold
    pivot_reason: str | None = None
    if pivot_suggested:
        pivot_reason = (
            f"query vector distance from session focus is "
            f"{pivot_distance:.3f} (threshold {pivot_threshold:.2f})"
        )

    filters = _build_search_filters(scope, owner_id, current_only, authorized_scopes)
    if filters is None:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
        )

    # Recall pool: at least RERANK_MAX_BATCH so the rerank stage has
    # headroom over max_results, and at least max_results so the
    # blend has the requested page worth of candidates even when
    # max_results > RERANK_MAX_BATCH.
    k_recall = max(RERANK_MAX_BATCH, max_results)

    use_pgvector = True
    try:
        distance_expr = MemoryNode.embedding.cosine_distance(query_embedding)
        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(*filters)
            .order_by(distance_expr)
            .limit(k_recall)
        )
    except Exception:
        use_pgvector = False
        stmt = (
            select(MemoryNode)
            .where(*filters)
            .order_by(MemoryNode.weight.desc())
            .limit(k_recall)
        )

    db_result = await session.execute(stmt)

    if use_pgvector:
        rows = db_result.all()
        candidate_nodes: list[MemoryNode] = [row[0] for row in rows]
    else:
        candidate_nodes = list(db_result.scalars().all())

    if not candidate_nodes:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
        )

    # Cosine ranks of the recall pool by query (already in this
    # order from pgvector). 1-based ranks.
    rank_query: dict[uuid.UUID, int] = {
        node.id: idx + 1 for idx, node in enumerate(candidate_nodes)
    }

    # Cross-encoder rerank stage (top RERANK_MAX_BATCH only).
    used_reranker = False
    fallback_reason: str | None = None
    if reranker is not None and getattr(reranker, "is_configured", True):
        rerank_pool = candidate_nodes[:RERANK_MAX_BATCH]
        try:
            order = await reranker.rerank(
                query, [n.content for n in rerank_pool]
            )
            # Replace the query-cosine ranks for the reranked subset
            # with cross-encoder ranks. Items beyond RERANK_MAX_BATCH
            # keep their cosine rank.
            for new_rank, original_idx in enumerate(order, start=1):
                node = rerank_pool[original_idx]
                rank_query[node.id] = new_rank
            # Items at positions [RERANK_MAX_BATCH..k_recall) need
            # ranks shifted to live after the reranked block.
            for idx in range(RERANK_MAX_BATCH, len(candidate_nodes)):
                rank_query[candidate_nodes[idx].id] = idx + 1
            used_reranker = True
        except Exception as exc:  # pragma: no cover - network error
            fallback_reason = (
                f"reranker call failed ({type(exc).__name__}); "
                "falling back to cosine rank"
            )
            logger.warning(
                "search_memories_with_focus reranker fallback: %s", exc
            )
    elif reranker is None:
        fallback_reason = (
            "no reranker configured; using cosine rank for query stage"
        )
    else:
        fallback_reason = (
            "reranker not configured (is_configured=False); using cosine rank"
        )

    # Focus cosine ranks across the candidate pool. Distance from the
    # focus vector ascending = best focus match first.
    focus_scored = sorted(
        candidate_nodes,
        key=lambda n: _cosine_distance(focus_embedding, list(n.embedding))
        if n.embedding is not None
        else 1.0,
    )
    rank_focus: dict[uuid.UUID, int] = {
        node.id: idx + 1 for idx, node in enumerate(focus_scored)
    }

    # RRF blend: rank_query carries the cross-encoder ranks (or
    # cosine fallback ranks); rank_focus carries the focus-cosine
    # ranks. weight_b = session_focus_weight pushes the result
    # toward focus.
    weight_q = 1.0 - session_focus_weight
    blended_scores: list[tuple[MemoryNode, float]] = []
    for node in candidate_nodes:
        score_q = weight_q / (RRF_K + rank_query.get(node.id, k_recall + 1))
        score_f = session_focus_weight / (
            RRF_K + rank_focus.get(node.id, k_recall + 1)
        )
        blended_scores.append((node, score_q + score_f))
    blended_scores.sort(key=lambda pair: pair[1], reverse=True)

    top_nodes = [node for node, _ in blended_scores[:max_results]]
    if not top_nodes:
        return FocusedSearchResult(
            pivot_suggested=pivot_suggested,
            pivot_distance=pivot_distance,
            pivot_threshold=pivot_threshold,
            pivot_reason=pivot_reason,
            used_reranker=used_reranker,
            fallback_reason=fallback_reason,
        )

    # Bulk-query branch flags for the final result set.
    branch_flags = await _bulk_branch_flags([n.id for n in top_nodes], session)

    # Compute relevance_score from the original query cosine distance
    # so existing MCP-tool formatting (which prints relevance_score
    # rounded to 4 decimals) shows a meaningful number even when the
    # rerank reordered the list. relevance_score reflects raw query
    # affinity, not the RRF-blended rank.
    if use_pgvector:
        # Recompute query cosine distance per node for the relevance
        # score. The values were available in the original SQL row
        # tuples but we discarded them above; recomputing here keeps
        # the data flow simple and the cost is negligible (top-N
        # nodes only, in-process).
        query_dist_by_id: dict[uuid.UUID, float] = {}
        for node in top_nodes:
            if node.embedding is not None:
                query_dist_by_id[node.id] = _cosine_distance(
                    query_embedding, list(node.embedding)
                )
            else:
                query_dist_by_id[node.id] = 1.0
    else:
        # SQLite fallback: synthetic rank-based scores like search_memories.
        query_dist_by_id = {
            node.id: idx / max(1, len(top_nodes))
            for idx, node in enumerate(top_nodes)
        }

    formatted: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for node in top_nodes:
        relevance_score = max(0.0, 1.0 - query_dist_by_id[node.id])
        has_children, has_rationale, branch_count = branch_flags.get(
            node.id, (False, False, 0)
        )
        if node.weight >= weight_threshold:
            formatted.append(
                (
                    node_to_read(
                        node,
                        has_children=has_children,
                        has_rationale=has_rationale,
                        branch_count=branch_count,
                    ),
                    relevance_score,
                )
            )
        else:
            formatted.append(
                (
                    MemoryNodeStub(
                        id=node.id,
                        parent_id=node.parent_id,
                        stub=node.stub,
                        scope=node.scope,
                        weight=node.weight,
                        branch_type=node.branch_type,
                        has_children=has_children,
                        has_rationale=has_rationale,
                    ),
                    relevance_score,
                )
            )

    return FocusedSearchResult(
        results=formatted,
        pivot_suggested=pivot_suggested,
        pivot_distance=pivot_distance,
        pivot_threshold=pivot_threshold,
        pivot_reason=pivot_reason,
        used_reranker=used_reranker,
        fallback_reason=fallback_reason,
    )


async def get_memory_history(
    memory_id: uuid.UUID,
    session: AsyncSession,
    max_versions: int = 20,
    offset: int = 0,
) -> dict:
    """Build a paginated version history for a memory.

    Walks the version chain in both directions from `memory_id`, so callers
    can pass any version ID (oldest, newest, or middle) and get back the
    full chain. Returns a dict with:
      - versions: list[MemoryVersionInfo] (newest-first, paginated)
      - total_versions: int (total count in the chain)
      - has_more: bool (whether more versions exist beyond this page)
      - offset: int (the offset used)
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    chain_nodes = await _walk_version_chain(node, session)
    all_versions: list[MemoryVersionInfo] = [
        MemoryVersionInfo(
            id=n.id,
            version=n.version,
            is_current=n.is_current,
            created_at=n.created_at,
            stub=n.stub,
            content=n.content,
            expires_at=n.expires_at,
        )
        for n in chain_nodes
    ]

    # Newest first (highest version number first)
    all_versions.sort(key=lambda v: v.version, reverse=True)

    total_versions = len(all_versions)
    page = all_versions[offset : offset + max_versions]
    has_more = (offset + max_versions) < total_versions

    return {
        "versions": page,
        "total_versions": total_versions,
        "has_more": has_more,
        "offset": offset,
    }


async def report_contradiction(
    memory_id: uuid.UUID,
    observed_behavior: str,
    confidence: float,
    reporter: str,
    session: AsyncSession,
) -> int:
    """Record a contradiction against a memory node.

    Inserts a row into contradiction_reports and returns the count of
    unresolved contradictions for this memory.
    """
    # Verify the memory exists and is not deleted. Reporting a contradiction
    # against a deleted memory is meaningless — there's no current version
    # for the curator to revise.
    stmt = select(MemoryNode.id).where(
        MemoryNode.id == memory_id,
        MemoryNode.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise MemoryNotFoundError(memory_id)

    # Insert the contradiction report
    report = ContradictionReport(
        memory_id=memory_id,
        observed_behavior=observed_behavior,
        confidence=confidence,
        reporter=reporter,
    )
    session.add(report)
    await session.flush()

    # Count unresolved contradictions for this memory
    count_stmt = (
        select(func.count())
        .select_from(ContradictionReport)
        .where(
            ContradictionReport.memory_id == memory_id,
            ContradictionReport.resolved == False,  # noqa: E712
        )
    )
    count_result = await session.execute(count_stmt)
    count = count_result.scalar_one()

    await session.commit()
    return count


async def resolve_contradiction(
    contradiction_id: uuid.UUID,
    session: AsyncSession,
) -> ContradictionReport:
    """Mark a contradiction report as resolved.

    Returns the updated ContradictionReport. Raises ContradictionNotFoundError
    if the ID doesn't exist, or ValueError if already resolved.
    """
    stmt = select(ContradictionReport).where(ContradictionReport.id == contradiction_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()

    if report is None:
        raise ContradictionNotFoundError(contradiction_id)

    if report.resolved:
        raise ValueError(f"Contradiction {contradiction_id} is already resolved")

    report.resolved = True
    report.resolved_at = datetime.now(UTC)

    await session.commit()
    return report


# -- Internal helpers --


async def _walk_version_chain(
    start: MemoryNode,
    session: AsyncSession,
) -> list[MemoryNode]:
    """Return every node in `start`'s version chain (both directions).

    Walks `previous_version_id` backward from `start`, then iteratively
    walks forward via reverse-pointers (nodes whose previous_version_id
    is in the visited set) until the chain is closed. The result is
    deduplicated and order-independent; callers that need ordering should
    sort by `version`.

    Used by `delete_memory` (so an old version ID still soft-deletes the
    whole chain) and `get_memory_history` (so an agent can pass any
    version ID and get the full history). Pre-#49 the two used divergent
    walkers; this helper is the single source of truth.
    """
    visited: dict[uuid.UUID, MemoryNode] = {}
    current: MemoryNode | None = start

    # Backward walk along previous_version_id
    while current is not None and current.id not in visited:
        visited[current.id] = current
        if current.previous_version_id is not None:
            prev_stmt = select(MemoryNode).where(
                MemoryNode.id == current.previous_version_id
            )
            current = (await session.execute(prev_stmt)).scalar_one_or_none()
        else:
            current = None

    # Forward walk: pull in any node whose previous_version_id points at
    # something we've already visited. Repeat until no new nodes appear.
    changed = True
    while changed:
        changed = False
        fwd_stmt = select(MemoryNode).where(
            MemoryNode.previous_version_id.in_(list(visited.keys())),
            ~MemoryNode.id.in_(list(visited.keys())),
        )
        for fwd_node in (await session.execute(fwd_stmt)).scalars().all():
            visited[fwd_node.id] = fwd_node
            changed = True

    return list(visited.values())


async def _bulk_branch_flags(
    parent_ids: list[uuid.UUID],
    session: AsyncSession,
) -> dict[uuid.UUID, tuple[bool, bool, int]]:
    """Compute has_children, has_rationale, and branch_count for multiple parents.

    Returns a dict mapping parent_id -> (has_children, has_rationale, branch_count).
    Parents with no children are absent from the dict.
    """
    if not parent_ids:
        return {}

    stmt = (
        select(
            MemoryNode.parent_id,
            func.count(MemoryNode.id).label("child_count"),
            func.sum(func.cast(MemoryNode.branch_type == "rationale", Integer)).label("rationale_count"),
        )
        .where(MemoryNode.parent_id.in_(parent_ids), MemoryNode.deleted_at.is_(None))
        .group_by(MemoryNode.parent_id)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return {
        row.parent_id: (
            row.child_count > 0,
            (row.rationale_count or 0) > 0,
            int(row.child_count or 0),
        )
        for row in rows
    }


async def _compute_branch_flags(
    node: MemoryNode,
    session: AsyncSession,
) -> tuple[bool, bool, int]:
    """Determine has_children, has_rationale, and branch_count for a node.

    Runs a single query for the count + rationale-presence flag instead of
    loading the child rows themselves -- read_memory no longer expands
    branches inline.
    """
    children_stmt = select(MemoryNode.branch_type).where(
        MemoryNode.parent_id == node.id, MemoryNode.deleted_at.is_(None)
    )
    children_result = await session.execute(children_stmt)
    rows = children_result.all()
    branch_count = len(rows)
    has_children = branch_count > 0
    has_rationale = any(row.branch_type == "rationale" for row in rows)
    return has_children, has_rationale, branch_count


def node_to_read(
    node: MemoryNode,
    has_children: bool,
    has_rationale: bool,
    branch_count: int = 0,
    current_version_id: uuid.UUID | None = None,
) -> MemoryNodeRead:
    """Convert a MemoryNode ORM instance to a MemoryNodeRead schema."""
    return MemoryNodeRead(
        id=node.id,
        parent_id=node.parent_id,
        content=node.content,
        stub=node.stub,
        storage_type=node.storage_type,
        content_ref=node.content_ref,
        weight=node.weight,
        scope=node.scope,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        is_current=node.is_current,
        version=node.version,
        previous_version_id=node.previous_version_id,
        metadata_=node.metadata_,
        created_at=node.created_at,
        updated_at=node.updated_at,
        expires_at=node.expires_at,
        has_children=has_children,
        has_rationale=has_rationale,
        branch_count=branch_count,
        current_version_id=current_version_id,
    )
