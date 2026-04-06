"""FastAPI route handlers for the MemoryHub UI BFF API."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub.models.contradiction import ContradictionReport
from memoryhub.models.curation import CuratorRule
from memoryhub.models.memory import MemoryNode, MemoryRelationship
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.database import get_db
from src.schemas import (
    ClientCreatedResponse,
    ClientResponse,
    ContradictionResponse,
    ContradictionStatsResponse,
    CreateClientRequest,
    CreateRuleRequest,
    CurationRuleResponse,
    GraphEdge,
    GraphNode,
    GraphResponse,
    MemoryDetail,
    RecentActivity,
    ScopeCount,
    SearchMatch,
    SecretRotatedResponse,
    StatsResponse,
    UpdateClientRequest,
    UpdateContradictionRequest,
    UpdateRuleRequest,
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


async def _admin_request(
    settings: Settings,
    method: str,
    path: str,
    json_body: dict | None = None,
) -> httpx.Response:
    """Make an authenticated request to the auth service admin API."""
    url = f"{settings.auth_service_url}{path}"
    headers = {"X-Admin-Key": settings.admin_key}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.request(method, url, headers=headers, json=json_body)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response


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


# ---------------------------------------------------------------------------
# Client management (proxy to auth service admin API)
# ---------------------------------------------------------------------------


@router.get("/api/clients", response_model=list[ClientResponse])
async def list_clients(settings: SettingsDep):
    resp = await _admin_request(settings, "GET", "/admin/clients")
    return resp.json()


@router.post("/api/clients", response_model=ClientCreatedResponse, status_code=201)
async def create_client(body: CreateClientRequest, settings: SettingsDep):
    resp = await _admin_request(settings, "POST", "/admin/clients", json_body=body.model_dump())
    return resp.json()


@router.patch("/api/clients/{client_id}", response_model=ClientResponse)
async def update_client(client_id: str, body: UpdateClientRequest, settings: SettingsDep):
    payload = body.model_dump(exclude_none=True)
    resp = await _admin_request(settings, "PATCH", f"/admin/clients/{client_id}", json_body=payload)
    return resp.json()


@router.post("/api/clients/{client_id}/rotate-secret", response_model=SecretRotatedResponse)
async def rotate_client_secret(client_id: str, settings: SettingsDep):
    resp = await _admin_request(settings, "POST", f"/admin/clients/{client_id}/rotate-secret")
    return resp.json()


# ---------------------------------------------------------------------------
# Users and agents roster
# ---------------------------------------------------------------------------


@router.get("/api/users", response_model=list[dict])
async def list_users(db: DbDep, settings: SettingsDep):
    """List all identities with memory counts and last active times.

    Merges OAuth client data from auth service with memory stats from DB.
    """
    # Get memory stats per owner from DB
    stats_query = (
        select(
            MemoryNode.owner_id,
            func.count().label("memory_count"),
            func.max(MemoryNode.updated_at).label("last_active"),
        )
        .where(MemoryNode.is_current.is_(True))
        .group_by(MemoryNode.owner_id)
    )
    result = await db.execute(stats_query)
    owner_stats = {
        row[0]: {"memory_count": row[1], "last_active": row[2]}
        for row in result.fetchall()
    }

    # Try to get client list from auth service
    clients = []
    try:
        resp = await _admin_request(settings, "GET", "/admin/clients")
        clients = resp.json()
    except Exception:
        logger.warning("Could not fetch clients from auth service, using DB owner_ids only")

    if clients:
        # Merge: auth clients enriched with memory stats
        users = []
        seen_owners: set[str] = set()
        for c in clients:
            cid = c["client_id"]
            stats = owner_stats.get(cid, {"memory_count": 0, "last_active": None})
            users.append({
                "name": c["client_name"],
                "owner_id": cid,
                "identity_type": c["identity_type"],
                "memory_count": stats["memory_count"],
                "last_active": stats["last_active"],
            })
            seen_owners.add(cid)
        # Add owners that exist in DB but not in auth service
        for owner_id, stats in owner_stats.items():
            if owner_id not in seen_owners:
                users.append({
                    "name": owner_id,
                    "owner_id": owner_id,
                    "identity_type": "unknown",
                    "memory_count": stats["memory_count"],
                    "last_active": stats["last_active"],
                })
        return users

    # Fallback: just DB owner_ids
    return [
        {
            "name": owner_id,
            "owner_id": owner_id,
            "identity_type": "unknown",
            "memory_count": stats["memory_count"],
            "last_active": stats["last_active"],
        }
        for owner_id, stats in owner_stats.items()
    ]


# ---------------------------------------------------------------------------
# Curation Rules
# ---------------------------------------------------------------------------


def _rule_to_response(rule: CuratorRule) -> CurationRuleResponse:
    return CurationRuleResponse(
        id=str(rule.id),
        name=rule.name,
        description=rule.description,
        trigger=rule.trigger,
        tier=rule.tier,
        config=rule.config,
        action=rule.action,
        scope_filter=rule.scope_filter,
        layer=rule.layer,
        owner_id=rule.owner_id,
        override=rule.override,
        enabled=rule.enabled,
        priority=rule.priority,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("/api/rules", response_model=list[CurationRuleResponse])
async def list_rules(
    db: DbDep,
    tier: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    layer: str | None = Query(default=None),
):
    """List all curation rules with optional filters."""
    stmt = select(CuratorRule).order_by(CuratorRule.priority)
    if tier:
        stmt = stmt.where(CuratorRule.tier == tier)
    if enabled is not None:
        stmt = stmt.where(CuratorRule.enabled == enabled)
    if layer:
        stmt = stmt.where(CuratorRule.layer == layer)
    result = await db.execute(stmt)
    rules = result.scalars().all()
    return [_rule_to_response(r) for r in rules]


@router.post("/api/rules", response_model=CurationRuleResponse, status_code=201)
async def create_rule(body: CreateRuleRequest, db: DbDep):
    """Create a new curation rule."""
    rule = CuratorRule(
        name=body.name,
        description=body.description,
        trigger=body.trigger,
        tier=body.tier,
        config=body.config,
        action=body.action,
        scope_filter=body.scope_filter,
        layer=body.layer,
        owner_id=body.owner_id,
        override=body.override,
        enabled=body.enabled,
        priority=body.priority,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_response(rule)


@router.get("/api/rules/{rule_id}", response_model=CurationRuleResponse)
async def get_rule(rule_id: str, db: DbDep):
    """Get a single curation rule by ID."""
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(select(CuratorRule).where(CuratorRule.id == parsed_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    return _rule_to_response(rule)


@router.patch("/api/rules/{rule_id}", response_model=CurationRuleResponse)
async def update_rule(rule_id: str, body: UpdateRuleRequest, db: DbDep):
    """Update a curation rule (toggle enabled, change priority, etc.)."""
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(select(CuratorRule).where(CuratorRule.id == parsed_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_response(rule)


@router.delete("/api/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, db: DbDep):
    """Delete a curation rule."""
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(select(CuratorRule).where(CuratorRule.id == parsed_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Contradiction Log
# ---------------------------------------------------------------------------


def _contradiction_to_response(report: ContradictionReport) -> ContradictionResponse:
    return ContradictionResponse(
        id=str(report.id),
        memory_id=str(report.memory_id),
        observed_behavior=report.observed_behavior,
        confidence=report.confidence,
        reporter=report.reporter,
        created_at=report.created_at,
        resolved=report.resolved,
        resolved_at=report.resolved_at,
    )


@router.get("/api/contradictions", response_model=list[ContradictionResponse])
async def list_contradictions(
    db: DbDep,
    resolved: bool | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
):
    """List contradiction reports with optional filters."""
    stmt = select(ContradictionReport).order_by(ContradictionReport.created_at.desc())
    if resolved is not None:
        stmt = stmt.where(ContradictionReport.resolved == resolved)
    if min_confidence is not None:
        stmt = stmt.where(ContradictionReport.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(ContradictionReport.confidence <= max_confidence)
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [_contradiction_to_response(r) for r in reports]


@router.get("/api/contradictions/stats", response_model=ContradictionStatsResponse)
async def contradiction_stats(db: DbDep):
    """Summary counts for the contradiction log dashboard."""
    total_result = await db.execute(
        select(func.count()).select_from(ContradictionReport)
    )
    total = total_result.scalar_one()

    unresolved_result = await db.execute(
        select(func.count()).select_from(ContradictionReport).where(
            ContradictionReport.resolved.is_(False)
        )
    )
    unresolved = unresolved_result.scalar_one()

    high_result = await db.execute(
        select(func.count()).select_from(ContradictionReport).where(
            ContradictionReport.confidence > 0.8
        )
    )
    high = high_result.scalar_one()

    medium_result = await db.execute(
        select(func.count()).select_from(ContradictionReport).where(
            ContradictionReport.confidence.between(0.5, 0.8)
        )
    )
    medium = medium_result.scalar_one()

    low_result = await db.execute(
        select(func.count()).select_from(ContradictionReport).where(
            ContradictionReport.confidence < 0.5
        )
    )
    low = low_result.scalar_one()

    return ContradictionStatsResponse(
        total=total,
        unresolved=unresolved,
        high_confidence=high,
        medium_confidence=medium,
        low_confidence=low,
    )


@router.patch("/api/contradictions/{report_id}", response_model=ContradictionResponse)
async def update_contradiction(report_id: str, body: UpdateContradictionRequest, db: DbDep):
    """Mark a contradiction report as resolved or unresolved."""
    try:
        parsed_id = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {report_id!r}")
    result = await db.execute(select(ContradictionReport).where(ContradictionReport.id == parsed_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail=f"Contradiction report {report_id!r} not found")
    report.resolved = body.resolved
    report.resolved_at = datetime.now(timezone.utc) if body.resolved else None
    await db.commit()
    await db.refresh(report)
    return _contradiction_to_response(report)
