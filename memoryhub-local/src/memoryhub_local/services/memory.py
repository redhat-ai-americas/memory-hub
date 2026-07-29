"""Memory CRUD and search operations for personal edition.

Thin service layer over the portable models. No auth, no multi-tenancy,
no push broadcast, no S3 spill. Hardcodes tenant_id="local".
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.embeddings.base import EmbeddingService
from memoryhub_local.identity import TENANT_ID, get_owner_id
from memoryhub_local.models.contradiction import ContradictionReport
from memoryhub_local.models.memory import MemoryNode, MemoryRelationship
from memoryhub_local.models.utils import generate_stub
from memoryhub_local.storage.recall import RecallBackend


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def create_memory(
    session: AsyncSession,
    content: str,
    embedding_service: EmbeddingService,
    *,
    scope: str = "user",
    weight: float = 0.7,
    parent_id: str | None = None,
    branch_type: str | None = None,
    metadata: dict | None = None,
    domains: list[str] | None = None,
    content_type: str = "declarative",
    driver_id: str | None = None,
) -> MemoryNode:
    """Create a new memory node with embedding."""
    embedding = await embedding_service.embed(content)
    owner = get_owner_id()

    node_id = uuid.uuid4()
    node = MemoryNode(
        id=node_id,
        logical_id=node_id,
        content=content,
        stub=generate_stub(content, scope, weight, 0, False),
        storage_type="inline",
        weight=weight,
        scope=scope,
        branch_type=branch_type,
        owner_id=owner,
        actor_id=owner,
        driver_id=driver_id,
        tenant_id=TENANT_ID,
        domains=domains or [],
        content_type=content_type,
        status="active",
        source="agent",
        content_hash=_content_hash(content),
        is_current=True,
        version=1,
        embedding=embedding,
        metadata_=metadata or {},
    )

    if parent_id:
        node.parent_id = uuid.UUID(parent_id)

    session.add(node)
    await session.commit()
    await session.refresh(node)
    return node


async def read_memory(
    session: AsyncSession,
    memory_id: str,
) -> MemoryNode | None:
    """Read a single memory node by ID."""
    result = await session.execute(
        select(MemoryNode).where(
            MemoryNode.id == uuid.UUID(memory_id),
            MemoryNode.tenant_id == TENANT_ID,
        )
    )
    return result.scalar_one_or_none()


async def update_memory(
    session: AsyncSession,
    memory_id: str,
    embedding_service: EmbeddingService,
    *,
    content: str | None = None,
    weight: float | None = None,
    metadata: dict | None = None,
    domains: list[str] | None = None,
) -> MemoryNode | None:
    """Update a memory by creating a new version."""
    old = await read_memory(session, memory_id)
    if old is None:
        return None
    if old.status != "active":
        return None

    # Mark old version as not current
    old.is_current = False
    await session.flush()

    new_content = content if content is not None else old.content
    new_weight = weight if weight is not None else old.weight
    new_domains = domains if domains is not None else old.domains
    if metadata:
        new_metadata = {**(old.metadata_ or {}), **metadata}
    else:
        new_metadata = old.metadata_ or {}

    embedding = await embedding_service.embed(new_content)

    new_id = uuid.uuid4()
    new_node = MemoryNode(
        id=new_id,
        logical_id=old.logical_id or old.id,
        content=new_content,
        stub=generate_stub(new_content, old.scope, new_weight, 0, False),
        storage_type="inline",
        weight=new_weight,
        scope=old.scope,
        branch_type=old.branch_type,
        owner_id=old.owner_id,
        actor_id=get_owner_id(),
        tenant_id=TENANT_ID,
        domains=new_domains,
        content_type=old.content_type,
        status="active",
        source=old.source,
        content_hash=_content_hash(new_content),
        is_current=True,
        version=old.version + 1,
        previous_version_id=old.id,
        parent_id=old.parent_id,
        embedding=embedding,
        metadata_=new_metadata,
    )

    session.add(new_node)

    # Re-point active graph edges from old version to new version (#472).
    await session.execute(
        update(MemoryRelationship)
        .where(
            MemoryRelationship.source_id == old.id,
            MemoryRelationship.valid_until.is_(None),
        )
        .values(source_id=new_node.id)
    )
    await session.execute(
        update(MemoryRelationship)
        .where(
            MemoryRelationship.target_id == old.id,
            MemoryRelationship.valid_until.is_(None),
        )
        .values(target_id=new_node.id)
    )

    await session.commit()
    await session.refresh(new_node)
    return new_node


async def delete_memory(
    session: AsyncSession,
    memory_id: str,
) -> dict:
    """Soft-delete a memory and its version chain."""
    parsed_id = uuid.UUID(memory_id)
    now = datetime.now(timezone.utc)

    # Walk backward through version chain (target -> oldest)
    version_ids: list[uuid.UUID] = []
    current_id: uuid.UUID | None = parsed_id
    while current_id:
        result = await session.execute(
            select(MemoryNode.id, MemoryNode.previous_version_id).where(
                MemoryNode.id == current_id,
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
        row = result.one_or_none()
        if row is None:
            break
        version_ids.append(row.id)
        current_id = row.previous_version_id

    # Walk forward through version chain (target -> newest)
    forward_frontier = {parsed_id}
    while forward_frontier:
        result = await session.execute(
            select(MemoryNode.id).where(
                MemoryNode.previous_version_id.in_(forward_frontier),
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
        new_ids = {row.id for row in result if row.id not in set(version_ids)}
        if not new_ids:
            break
        version_ids.extend(new_ids)
        forward_frontier = new_ids

    if not version_ids:
        return {"total_deleted": 0, "versions_deleted": 0, "branches_deleted": 0}

    unique_ids = list(set(version_ids))
    await session.execute(
        update(MemoryNode)
        .where(MemoryNode.id.in_(unique_ids))
        .values(status="deleted", deleted_at=now, is_current=False)
    )

    # Also delete child branches
    result = await session.execute(
        select(func.count()).select_from(MemoryNode).where(
            MemoryNode.parent_id.in_(unique_ids),
            MemoryNode.status != "deleted",
        )
    )
    branches = result.scalar() or 0
    if branches > 0:
        await session.execute(
            update(MemoryNode)
            .where(MemoryNode.parent_id.in_(unique_ids))
            .values(status="deleted", deleted_at=now, is_current=False)
        )

    await session.commit()
    return {
        "total_deleted": len(unique_ids) + branches,
        "versions_deleted": len(unique_ids),
        "branches_deleted": branches,
    }


async def list_memories(
    session: AsyncSession,
    *,
    scope: str | None = None,
    max_results: int = 100,
    current_only: bool = True,
    content_type: str | None = None,
) -> dict:
    """List memories ordered by creation time."""
    owner = get_owner_id()
    stmt = select(MemoryNode).where(
        MemoryNode.tenant_id == TENANT_ID,
        MemoryNode.status == "active",
        MemoryNode.owner_id == owner,
    )
    if scope:
        stmt = stmt.where(MemoryNode.scope == scope)
    if current_only:
        stmt = stmt.where(MemoryNode.is_current.is_(True))
    if content_type:
        stmt = stmt.where(MemoryNode.content_type == content_type)

    stmt = stmt.order_by(MemoryNode.created_at.desc()).limit(max_results + 1)
    result = await session.execute(stmt)
    nodes = list(result.scalars().all())

    has_more = len(nodes) > max_results
    if has_more:
        nodes = nodes[:max_results]

    return {
        "results": [_node_to_compact(n) for n in nodes],
        "count": len(nodes),
        "has_more": has_more,
    }


async def search_memories(
    session: AsyncSession,
    query: str,
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
    *,
    scope: str | None = None,
    max_results: int = 10,
    content_type: str | None = None,
) -> dict:
    """Search memories using vector and keyword recall."""
    owner = get_owner_id()
    query_embedding = await embedding_service.embed(query)

    filters = [
        MemoryNode.tenant_id == TENANT_ID,
        MemoryNode.status == "active",
        MemoryNode.owner_id == owner,
        MemoryNode.is_current.is_(True),
    ]
    if scope:
        filters.append(MemoryNode.scope == scope)
    if content_type:
        filters.append(MemoryNode.content_type == content_type)

    # Vector recall
    vector_results = await recall_backend.vector_recall(
        query_embedding, filters, max_results * 2, session,
    )

    # Keyword recall (FTS kept in sync by triggers installed at startup)
    keyword_results = await recall_backend.keyword_recall(
        query, filters, max_results, session,
    )

    # Merge: vector results first, then keyword results not already included
    seen_ids = set()
    merged = []
    for node, score in vector_results:
        if node.id not in seen_ids:
            seen_ids.add(node.id)
            merged.append((node, score, "vector"))
    for node, score in keyword_results:
        if node.id not in seen_ids:
            seen_ids.add(node.id)
            merged.append((node, score, "keyword"))

    merged = merged[:max_results]

    return {
        "results": [_node_to_search_result(n, s, src) for n, s, src in merged],
        "total_matching": len(merged),
        "has_more": False,
    }


async def get_memory_history(
    session: AsyncSession,
    memory_id: str,
    *,
    max_versions: int = 10,
) -> dict:
    """Get version history for a memory."""
    parsed_id = uuid.UUID(memory_id)

    # Walk the version chain backward
    versions = []
    current_id: uuid.UUID | None = parsed_id
    while current_id and len(versions) < max_versions:
        result = await session.execute(
            select(MemoryNode).where(
                MemoryNode.id == current_id,
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
        node = result.scalar_one_or_none()
        if node is None:
            break
        versions.append(node)
        current_id = node.previous_version_id

    return {
        "versions": [_node_to_compact(v) for v in versions],
        "total_versions": len(versions),
        "has_more": False,
    }


async def get_similar_memories(
    session: AsyncSession,
    memory_id: str,
    recall_backend: RecallBackend,
    *,
    threshold: float = 0.80,
    max_results: int = 10,
) -> list[dict]:
    """Find memories similar to a given memory."""
    node = await read_memory(session, memory_id)
    if node is None or not node.embedding:
        return []

    max_distance = 1.0 - threshold
    filters = [
        MemoryNode.tenant_id == TENANT_ID,
        MemoryNode.status == "active",
        MemoryNode.is_current.is_(True),
        MemoryNode.id != node.id,
    ]

    pairs = await recall_backend.similarity_check(
        node.embedding, filters, max_distance, max_results, session,
    )

    results = []
    for mem_id, distance in pairs:
        similar = await read_memory(session, str(mem_id))
        if similar:
            results.append({
                "id": str(similar.id),
                "content": similar.content,
                "scope": similar.scope,
                "relevance_score": round(1.0 - distance, 4),
            })
    return results


async def get_relationships(
    session: AsyncSession,
    memory_id: str,
    *,
    direction: str = "both",
) -> dict:
    """Get relationships for a memory node."""
    parsed_id = uuid.UUID(memory_id)
    relationships = []

    if direction in ("both", "outgoing"):
        result = await session.execute(
            select(MemoryRelationship).where(
                MemoryRelationship.source_id == parsed_id,
                MemoryRelationship.tenant_id == TENANT_ID,
            )
        )
        for rel in result.scalars():
            relationships.append({
                "source_id": str(rel.source_id),
                "target_id": str(rel.target_id),
                "relationship_type": rel.relationship_type,
                "created_at": rel.created_at.isoformat() if rel.created_at else None,
            })

    if direction in ("both", "incoming"):
        result = await session.execute(
            select(MemoryRelationship).where(
                MemoryRelationship.target_id == parsed_id,
                MemoryRelationship.tenant_id == TENANT_ID,
            )
        )
        for rel in result.scalars():
            relationships.append({
                "source_id": str(rel.source_id),
                "target_id": str(rel.target_id),
                "relationship_type": rel.relationship_type,
                "created_at": rel.created_at.isoformat() if rel.created_at else None,
            })

    return {"relationships": relationships}


async def create_relationship(
    session: AsyncSession,
    source_id: str,
    target_id: str,
    relationship_type: str,
    *,
    metadata: dict | None = None,
) -> dict:
    """Create a directed relationship between two memories."""
    rel = MemoryRelationship(
        source_id=uuid.UUID(source_id),
        target_id=uuid.UUID(target_id),
        relationship_type=relationship_type,
        created_by=get_owner_id(),
        tenant_id=TENANT_ID,
        metadata_=metadata,
    )
    session.add(rel)
    await session.commit()
    return {
        "id": str(rel.id),
        "source_id": source_id,
        "target_id": target_id,
        "relationship_type": relationship_type,
    }


async def report_contradiction(
    session: AsyncSession,
    memory_id: str,
    observed_behavior: str,
    *,
    confidence: float = 0.7,
) -> dict:
    """Report a contradiction against a stored memory."""
    report = ContradictionReport(
        memory_id=uuid.UUID(memory_id),
        observed_behavior=observed_behavior,
        confidence=confidence,
        reporter=get_owner_id(),
        tenant_id=TENANT_ID,
    )
    session.add(report)
    await session.commit()

    # Count total reports for this memory
    result = await session.execute(
        select(func.count()).select_from(ContradictionReport).where(
            ContradictionReport.memory_id == uuid.UUID(memory_id),
        )
    )
    count = result.scalar() or 0

    return {
        "contradiction_count": count,
        "threshold": 3,
        "revision_triggered": count >= 3,
    }


def _node_to_compact(node: MemoryNode) -> dict:
    """Convert a MemoryNode to a compact dict for tool responses."""
    return {
        "id": str(node.id),
        "content": node.content,
        "scope": node.scope,
        "weight": node.weight,
        "version": node.version,
        "is_current": node.is_current,
        "content_type": node.content_type,
        "source": node.source,
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def _node_to_search_result(
    node: MemoryNode,
    score: float,
    source: str,
) -> dict:
    """Convert a MemoryNode to a search result dict."""
    return {
        "id": str(node.id),
        "content": node.content,
        "result_type": "full",
        "relevance_score": round(1.0 - score, 4) if source == "vector" else round(score, 4),
        "content_truncated": False,
        "full_available": False,
        "source": node.source,
    }
