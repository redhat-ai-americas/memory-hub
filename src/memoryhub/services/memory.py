"""Core memory service — CRUD, versioning, search, and contradiction reporting.

This module sits between the MCP tools and the database. All methods are async
and receive an explicit AsyncSession (no hidden global state).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from memoryhub.config import AppSettings
from memoryhub.models.memory import MemoryNode
from memoryhub.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryVersionInfo,
)
from memoryhub.models.utils import generate_stub
from memoryhub.services.embeddings import EmbeddingService
from memoryhub.services.exceptions import MemoryNotCurrentError, MemoryNotFoundError


async def create_memory(
    data: MemoryNodeCreate,
    session: AsyncSession,
    embedding_service: EmbeddingService,
) -> MemoryNodeRead:
    """Create a new memory node.

    Generates the stub and embedding, persists the node, and returns it
    as a MemoryNodeRead.
    """
    embedding = await embedding_service.embed(data.content)
    stub = generate_stub(
        content=data.content,
        scope=data.scope,
        weight=data.weight,
        branch_count=0,
        has_rationale=False,
    )

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

    return _node_to_read(node, has_children=False, has_rationale=False)


async def read_memory(
    memory_id: uuid.UUID,
    session: AsyncSession,
    depth: int = 0,
) -> MemoryNodeRead:
    """Read a memory node by ID.

    If depth > 0, eagerly loads children (one level). Raises
    MemoryNotFoundError if the node does not exist.
    """
    options = []
    if depth > 0:
        options.append(selectinload(MemoryNode.children))

    stmt = select(MemoryNode).where(MemoryNode.id == memory_id).options(*options)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    has_children, has_rationale = await _compute_branch_flags(node, session, depth)
    read = _node_to_read(node, has_children=has_children, has_rationale=has_rationale)

    # Populate branches when depth > 0 and children were eagerly loaded
    if depth > 0 and node.children:
        read.branches = [
            MemoryNodeStub(
                id=child.id,
                stub=child.stub,
                scope=child.scope,
                weight=child.weight,
                branch_type=child.branch_type,
            )
            for child in node.children
        ]

    return read


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
    return _node_to_read(new_node, has_children=has_children, has_rationale=has_rationale)


async def search_memories(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    scope: str | None = None,
    owner_id: str | None = None,
    weight_threshold: float = 0.8,
    max_results: int = 20,
    current_only: bool = True,
) -> list[tuple[MemoryNodeRead | MemoryNodeStub, float]]:
    """Search memories using pgvector cosine similarity.

    Returns a list of (result, relevance_score) tuples. High-weight results
    are MemoryNodeRead, low-weight results are MemoryNodeStub. The relevance
    score is 1.0 - cosine_distance (range 0-1 for normalized vectors).

    Falls back to weight-based ordering with synthetic scores when pgvector
    is not available (e.g., SQLite in tests).
    """
    query_embedding = await embedding_service.embed(query)

    # Build base filters
    filters = []
    if current_only:
        filters.append(MemoryNode.is_current.is_(True))
    if scope is not None:
        filters.append(MemoryNode.scope == scope)
    if owner_id is not None:
        filters.append(MemoryNode.owner_id == owner_id)

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
        relevance_score = 1.0 - distance
        has_children, has_rationale = branch_flags.get(node.id, (False, False))
        if node.weight >= weight_threshold:
            results.append(
                (
                    _node_to_read(node, has_children=has_children, has_rationale=has_rationale),
                    relevance_score,
                )
            )
        else:
            results.append(
                (
                    MemoryNodeStub(
                        id=node.id,
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


async def get_memory_history(
    memory_id: uuid.UUID,
    session: AsyncSession,
    max_versions: int = 20,
    offset: int = 0,
) -> dict:
    """Walk the previous_version_id chain to build a paginated version history.

    Returns a dict with:
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

    all_versions: list[MemoryVersionInfo] = []
    visited: set[uuid.UUID] = set()
    current = node

    while current is not None and current.id not in visited:
        visited.add(current.id)
        all_versions.append(
            MemoryVersionInfo(
                id=current.id,
                version=current.version,
                is_current=current.is_current,
                created_at=current.created_at,
                stub=current.stub,
                content=current.content,
                expires_at=current.expires_at,
            )
        )
        if current.previous_version_id is not None:
            prev_stmt = select(MemoryNode).where(MemoryNode.id == current.previous_version_id)
            prev_result = await session.execute(prev_stmt)
            current = prev_result.scalar_one_or_none()
        else:
            current = None

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
    session: AsyncSession,
) -> int:
    """Record a contradiction against a memory node.

    Stores contradictions in the node's metadata under a "contradictions" list.
    Returns the total number of contradictions recorded so far.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    metadata = dict(node.metadata_) if node.metadata_ else {}
    contradictions = list(metadata.get("contradictions", []))
    contradictions.append(
        {
            "observed_behavior": observed_behavior,
            "confidence": confidence,
            "reported_at": datetime.now(UTC).isoformat(),
        }
    )
    metadata["contradictions"] = contradictions
    node.metadata_ = metadata

    await session.commit()
    return len(contradictions)


# -- Internal helpers --


async def _bulk_branch_flags(
    parent_ids: list[uuid.UUID],
    session: AsyncSession,
) -> dict[uuid.UUID, tuple[bool, bool]]:
    """Compute has_children and has_rationale for multiple parent IDs in one query.

    Returns a dict mapping parent_id -> (has_children, has_rationale).
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
        .where(MemoryNode.parent_id.in_(parent_ids))
        .group_by(MemoryNode.parent_id)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return {row.parent_id: (row.child_count > 0, (row.rationale_count or 0) > 0) for row in rows}


async def _compute_branch_flags(
    node: MemoryNode,
    session: AsyncSession,
    depth: int,
) -> tuple[bool, bool]:
    """Determine has_children and has_rationale for a node.

    If depth > 0 and children were eagerly loaded, inspects them directly.
    Otherwise, runs a lightweight existence check.
    """
    if depth > 0 and node.children is not None:
        has_children = len(node.children) > 0
        has_rationale = any(c.branch_type == "rationale" for c in node.children)
    else:
        children_stmt = select(MemoryNode.id, MemoryNode.branch_type).where(MemoryNode.parent_id == node.id)
        children_result = await session.execute(children_stmt)
        rows = children_result.all()
        has_children = len(rows) > 0
        has_rationale = any(row.branch_type == "rationale" for row in rows)
    return has_children, has_rationale


def _node_to_read(
    node: MemoryNode,
    has_children: bool,
    has_rationale: bool,
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
    )
