"""FastAPI route handlers for the MemoryHub UI BFF API."""

import logging
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub.models.memory import MemoryNode, MemoryRelationship
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.database import get_db
from src.schemas import (
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryDetail,
    RecentActivity,
    ScopeCount,
    SearchMatch,
    StatsResponse,
    VersionEntry,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_to_graph_node(node: MemoryNode) -> GraphNode:
    return GraphNode(
        id=str(node.id),
        content=node.content,
        stub=node.stub,
        scope=node.scope,
        weight=node.weight,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        version=node.version,
        created_at=node.created_at,
        updated_at=node.updated_at,
        metadata=node.metadata_,
        parent_id=str(node.parent_id) if node.parent_id else None,
    )


def _rel_to_edge(rel: MemoryRelationship) -> GraphEdge:
    return GraphEdge(
        id=str(rel.id),
        source=str(rel.source_id),
        target=str(rel.target_id),
        type=rel.relationship_type,
    )


async def _get_embedding(text_query: str, embedding_url: str) -> list[float] | None:
    """Call the embedding service; return None if unavailable."""
    if not embedding_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(embedding_url, json={"text": text_query})
            response.raise_for_status()
            data = response.json()
            return data.get("embedding")
    except Exception as exc:
        logger.warning("Embedding service unavailable, falling back to text search: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


@router.get("/api/graph", response_model=GraphResponse)
async def get_graph(
    db: DbDep,
    scope: str | None = Query(default=None),
    owner_id: str | None = Query(default=None),
):
    """Return all current memory nodes and their edges for graph visualization."""
    stmt = select(MemoryNode).where(MemoryNode.is_current.is_(True))
    if scope:
        stmt = stmt.where(MemoryNode.scope == scope)
    if owner_id:
        stmt = stmt.where(MemoryNode.owner_id == owner_id)

    result = await db.execute(stmt)
    nodes = result.scalars().all()

    node_ids = {node.id for node in nodes}
    graph_nodes = [_node_to_graph_node(n) for n in nodes]

    edges: list[GraphEdge] = []

    # Parent-child edges (both parent and child must be current)
    for node in nodes:
        if node.parent_id and node.parent_id in node_ids:
            edges.append(
                GraphEdge(
                    id=f"pc-{node.parent_id}-{node.id}",
                    source=str(node.parent_id),
                    target=str(node.id),
                    type="parent_child",
                )
            )

    # Explicit relationships where both endpoints are in our current node set
    if node_ids:
        node_id_list = list(node_ids)
        rel_stmt = select(MemoryRelationship).where(
            MemoryRelationship.source_id.in_(node_id_list),
            MemoryRelationship.target_id.in_(node_id_list),
        )
        rel_result = await db.execute(rel_stmt)
        relationships = rel_result.scalars().all()
        edges.extend(_rel_to_edge(r) for r in relationships)

    return GraphResponse(nodes=graph_nodes, edges=edges)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@router.get("/api/graph/search", response_model=list[SearchMatch])
async def search_graph(
    db: DbDep,
    settings: SettingsDep,
    q: str = Query(min_length=1),
):
    """Search current memories by semantic similarity or text fallback."""
    embedding = await _get_embedding(q, settings.embedding_url)

    if embedding is not None:
        sql = text(
            """
            SELECT id::text, 1 - (embedding <=> CAST(:query_vec AS vector)) AS score
            FROM memory_nodes
            WHERE is_current = true
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT 20
            """
        )
        result = await db.execute(sql, {"query_vec": str(embedding)})
        rows = result.fetchall()
        return [SearchMatch(id=row[0], score=float(row[1])) for row in rows]

    # Text fallback
    pattern = f"%{q}%"
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.is_current.is_(True),
            (MemoryNode.content.ilike(pattern) | MemoryNode.stub.ilike(pattern)),
        )
        .limit(20)
    )
    result = await db.execute(stmt)
    nodes = result.scalars().all()
    return [SearchMatch(id=str(n.id), score=1.0) for n in nodes]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/api/stats", response_model=StatsResponse)
async def get_stats(db: DbDep, settings: SettingsDep):
    """Return dashboard statistics."""
    # Total current memories
    total_result = await db.execute(select(func.count()).select_from(MemoryNode).where(MemoryNode.is_current.is_(True)))
    total = total_result.scalar_one()

    # Count by scope
    scope_result = await db.execute(
        select(MemoryNode.scope, func.count().label("cnt"))
        .where(MemoryNode.is_current.is_(True))
        .group_by(MemoryNode.scope)
    )
    scope_counts = [ScopeCount(scope=row[0], count=row[1]) for row in scope_result.fetchall()]

    # 10 most recently touched nodes
    recent_result = await db.execute(
        select(MemoryNode).where(MemoryNode.is_current.is_(True)).order_by(MemoryNode.updated_at.desc()).limit(10)
    )
    recent_nodes = recent_result.scalars().all()
    recent_activity = [
        RecentActivity(
            id=str(n.id),
            stub=n.stub,
            scope=n.scope,
            owner_id=n.owner_id,
            updated_at=n.updated_at,
            action="created" if n.version == 1 else "updated",
        )
        for n in recent_nodes
    ]

    # MCP health probe
    mcp_healthy = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.mcp_server_url)
            mcp_healthy = resp.status_code < 500
    except Exception:
        mcp_healthy = False

    return StatsResponse(
        total_memories=total,
        scope_counts=scope_counts,
        recent_activity=recent_activity,
        mcp_health=mcp_healthy,
    )


# ---------------------------------------------------------------------------
# Memory detail
# ---------------------------------------------------------------------------


@router.get("/api/memory/{memory_id}", response_model=MemoryDetail)
async def get_memory(memory_id: str, db: DbDep):
    """Return full detail for a single memory node."""
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}")

    result = await db.execute(select(MemoryNode).where(MemoryNode.id == parsed_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")

    # Children count
    count_result = await db.execute(
        select(func.count()).select_from(MemoryNode).where(MemoryNode.parent_id == parsed_id)
    )
    children_count = count_result.scalar_one()

    # Relationships (both incoming and outgoing)
    rel_result = await db.execute(
        select(MemoryRelationship).where(
            (MemoryRelationship.source_id == parsed_id) | (MemoryRelationship.target_id == parsed_id)
        )
    )
    relationships = rel_result.scalars().all()
    edges = [_rel_to_edge(r) for r in relationships]

    return MemoryDetail(
        id=str(node.id),
        content=node.content,
        stub=node.stub,
        scope=node.scope,
        weight=node.weight,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        version=node.version,
        is_current=node.is_current,
        parent_id=str(node.parent_id) if node.parent_id else None,
        metadata=node.metadata_,
        created_at=node.created_at,
        updated_at=node.updated_at,
        expires_at=node.expires_at,
        children_count=children_count,
        relationships=edges,
    )


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


@router.get("/api/memory/{memory_id}/history", response_model=list[VersionEntry])
async def get_memory_history(memory_id: str, db: DbDep):
    """Return the full version chain for a memory, newest first."""
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}")

    # Find the node (any version)
    result = await db.execute(select(MemoryNode).where(MemoryNode.id == parsed_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")

    # Walk the previous_version_id chain to collect all versions
    chain: list[MemoryNode] = [node]
    current = node
    seen: set[uuid.UUID] = {current.id}

    while current.previous_version_id and current.previous_version_id not in seen:
        seen.add(current.previous_version_id)
        prev_result = await db.execute(select(MemoryNode).where(MemoryNode.id == current.previous_version_id))
        prev = prev_result.scalar_one_or_none()
        if prev is None:
            break
        chain.append(prev)
        current = prev

    return [
        VersionEntry(
            id=str(n.id),
            version=n.version,
            is_current=n.is_current,
            stub=n.stub,
            content=n.content,
            created_at=n.created_at,
        )
        for n in chain
    ]
