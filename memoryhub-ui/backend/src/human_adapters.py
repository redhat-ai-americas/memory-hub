"""Human BFF adapters for existing Core operations.

These routes use the OAuth-proxy principal and object grants. MCP scopes are
deliberately not accepted as dashboard permissions.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.config import ValkeySettings
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate, RelationshipCreate, RelationshipType
from memoryhub_core.services.admin import quarantine_memory, record_moderation_audit, restore_memory
from memoryhub_core.services.embeddings import HttpEmbeddingService
from memoryhub_core.services.entity import merge_entities, rename_entity
from memoryhub_core.services.exceptions import (
    CrossTenantRelationshipError,
    LastAdminError,
    MembershipNotFoundError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import (
    collect_delete_nodes,
)
from memoryhub_core.services.memory import (
    create_memory as core_create_memory,
)
from memoryhub_core.services.memory import (
    report_contradiction as core_report_contradiction,
)
from memoryhub_core.services.memory import (
    update_memory as core_update_memory,
)
from memoryhub_core.services.project import (
    add_project_member,
    get_project_members,
    remove_project_member,
)
from memoryhub_core.services.project import (
    create_project as core_create_project,
)
from memoryhub_core.services.valkey_client import ValkeyClient, ValkeyUnavailableError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.authorization import AccessDep, AgentOwner
from src.config import Settings, get_settings
from src.database import get_db

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectMemberBody(StrictBody):
    user_id: str = Field(min_length=1, max_length=255)
    role: Literal["member", "admin"] = "member"


class ProjectCreateBody(StrictBody):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$", max_length=255)
    description: str | None = None
    invite_only: bool = False
    members: list[ProjectMemberBody] = Field(default_factory=list, max_length=100)


class MemoryCreateBody(StrictBody):
    content: str = Field(min_length=1)
    scope: Literal["user", "project", "organizational"]
    weight: float = Field(default=0.7, ge=0, le=1)
    owner_id: str | None = None
    scope_id: str | None = None
    domains: list[str] | None = None


class VersionBody(StrictBody):
    content: str | None = Field(default=None, min_length=1)
    weight: float | None = Field(default=None, ge=0, le=1)
    domains: list[str] | None = None
    metadata: dict | None = None


class BranchBody(StrictBody):
    branch_type: Literal["rationale", "provenance", "evidence", "description"]
    content: str = Field(min_length=1)


class RelationshipBody(StrictBody):
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: Literal["related_to", "derived_from", "supersedes", "conflicts_with"]


class ReportBody(StrictBody):
    observed_behavior: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class BulkBody(StrictBody):
    action: Literal["quarantine", "restore", "delete", "relate"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=500)
    target_id: uuid.UUID | None = None
    relationship_type: Literal["related_to", "derived_from", "supersedes", "conflicts_with"] | None = None


class EntityUpdateBody(StrictBody):
    name: str | None = Field(default=None, min_length=1)
    entity_type: str | None = None
    aliases: list[str] | None = None


class EntityMergeBody(StrictBody):
    into: uuid.UUID
    dry_run: bool = False


@lru_cache(maxsize=4)
def _cached_embedding_service(url: str) -> HttpEmbeddingService:
    return HttpEmbeddingService(url)


@lru_cache(maxsize=4)
def _cached_valkey_client(url: str) -> ValkeyClient:
    return ValkeyClient(ValkeySettings(url=url))


def get_embedding_service(settings: SettingsDep) -> HttpEmbeddingService:
    if not settings.embedding_url:
        raise HTTPException(status_code=503, detail="Embedding service is not configured")
    return _cached_embedding_service(settings.embedding_url)


EmbeddingDep = Annotated[HttpEmbeddingService, Depends(get_embedding_service)]


def _record_human_audit(
    db: AsyncSession, access: AccessDep, event_type: str, scope: str,
    owner_id: str, memory_id: uuid.UUID | None = None, metadata: dict | None = None,
) -> None:
    """Stage an append-only audit row in the mutation's existing transaction."""
    if not isinstance(db, AsyncSession):
        return  # Test doubles have no SQLAlchemy unit of work.
    db.add(AuditLog(
        event_type=event_type, actor_id=access.principal.username,
        driver_id=access.principal.username, scope=scope,
        owner_id=owner_id, memory_id=memory_id, decision="allowed",
        event_metadata=metadata, tenant_id=access.principal.tenant_id,
    ))


async def _project(db: AsyncSession, access: AccessDep, name: str, *, lock: bool = False) -> Project:
    stmt = select(Project).where(Project.name == name, Project.tenant_id == access.principal.tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    project = (await db.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _membership(db: AsyncSession, access: AccessDep, name: str, *, admin: bool = False) -> bool:
    """Recheck a live human membership inside the mutation transaction."""
    stmt = select(ProjectMembership).join(Project, ProjectMembership.project_id == Project.name).where(
        Project.tenant_id == access.principal.tenant_id,
        ProjectMembership.project_id == name,
        ProjectMembership.user_id == access.principal.username,
    ).with_for_update(of=ProjectMembership)
    rows = (await db.execute(stmt)).scalars().all()
    return any(m.role == "admin" for m in rows) if admin else bool(rows)


async def _known_member(db: AsyncSession, settings: Settings, tenant: str, user_id: str) -> bool:
    humans = {name.strip() for raw in (settings.ui_allowed_users, settings.ui_admin_users)
              for name in raw.split(",") if name.strip()}
    if user_id in humans:
        return True
    stmt = select(AgentOwner.client_id).where(AgentOwner.tenant_id == tenant, AgentOwner.client_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _project_row(db: AsyncSession, access: AccessDep, project: Project) -> dict:
    tenant = access.principal.tenant_id
    member_count = (await db.execute(select(func.count()).select_from(ProjectMembership).where(
        ProjectMembership.project_id == project.name,
    ))).scalar_one()
    memory_info = (await db.execute(select(func.count(MemoryNode.id), func.max(MemoryNode.updated_at)).where(
        MemoryNode.tenant_id == tenant,
        MemoryNode.scope == "project",
        MemoryNode.scope_id == project.name,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
    ))).one()
    campaigns = (await db.execute(select(Campaign).join(
        CampaignMembership, CampaignMembership.campaign_id == Campaign.id,
    ).where(Campaign.tenant_id == tenant, CampaignMembership.project_id == project.name))).scalars().all()
    my_role = (await db.execute(select(ProjectMembership.role).where(
        ProjectMembership.project_id == project.name,
        ProjectMembership.user_id == access.principal.username,
    ))).scalar_one_or_none()
    return {
        "name": project.name,
        "description": project.description,
        "invite_only": project.invite_only,
        "created_at": project.created_at,
        "created_by": project.created_by,
        "memories": memory_info[0],
        "last_write": memory_info[1],
        "members": member_count,
        "campaigns": [{"id": str(c.id), "name": c.name, "status": c.status} for c in campaigns],
        "my_role": my_role,
        "owner": project.created_by,
    }


@router.get("/api/projects")
async def list_projects(db: DbDep, access: AccessDep, mine: bool = Query(False)):
    tenant = access.principal.tenant_id
    my_projects = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == access.principal.username,
    )
    stmt = select(Project).where(Project.tenant_id == tenant)
    if mine:
        stmt = stmt.where(Project.name.in_(my_projects))
    elif access.principal.role == "user":
        stmt = stmt.where(or_(Project.name.in_(my_projects), Project.invite_only.is_(False)))
    projects = (await db.execute(stmt.order_by(Project.name))).scalars().all()
    items = [await _project_row(db, access, p) for p in projects]
    return {
        "items": items,
        "total": len(items),
        "viewer": access.principal.username,
        "can_create": access.principal.role == "admin",
        "can_delete": False,
    }


@router.get("/api/projects/{name}")
async def project_detail(name: str, db: DbDep, settings: SettingsDep, access: AccessDep):
    project = await _project(db, access, name)
    is_member = await _membership(db, access, name)
    if access.principal.role == "user" and project.invite_only and not is_member:
        raise HTTPException(status_code=404, detail="Project not found")
    can_read_project_details = is_member or access.principal.role == "admin"
    row = await _project_row(db, access, project)
    focus = None
    focus_available = False
    if can_read_project_details and settings.valkey_url:
        end = datetime.now(UTC).date()
        client = _cached_valkey_client(settings.valkey_url)
        try:
            entries = await client.read_focus_history(name, end - timedelta(days=29), end)
        except ValkeyUnavailableError:
            pass
        else:
            focus_counts = Counter(entry["focus"] for entry in entries
                                   if isinstance(entry.get("focus"), str) and entry["focus"])
            focus = [{"focus": value, "count": count}
                     for value, count in sorted(focus_counts.items(), key=lambda item: (-item[1], item[0]))]
            focus_available = True
    row.update({
        "can_manage": access.principal.role == "admin" and await _membership(db, access, name, admin=True),
        "can_delete": False,
        "members_list": await get_project_members(db, name) if can_read_project_details else [],
        "focus_history": focus,
        "focus_available": focus_available,
    })
    return row


@router.post("/api/projects", status_code=201)
async def create_project(body: ProjectCreateBody, db: DbDep, settings: SettingsDep, access: AccessDep):
    if access.principal.role != "admin":
        raise HTTPException(status_code=403, detail="Project creation forbidden")
    members = body.members
    if len({m.user_id for m in members}) != len(members) or any(
        m.user_id == access.principal.username for m in members
    ):
        raise HTTPException(status_code=422, detail="Duplicate project member")
    for member in members:
        if not await _known_member(db, settings, access.principal.tenant_id, member.user_id):
            raise HTTPException(status_code=422, detail="Unknown project member")
    try:
        await core_create_project(
            db, body.name, access.principal.tenant_id, access.principal.username,
            description=body.description, invite_only=body.invite_only,
        )
        _record_human_audit(db, access, "project.created", "project", access.principal.username,
                            metadata={"project_id": body.name})
        for member in members:
            added = await add_project_member(db, body.name, member.user_id, access.principal.username, member.role)
            if not added:
                raise HTTPException(status_code=409, detail="Project member already exists")
            _record_human_audit(db, access, "project.member_added", "project", access.principal.username,
                                metadata={"project_id": body.name, "user_id": member.user_id, "role": member.role})
        await db.commit()
    except ProjectAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Project already exists") from None
    return {"name": body.name}


@router.post("/api/projects/{name}/members")
async def add_member(name: str, body: ProjectMemberBody, db: DbDep, settings: SettingsDep, access: AccessDep):
    if access.principal.role != "admin":
        raise HTTPException(status_code=403, detail="Project membership management forbidden")
    await _project(db, access, name, lock=True)
    if not await _membership(db, access, name, admin=True):
        raise HTTPException(status_code=403, detail="Project membership management forbidden")
    if not await _known_member(db, settings, access.principal.tenant_id, body.user_id):
        raise HTTPException(status_code=422, detail="Unknown project member")
    try:
        added = await add_project_member(db, name, body.user_id, access.principal.username, body.role)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    if not added:
        raise HTTPException(status_code=409, detail="Project member already exists")
    _record_human_audit(db, access, "project.member_added", "project", access.principal.username,
                        metadata={"project_id": name, "user_id": body.user_id, "role": body.role})
    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/members/{user_id}", status_code=204)
async def remove_member(name: str, user_id: str, db: DbDep, access: AccessDep):
    await _project(db, access, name, lock=True)
    self_leave = access.principal.role == "user" and user_id == access.principal.username
    admin_remove = access.principal.role == "admin" and user_id != access.principal.username
    if self_leave:
        if not await _membership(db, access, name):
            raise HTTPException(status_code=404, detail="Project membership not found")
    elif admin_remove:
        if not await _membership(db, access, name, admin=True):
            raise HTTPException(status_code=403, detail="Project membership management forbidden")
    else:
        raise HTTPException(status_code=403, detail="Project membership management forbidden")
    try:
        await remove_project_member(db, name, user_id)
        _record_human_audit(db, access, "project.member_removed", "project", access.principal.username,
                            metadata={"project_id": name, "user_id": user_id})
        await db.commit()
    except (ProjectNotFoundError, MembershipNotFoundError):
        raise HTTPException(status_code=404, detail="Project membership not found") from None
    except LastAdminError:
        raise HTTPException(status_code=409, detail="Cannot remove the last project admin") from None


async def _node(db: AsyncSession, access: AccessDep, memory_id: uuid.UUID, *, lock: bool = False) -> MemoryNode:
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id,
                                    MemoryNode.tenant_id == access.principal.tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    node = (await db.execute(stmt)).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return node


async def _require_write(db: AsyncSession, access: AccessDep, node: MemoryNode) -> None:
    if not access.can_write(node):
        raise HTTPException(status_code=404, detail="Memory not found")
    if node.scope == "project" and not await _membership(
        db, access, node.scope_id, admin=access.principal.role == "admin",
    ):
        raise HTTPException(status_code=404, detail="Memory not found")


async def _mutation_neighbors(db: AsyncSession, access: AccessDep, node: MemoryNode) -> None:
    """Preflight the branch/relationship set that Core versioning mutates."""
    children = (await db.execute(select(MemoryNode).where(
        MemoryNode.parent_id == node.id,
    ).with_for_update())).scalars().all()
    rels = (await db.execute(select(MemoryRelationship).where(
        MemoryRelationship.valid_until.is_(None),
        or_(MemoryRelationship.source_id == node.id, MemoryRelationship.target_id == node.id),
    ).with_for_update())).scalars().all()
    if any(rel.tenant_id != access.principal.tenant_id for rel in rels):
        raise HTTPException(status_code=409, detail="Memory relationship boundary invalid")
    neighbor_ids = {rel.target_id if rel.source_id == node.id else rel.source_id for rel in rels}
    if node.parent_id:
        neighbor_ids.add(node.parent_id)
    if neighbor_ids:
        neighbors = (await db.execute(select(MemoryNode).where(
            MemoryNode.id.in_(neighbor_ids),
        ).with_for_update())).scalars().all()
    else:
        neighbors = []
    if len(neighbors) != len(neighbor_ids):
        raise HTTPException(status_code=409, detail="Memory relationship boundary invalid")
    for child in children:
        await _require_write(db, access, child)
    for related in neighbors:
        # Core only re-points an existing MENTIONS edge to an entity when a
        # memory gets a new version. It does not edit the entity itself.
        # Requiring entity write here would block ordinary versioning because
        # entity nodes have their own managed scope.
        related_edges = [rel for rel in rels if related.id in (rel.source_id, rel.target_id)]
        entity_reference = (
            related.id != node.parent_id
            and related.scope == "entity"
            and related.tenant_id == access.principal.tenant_id
            and related.deleted_at is None
            and related.is_current
            and related.status == "active"
            and related_edges
            and all(rel.relationship_type == "mentions" and rel.source_id == node.id
                    and rel.target_id == related.id for rel in related_edges)
        )
        if not entity_reference:
            await _require_write(db, access, related)


@router.post("/api/memories", status_code=201)
async def create_memory(body: MemoryCreateBody, db: DbDep, access: AccessDep, embedding: EmbeddingDep):
    username = access.principal.username
    if body.scope == "user":
        if access.principal.role != "user" or body.scope_id is not None or body.owner_id not in (None, username):
            raise HTTPException(status_code=403, detail="Memory scope forbidden")
        owner, scope_id = username, None
    elif body.scope == "project":
        if not body.scope_id or body.owner_id not in (None, username, body.scope_id):
            raise HTTPException(status_code=403, detail="Memory scope forbidden")
        await _project(db, access, body.scope_id, lock=True)
        if not await _membership(db, access, body.scope_id, admin=access.principal.role == "admin"):
            raise HTTPException(status_code=403, detail="Project write forbidden")
        owner, scope_id = username, body.scope_id
    else:
        if (access.principal.role != "admin" or "organizational" not in access.admin_write_scopes
                or body.scope_id is not None or body.owner_id not in (None, username)):
            raise HTTPException(status_code=403, detail="Memory scope forbidden")
        owner, scope_id = username, None
    data = MemoryNodeCreate(
        content=body.content, scope=body.scope, weight=body.weight, owner_id=owner,
        actor_id=username, driver_id=username, scope_id=scope_id, domains=body.domains,
    )
    _record_human_audit(db, access, "memory.write", body.scope, owner,
                        metadata={"scope_id": scope_id})
    created, curation = await core_create_memory(
        data, db, embedding, tenant_id=access.principal.tenant_id,
    )
    if created is None:
        raise HTTPException(status_code=409, detail="Curation blocked write")
    return {"id": str(created.id)}


@router.post("/api/memory/{memory_id}/versions", status_code=201)
async def new_version(memory_id: uuid.UUID, body: VersionBody, db: DbDep, access: AccessDep, embedding: EmbeddingDep):
    if body.content is None and body.weight is None and body.domains is None and body.metadata is None:
        raise HTTPException(status_code=422, detail="No changes provided")
    node = await _node(db, access, memory_id, lock=True)
    await _require_write(db, access, node)
    await _mutation_neighbors(db, access, node)
    _record_human_audit(db, access, "memory.update", node.scope, node.owner_id, node.id)
    try:
        version = await core_update_memory(
            memory_id, MemoryNodeUpdate(**body.model_dump(exclude_unset=True)), db, embedding,
            actor_id=access.principal.username, driver_id=access.principal.username,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    except MemoryNotCurrentError:
        raise HTTPException(status_code=409, detail="Memory is not current") from None
    return {"id": str(version.id), "version": version.version}


@router.post("/api/memory/{memory_id}/branches", status_code=201)
async def add_branch(memory_id: uuid.UUID, body: BranchBody, db: DbDep, access: AccessDep, embedding: EmbeddingDep):
    parent = await _node(db, access, memory_id, lock=True)
    await _require_write(db, access, parent)
    if parent.scope not in ("user", "project", "organizational"):
        raise HTTPException(status_code=403, detail="Branch scope forbidden")
    data = MemoryNodeCreate(
        content=body.content, scope=parent.scope, scope_id=parent.scope_id,
        owner_id=parent.owner_id, actor_id=access.principal.username,
        driver_id=access.principal.username, weight=parent.weight,
        parent_id=parent.id, branch_type=body.branch_type,
    )
    _record_human_audit(db, access, "memory.write", parent.scope, parent.owner_id,
                        metadata={"parent_id": str(parent.id), "branch_type": body.branch_type})
    created, curation = await core_create_memory(data, db, embedding, tenant_id=access.principal.tenant_id)
    if created is None:
        raise HTTPException(status_code=409, detail="Curation blocked write")
    return {"id": str(created.id)}


@router.post("/api/relationships", status_code=201)
async def relate(body: RelationshipBody, db: DbDep, access: AccessDep):
    if body.source_id == body.target_id:
        raise HTTPException(status_code=422, detail="A relationship requires two memories")
    source = await _node(db, access, body.source_id, lock=True)
    target = await _node(db, access, body.target_id, lock=True)
    await _require_write(db, access, source)
    await _require_write(db, access, target)
    if (source.scope != target.scope or source.scope_id != target.scope_id
            or (source.scope == "user" and source.owner_id != target.owner_id)):
        raise HTTPException(status_code=403, detail="Relationship scope forbidden")
    data = RelationshipCreate(
        source_id=body.source_id, target_id=body.target_id,
        relationship_type=RelationshipType(body.relationship_type), created_by=access.principal.username,
    )
    _record_human_audit(db, access, "memory.relationship_created", source.scope, source.owner_id,
                        source.id, {"target_id": str(target.id), "relationship_type": body.relationship_type})
    try:
        result = await create_relationship(data, db)
    except (MemoryNotFoundError, ValueError):
        raise HTTPException(status_code=409, detail="Relationship cannot be created") from None
    return {"id": str(result.id)}


@router.post("/api/memory/{memory_id}/contradictions", status_code=201)
async def report(memory_id: uuid.UUID, body: ReportBody, db: DbDep, access: AccessDep):
    node = await _node(db, access, memory_id, lock=True)
    await _require_write(db, access, node)
    _record_human_audit(db, access, "memory.contradiction_reported", node.scope, node.owner_id, node.id)
    try:
        unresolved = await core_report_contradiction(
            memory_id, body.observed_behavior, body.confidence, access.principal.username, db,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    return {"unresolved": unresolved}


@router.post("/api/memories/bulk")
async def moderate_bulk(body: BulkBody, db: DbDep, access: AccessDep):
    """Apply existing Core transitions only after full-set preflight."""
    if len(set(body.ids)) != len(body.ids):
        raise HTTPException(status_code=422, detail="Duplicate memory IDs")
    if body.action == "delete":
        if body.target_id or body.relationship_type:
            raise HTTPException(status_code=422, detail="Unexpected relationship options")
        return await _bulk_delete(body.ids, db, access)
    if body.action == "relate":
        if body.target_id is None or body.relationship_type is None:
            raise HTTPException(status_code=422, detail="Target and relationship type required")
        return await _bulk_relate(body.ids, body.target_id, body.relationship_type, db, access)
    if access.principal.role != "admin":
        raise HTTPException(status_code=403, detail="Moderation forbidden")
    if body.target_id or body.relationship_type:
        raise HTTPException(status_code=422, detail="Unexpected relationship options")
    nodes = []
    for memory_id in sorted(body.ids):
        node = await _node(db, access, memory_id, lock=True)
        if not access.can_moderate(node):
            raise HTTPException(status_code=404, detail="Memory not found")
        if node.scope == "project" and not await _membership(db, access, node.scope_id, admin=True):
            raise HTTPException(status_code=404, detail="Memory not found")
        expected = "active" if body.action == "quarantine" else "quarantined"
        if node.status != expected:
            raise HTTPException(status_code=409, detail="Memory status does not permit this transition")
        nodes.append(node)
    reason = body.reason.strip() if body.reason else "Dashboard moderation"
    service = quarantine_memory if body.action == "quarantine" else restore_memory
    for node in nodes:
        _record_human_audit(db, access, f"admin.{body.action}", node.scope, node.owner_id, node.id,
                            {"reason": reason})
        await service(
            db, memory_id=node.id, tenant_id=access.principal.tenant_id,
            actor_id=access.principal.username, actor_type="user", reason=reason, commit=False,
        )
    await db.commit()
    for node in nodes:
        record_moderation_audit(
            body.action, actor_id=access.principal.username, actor_type="user",
            tenant_id=access.principal.tenant_id, memory_id=node.id,
            previous_status="active" if body.action == "quarantine" else "quarantined",
            reason=reason,
        )
    return {"done": [str(node.id) for node in nodes], "errors": []}


async def _bulk_delete(ids: list[uuid.UUID], db: AsyncSession, access: AccessDep) -> dict:
    """Use the Core delete closure; update all rows in one transaction."""
    tenant = access.principal.tenant_id
    roots = []
    closure: dict[uuid.UUID, MemoryNode] = {}
    for memory_id in sorted(ids):
        node = await _node(db, access, memory_id, lock=True)
        access.require_delete(node)
        if node.deleted_at is not None:
            raise HTTPException(status_code=409, detail="Memory is already deleted")
        roots.append(node)
        try:
            related = await collect_delete_nodes(node, db, tenant, seed_locked=True)
        except MemoryNotFoundError:
            raise HTTPException(status_code=404, detail="Memory not found") from None
        for member in related.values():
            access.require_delete(member)
            if member.deleted_at is not None:
                raise HTTPException(status_code=409, detail="Memory is already deleted")
            closure[member.id] = member
    # Soft-delete does not mutate unrelated edge endpoints. A corrupt
    # cross-tenant edge is nevertheless a boundary failure, not a reason to
    # proceed with a partially visible graph.
    edges = (await db.execute(select(MemoryRelationship).where(
        MemoryRelationship.valid_until.is_(None),
        or_(MemoryRelationship.source_id.in_(closure),
            MemoryRelationship.target_id.in_(closure)),
    ).with_for_update())).scalars().all()
    if any(edge.tenant_id != tenant for edge in edges):
        raise HTTPException(status_code=409, detail="Memory relationship boundary invalid")
    now = datetime.now(UTC)
    for node in roots:
        _record_human_audit(db, access, "memory.delete", node.scope, node.owner_id, node.id,
                            {"deleted_rows": len(closure), "bulk": True})
    try:
        await db.execute(sa_update(MemoryNode).where(
            MemoryNode.tenant_id == tenant, MemoryNode.id.in_(closure),
        ).values(deleted_at=now, is_current=False))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"done": [str(node.id) for node in roots], "errors": []}


async def _bulk_relate(ids: list[uuid.UUID], target_id: uuid.UUID,
                       relationship_type: str, db: AsyncSession, access: AccessDep) -> dict:
    """Preflight every source and target before creating any edge."""
    if target_id in ids:
        raise HTTPException(status_code=422, detail="A relationship requires two memories")
    target = await _node(db, access, target_id, lock=True)
    await _require_write(db, access, target)
    sources = []
    for memory_id in sorted(ids):
        source = await _node(db, access, memory_id, lock=True)
        await _require_write(db, access, source)
        if (source.scope != target.scope or source.scope_id != target.scope_id
                or (source.scope == "user" and source.owner_id != target.owner_id)):
            raise HTTPException(status_code=403, detail="Relationship scope forbidden")
        sources.append(source)
    existing = (await db.execute(select(MemoryRelationship.source_id).where(
        MemoryRelationship.tenant_id == access.principal.tenant_id,
        MemoryRelationship.source_id.in_(ids),
        MemoryRelationship.target_id == target_id,
        MemoryRelationship.relationship_type == relationship_type,
        MemoryRelationship.valid_until.is_(None),
    ).with_for_update())).scalars().all()
    if existing:
        raise HTTPException(status_code=409, detail="Relationship already exists")
    try:
        for source in sources:
            data = RelationshipCreate(
                source_id=source.id, target_id=target.id,
                relationship_type=RelationshipType(relationship_type),
                created_by=access.principal.username,
            )
            _record_human_audit(db, access, "memory.relationship_created", source.scope,
                                source.owner_id, source.id,
                                {"target_id": str(target.id), "relationship_type": relationship_type})
            await create_relationship(data, db, commit=False)
        await db.commit()
    except (MemoryNotFoundError, CrossTenantRelationshipError, ValueError):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Relationship cannot be created") from None
    except Exception:
        await db.rollback()
        raise
    return {"done": [str(node.id) for node in sources], "errors": []}


def _human_content_clause(access: AccessDep, model=MemoryNode):
    """Content access from direct human grants, never an agent membership."""
    tenant = and_(model.tenant_id == access.principal.tenant_id,
                  model.deleted_at.is_(None))
    if access.principal.role == "user":
        return and_(tenant, model.status == "active", or_(
            and_(model.scope == "user", model.owner_id.in_(access.identities)),
            and_(model.scope == "project", model.scope_id.in_(access.human_projects)),
            and_(model.scope == "role", model.scope_id.in_(access.human_roles)),
            and_(model.scope == "campaign", model.owner_id.in_(access.human_campaigns)),
            model.scope.in_(("organizational", "enterprise")),
        ))
    allowed = []
    if "organizational" in access.moderation_scopes:
        allowed.append(model.scope == "organizational")
    if "project" in access.moderation_scopes:
        allowed.append(and_(model.scope == "project", model.scope_id.in_(access.human_projects)))
    if "role" in access.moderation_scopes:
        allowed.append(and_(model.scope == "role", model.scope_id.in_(access.human_roles)))
    if "campaign" in access.moderation_scopes:
        allowed.append(and_(model.scope == "campaign", model.owner_id.in_(access.human_campaigns)))
    return and_(tenant, or_(*allowed)) if allowed else and_(tenant, model.id.is_(None))


def _human_can_see_content(access: AccessDep, memory: MemoryNode) -> bool:
    if memory.tenant_id != access.principal.tenant_id or memory.deleted_at is not None:
        return False
    if access.principal.role == "user":
        return memory.status == "active" and memory.deleted_at is None and (
            (memory.scope == "user" and memory.owner_id in access.identities)
            or (memory.scope == "project" and memory.scope_id in access.human_projects)
            or (memory.scope == "role" and memory.scope_id in access.human_roles)
            or (memory.scope == "campaign" and memory.owner_id in access.human_campaigns)
            or memory.scope in ("organizational", "enterprise")
        )
    return (
        (memory.scope == "organizational" and "organizational" in access.moderation_scopes)
        or (memory.scope == "project" and memory.scope_id in access.human_projects
            and "project" in access.moderation_scopes)
        or (memory.scope == "role" and memory.scope_id in access.human_roles
            and "role" in access.moderation_scopes)
        or (memory.scope == "campaign" and memory.owner_id in access.human_campaigns
            and "campaign" in access.moderation_scopes)
    )


@router.get("/api/memories/browse")
async def browse_memories(
    db: DbDep,
    access: AccessDep,
    tab: Literal["current", "all", "quarantined", "deleted"] = "current",
    q: str | None = None,
    mode: Literal["semantic", "text", "metadata"] = "semantic",
    scope: list[str] | None = Query(None),
    actor: list[str] | None = Query(None),
    project: str | None = None,
    domain: list[str] | None = Query(None),
    min_weight: float | None = Query(None, ge=0, le=1),
    max_weight: float | None = Query(None, ge=0, le=1),
    created_from: date | None = None,
    created_to: date | None = None,
    branch_type: str | None = None,
    flag: list[str] | None = Query(None),
    entity: uuid.UUID | None = None,
    sort: Literal["updated", "created", "weight", "relevance"] = "updated",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Read existing memories with the same human scope as other BFF reads."""
    if min_weight is not None and max_weight is not None and min_weight > max_weight:
        raise HTTPException(status_code=422, detail="Invalid weight range")
    if flag and any(value not in ("contradicted", "has_branches") for value in flag):
        raise HTTPException(status_code=422, detail="Unsupported flag filter")
    if access.principal.role == "user" and tab in ("quarantined", "deleted"):
        raise HTTPException(status_code=403, detail="Memory state forbidden")
    access.forbid_person_filter(actor)
    tenant = access.principal.tenant_id
    base = [MemoryNode.tenant_id == tenant]
    if access.principal.role == "user":
        base.append(_human_content_clause(access))
    else:
        # Admin rows are metadata of shared scopes only; personal memories are excluded (#667).
        base.append(access.clause())
    filters = list(base)
    if tab == "current":
        filters.extend((MemoryNode.deleted_at.is_(None), MemoryNode.is_current.is_(True),
                        MemoryNode.status == "active"))
    elif tab == "all":
        filters.append(MemoryNode.deleted_at.is_(None))
    elif tab == "quarantined":
        filters.extend((MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined"))
    else:
        filters.append(MemoryNode.deleted_at.is_not(None))
    if scope:
        filters.append(MemoryNode.scope.in_(scope))
    if actor:
        filters.append(MemoryNode.actor_id.in_(actor))
    if project:
        filters.extend((MemoryNode.scope == "project", MemoryNode.scope_id == project))
    if domain:
        filters.extend((_human_content_clause(access), MemoryNode.domains.overlap(domain)))
    if min_weight is not None:
        filters.append(MemoryNode.weight >= min_weight)
    if max_weight is not None:
        filters.append(MemoryNode.weight <= max_weight)
    if created_from:
        filters.append(MemoryNode.created_at >= created_from)
    if created_to:
        filters.append(MemoryNode.created_at < created_to + timedelta(days=1))
    if branch_type:
        child = aliased(MemoryNode)
        filters.append(select(child.id).where(
            child.parent_id == MemoryNode.id, child.tenant_id == tenant,
            child.branch_type == branch_type, child.deleted_at.is_(None),
            access.clause(child),
        ).exists())
    if flag:
        if "contradicted" in flag:
            filters.append(select(ContradictionReport.id).where(
                ContradictionReport.memory_id == MemoryNode.id,
                ContradictionReport.tenant_id == tenant,
                ContradictionReport.resolved.is_(False),
            ).exists())
        if "has_branches" in flag:
            child = aliased(MemoryNode)
            filters.append(select(child.id).where(
                child.parent_id == MemoryNode.id, child.tenant_id == tenant,
                child.deleted_at.is_(None),
                access.clause(child),
            ).exists())
    if entity:
        filters.extend((_human_content_clause(access), select(MemoryRelationship.id).where(
            MemoryRelationship.source_id == MemoryNode.id,
            MemoryRelationship.target_id == entity,
            MemoryRelationship.tenant_id == tenant,
            MemoryRelationship.relationship_type == "mentions",
            MemoryRelationship.valid_until.is_(None),
        ).exists()))
    search_mode = "none"
    if q:
        pattern = f"%{q.strip()}%"
        # Searching by owner would count one person's memories; admins match IDs only.
        metadata_match = or_(
            cast(MemoryNode.id, String).ilike(pattern), MemoryNode.owner_id.ilike(pattern),
        ) if access.sees_individual_activity else cast(MemoryNode.id, String).ilike(pattern)
        if mode == "metadata":
            filters.append(metadata_match)
            search_mode = "metadata"
        elif access.principal.role == "admin":
            filters.append(or_(metadata_match, _human_content_clause(access) &
                               or_(MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern))))
            search_mode = "text"
        else:
            filters.append(or_(metadata_match, MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern)))
            search_mode = "text"
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one()
    sort_col = {"updated": MemoryNode.updated_at, "created": MemoryNode.created_at,
                "weight": MemoryNode.weight, "relevance": MemoryNode.updated_at}[sort]
    ordered = sort_col.asc() if order == "asc" else sort_col.desc()
    memories = (await db.execute(select(MemoryNode).where(*filters).order_by(ordered, MemoryNode.id)
                                 .offset((page - 1) * per_page).limit(per_page))).scalars().all()
    memories = [
        memory for memory in memories
        if memory.tenant_id == tenant and (
            access.can_read(memory) if access.principal.role == "admin"
            else _human_can_see_content(access, memory)
        )
    ]
    ids = [memory.id for memory in memories]
    branch_counts: dict[uuid.UUID, Counter] = {}
    report_counts: dict[uuid.UUID, int] = {}
    entities_by_memory: dict[uuid.UUID, list[dict]] = {}
    if ids:
        children = (await db.execute(select(MemoryNode.parent_id, MemoryNode.branch_type).where(
            MemoryNode.parent_id.in_(ids), MemoryNode.tenant_id == tenant,
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        ))).all()
        for parent_id, branch in children:
            branch_counts.setdefault(parent_id, Counter())[branch or "other"] += 1
        reports = (await db.execute(select(ContradictionReport.memory_id, func.count()).where(
            ContradictionReport.memory_id.in_(ids), ContradictionReport.tenant_id == tenant,
            ContradictionReport.resolved.is_(False),
        ).group_by(ContradictionReport.memory_id))).all()
        report_counts = dict(reports)
        # Entity names are content. The selected source memory is already
        # authorized, and a redacted Admin row gets no linked entity names.
        content_ids = [memory.id for memory in memories if _human_can_see_content(access, memory)]
        if content_ids:
            entity_node = aliased(MemoryNode)
            entity_rows = (await db.execute(select(
                MemoryRelationship.source_id, entity_node.id,
                entity_node.content, entity_node.branch_type,
            ).join(entity_node, entity_node.id == MemoryRelationship.target_id).where(
                MemoryRelationship.source_id.in_(content_ids),
                MemoryRelationship.tenant_id == tenant,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
                entity_node.tenant_id == tenant,
                entity_node.scope == "entity",
                entity_node.status == "active",
                entity_node.is_current.is_(True),
                entity_node.deleted_at.is_(None),
            ))).all()
            for source_id, entity_id, name, kind in entity_rows:
                entities_by_memory.setdefault(source_id, []).append({
                    "id": str(entity_id), "name": name,
                    "type": (kind or "").removeprefix("entity:"),
                })
    items = []
    for memory in memories:
        hidden = not _human_can_see_content(access, memory)
        writable = access.can_write(memory) and (
            memory.scope != "project" or memory.scope_id in (
                access.human_projects if access.principal.role == "user" else access.human_project_admins
            )
        )
        moderatable = access.can_moderate(memory) and (
            memory.scope != "project" or memory.scope_id in access.human_project_admins
        )
        branches = branch_counts.get(memory.id, Counter())
        items.append({
            "id": str(memory.id), "stub": "Content hidden" if hidden else memory.stub,
            "content_preview": "" if hidden else memory.content[:240],
            "scope": memory.scope, "scope_id": memory.scope_id,
            "owner_id": memory.owner_id, "actor_id": memory.actor_id, "driver_id": memory.driver_id,
            "domains": [] if hidden else (memory.domains or []),
            "weight": memory.weight, "version": memory.version,
            "is_current": memory.is_current, "status": memory.status,
            "content_type": memory.content_type,
            "branch_count": sum(branches.values()),
            "branch_summary": [{"type": kind, "count": count} for kind, count in branches.items()],
            "open_contradictions": report_counts.get(memory.id, 0),
            "near_duplicate": None, "created_at": memory.created_at,
            "updated_at": memory.updated_at, "deleted_at": memory.deleted_at,
            "relevant_until": memory.relevant_until, "score": None,
            "entities": [] if hidden else entities_by_memory.get(memory.id, []),
            "entity_count": 0 if hidden else len(entities_by_memory.get(memory.id, [])),
            "redacted": hidden,
            "capabilities": {"write": writable, "moderate": moderatable},
            "can_delete": access.can_delete(memory) and (
                memory.scope != "project" or memory.scope_id in access.human_projects
            ),
        })
    tabs = {}
    for name, condition in (
        ("current", (MemoryNode.deleted_at.is_(None), MemoryNode.is_current.is_(True),
                     MemoryNode.status == "active")),
        ("all", (MemoryNode.deleted_at.is_(None),)),
        ("quarantined", (MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined")),
        ("deleted", (MemoryNode.deleted_at.is_not(None),)),
    ):
        if access.principal.role == "user" and name in ("quarantined", "deleted"):
            tabs[name] = 0
        else:
            stmt = select(func.count()).select_from(MemoryNode).where(*base, *condition)
            tabs[name] = (await db.execute(stmt)).scalar_one()
    facets = {"writers": []}
    for name, column, extra in (
        ("scopes", MemoryNode.scope, ()),
        # Memories per person is individual activity: not an admin facet (#667).
        *((("writers", MemoryNode.owner_id, ()),) if access.sees_individual_activity else ()),
        ("projects", MemoryNode.scope_id, (MemoryNode.scope == "project",)),
    ):
        rows = (await db.execute(select(column, func.count()).select_from(MemoryNode).where(
            *base, MemoryNode.deleted_at.is_(None), *extra,
        ).group_by(column))).all()
        facets[name] = [{"value": value, "count": count} for value, count in rows if value is not None]
    facets["domains"] = []
    # These counts describe only authorized memories. Domain values are
    # content metadata and must exclude Admin's redacted personal rows.
    domain_rows = select(func.unnest(MemoryNode.domains).label("value")).where(
        *base, MemoryNode.deleted_at.is_(None), _human_content_clause(access),
    ).subquery()
    domains = (await db.execute(select(domain_rows.c.value, func.count()).select_from(
        domain_rows).group_by(domain_rows.c.value))).all()
    facets["domains"] = [{"value": value, "count": count} for value, count in domains if value]
    contradicted = (await db.execute(select(func.count()).select_from(MemoryNode).where(
        *base, MemoryNode.deleted_at.is_(None),
        select(ContradictionReport.id).where(
            ContradictionReport.memory_id == MemoryNode.id,
            ContradictionReport.tenant_id == tenant,
            ContradictionReport.resolved.is_(False),
        ).exists(),
    ))).scalar_one()
    branch = aliased(MemoryNode)
    has_branches = (await db.execute(select(func.count()).select_from(MemoryNode).where(
        *base, MemoryNode.deleted_at.is_(None),
        select(branch.id).where(
            branch.parent_id == MemoryNode.id, branch.tenant_id == tenant,
            branch.deleted_at.is_(None), access.clause(branch),
        ).exists(),
    ))).scalar_one()
    facets["flags"] = {"contradicted": contradicted, "has_branches": has_branches,
                       "near_duplicate": None}
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "search_mode": search_mode, "metadata_only": access.principal.role == "admin",
            "hidden_scopes": ["user", "enterprise"] if access.principal.role == "admin" else [],
            "tab_counts": tabs, "facets": facets}


def _entity_type(node: MemoryNode) -> str:
    return (node.branch_type or "").removeprefix("entity:")


def _aliases(node: MemoryNode) -> list[str]:
    value = (node.metadata_ or {}).get("aliases", [])
    return value if isinstance(value, list) else []


async def _entity_sources(db: AsyncSession, access: AccessDep, entity_id: uuid.UUID) -> list[MemoryNode]:
    rels = (await db.execute(select(MemoryRelationship).where(
        MemoryRelationship.target_id == entity_id,
        MemoryRelationship.tenant_id == access.principal.tenant_id,
        MemoryRelationship.relationship_type == "mentions",
        MemoryRelationship.valid_until.is_(None),
    ))).scalars().all()
    source_ids = {rel.source_id for rel in rels}
    if not source_ids:
        return []
    sources = (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(source_ids), _human_content_clause(access),
    ))).scalars().all()
    visible = [
        source for source in sources
        if source.tenant_id == access.principal.tenant_id
        and source.deleted_at is None and source.is_current and _human_can_see_content(access, source)
        and all(rel.tenant_id == access.principal.tenant_id for rel in rels if rel.source_id == source.id)
    ]
    return visible


async def _entity(db: AsyncSession, access: AccessDep, entity_id: uuid.UUID, *, lock: bool = False) -> MemoryNode:
    if access.principal.role != "user":
        raise HTTPException(status_code=403, detail="Entity access forbidden")
    stmt = select(MemoryNode).where(
        MemoryNode.id == entity_id,
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()
    entity = (await db.execute(stmt)).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


async def _entity_mutation_sources(db: AsyncSession, access: AccessDep, entity: MemoryNode) -> list[MemoryNode]:
    """Core merge rewires every active mention; reject if any is not writable."""
    if entity.owner_id != access.principal.username:
        raise HTTPException(status_code=404, detail="Entity not found")
    rels = (await db.execute(select(MemoryRelationship).where(
        MemoryRelationship.target_id == entity.id,
        MemoryRelationship.relationship_type == "mentions",
        MemoryRelationship.valid_until.is_(None),
    ).with_for_update())).scalars().all()
    source_ids = {rel.source_id for rel in rels}
    if any(rel.tenant_id != access.principal.tenant_id for rel in rels):
        raise HTTPException(status_code=409, detail="Entity relationship boundary invalid")
    if source_ids:
        sources = (await db.execute(select(MemoryNode).where(MemoryNode.id.in_(source_ids)))).scalars().all()
    else:
        sources = []
    if len({source.id for source in sources}) != len(source_ids):
        raise HTTPException(status_code=409, detail="Entity relationship boundary invalid")
    for source in sources:
        if not _human_can_see_content(access, source):
            raise HTTPException(status_code=404, detail="Entity not found")
        await _require_write(db, access, source)
    return sources


@router.get("/api/entities")
async def list_entities(
    db: DbDep,
    access: AccessDep,
    q: str | None = None,
    type: Literal["all", "person", "organization", "location", "object", "event"] = "all",  # noqa: A002
    project: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    if access.principal.role != "user":
        raise HTTPException(status_code=403, detail="Entity access forbidden")
    if project and not await _membership(db, access, project):
        raise HTTPException(status_code=404, detail="Project not found")
    source = aliased(MemoryNode)
    mention = MemoryRelationship
    visibility = select(
        mention.target_id.label("entity_id"),
        func.count(func.distinct(source.id)).label("memory_count"),
        func.max(source.updated_at).label("last_seen"),
    ).join(source, source.id == mention.source_id).where(
        mention.tenant_id == access.principal.tenant_id,
        mention.relationship_type == "mentions",
        mention.valid_until.is_(None),
        source.deleted_at.is_(None),
        source.is_current.is_(True),
        _human_content_clause(access, source),
    )
    if project:
        visibility = visibility.where(source.scope == "project", source.scope_id == project)
    visible = visibility.group_by(mention.target_id).subquery()
    conditions = [
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status == "active",
    ]
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(MemoryNode.content.ilike(pattern), cast(MemoryNode.metadata_, String).ilike(pattern)))
    visible_or_owned = (
        visible.c.entity_id.is_not(None) if project else
        or_(visible.c.entity_id.is_not(None), MemoryNode.owner_id == access.principal.username)
    )
    base = select(MemoryNode.id).outerjoin(visible, visible.c.entity_id == MemoryNode.id).where(
        *conditions, visible_or_owned,
    )
    counts_rows = (await db.execute(select(MemoryNode.branch_type, func.count()).outerjoin(
        visible, visible.c.entity_id == MemoryNode.id,
    ).where(*conditions, visible_or_owned).group_by(MemoryNode.branch_type))).all()
    counts = {kind: 0 for kind in ("person", "organization", "location", "object", "event")}
    for branch_type, count in counts_rows:
        kind = (branch_type or "").removeprefix("entity:")
        if kind in counts:
            counts[kind] = count
    counts["all"] = sum(counts.values())
    if type != "all":
        base = base.where(MemoryNode.branch_type == f"entity:{type}")
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(select(MemoryNode, visible.c.memory_count, visible.c.last_seen).outerjoin(
        visible, visible.c.entity_id == MemoryNode.id,
    ).where(*conditions, visible_or_owned,
            *([MemoryNode.branch_type == f"entity:{type}"] if type != "all" else []))
        .order_by(func.coalesce(visible.c.memory_count, 0).desc(), MemoryNode.content)
        .offset((page - 1) * per_page).limit(per_page))).all()
    entity_ids = [entity.id for entity, _count, _last in rows]
    projects_by_entity: dict[uuid.UUID, set[str]] = {entity_id: set() for entity_id in entity_ids}
    if entity_ids:
        linked_source = aliased(MemoryNode)
        project_rows = (await db.execute(select(mention.target_id, linked_source.scope_id).join(
            linked_source, linked_source.id == mention.source_id,
        ).where(
            mention.target_id.in_(entity_ids), mention.relationship_type == "mentions",
            mention.valid_until.is_(None), mention.tenant_id == access.principal.tenant_id,
            linked_source.scope == "project", linked_source.deleted_at.is_(None),
            linked_source.is_current.is_(True), _human_content_clause(access, linked_source),
        ))).all()
        for entity_id, project_name in project_rows:
            if project_name:
                projects_by_entity[entity_id].add(project_name)
    items = [{
        "id": str(entity.id), "name": entity.content, "entity_type": _entity_type(entity),
        "aliases": _aliases(entity), "memory_count": count or 0,
        "projects": sorted(projects_by_entity[entity.id]),
        "created_at": entity.created_at, "last_seen": last_seen,
    } for entity, count, last_seen in rows]
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "has_more": page * per_page < total, "counts": counts}


@router.get("/api/entities/{entity_id}")
async def entity_detail(entity_id: uuid.UUID, db: DbDep, access: AccessDep):
    entity = await _entity(db, access, entity_id)
    sources = await _entity_sources(db, access, entity_id)
    if not sources and entity.owner_id != access.principal.username:
        raise HTTPException(status_code=404, detail="Entity not found")
    scope_counts = Counter(source.scope for source in sources)
    writer_counts = Counter(source.owner_id for source in sources)
    project_counts = Counter(source.scope_id for source in sources if source.scope == "project" and source.scope_id)
    month_counts = Counter(source.created_at.strftime("%Y-%m") for source in sources if source.created_at)
    co_mentions = []
    if sources:
        other = aliased(MemoryNode)
        edge = aliased(MemoryRelationship)
        count = func.count(func.distinct(edge.source_id)).label("mentions_count")
        rows = (await db.execute(select(other, count).join(edge, edge.target_id == other.id).where(
            edge.source_id.in_([source.id for source in sources]),
            edge.target_id != entity.id,
            edge.relationship_type == "mentions",
            edge.tenant_id == access.principal.tenant_id,
            edge.valid_until.is_(None),
            other.tenant_id == access.principal.tenant_id,
            other.scope == "entity",
            other.deleted_at.is_(None),
            other.status == "active",
        ).group_by(other.id).order_by(count.desc()).limit(20))).all()
        co_mentions = [{"id": str(other_entity.id), "name": other_entity.content,
                        "type": _entity_type(other_entity), "count": mentions}
                       for other_entity, mentions in rows]
    memories = [{
        "id": str(source.id), "stub": source.stub, "scope": source.scope,
        "scope_id": source.scope_id, "owner_id": source.owner_id, "weight": source.weight,
        "version": source.version, "created_at": source.created_at, "updated_at": source.updated_at,
    } for source in sources]
    return {
        "id": str(entity.id), "name": entity.content, "entity_type": _entity_type(entity),
        "aliases": _aliases(entity), "created_at": entity.created_at,
        # Keep the UI response shape without revealing inaccessible sources.
        "memory_count": len(sources), "hidden_mentions": 0,
        "first_seen": min((s.created_at for s in sources), default=None),
        "last_seen": max((s.updated_at for s in sources), default=None),
        "scopes": dict(scope_counts),
        "writers": [{"value": key, "count": value} for key, value in writer_counts.items()],
        "projects": [{"value": key, "count": value} for key, value in project_counts.items()],
        "months": [{"month": key, "count": value} for key, value in sorted(month_counts.items())],
        "co_mentions": co_mentions, "memories": memories,
    }


@router.patch("/api/entities/{entity_id}")
async def update_entity(entity_id: uuid.UUID, body: EntityUpdateBody, db: DbDep,
                        access: AccessDep, embedding: EmbeddingDep):
    entity = await _entity(db, access, entity_id, lock=True)
    await _entity_mutation_sources(db, access, entity)
    if (not body.name or body.name == entity.content or
            (body.entity_type is not None and body.entity_type != _entity_type(entity)) or
            (body.aliases is not None and sorted(body.aliases) != sorted(_aliases(entity)))):
        raise HTTPException(status_code=422, detail="Only an existing entity name can be changed")
    _record_human_audit(db, access, "entity.renamed", "entity", entity.owner_id, entity.id)
    try:
        changed = await rename_entity(
            entity_id, body.name, db, embedding,
            tenant_id=access.principal.tenant_id, owner_id=access.principal.username,
        )
    except ValueError:
        raise HTTPException(status_code=409, detail="Entity rename rejected") from None
    value = changed["entity"]
    return {"id": value["id"], "name": value["content"],
            "entity_type": value["entity_type"], "aliases": value["aliases"]}


@router.post("/api/entities/{entity_id}/merge")
async def merge_entity(entity_id: uuid.UUID, body: EntityMergeBody, db: DbDep,
                       access: AccessDep, embedding: EmbeddingDep):
    if entity_id == body.into:
        raise HTTPException(status_code=422, detail="An entity cannot be merged into itself")
    if entity_id < body.into:
        source = await _entity(db, access, entity_id, lock=True)
        target = await _entity(db, access, body.into, lock=True)
    else:
        target = await _entity(db, access, body.into, lock=True)
        source = await _entity(db, access, entity_id, lock=True)
    source_memories = await _entity_mutation_sources(db, access, source)
    target_memories = await _entity_mutation_sources(db, access, target)
    source_ids = {memory.id for memory in source_memories}
    target_ids = {memory.id for memory in target_memories}
    preview = {
        "source": {"id": str(source.id), "name": source.content, "entity_type": _entity_type(source),
                   "aliases": _aliases(source)},
        "target": {"id": str(target.id), "name": target.content, "entity_type": _entity_type(target),
                   "aliases": _aliases(target)},
        "moving": len(source_ids - target_ids), "both": len(source_ids & target_ids), "staying": 0,
        "aliases_after": sorted(set(_aliases(source)) | set(_aliases(target)) | {source.content}),
        "source_removed": not body.dry_run,
        "memories": [{"id": str(m.id), "stub": m.stub, "scope": m.scope} for m in source_memories],
        "dry_run": body.dry_run,
    }
    if not body.dry_run:
        _record_human_audit(db, access, "entity.merged", "entity", source.owner_id, source.id,
                            {"target_id": str(target.id)})
        try:
            await merge_entities(
                entity_id, body.into, db, embedding,
                tenant_id=access.principal.tenant_id, owner_id=access.principal.username,
            )
        except ValueError:
            raise HTTPException(status_code=409, detail="Entity merge rejected") from None
    return preview
