"""FastAPI route handlers for the MemoryHub UI BFF API."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.conversation import ConversationThread
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import (
    get_memory_history as get_memory_history_service,
)
from sqlalchemy import and_, any_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.authorization import AccessDep, Principal, get_principal
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import _record_human_audit
from src.schemas import (
    ApiKeyRotatedResponse,
    AuthStatusResponse,
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
    MeResponse,
    NavCountsResponse,
    PublicConfigResponse,
    RecentActivity,
    RuleVersionEntry,
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


def _node_to_graph_node(node: MemoryNode, access: AccessDep) -> GraphNode:
    hidden = access.hides_content(node)
    return GraphNode(
        id=str(node.id),
        content="" if hidden else node.content,
        stub="Content hidden" if hidden else node.stub,
        scope=node.scope,
        weight=node.weight,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        version=node.version,
        created_at=node.created_at,
        updated_at=node.updated_at,
        metadata=None if hidden else node.metadata_,
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
    tenant_id: str | None = None,
    owner: str | None = None,
) -> httpx.Response:
    """Make an authenticated request to the auth service admin API."""
    if not settings.auth_service_url:
        raise HTTPException(
            status_code=503,
            detail="The auth service is not configured for this local deployment.",
        )
    url = f"{settings.auth_service_url}{path}"
    headers = {"X-Admin-Key": settings.admin_key}
    params: dict[str, str] = {}
    if tenant_id is not None:
        params["tenant_id"] = tenant_id
    if owner is not None:
        params["owner"] = owner
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method, url, headers=headers, json=json_body, params=params
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="The auth service is unavailable for this local deployment.",
        ) from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response


async def _get_embedding(text_query: str, embedding_url: str) -> list[float] | None:
    """Call the embedding service; return None if unavailable.

    Compatible with HuggingFace Text Embeddings Inference (TEI):
    POST {"inputs": "text"} → [[float, …]]
    """
    if not embedding_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(embedding_url, json={"inputs": text_query})
            response.raise_for_status()
            data = response.json()
            # TEI returns [[float, ...]] — unwrap the outer batch array
            if not data:
                return None
            return data[0] if isinstance(data[0], list) else data
    except Exception as exc:
        logger.warning("Embedding service unavailable, falling back to text search: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/api/me", response_model=MeResponse)
async def get_me(access: AccessDep, settings: SettingsDep, response: Response):
    """Expose only the verified OAuth-proxy principal needed by the UI Shell."""
    response.headers["Cache-Control"] = "no-store"
    principal = access.principal
    if principal.role == "user":
        write_scopes = ["user"] + (["project"] if access.human_projects else [])
        project_ids = sorted(access.human_projects)
    else:
        write_scopes = (["project"] if access.human_project_admins else [])
        if "organizational" in access.admin_write_scopes:
            write_scopes.append("organizational")
        project_ids = sorted(access.human_project_admins)
    return MeResponse(
        username=principal.username,
        name=principal.username,
        email=None,
        initials=principal.username[:2].upper(),
        source="local" if settings.ui_auth_mode == "local" else "oauth-proxy",
        role=principal.role,
        tenant_id=principal.tenant_id,
        write={"scopes": write_scopes, "project_ids": project_ids,
               "campaign_ids": [], "owner_id": principal.username},
        access={
            "hidden_scopes": sorted({
                "user", "project", "campaign", "role", "organizational", "enterprise",
            } - access.moderation_scopes),
            "break_glass": None,
        } if principal.role == "admin" else None,
    )


@router.get("/api/auth/status", response_model=AuthStatusResponse)
async def auth_status(principal: Annotated[Principal, Depends(get_principal)], response: Response):
    """Describe the existing OAuth-proxy login mode for a valid session."""
    response.headers["Cache-Control"] = "no-store"
    return AuthStatusResponse(
        mode="oauth-proxy", authenticated=True, api_key_login=False,
        local_accounts=False, user=principal.username, role=principal.role,
        cluster_domain=None, setup_required=False,
    )


@router.post("/api/auth/logout")
async def auth_logout(_principal: Annotated[Principal, Depends(get_principal)]):
    """Direct the browser to the proxy's existing cookie-clearing endpoint."""
    return {"ok": True, "redirect": "/oauth/sign_out", "method": "GET"}


@router.get("/api/nav-counts", response_model=NavCountsResponse)
async def nav_counts(db: DbDep, access: AccessDep):
    """Count only memories and review items visible to this human principal."""
    tenant = access.principal.tenant_id
    memories = (await db.execute(select(func.count()).select_from(MemoryNode).where(
        MemoryNode.tenant_id == tenant,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        access.clause(),
    ))).scalar_one()
    review_queue = 0
    if access.principal.role == "admin" and access.human_project_admins and "project" in access.moderation_scopes:
        review_queue = (await db.execute(select(func.count()).select_from(ContradictionReport).join(
            MemoryNode, ContradictionReport.memory_id == MemoryNode.id,
        ).where(
            ContradictionReport.tenant_id == tenant,
            ContradictionReport.resolved.is_(False),
            MemoryNode.tenant_id == tenant,
            MemoryNode.deleted_at.is_(None),
            MemoryNode.scope == "project",
            MemoryNode.scope_id.in_(access.human_project_admins),
            ~ContradictionReport.reporter.in_(access.identities),
            ~MemoryNode.owner_id.in_(access.identities),
            or_(MemoryNode.actor_id.is_(None), ~MemoryNode.actor_id.in_(access.identities)),
            or_(MemoryNode.driver_id.is_(None), ~MemoryNode.driver_id.in_(access.identities)),
        ))).scalar_one()
    return NavCountsResponse(memories=memories, review_queue=review_queue)


@router.get("/api/nav-features")
async def nav_features(_access: AccessDep):
    """No content-backed Labs modules are implemented by this BFF."""
    return {}


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
    access: AccessDep,
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
        access.clause(),
    )
    if scope:
        stmt = stmt.where(MemoryNode.scope == scope)
    if owner_id:
        stmt = stmt.where(MemoryNode.owner_id == owner_id)

    result = await db.execute(stmt)
    nodes = [n for n in result.scalars().all() if access.can_read(n)]

    node_ids = {node.id for node in nodes}
    graph_nodes = [_node_to_graph_node(n, access) for n in nodes]
    visible_node_ids = {str(node_id) for node_id in node_ids}
    for graph_node in graph_nodes:
        if graph_node.parent_id not in visible_node_ids:
            graph_node.parent_id = None

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
            MemoryRelationship.valid_until.is_(None),
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
    access: AccessDep,
    q: str = Query(min_length=1),
):
    """Search current memories by semantic similarity or text fallback.

    Filters strictly by ``settings.ui_tenant_id`` (Phase 6 / issue #46).
    """
    tenant_id = settings.ui_tenant_id
    embedding = await _get_embedding(q, settings.embedding_url)

    if embedding is not None:
        distance = MemoryNode.embedding.cosine_distance(embedding)
        stmt = (
            select(MemoryNode.id, (1 - distance).label("score"))
            .where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
                access.content_clause(),
            )
            .order_by(distance)
            .limit(20)
        )
        result = await db.execute(stmt)
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
            access.content_clause(),
            (MemoryNode.content.ilike(pattern) | MemoryNode.stub.ilike(pattern)),
        )
        .limit(20)
    )
    result = await db.execute(stmt)
    nodes = [n for n in result.scalars().all() if access.can_read(n)]
    return [SearchMatch(id=str(n.id), score=1.0) for n in nodes]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/api/stats", response_model=StatsResponse)
async def get_stats(db: DbDep, settings: SettingsDep, access: AccessDep):
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
            access.clause(),
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
            access.clause(),
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
            access.clause(),
        )
        .order_by(MemoryNode.updated_at.desc())
        .limit(10)
    )
    recent_nodes = recent_result.scalars().all()
    recent_activity = [
        RecentActivity(
            id=str(n.id),
            stub="Content hidden" if access.hides_content(n) else n.stub,
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
async def get_memory(memory_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Return full detail for a single memory node.

    Filters by ``settings.ui_tenant_id`` (Phase 6 / issue #46). Cross-
    tenant lookups return 404 to avoid leaking existence across tenant
    boundaries -- same semantics as the service layer in Phase 4.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}") from None

    result = await db.execute(
        select(MemoryNode).where(
            MemoryNode.id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")
    access.require_read(node)

    # Children count (exclude deleted)
    count_result = await db.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(
            MemoryNode.parent_id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
    )
    children_count = count_result.scalar_one()

    # Relationships (both incoming and outgoing)
    source = aliased(MemoryNode)
    target = aliased(MemoryNode)
    rel_result = await db.execute(
        select(MemoryRelationship)
        .join(source, source.id == MemoryRelationship.source_id)
        .join(target, target.id == MemoryRelationship.target_id)
        .where(
            MemoryRelationship.tenant_id == tenant_id,
            MemoryRelationship.valid_until.is_(None),
            access.clause(source),
            access.clause(target),
            source.deleted_at.is_(None),
            target.deleted_at.is_(None),
            (
                (MemoryRelationship.source_id == parsed_id)
                | (MemoryRelationship.target_id == parsed_id)
            ),
        )
    )
    relationships = rel_result.scalars().all()
    edges = [_rel_to_edge(r) for r in relationships]

    visible_parent_id = None
    if node.parent_id:
        parent = (await db.execute(select(MemoryNode.id).where(
            MemoryNode.id == node.parent_id,
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        ))).scalar_one_or_none()
        visible_parent_id = str(parent) if parent else None

    return MemoryDetail(
        id=str(node.id),
        content="" if access.hides_content(node) else node.content,
        stub="Content hidden" if access.hides_content(node) else node.stub,
        scope=node.scope,
        weight=node.weight,
        branch_type=node.branch_type,
        owner_id=node.owner_id,
        version=node.version,
        is_current=node.is_current,
        parent_id=visible_parent_id,
        metadata=None if access.hides_content(node) else node.metadata_,
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
async def get_memory_history(memory_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
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
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}") from None

    seed = (await db.execute(select(MemoryNode).where(
        MemoryNode.id == parsed_id,
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.deleted_at.is_(None),
        access.clause(),
    ))).scalar_one_or_none()
    if seed is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")
    access.require_read(seed)

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
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found") from None

    # Core's public history entries intentionally omit owner/scope fields.
    # Re-read the underlying rows with the human policy before returning any
    # version content; checking only the seed would expose changed ownership.
    versions = result["versions"]
    visible_rows = {}
    if versions:
        version_rows = (await db.execute(select(MemoryNode).where(
            MemoryNode.id.in_([version.id for version in versions]),
            MemoryNode.tenant_id == access.principal.tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        ))).scalars().all()
        visible_rows = {row.id: row for row in version_rows
                        if row.deleted_at is None and access.can_read(row)}

    return [
        VersionEntry(
            id=str(v.id),
            version=v.version,
            is_current=v.is_current,
            stub="Content hidden" if access.hides_content(visible_rows[v.id]) else v.stub,
            content="" if access.hides_content(visible_rows[v.id]) else v.content,
            created_at=v.created_at,
        )
        for v in versions if v.id in visible_rows
    ]


# ---------------------------------------------------------------------------
# Memory deletion
# ---------------------------------------------------------------------------


@router.delete("/api/memory/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
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
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {memory_id!r}") from None

    result = await db.execute(
        select(MemoryNode).where(
            MemoryNode.id == parsed_id,
            MemoryNode.tenant_id == tenant_id,
        ).with_for_update()
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")
    if node.deleted_at is not None:
        raise HTTPException(status_code=409, detail=f"Memory {memory_id!r} is already deleted")
    access.require_delete(node)

    # Use the same closure as the Core delete path, then authorize every row.
    from memoryhub_core.services.memory import collect_delete_nodes

    found = await collect_delete_nodes(node, db, tenant_id, seed_locked=True)
    for related in found.values():
        access.require_delete(related)

    now = datetime.now(UTC)
    all_ids = set(found)
    _record_human_audit(
        db, access, "memory.delete", node.scope, node.owner_id, node.id,
        {"deleted_rows": len(all_ids)},
    )

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
# ---------------------------------------------------------------------------

READ_CLIENT_SCOPES = frozenset({
    "memory:read", "memory:read:user", "memory:read:project",
    "memory:read:campaign", "memory:read:role", "memory:read:organizational",
    "memory:read:enterprise",
})
ASSIGNABLE_CLIENT_SCOPES = READ_CLIENT_SCOPES | {"memory:write:user"}


def _client_scopes_allowed(access: AccessDep, scopes: list[str], identity_type: str) -> None:
    # Human role alone cannot grant project/organizational/service-wide writes:
    # the current client model has no per-client project or object grant.
    if not scopes or len(scopes) != len(set(scopes)) or set(scopes) - ASSIGNABLE_CLIENT_SCOPES:
        raise HTTPException(status_code=403, detail="Client scope forbidden")
    if identity_type == "service" and "memory:write:user" in scopes:
        raise HTTPException(status_code=403, detail="Service client personal write forbidden")
    if access.principal.role == "user" and identity_type != "user":
        raise HTTPException(status_code=403, detail="Only user agents can be created")
    if access.principal.role == "admin":
        allowed_admin_reads = {f"memory:read:{scope}" for scope in access.moderation_scopes}
        if identity_type != "service" or set(scopes) - allowed_admin_reads:
            raise HTTPException(status_code=403, detail="Admin client scope or type forbidden")


async def _authorize_client(
    settings: Settings, access: AccessDep, client_id: str,
) -> dict:
    if access.principal.role == "user" and client_id not in access.agents:
        raise HTTPException(status_code=404, detail="Client not found")
    response = await _admin_request(
        settings, "GET", f"/admin/clients/{quote(client_id, safe='')}",
        tenant_id=access.principal.tenant_id,
        owner=access.principal.username if access.principal.role == "user" else None,
    )
    client = response.json()
    if client.get("tenant_id") != access.principal.tenant_id:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _reject_existing_identity_claim(
    db: AsyncSession, settings: Settings, client_id: str, tenant_id: str,
) -> None:
    """Do not let a new OAuth sub inherit an existing person's object grants."""
    human_names = {
        name.strip() for names in (settings.ui_allowed_users, settings.ui_admin_users)
        for name in names.split(",") if name.strip()
    }
    if not client_id or client_id in human_names:
        raise HTTPException(status_code=409, detail="Client ID is reserved by an existing identity")
    occupied = or_(
        select(MemoryNode.id).where(
            MemoryNode.tenant_id == tenant_id,
            or_(MemoryNode.owner_id == client_id, MemoryNode.actor_id == client_id,
                MemoryNode.driver_id == client_id),
        ).exists(),
        select(ProjectMembership.id).join(Project, Project.name == ProjectMembership.project_id).where(
            Project.tenant_id == tenant_id, ProjectMembership.user_id == client_id,
        ).exists(),
        select(RoleAssignment.id).where(
            RoleAssignment.tenant_id == tenant_id, RoleAssignment.user_id == client_id,
        ).exists(),
        select(CuratorRule.id).where(
            CuratorRule.tenant_id == tenant_id, CuratorRule.layer == "user",
            CuratorRule.owner_id == client_id,
        ).exists(),
        select(ConversationThread.id).where(
            ConversationThread.tenant_id == tenant_id,
            or_(ConversationThread.owner_id == client_id,
                ConversationThread.actor_id == client_id,
                ConversationThread.driver_id == client_id,
                client_id == any_(ConversationThread.participant_ids)),
        ).exists(),
    )
    if (await db.execute(select(occupied))).scalar_one():
        raise HTTPException(status_code=409, detail="Client ID is reserved by an existing identity")


@router.get("/api/clients", response_model=list[ClientResponse])
async def list_clients(settings: SettingsDep, access: AccessDep):
    resp = await _admin_request(
        settings, "GET", "/admin/clients", tenant_id=access.principal.tenant_id,
        owner=access.principal.username if access.principal.role == "user" else None,
    )
    clients = [c for c in resp.json() if c.get("tenant_id") == access.principal.tenant_id]
    if access.principal.role == "user":
        clients = [c for c in clients if c.get("client_id") in access.agents]
    return clients


@router.post("/api/clients", response_model=ClientCreatedResponse, status_code=201)
async def create_client(body: CreateClientRequest, db: DbDep, settings: SettingsDep, access: AccessDep):
    if body.tenant_id != access.principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant override forbidden")
    if access.principal.role == "user" and body.identity_type != "user":
        raise HTTPException(status_code=403, detail="Only user agents can be created")
    _client_scopes_allowed(access, body.default_scopes, body.identity_type)
    await _reject_existing_identity_claim(db, settings, body.client_id, access.principal.tenant_id)
    payload = body.model_dump()
    payload["tenant_id"] = access.principal.tenant_id
    # Every dashboard-created technical identity has a verified human owner.
    # Admin-created clients are service-only until the product has a trusted
    # way to assign a user-type client to the intended person.
    payload["owner"] = access.principal.username
    resp = await _admin_request(
        settings, "POST", "/admin/clients",
        json_body=payload, tenant_id=access.principal.tenant_id,
    )
    return resp.json()


@router.patch("/api/clients/{client_id}", response_model=ClientResponse)
async def update_client(client_id: str, body: UpdateClientRequest, settings: SettingsDep, access: AccessDep):
    payload = body.model_dump(exclude_none=True)
    client = await _authorize_client(settings, access, client_id)
    if (access.principal.role == "admin" and body.default_scopes is not None
            and client_id not in access.agents
            and (client["identity_type"] == "user"
                 or set(body.default_scopes) - set(client["default_scopes"]))):
        raise HTTPException(status_code=403, detail="Foreign agent scope expansion is forbidden")
    if body.default_scopes is not None:
        _client_scopes_allowed(access, body.default_scopes, client["identity_type"])
        if access.principal.role == "user" and set(body.default_scopes) - set(client["default_scopes"]):
            raise HTTPException(status_code=403, detail="Users cannot expand client scopes")
    if access.principal.role == "user" and body.active is True:
        raise HTTPException(status_code=403, detail="Users cannot reactivate clients")
    resp = await _admin_request(
        settings, "PATCH", f"/admin/clients/{quote(client_id, safe='')}",
        json_body=payload, tenant_id=access.principal.tenant_id,
        owner=access.principal.username if client_id in access.agents else None,
    )
    return resp.json()


@router.post("/api/clients/{client_id}/rotate-secret", response_model=SecretRotatedResponse)
async def rotate_client_secret(client_id: str, settings: SettingsDep, access: AccessDep):
    client = await _authorize_client(settings, access, client_id)
    _client_scopes_allowed(access, client["default_scopes"], client["identity_type"])
    if access.principal.role == "admin" and client_id not in access.agents:
        raise HTTPException(status_code=403, detail="Another agent's credentials are protected")
    resp = await _admin_request(
        settings, "POST", f"/admin/clients/{quote(client_id, safe='')}/rotate-secret",
        tenant_id=access.principal.tenant_id,
        owner=access.principal.username,
    )
    return resp.json()


@router.post("/api/clients/{client_id}/rotate-api-key", response_model=ApiKeyRotatedResponse)
async def rotate_api_key(client_id: str, settings: SettingsDep, access: AccessDep):
    client = await _authorize_client(settings, access, client_id)
    _client_scopes_allowed(access, client["default_scopes"], client["identity_type"])
    if access.principal.role == "admin" and client_id not in access.agents:
        raise HTTPException(status_code=403, detail="Another agent's credentials are protected")
    resp = await _admin_request(
        settings, "POST", f"/admin/clients/{quote(client_id, safe='')}/rotate-api-key",
        tenant_id=access.principal.tenant_id,
        owner=access.principal.username,
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Users and agents roster
# ---------------------------------------------------------------------------


@router.get("/api/users", response_model=list[dict])
async def list_users(db: DbDep, settings: SettingsDep, access: AccessDep):
    """List all identities with memory counts and last active times.

    Merges OAuth client data from auth service with memory stats from DB.
    Both the local memory_nodes aggregation and the auth service client
    list are tenant-scoped by ``settings.ui_tenant_id`` (#105).
    """
    tenant_id = access.principal.tenant_id

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
            access.clause(),
        )
        .group_by(MemoryNode.owner_id)
    )
    if access.principal.role == "user":
        stats_query = stats_query.where(MemoryNode.owner_id.in_(access.identities))
    result = await db.execute(stats_query)
    owner_stats = {
        row[0]: {"memory_count": row[1], "last_active": row[2]}
        for row in result.fetchall()
    }

    # The roster must not masquerade as complete when Auth is unavailable.
    resp = await _admin_request(
        settings, "GET", "/admin/clients", tenant_id=tenant_id,
        owner=access.principal.username if access.principal.role == "user" else None,
    )
    clients = [c for c in resp.json() if c.get("tenant_id") == tenant_id]
    if access.principal.role == "user":
        clients = [c for c in clients if c.get("client_id") in access.agents]

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
        version=rule.version,
        is_current=rule.is_current,
        previous_version_id=str(rule.previous_version_id) if rule.previous_version_id else None,
        edited_by=rule.edited_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _can_read_rule(access: AccessDep, rule: CuratorRule) -> bool:
    if rule.tenant_id != access.principal.tenant_id:
        return False
    if rule.layer in ("system", "organizational"):
        return True
    return rule.layer == "user" and (
        access.principal.role == "admin" or rule.owner_id == access.principal.username
    )


def _can_change_rule(access: AccessDep, rule: CuratorRule) -> bool:
    if rule.tenant_id != access.principal.tenant_id:
        return False
    if rule.layer == "user":
        return rule.owner_id == access.principal.username
    return access.principal.role == "admin" and rule.layer == "organizational"


@router.get("/api/rules", response_model=list[CurationRuleResponse])
async def list_rules(
    db: DbDep,
    settings: SettingsDep,
    access: AccessDep,
    tier: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    layer: str | None = Query(default=None),
):
    """List all curation rules with optional filters.

    Tenant-scoped to ``settings.ui_tenant_id`` (Phase 6 / #46). Each
    tenant maintains its own rule set -- default rules are seeded per
    tenant at the service layer.
    """
    tenant_id = access.principal.tenant_id
    visible_user_rules = (
        CuratorRule.layer == "user" if access.principal.role == "admin"
        else and_(CuratorRule.layer == "user", CuratorRule.owner_id == access.principal.username)
    )
    stmt = (
        select(CuratorRule)
        .where(CuratorRule.tenant_id == tenant_id, CuratorRule.is_current.is_(True))
        .where(or_(
            CuratorRule.layer.in_(("system", "organizational")),
            visible_user_rules,
        ))
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
    return [_rule_to_response(r) for r in rules if _can_read_rule(access, r)]


@router.post("/api/rules", response_model=CurationRuleResponse, status_code=201)
async def create_rule(body: CreateRuleRequest, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Create a new curation rule.

    Phase 6 (#46): stamps ``settings.ui_tenant_id`` on the new rule so it
    is owned by this UI deployment's tenant. The BFF never writes rules
    into other tenants' namespaces.
    """
    if body.layer == "system" or body.layer not in ("user", "organizational"):
        raise HTTPException(status_code=403, detail="Rule layer is protected")
    if access.principal.role == "user" and body.layer != "user":
        raise HTTPException(status_code=403, detail="Only personal rules may be created")
    if body.layer == "user" and body.owner_id not in (None, access.principal.username):
        raise HTTPException(status_code=403, detail="Rule owner override forbidden")
    if body.layer == "organizational" and body.owner_id is not None:
        raise HTTPException(status_code=403, detail="Organizational rule cannot have a personal owner")
    if access.principal.role == "user" and body.override:
        raise HTTPException(status_code=403, detail="Personal override forbidden")
    rule = CuratorRule(
        tenant_id=access.principal.tenant_id,
        name=body.name,
        description=body.description,
        trigger=body.trigger,
        tier=body.tier,
        config=body.config,
        action=body.action,
        scope_filter=body.scope_filter,
        layer=body.layer,
        owner_id=access.principal.username if body.layer == "user" else None,
        override=body.override,
        enabled=body.enabled,
        priority=body.priority,
        version=1,
        is_current=True,
        edited_by=access.principal.username,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_response(rule)


@router.get("/api/rules/{rule_id}", response_model=CurationRuleResponse)
async def get_rule(rule_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Get a single curation rule by ID.

    Phase 6 (#46): cross-tenant rule lookups return 404.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}") from None
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    if not _can_read_rule(access, rule):
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    return _rule_to_response(rule)


@router.patch("/api/rules/{rule_id}", response_model=CurationRuleResponse)
async def update_rule(
    rule_id: str,
    body: UpdateRuleRequest,
    db: DbDep,
    settings: SettingsDep,
    access: AccessDep,
):
    """Create a new version of a curation rule (copy-on-write).

    Marks the existing row as is_current=False and inserts a new row with
    version+1 and previous_version_id pointing to the old row. This preserves
    the full audit trail of every change.

    Phase 6 (#46): cross-tenant updates return 404.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}") from None
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        ).with_for_update()
    )
    old_rule = result.scalar_one_or_none()
    if old_rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    if not _can_change_rule(access, old_rule):
        raise HTTPException(status_code=403, detail="Rule change forbidden")
    if not old_rule.is_current:
        raise HTTPException(status_code=409, detail=f"Rule {rule_id!r} is not the current version")

    update_data = body.model_dump(exclude_unset=True)
    update_data.pop("edited_by", None)
    if "layer" in update_data and update_data["layer"] != old_rule.layer:
        raise HTTPException(status_code=403, detail="Rule layer change forbidden")
    if "owner_id" in update_data and update_data["owner_id"] != old_rule.owner_id:
        raise HTTPException(status_code=403, detail="Rule owner change forbidden")
    if access.principal.role == "user" and update_data.get("override"):
        raise HTTPException(status_code=403, detail="Personal override forbidden")
    if access.principal.role == "user" and old_rule.override:
        update_data["override"] = False

    if not update_data:
        return _rule_to_response(old_rule)

    new_rule = CuratorRule(
        tenant_id=tenant_id,
        name=update_data.get("name", old_rule.name),
        description=update_data.get("description", old_rule.description),
        trigger=update_data.get("trigger", old_rule.trigger),
        tier=update_data.get("tier", old_rule.tier),
        config=update_data.get("config", old_rule.config),
        action=update_data.get("action", old_rule.action),
        scope_filter=update_data.get("scope_filter", old_rule.scope_filter),
        layer=update_data.get("layer", old_rule.layer),
        owner_id=update_data.get("owner_id", old_rule.owner_id),
        override=update_data.get("override", old_rule.override),
        enabled=update_data.get("enabled", old_rule.enabled),
        priority=update_data.get("priority", old_rule.priority),
        version=old_rule.version + 1,
        previous_version_id=old_rule.id,
        is_current=True,
        edited_by=access.principal.username,
    )

    old_rule.is_current = False
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    return _rule_to_response(new_rule)


@router.get("/api/rules/{rule_id}/history", response_model=list[RuleVersionEntry])
async def get_rule_history(rule_id: str, db: DbDep, settings: SettingsDep, request: Request):
    """Return the full version chain for a rule, newest first.

    Accepts any version's UUID — walks backward via previous_version_id
    and forward to find all versions in the chain.

    Phase 6 (#46): tenant-scoped; cross-tenant lookups return 404.
    """
    # The audited UI has no human rule-history operation. This legacy route
    # remains available only to a local technical caller with the service key.
    import hmac
    peer = request.client.host if request.client else ""
    if peer not in ("127.0.0.1", "::1") or not settings.admin_key or not hmac.compare_digest(
        request.headers.get("x-admin-key", ""), settings.admin_key
    ):
        raise HTTPException(status_code=403, detail="Technical access only")
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}") from None

    # 404 check — also gates the CTE below to this tenant's data
    seed_result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
    if seed_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")

    # Single recursive CTE: walk backward to the oldest ancestor, then forward
    # through all descendants — replaces the previous O(N) per-version loop.
    chain_result = await db.execute(
        text("""
            WITH RECURSIVE
              ancestors(id, previous_version_id) AS (
                SELECT id, previous_version_id FROM curator_rules WHERE id = :seed_id AND tenant_id = :tenant_id
                UNION
                SELECT r.id, r.previous_version_id FROM curator_rules r
                JOIN ancestors a ON r.id = a.previous_version_id WHERE r.tenant_id = :tenant_id
              ),
              root AS (SELECT id FROM ancestors WHERE previous_version_id IS NULL),
              chain AS (
                SELECT r.id, r.version, r.is_current, r.name, r.edited_by, r.created_at
                FROM curator_rules r JOIN root ON r.id = root.id WHERE r.tenant_id = :tenant_id
                UNION
                SELECT r.id, r.version, r.is_current, r.name, r.edited_by, r.created_at
                FROM curator_rules r
                JOIN chain c ON r.previous_version_id = c.id WHERE r.tenant_id = :tenant_id
              )
            SELECT id, version, is_current, name, edited_by, created_at
            FROM chain
            ORDER BY version DESC
        """),
        {"seed_id": parsed_id, "tenant_id": tenant_id},
    )
    return [
        RuleVersionEntry(
            id=str(row.id),
            version=row.version,
            is_current=row.is_current,
            name=row.name,
            edited_by=row.edited_by,
            created_at=row.created_at,
        )
        for row in chain_result.fetchall()
    ]


@router.delete("/api/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Delete a curation rule.

    Only the current version can be deleted (non-current → 409). Historical
    versions (is_current=False) are retained as a permanent audit trail — they
    become permanently orphaned with no current anchor. If a new rule with the
    same (layer, owner_id, name) is later created it starts at version 1 with
    no chain connection to the prior history. There is no bulk-delete endpoint
    for the orphaned chain; storage must be reclaimed via DB maintenance.

    Phase 6 (#46): cross-tenant deletes return 404.
    """
    tenant_id = settings.ui_tenant_id
    try:
        parsed_id = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {rule_id!r}") from None
    result = await db.execute(
        select(CuratorRule).where(
            CuratorRule.id == parsed_id,
            CuratorRule.tenant_id == tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id!r} not found")
    if not _can_change_rule(access, rule):
        raise HTTPException(status_code=403, detail="Rule delete forbidden")
    if not rule.is_current:
        raise HTTPException(
            status_code=409,
            detail=f"Rule {rule_id!r} is not the current version; only current rules can be deleted",
        )
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Contradiction Log
# ---------------------------------------------------------------------------


def _live_contradictions(tenant_id: str, access: AccessDep):
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
    stmt = (
        select(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.content_clause(),
        )
    )
    if access.principal.role == "admin":
        stmt = stmt.where(MemoryNode.scope.in_(access.moderation_scopes))
    return stmt


def _live_contradiction_count(tenant_id: str, access: AccessDep):
    """Count of contradictions whose target memory still exists.

    Phase 6 (#46): tenant-scoped via both the report and memory joined
    rows, matching _live_contradictions above.
    """
    stmt = (
        select(func.count())
        .select_from(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.content_clause(),
        )
    )
    if access.principal.role == "admin":
        stmt = stmt.where(MemoryNode.scope.in_(access.moderation_scopes))
    return stmt


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
    access: AccessDep,
    resolved: bool | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
):
    """List contradiction reports with optional filters.

    Reports whose target memory has been soft-deleted are excluded.
    Phase 6 (#46): tenant-scoped to ``settings.ui_tenant_id``.
    """
    tenant_id = settings.ui_tenant_id
    stmt = _live_contradictions(tenant_id, access).order_by(ContradictionReport.created_at.desc())
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
async def contradiction_stats(db: DbDep, settings: SettingsDep, access: AccessDep):
    """Summary counts for the contradiction log dashboard.

    All counts exclude reports whose target memory has been soft-deleted.
    Phase 6 (#46): tenant-scoped to ``settings.ui_tenant_id``.
    """
    tenant_id = settings.ui_tenant_id

    total_result = await db.execute(_live_contradiction_count(tenant_id, access))
    total = total_result.scalar_one()

    unresolved_result = await db.execute(
        _live_contradiction_count(tenant_id, access).where(ContradictionReport.resolved.is_(False))
    )
    unresolved = unresolved_result.scalar_one()

    high_result = await db.execute(
        _live_contradiction_count(tenant_id, access).where(ContradictionReport.confidence > 0.8)
    )
    high = high_result.scalar_one()

    medium_result = await db.execute(
        _live_contradiction_count(tenant_id, access).where(
            ContradictionReport.confidence.between(0.5, 0.8)
        )
    )
    medium = medium_result.scalar_one()

    low_result = await db.execute(
        _live_contradiction_count(tenant_id, access).where(ContradictionReport.confidence < 0.5)
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
    access: AccessDep,
):
    """Mark a contradiction report as resolved or unresolved.

    Phase 6 (#46): cross-tenant updates return 404. We belt-and-suspenders
    filter the joined memory row too, even though tenant consistency
    between report and target memory is already enforced at creation.
    """
    if access.principal.role != "admin":
        raise HTTPException(status_code=403, detail="Review is for admins only")
    tenant_id = access.principal.tenant_id
    try:
        parsed_id = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid UUID: {report_id!r}") from None
    result = await db.execute(
        select(ContradictionReport, MemoryNode)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.id == parsed_id,
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Contradiction report {report_id!r} not found")
    report, memory = row
    if not access.can_review(memory):
        raise HTTPException(status_code=404, detail=f"Contradiction report {report_id!r} not found")
    if (
        report.reporter in access.identities
        or memory.owner_id in access.identities
        or memory.actor_id in access.identities
        or memory.driver_id in access.identities
    ):
        raise HTTPException(status_code=403, detail="Self review forbidden")
    report.resolved = body.resolved
    report.resolved_at = datetime.now(UTC) if body.resolved else None
    report.resolved_by = access.principal.username if body.resolved else None
    _record_human_audit(
        db, access,
        "memory.contradiction_resolved" if body.resolved else "memory.contradiction_reopened",
        memory.scope, memory.owner_id, memory.id,
        {"report_id": str(report.id), "resolved": body.resolved},
    )
    await db.commit()
    await db.refresh(report)
    return _contradiction_to_response(report)
