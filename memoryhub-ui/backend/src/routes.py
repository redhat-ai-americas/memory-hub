"""FastAPI route handlers for the MemoryHub UI BFF API."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import (
    get_memory_history as get_memory_history_service,
)
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
    PublicConfigResponse,
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


@router.get("/api/public-config", response_model=PublicConfigResponse)
async def get_public_config(settings: SettingsDep) -> PublicConfigResponse:
    """Return the public-facing route URLs the UI uses to compose contributor
    welcome emails. These are the URLs an external agent would connect to
    (not the BFF-internal SVC addresses used by the backend itself).

    Populated from MEMORYHUB_PUBLIC_MCP_URL and MEMORYHUB_PUBLIC_AUTH_URL
    env vars at deploy time. If the env vars are missing, returns the
    example.com placeholders from config defaults so the UI renders an
    obviously wrong URL rather than silently returning localhost.
    """
    return PublicConfigResponse(
        mcp_url=settings.public_mcp_url,
        auth_url=settings.public_auth_url,
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


@router.get("/api/graph", response_model=GraphResponse)
async def get_graph(
    db: DbDep,
    settings: SettingsDep,
    scope: str | None = Query(default=None),
    owner_id: str | None = Query(default=None),
):
    """Return all current memory nodes and their edges for graph visualization.

    Filters strictly by ``settings.ui_tenant_id`` (Phase 6 / issue #46).
    Cross-tenant rows are invisible at the SQL level, not merely hidden in
    the response, so the join below naturally excludes edges that would
    straddle tenants even though we defensively filter the relationship
    table too.
    """
    tenant_id = settings.ui_tenant_id
    stmt = select(MemoryNode).where(
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
    )
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

    # Explicit relationships where both endpoints are in our current node set.
    # We already scoped node_ids to this tenant above, so the IN() clause
    # alone would suffice; the explicit tenant_id predicate is belt-and-
    # suspenders for defence-in-depth and to keep this query readable
    # without cross-referencing upstream filters.
    if node_ids:
        node_id_list = list(node_ids)
        rel_stmt = select(MemoryRelationship).where(
            MemoryRelationship.tenant_id == tenant_id,
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
    """Search current memories by semantic similarity or text fallback.

    Filters strictly by ``settings.ui_tenant_id`` (Phase 6 / issue #46).
    """
    tenant_id = settings.ui_tenant_id
    embedding = await _get_embedding(q, settings.embedding_url)

    if embedding is not None:
        sql = text(
            """
            SELECT id::text, 1 - (embedding <=> CAST(:query_vec AS vector)) AS score
            FROM memory_nodes
            WHERE tenant_id = :tenant_id
              AND is_current = true
              AND deleted_at IS NULL
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT 20
            """
        )
        result = await db.execute(
            sql, {"query_vec": str(embedding), "tenant_id": tenant_id}
        )
        rows = result.fetchall()
        return [SearchMatch(id=row[0], score=float(row[1])) for row in rows]

    # Text fallback
    pattern = f"%{q}%"
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
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
    """Return dashboard statistics.

    All memory counts are scoped to ``settings.ui_tenant_id`` (Phase 6 /
    issue #46) -- the dashboard never surfaces totals or recent activity
    from other tenants.
    """
    tenant_id = settings.ui_tenant_id

    # Total current memories
    total_result = await db.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
    )
    total = total_result.scalar_one()

    # Count by scope
    scope_result = await db.execute(
        select(MemoryNode.scope, func.count().label("cnt"))
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
        .group_by(MemoryNode.scope)
    )
    scope_counts = [ScopeCount(scope=row[0], count=row[1]) for row in scope_result.fetchall()]

    # 10 most recently touched nodes
    recent_result = await db.execute(
        select(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
        .order_by(MemoryNode.updated_at.desc())
        .limit(10)
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
async def get_memory(memory_id: str, db: DbDep, settings: SettingsDep):
    """Return full detail for a single memory node.

    Filters by ``settings.ui_tenant_id`` (Phase 6 / issue #46). Cross-
    tenant lookups return 404 to avoid leaking existence across tenant
    boundaries -- same semantics as the service layer in Phase 4.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}")

    result = await db.execute(
        select(MemoryNode).where(
            MemoryNode.id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")

    # Children count (exclude deleted)
    count_result = await db.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(
            MemoryNode.parent_id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
        )
    )
    children_count = count_result.scalar_one()

    # Relationships (both incoming and outgoing)
    rel_result = await db.execute(
        select(MemoryRelationship).where(
            MemoryRelationship.tenant_id == tenant_id,
            (
                (MemoryRelationship.source_id == parsed_id)
                | (MemoryRelationship.target_id == parsed_id)
            ),
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
async def get_memory_history(memory_id: str, db: DbDep, settings: SettingsDep):
    """Return the full version chain for a memory, newest first.

    Delegates to ``memoryhub.services.memory.get_memory_history`` so the
    walker is bidirectional and a middle-version ID still returns the
    entire chain. Previously this endpoint hand-rolled a backward-only
    walker that was a parallel copy of the bug fixed in #49 at the
    service layer. See #63.

    Phase 6 (#46): forwards ``settings.ui_tenant_id`` to the service so
    cross-tenant history lookups raise ``MemoryNotFoundError`` (which the
    BFF translates to a 404), matching the service-layer semantics and
    avoiding existence leaks across tenants.
    """
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}")

    try:
        # Large max_versions preserves the BFF's unpaginated contract.
        # Version chains are realistically 10s of entries; pagination at
        # the BFF layer is future work and not part of the #63 walker fix.
        result = await get_memory_history_service(
            memory_id=parsed_id,
            session=db,
            tenant_id=settings.ui_tenant_id,
            max_versions=10_000,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")

    return [
        VersionEntry(
            id=str(v.id),
            version=v.version,
            is_current=v.is_current,
            stub=v.stub,
            content=v.content,
            created_at=v.created_at,
        )
        for v in result["versions"]
    ]


# ---------------------------------------------------------------------------
# Memory deletion
# ---------------------------------------------------------------------------


@router.delete("/api/memory/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, db: DbDep, settings: SettingsDep):
    """Soft-delete a memory and its entire version chain.

    Phase 6 (#46): every SELECT and the final bulk UPDATE filter by
    ``settings.ui_tenant_id``. Because the version chain and child
    branches inherit tenant from their parent row (Phase 3), adding a
    tenant filter on the walker queries is defensive but also prevents a
    pathological cross-tenant reparenting from escalating into a cross-
    tenant delete. Cross-tenant delete attempts 404.
    """
    from sqlalchemy import update as sa_update

    tenant_id = settings.ui_tenant_id

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}")

    result = await db.execute(
        select(MemoryNode).where(
            MemoryNode.id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")
    if node.deleted_at is not None:
        raise HTTPException(status_code=409, detail=f"Memory {memory_id!r} is already deleted")

    now = datetime.now(timezone.utc)

    # Collect version chain (walk backwards with cycle guard)
    version_ids: set = {parsed_id}
    current = node
    while current.previous_version_id and current.previous_version_id not in version_ids:
        version_ids.add(current.previous_version_id)
        prev_result = await db.execute(
            select(MemoryNode).where(
                MemoryNode.id == current.previous_version_id,
                MemoryNode.tenant_id == tenant_id,
            )
        )
        current = prev_result.scalar_one_or_none()
        if current is None:
            break

    # Walk forward through newer versions
    changed = True
    while changed:
        changed = False
        fwd_result = await db.execute(
            select(MemoryNode).where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.previous_version_id.in_(list(version_ids)),
                ~MemoryNode.id.in_(list(version_ids)),
            )
        )
        for fwd_node in fwd_result.scalars().all():
            version_ids.add(fwd_node.id)
            changed = True

    # Child branches
    child_result = await db.execute(
        select(MemoryNode).where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.parent_id.in_(list(version_ids)),
        )
    )
    child_ids = {child.id for child in child_result.scalars().all()}
    all_ids = version_ids | child_ids

    # Bulk soft-delete
    await db.execute(
        sa_update(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.id.in_(list(all_ids)),
        )
        .values(deleted_at=now, is_current=False)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Client management (proxy to auth service admin API)
#
# Phase 6 (#46) note: the /api/clients/* routes deliberately remain
# unscoped by tenant because they proxy verbatim to the auth service's
# /admin/clients API, which is itself not yet tenant-scoped. The auth
# admin API is a separate design concern (tracked as Phase 6 follow-up)
# and tenant scoping it there is out of scope for the BFF work. If/when
# the auth service grows a tenant filter, the BFF's ui_tenant_id should
# be forwarded in the _admin_request call so operators only see their
# own tenant's clients.
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

    Phase 6 (#46): the local memory_nodes aggregation is tenant-scoped by
    ``settings.ui_tenant_id`` so owners only appear with the memory
    counts from their own tenant. The auth service /admin/clients proxy
    portion is NOT tenant-scoped yet -- same caveat as /api/clients --
    so the merged roster may still show clients that have not written
    anything in this tenant (they'll appear with memory_count=0).
    """
    tenant_id = settings.ui_tenant_id

    # Get memory stats per owner from DB
    stats_query = (
        select(
            MemoryNode.owner_id,
            func.count().label("memory_count"),
            func.max(MemoryNode.updated_at).label("last_active"),
        )
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
        )
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
    settings: SettingsDep,
    tier: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    layer: str | None = Query(default=None),
):
    """List all curation rules with optional filters.

    Tenant-scoped to ``settings.ui_tenant_id`` (Phase 6 / #46). Each
    tenant maintains its own rule set -- default rules are seeded per
    tenant at the service layer.
    """
    tenant_id = settings.ui_tenant_id
    stmt = (
        select(CuratorRule)
        .where(CuratorRule.tenant_id == tenant_id)
        .order_by(CuratorRule.priority)
    )
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
async def create_rule(body: CreateRuleRequest, db: DbDep, settings: SettingsDep):
    """Create a new curation rule.

    Phase 6 (#46): stamps ``settings.ui_tenant_id`` on the new rule so it
    is owned by this UI deployment's tenant. The BFF never writes rules
    into other tenants' namespaces.
    """
    rule = CuratorRule(
        tenant_id=settings.ui_tenant_id,
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
async def get_rule(rule_id: str, db: DbDep, settings: SettingsDep):
    """Get a single curation rule by ID.

    Phase 6 (#46): cross-tenant rule lookups return 404.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    return _rule_to_response(rule)


@router.patch("/api/rules/{rule_id}", response_model=CurationRuleResponse)
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    db: DbDep,
    settings: SettingsDep,
):
    """Update a curation rule (toggle enabled, change priority, etc.).

    Phase 6 (#46): cross-tenant updates return 404 -- an operator cannot
    mutate another tenant's rule via this BFF even by guessing the UUID.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
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
async def delete_rule(rule_id: str, db: DbDep, settings: SettingsDep):
    """Delete a curation rule.

    Phase 6 (#46): cross-tenant deletes return 404.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}")
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Contradiction Log
# ---------------------------------------------------------------------------


def _live_contradictions(tenant_id: str):
    """Build a base SELECT for ContradictionReport joined to non-deleted memories.

    Reports whose target memory has been soft-deleted are excluded from
    every list/count/stats response. The MCP report_contradiction tool
    already prevents new reports from being created against deleted
    memories, but historical reports against memories that were later
    deleted still exist in the table and need to be filtered out here.

    Phase 6 (#46): filters both the report table and the joined memory
    table by ``tenant_id``. Tenant consistency across report and memory
    is already enforced at report creation time (Phase 3's
    report_contradiction inherits tenant from the memory), so filtering
    the report table alone would be sufficient -- filtering both is
    belt-and-suspenders defence-in-depth.
    """
    return (
        select(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
        )
    )


def _live_contradiction_count(tenant_id: str):
    """Count of contradictions whose target memory still exists.

    Phase 6 (#46): tenant-scoped via both the report and memory joined
    rows, matching _live_contradictions above.
    """
    return (
        select(func.count())
        .select_from(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
        )
    )


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
    settings: SettingsDep,
    resolved: bool | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
):
    """List contradiction reports with optional filters.

    Reports whose target memory has been soft-deleted are excluded.
    Phase 6 (#46): tenant-scoped to ``settings.ui_tenant_id``.
    """
    tenant_id = settings.ui_tenant_id
    stmt = _live_contradictions(tenant_id).order_by(ContradictionReport.created_at.desc())
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
async def contradiction_stats(db: DbDep, settings: SettingsDep):
    """Summary counts for the contradiction log dashboard.

    All counts exclude reports whose target memory has been soft-deleted.
    Phase 6 (#46): tenant-scoped to ``settings.ui_tenant_id``.
    """
    tenant_id = settings.ui_tenant_id

    total_result = await db.execute(_live_contradiction_count(tenant_id))
    total = total_result.scalar_one()

    unresolved_result = await db.execute(
        _live_contradiction_count(tenant_id).where(ContradictionReport.resolved.is_(False))
    )
    unresolved = unresolved_result.scalar_one()

    high_result = await db.execute(
        _live_contradiction_count(tenant_id).where(ContradictionReport.confidence > 0.8)
    )
    high = high_result.scalar_one()

    medium_result = await db.execute(
        _live_contradiction_count(tenant_id).where(
            ContradictionReport.confidence.between(0.5, 0.8)
        )
    )
    medium = medium_result.scalar_one()

    low_result = await db.execute(
        _live_contradiction_count(tenant_id).where(ContradictionReport.confidence < 0.5)
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
async def update_contradiction(
    report_id: str,
    body: UpdateContradictionRequest,
    db: DbDep,
    settings: SettingsDep,
):
    """Mark a contradiction report as resolved or unresolved.

    Phase 6 (#46): cross-tenant updates return 404. We belt-and-suspenders
    filter the joined memory row too, even though tenant consistency
    between report and target memory is already enforced at creation.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {report_id!r}")
    result = await db.execute(
        select(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.id == parsed_id,
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail=f"Contradiction report {report_id!r} not found")
    report.resolved = body.resolved
    report.resolved_at = datetime.now(timezone.utc) if body.resolved else None
    await db.commit()
    await db.refresh(report)
    return _contradiction_to_response(report)
