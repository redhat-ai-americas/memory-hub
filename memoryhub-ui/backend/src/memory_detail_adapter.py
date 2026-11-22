"""Memory detail page: who accessed a memory, how agents use it, and undoing a delete.

Every value here is computed from data Core already keeps: the version chain
in memory_nodes and the append-only audit_log. MCP search records one
"memory.served" event per search with the IDs it returned (and which of them
in full); reads, updates and links are recorded per memory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, AccessDep
from src.database import get_db
from src.human_adapters import _human_can_see_content, _membership, _record_human_audit

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]

# MCP search returns full text at or above this weight (Core default).
FULL_TEXT_WEIGHT = 0.8
# An agent "acted on" a served memory when it read, changed, linked or
# reported it within this window after the search.
ACTED_WINDOW = timedelta(minutes=30)
ACTED_EVENTS = ("memory.read", "memory.update", "memory.relationship_created",
                "memory.contradiction_reported")
# What the access log shows about an event. Search text and rule details stay out:
# a reader of the log learns who touched the memory and why, not what they asked.
SHOWN_METADATA = ("purpose", "reason", "origin", "bulk", "restored_rows", "from_scope",
                  "target_scope_id", "weight", "relationship_type", "full")
MAX_CHAIN = 10_000


# --- who may see what ----------------------------------------------------

def can_restore(access: Access, node: MemoryNode) -> bool:
    """Whoever may delete a memory may bring it back."""
    return node.deleted_at is not None and node.tenant_id == access.principal.tenant_id \
        and access.can_delete(node)


def content_visible(access: Access, node: MemoryNode) -> bool:
    """Content rule of the BFF, applied to a deleted row as if it were live.

    A deleted memory shows its text only to someone who may restore it and
    would read it if it were live; everyone else sees metadata.
    """
    if node.deleted_at is None:
        return _human_can_see_content(access, node)
    live = SimpleNamespace(tenant_id=node.tenant_id, deleted_at=None, status=node.status,
                           scope=node.scope, scope_id=node.scope_id, owner_id=node.owner_id)
    return can_restore(access, node) and _human_can_see_content(access, live)


def can_open(access: Access, node: MemoryNode) -> bool:
    """The memory page: live memories this person reads, deletes they may undo."""
    if node.tenant_id != access.principal.tenant_id:
        return False
    if node.deleted_at is not None:
        return can_restore(access, node)
    return access.can_read(node)


def can_view_access(access: Access, node: MemoryNode) -> bool:
    """Who read a memory is the business of its author, its project's admins and admins.

    Readers are people and agents; listing them for a shared memory to every
    member would expose colleagues' activity, so members see counts only.
    """
    if not can_open(access, node):
        return False
    if access.principal.role == "admin":
        return True
    authored = node.owner_id in access.identities or node.actor_id in access.identities
    return authored or (node.scope == "project" and node.scope_id in access.human_project_admins)


# --- the version chain ---------------------------------------------------

async def chain_ids(db: AsyncSession, tenant: str, seed: MemoryNode) -> list[uuid.UUID]:
    """Every version of the memory: Core gives all versions of one memory the same logical_id."""
    if seed.logical_id is None:
        return [seed.id]
    return list((await db.execute(select(MemoryNode.id).where(
        MemoryNode.tenant_id == tenant, MemoryNode.logical_id == seed.logical_id,
    ).limit(MAX_CHAIN))).scalars().all())


async def _seed(db: AsyncSession, access: Access, memory_id: uuid.UUID, *, lock: bool = False) -> MemoryNode:
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id,
                                    MemoryNode.tenant_id == access.principal.tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    node = (await db.execute(stmt)).scalar_one_or_none()
    if node is None or not can_open(access, node):
        raise HTTPException(status_code=404, detail="Memory not found")
    return node


def _served_any(ids: list[uuid.UUID]):
    """audit_log rows of searches that returned any of these memories."""
    return or_(*[AuditLog.event_metadata["result_ids"].cast(JSONB).contains([str(i)]) for i in ids])


def access_events(ids: list[uuid.UUID], reads_only: bool = False):
    """audit_log rows that touched any of these memories, or searches that returned one.

    ``reads_only`` keeps reads and searches ("who read it"). The memory page's
    ``access_count`` and the access log use this same filter, so the count matches the log.
    """
    by_id = and_(AuditLog.memory_id.in_(ids), AuditLog.event_type == "memory.read") if reads_only \
        else AuditLog.memory_id.in_(ids)
    return or_(by_id, and_(AuditLog.event_type == "memory.served", _served_any(ids)))


# --- routes ----------------------------------------------------------------

@router.get("/api/memory/{memory_id}/access-log")
async def memory_access_log(
    memory_id: uuid.UUID, db: DbDep, access: AccessDep,
    page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100),
    days: int | None = Query(None, ge=1, le=3650),
    reads_only: bool = False,
):
    """Every audited access to any version of the memory, newest first.

    ``reads_only`` keeps reads and searches that returned it ("who read it").
    """
    tenant = access.principal.tenant_id
    seed = await _seed(db, access, memory_id)
    if not can_view_access(access, seed):
        raise HTTPException(status_code=403, detail="Access log forbidden")
    ids = await chain_ids(db, tenant, seed)
    where = [AuditLog.tenant_id == tenant, access_events(ids, reads_only)]
    if days:
        where.append(AuditLog.timestamp >= datetime.now(UTC) - timedelta(days=days))
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(*where))).scalar_one()
    rows = (await db.execute(select(AuditLog).where(*where).order_by(
        AuditLog.timestamp.desc(), AuditLog.id.desc(),
    ).offset((page - 1) * per_page).limit(per_page))).scalars().all()
    versions = dict((await db.execute(select(MemoryNode.id, MemoryNode.version).where(
        MemoryNode.id.in_(ids)))).all())
    items = []
    for event in rows:
        metadata = event.event_metadata or {}
        served = event.event_type == "memory.served"
        target = event.memory_id
        if served:
            hit = next((i for i in ids if str(i) in (metadata.get("result_ids") or [])), None)
            target = hit
            shown = {"full": str(hit) in (metadata.get("full_ids") or [])} if hit else {}
        else:
            shown = {key: metadata[key] for key in SHOWN_METADATA if key in metadata}
        items.append({
            "id": event.id, "timestamp": event.timestamp,
            "event_type": event.event_type,
            # A served event is how an agent's search received the memory.
            "operation": "memory.search" if served else event.event_type,
            "actor_id": event.actor_id, "driver_id": event.driver_id, "actor_type": None,
            "scope": event.scope, "owner_id": event.owner_id,
            "memory_id": str(target) if target else None, "memory_stub": None,
            "memory_version": versions.get(target), "decision": event.decision,
            "metadata": shown,
        })
    return {"total": total, "page": page, "per_page": per_page, "items": items}


@router.get("/api/memory/{memory_id}/usage")
async def memory_usage(
    memory_id: uuid.UUID, db: DbDep, access: AccessDep,
    days: int = Query(30, ge=1, le=365),
):
    """How often agent searches returned the memory, and whether the agent then acted on it.

    Counts only: anyone who may open the memory sees them. A served memory is
    "used" when the same agent read, updated, linked or reported it within
    30 minutes. Full-text results need no follow-up read, so they are not
    counted as skipped.
    """
    tenant = access.principal.tenant_id
    seed = await _seed(db, access, memory_id)
    ids = await chain_ids(db, tenant, seed)
    since = datetime.now(UTC) - timedelta(days=days)
    served = (await db.execute(select(AuditLog).where(
        AuditLog.tenant_id == tenant, AuditLog.event_type == "memory.served",
        AuditLog.timestamp >= since, _served_any(ids),
    ))).scalars().all()
    actions = (await db.execute(select(AuditLog.actor_id, AuditLog.timestamp).where(
        AuditLog.tenant_id == tenant, AuditLog.memory_id.in_(ids),
        AuditLog.event_type.in_(ACTED_EVENTS), AuditLog.decision == "allowed",
        AuditLog.timestamp >= since,
    ))).all()
    reads = sum(1 for _ in actions)
    names = {str(i) for i in ids}
    used = skipped = full = 0
    for event in served:
        in_full = bool(names & set((event.event_metadata or {}).get("full_ids") or []))
        acted = any(actor == event.actor_id and event.timestamp <= at <= event.timestamp + ACTED_WINDOW
                    for actor, at in actions)
        if in_full:
            full += 1
        if acted:
            used += 1
        elif not in_full:
            skipped += 1
    measured = used + skipped
    last = max((event.timestamp for event in served), default=None)
    return {"days": days, "served": len(served), "used": used, "skipped": skipped, "full": full,
            "reads": reads, "last": last, "full_text": seed.weight >= FULL_TEXT_WEIGHT,
            "use_rate": round(used / measured, 4) if measured else None}


@router.post("/api/memory/{memory_id}/restore")
async def restore_memory(memory_id: uuid.UUID, db: DbDep, access: AccessDep):
    """Undo a soft delete: the rows deleted together come back as they were.

    Only rows whose deleted_at equals this memory's come back, so a branch
    removed earlier on its own stays deleted. A row is current again when no
    newer version exists and its parent (if any) is current. Audited.
    """
    tenant = access.principal.tenant_id
    node = await _seed(db, access, memory_id, lock=True)
    if node.deleted_at is None:
        raise HTTPException(status_code=409, detail="Memory is not deleted")
    if not can_restore(access, node):
        raise HTTPException(status_code=404, detail="Memory not found")
    authored = node.owner_id in access.identities or node.actor_id in access.identities
    # Recheck the live membership: an author needs to be a member, anyone else a project admin.
    if node.scope == "project" and not await _membership(db, access, node.scope_id, admin=not authored):
        raise HTTPException(status_code=404, detail="Memory not found")
    ids = await chain_ids(db, tenant, node)
    together: dict[uuid.UUID, MemoryNode] = {}
    frontier = set(ids)
    while frontier:  # the chain and every branch under it, deleted at the same moment
        rows = (await db.execute(select(MemoryNode).where(
            MemoryNode.tenant_id == tenant,
            or_(MemoryNode.id.in_(frontier), MemoryNode.parent_id.in_(frontier)),
            MemoryNode.deleted_at == node.deleted_at,
        ).with_for_update())).scalars().all()
        fresh = {row.id: row for row in rows if row.id not in together}
        together.update(fresh)
        frontier = set(fresh) - set(ids)
        ids = list(set(ids) | set(fresh))
    for member in together.values():
        if not can_restore(access, member):
            raise HTTPException(status_code=403, detail="Memory restore forbidden")
    successors = set((await db.execute(select(MemoryNode.previous_version_id).where(
        MemoryNode.tenant_id == tenant, MemoryNode.previous_version_id.in_(together),
    ))).scalars().all())
    outside = {m.parent_id for m in together.values() if m.parent_id and m.parent_id not in together}
    live_parents = {row.id: row for row in (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(outside), MemoryNode.tenant_id == tenant,
    ))).scalars().all()} if outside else {}
    current: dict[uuid.UUID, bool] = {}

    def is_current(member: MemoryNode) -> bool:
        if member.id not in current:
            parent_ok = True
            if member.parent_id is not None:
                parent = together.get(member.parent_id)
                if parent is not None:
                    parent_ok = is_current(parent)
                else:
                    live = live_parents.get(member.parent_id)
                    parent_ok = bool(live and live.deleted_at is None and live.is_current)
            current[member.id] = member.id not in successors and parent_ok
        return current[member.id]

    head = max((m for m in together.values() if m.parent_id == node.parent_id and m.id not in successors),
               key=lambda m: m.version, default=node)
    _record_human_audit(db, access, "memory.restore", node.scope, node.owner_id, node.id,
                        {"restored_rows": len(together)})
    try:
        for member in together.values():
            member.is_current = is_current(member)
            member.deleted_at = None
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"id": str(head.id), "restored_rows": len(together)}
