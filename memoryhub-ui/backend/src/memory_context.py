"""Human memory context projection over existing Core read operations."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.curation.similarity import get_similar_memories
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import get_memory_history
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, AccessDep
from src.database import get_db
from src.human_adapters import _human_can_see_content

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]

# Core search_memories uses this default when deciding full text versus stub.
DEFAULT_FULL_WEIGHT = 0.8
CONTRADICTION_THRESHOLD = 5  # Existing MCP manage_curation threshold.


def _readable(access: Access, node: MemoryNode) -> bool:
    return (
        node.tenant_id == access.principal.tenant_id
        and node.deleted_at is None
        and access.can_read(node)
    )


def _brief(node: MemoryNode, access: Access) -> dict:
    hidden = not _human_can_see_content(access, node)
    return {
        "id": str(node.id), "stub": "Content hidden" if hidden else node.stub,
        "scope": node.scope, "scope_id": node.scope_id, "owner_id": node.owner_id,
        "weight": node.weight, "version": node.version,
        "is_current": node.is_current, "status": node.status,
        "created_at": node.created_at, "updated_at": node.updated_at,
        "redacted": hidden,
    }


@router.get("/api/memory/{memory_id}/context")
async def memory_context(memory_id: uuid.UUID, db: DbDep, access: AccessDep):
    tenant = access.principal.tenant_id
    seed = (await db.execute(select(MemoryNode).where(
        MemoryNode.id == memory_id, MemoryNode.tenant_id == tenant,
        MemoryNode.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if seed is None or not _readable(access, seed):
        raise HTTPException(status_code=404, detail="Memory not found")

    hidden = not _human_can_see_content(access, seed)
    try:
        history = await get_memory_history(memory_id, db, tenant_id=tenant, max_versions=10_000)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
    version_ids = [version.id for version in history["versions"]]
    version_rows = (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(version_ids), MemoryNode.tenant_id == tenant,
        MemoryNode.deleted_at.is_(None),
    ))).scalars().all() if version_ids else []
    version_map = {row.id: row for row in version_rows if _readable(access, row)}
    versions = [{
        "id": str(row.id), "version": row.version, "is_current": row.is_current,
        "content": "" if not _human_can_see_content(access, row) else row.content,
        "weight": row.weight, "actor_id": row.actor_id,
        "driver_id": row.driver_id, "owner_id": row.owner_id,
        "created_at": row.created_at, "deleted_at": row.deleted_at,
    } for version in history["versions"] if (row := version_map.get(version.id)) is not None]

    children = (await db.execute(select(MemoryNode).where(
        MemoryNode.parent_id == seed.id, MemoryNode.tenant_id == tenant,
        MemoryNode.deleted_at.is_(None),
    ))).scalars().all()
    branches = [{
        "id": str(child.id), "branch_type": child.branch_type,
        "content": child.content if _human_can_see_content(access, child) else "",
        "actor_id": child.actor_id, "created_at": child.created_at,
    } for child in children if _readable(access, child)]

    rels = (await db.execute(select(MemoryRelationship).where(
        MemoryRelationship.tenant_id == tenant,
        MemoryRelationship.valid_until.is_(None),
        or_(MemoryRelationship.source_id == seed.id, MemoryRelationship.target_id == seed.id),
    ))).scalars().all()
    neighbor_ids = {rel.target_id if rel.source_id == seed.id else rel.source_id for rel in rels}
    neighbor_rows = (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(neighbor_ids), MemoryNode.tenant_id == tenant,
        MemoryNode.deleted_at.is_(None),
    ))).scalars().all() if neighbor_ids else []
    neighbors = {node.id: node for node in neighbor_rows if _readable(access, node)}
    relationships = []
    for rel in rels:
        other_id = rel.target_id if rel.source_id == seed.id else rel.source_id
        other = neighbors.get(other_id)
        if other is None:
            continue
        relationships.append({
            "id": str(rel.id), "type": rel.relationship_type,
            "direction": "out" if rel.source_id == seed.id else "in",
            "created_by": rel.created_by, "created_at": rel.created_at,
            "other": _brief(other, access),
        })

    if hidden:
        contradictions = []
    else:
        report_rows = (await db.execute(select(ContradictionReport).where(
            ContradictionReport.memory_id == seed.id, ContradictionReport.tenant_id == tenant,
        ).order_by(ContradictionReport.created_at.desc()))).scalars().all()
        contradictions = [{
            "id": str(report.id), "observed_behavior": report.observed_behavior,
            "confidence": report.confidence, "reporter": report.reporter,
            "created_at": report.created_at, "resolved": report.resolved,
        } for report in report_rows]

    similar = []
    if not hidden and seed.embedding is not None:
        try:
            matches = await get_similar_memories(seed.id, db, tenant_id=tenant, max_results=10)
        except (MemoryNotFoundError, SQLAlchemyError):
            matches = {"results": []}
        match_ids = [uuid.UUID(str(item["id"])) for item in matches["results"]]
        match_rows = (await db.execute(select(MemoryNode).where(
            MemoryNode.id.in_(match_ids), MemoryNode.tenant_id == tenant,
            MemoryNode.deleted_at.is_(None),
        ))).scalars().all() if match_ids else []
        match_map = {row.id: row for row in match_rows if _readable(access, row)}
        similar = [{**_brief(match_map[uid], access), "score": item["score"]}
                   for item in matches["results"] if (uid := uuid.UUID(str(item["id"]))) in match_map]

    access_count = (await db.execute(select(func.count()).select_from(AuditLog).where(
        AuditLog.tenant_id == tenant, AuditLog.memory_id == seed.id,
        AuditLog.event_type == "memory.read", AuditLog.decision == "allowed",
    ))).scalar_one()
    visible_parent = None
    if seed.parent_id:
        parent = (await db.execute(select(MemoryNode).where(
            MemoryNode.id == seed.parent_id, MemoryNode.tenant_id == tenant,
            MemoryNode.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if parent is not None and _readable(access, parent):
            visible_parent = str(parent.id)

    memory = {
        **_brief(seed, access),
        "capabilities": {
            "write": access.can_write(seed), "moderate": access.can_moderate(seed),
        },
        "can_delete": access.can_delete(seed),
        "content": "" if hidden else seed.content,
        "logical_id": str(seed.logical_id) if seed.logical_id else None,
        "parent_id": visible_parent, "branch_type": seed.branch_type,
        "actor_id": seed.actor_id, "driver_id": seed.driver_id,
        "tenant_id": tenant, "domains": [] if hidden else (seed.domains or []),
        "content_type": seed.content_type, "source": seed.source,
        "metadata": None if hidden else seed.metadata_,
        "upstream_trust_level": seed.upstream_trust_level,
        "relevant_until": seed.relevant_until,
        "deleted_at": seed.deleted_at, "expires_at": seed.expires_at,
        "embedding_dims": None if hidden or seed.embedding is None else len(seed.embedding),
        "injection": "full" if seed.weight >= DEFAULT_FULL_WEIGHT else "stub",
        "full_content_threshold": DEFAULT_FULL_WEIGHT,
    }
    return {
        "memory": memory, "versions": versions, "branches": branches,
        "relationships": relationships, "relationships_omitted": 0,
        "contradictions": contradictions,
        "contradiction_threshold": CONTRADICTION_THRESHOLD,
        "similar": similar, "access_count": access_count,
    }
