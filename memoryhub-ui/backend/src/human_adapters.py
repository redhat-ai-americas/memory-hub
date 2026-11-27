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
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate, RelationshipCreate, RelationshipType
from memoryhub_core.queries import browse as browse_queries
from memoryhub_core.queries import entities as entity_queries
from memoryhub_core.queries import identities as identity_queries
from memoryhub_core.queries import memories as memory_queries
from memoryhub_core.queries import mutations as mutation_queries
from memoryhub_core.queries import projects as project_queries
from memoryhub_core.queries.filters import MemoryFilters
from memoryhub_core.services.admin import quarantine_memory, record_moderation_audit, restore_memory
from memoryhub_core.services.audit import stage_event
from memoryhub_core.services.embeddings import HttpEmbeddingService
from memoryhub_core.services.entity import merge_entities, rename_entity
from memoryhub_core.services.exceptions import (
    CrossTenantRelationshipError,
    CurationBlockedError,
    LastAdminError,
    MembershipNotFoundError,
    MemoryAccessDeniedError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.memory import (
    create_memory as core_create_memory,
)
from memoryhub_core.services.memory import (
    report_contradiction as core_report_contradiction,
)
from memoryhub_core.services.memory import stage_memory_delete
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
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import AccessDep
from src.config import Settings, get_settings
from src.database import get_db
from src.deletion import delete_capabilities, prepare_human_delete

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
    stage_event(
        db, actor_id=access.principal.username, tenant_id=access.principal.tenant_id,
        event_type=event_type, scope=scope, owner_id=owner_id, memory_id=memory_id, metadata=metadata,
    )


async def _project(db: AsyncSession, access: AccessDep, name: str, *, lock: bool = False) -> Project:
    project = await project_queries.project_by_name(db, name, access.principal.tenant_id, lock=lock)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _membership(db: AsyncSession, access: AccessDep, name: str, *, admin: bool = False) -> bool:
    """Recheck a live human membership inside the mutation transaction."""
    return await project_queries.human_membership(db, access, name, admin=admin)


async def _known_member(db: AsyncSession, settings: Settings, tenant: str, user_id: str) -> bool:
    humans = {name.strip() for raw in (settings.ui_allowed_users, settings.ui_admin_users)
              for name in raw.split(",") if name.strip()}
    if user_id in humans:
        return True
    return await identity_queries.owner_binding_exists(db, user_id, tenant)


async def _project_row(db: AsyncSession, access: AccessDep, project: Project, *, summary=None) -> dict:
    if summary is None:
        summary = await project_queries.project_summary(db, access, project)
    member_count, memory_info, campaigns, my_role = summary
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
    projects = await project_queries.visible_projects(db, access, mine=mine)
    summaries = await project_queries.project_summaries(db, access, projects)
    items = [await _project_row(db, access, p, summary=summaries[p.name]) for p in projects]
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
    # Focus declarations contain project content. The tenant-wide Admin roster
    # grant does not authorize reading them, and agent memberships do not count.
    can_read_project_content = is_member and (
        access.principal.role == "user" or "project" in access.moderation_scopes
    )
    row = await _project_row(db, access, project)
    focus = None
    focus_available = False
    if can_read_project_content and settings.valkey_url:
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
    node = await memory_queries.get_memory_row(db, memory_id, access.principal.tenant_id, lock=lock)
    if node is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return node


async def _require_write(db: AsyncSession, access: AccessDep, node: MemoryNode) -> None:
    if not await project_queries.writable_by_human(db, access, node):
        raise HTTPException(status_code=404, detail="Memory not found")


async def _mutation_neighbors(db: AsyncSession, access: AccessDep, node: MemoryNode) -> None:
    """Preflight the branch/relationship set that Core versioning mutates."""
    try:
        await mutation_queries.authorize_version_neighbors(db, access, node)
    except mutation_queries.RelationshipBoundaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except MemoryAccessDeniedError:
        raise HTTPException(status_code=404, detail="Memory not found") from None


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
    except CurationBlockedError:
        raise HTTPException(status_code=409, detail="Curation blocked write") from None
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
    """Authorize through Core preflight, then commit one audited transaction."""
    plan = await prepare_human_delete(db, access, ids)
    for node in plan.roots:
        _record_human_audit(db, access, "memory.delete", node.scope, node.owner_id, node.id,
                            {"deleted_rows": len(plan.nodes), "bulk": True})
    try:
        await stage_memory_delete(plan, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"done": [str(node.id) for node in plan.roots], "errors": []}


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
    existing = await mutation_queries.existing_relationship_sources(
        db, ids, target_id, relationship_type, access.principal.tenant_id,
    )
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
    """Compatibility helper for the single shared Core content policy."""
    return access.live_content_clause(model)


def _human_can_see_content(access: AccessDep, memory: MemoryNode) -> bool:
    return access.can_see_content(memory)


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
    query = MemoryFilters(tab=tab, q=q, mode=mode, scope=scope, actor=actor,
        project=project, domain=domain, min_weight=min_weight, max_weight=max_weight,
        created_from=created_from, created_to=created_to, branch_type=branch_type, flag=flag, entity=entity)
    total, memories, branch_counts, report_counts, entities_by_memory, search_mode = await browse_queries.browse_page(
        db, access, query, sort=sort, order=order, page=page, per_page=per_page,
    )
    deletable = await delete_capabilities(db, access, memories)
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
            "owner_id": access.visible_identity(memory.owner_id),
            "actor_id": access.visible_identity(memory.actor_id),
            "driver_id": access.visible_identity(memory.driver_id),
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
            "can_delete": deletable[memory.id],
        })
    tabs, facets = await browse_queries.browse_facets(db, access)
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
    return await entity_queries.readable_sources(db, access, entity_id)


async def _entity(db: AsyncSession, access: AccessDep, entity_id: uuid.UUID, *, lock: bool = False) -> MemoryNode:
    if access.principal.role != "user":
        raise HTTPException(status_code=403, detail="Entity access forbidden")
    entity = await entity_queries.entity_row(db, entity_id, access.principal.tenant_id, lock=lock)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


async def _entity_mutation_sources(db: AsyncSession, access: AccessDep, entity: MemoryNode) -> list[MemoryNode]:
    try:
        return await entity_queries.mutation_sources(db, access, entity, lock=True)
    except entity_queries.EntityBoundaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except MemoryAccessDeniedError:
        raise HTTPException(status_code=404, detail="Entity not found") from None


async def _entity_editable(db: AsyncSession, access: AccessDep, entity: MemoryNode) -> bool:
    try:
        await entity_queries.mutation_sources(db, access, entity)
        return True
    except (entity_queries.EntityBoundaryError, MemoryAccessDeniedError):
        return False


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
    rows, total, counts, projects_by_entity = await entity_queries.entity_page(
        db, access, q=q, entity_type=type, project=project, page=page, per_page=per_page,
    )
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
        rows = await entity_queries.co_mentions(db, access, entity, sources)
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
        "can_edit": await _entity_editable(db, access, entity),
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
