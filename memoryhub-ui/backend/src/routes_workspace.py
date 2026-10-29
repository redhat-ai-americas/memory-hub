"""Memory workspace endpoints: restore, the timeline view, entity pages and
the agent usage signal.

* Restore undoes a soft delete for the whole version chain that was deleted
  together, and makes the newest version current again.
* The timeline returns memories on a time axis with the same filters as the
  table, so the browser can switch views without losing the filter.
* Entity pages show one entity's memories, months, co-mentioned entities and
  aliases; users can rename it, edit aliases and merge it into another one.
  A merge only moves mentions in memories the user can read.
* Usage tells, from the audit log, whether agents act on a memory after a
  search returns it, or keep skipping it.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.access import ContentDep, LabsDep, ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import audit, clean_stub, live_filters, now_utc, parse_uuid, viewer_from_request

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

ENTITY_TYPES = ("person", "organization", "location", "object", "event")


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


async def _deleted_batch(db: AsyncSession, tenant_id: str, node: MemoryNode) -> list[MemoryNode]:
    """Every row deleted together with ``node``: its versions and their branches."""
    when = node.deleted_at
    chain: dict[uuid.UUID, MemoryNode] = {node.id: node}
    current = node
    while current.previous_version_id and current.previous_version_id not in chain:
        prev = (
            await db.execute(
                select(MemoryNode).where(
                    MemoryNode.id == current.previous_version_id, MemoryNode.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if prev is None:
            break
        chain[prev.id] = prev
        current = prev
    changed = True
    while changed:
        changed = False
        for n in (
            await db.execute(
                select(MemoryNode).where(
                    MemoryNode.tenant_id == tenant_id,
                    MemoryNode.previous_version_id.in_(list(chain)),
                    ~MemoryNode.id.in_(list(chain)),
                )
            )
        ).scalars():
            chain[n.id] = n
            changed = True
    children = (
        (
            await db.execute(
                select(MemoryNode).where(MemoryNode.tenant_id == tenant_id, MemoryNode.parent_id.in_(list(chain)))
            )
        )
        .scalars()
        .all()
    )
    rows = list(chain.values()) + list(children)
    return [r for r in rows if r.deleted_at is not None and r.deleted_at == when]


def heads(rows: list) -> set:
    """Rows no other row in the batch supersedes — the ones to make current again."""
    superseded = {r.previous_version_id for r in rows if r.previous_version_id}
    return {r.id for r in rows if r.id not in superseded}


async def restore_memory(db: AsyncSession, settings: Settings, viewer, memory_id: str) -> dict:
    from src.routes_dashboard import _load_memory, _writable

    tenant_id = settings.ui_tenant_id
    node = await _load_memory(db, tenant_id, memory_id)
    acc = await access_for(db, settings, viewer)
    acc.ensure_readable(node)
    if node.deleted_at is None:
        raise HTTPException(status_code=409, detail="This memory is not deleted")
    if viewer.redacts_content:
        acc.ensure_moderatable(node)  # #667 moderation
    else:
        await _writable(db, settings, viewer, node)
    rows = await _deleted_batch(db, tenant_id, node)
    current = heads(rows)
    ids = [r.id for r in rows]
    await db.execute(
        update(MemoryNode).where(MemoryNode.tenant_id == tenant_id, MemoryNode.id.in_(ids)).values(deleted_at=None)
    )
    if current:
        await db.execute(
            update(MemoryNode)
            .where(MemoryNode.tenant_id == tenant_id, MemoryNode.id.in_(list(current)))
            .values(is_current=True)
        )
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="memory.restore",
        scope=node.scope,
        owner_id=node.owner_id,
        memory_id=node.id,
        metadata={"rows": len(ids)},
    )
    head = next((r for r in rows if r.id in current and r.parent_id is None), node)
    return {"id": str(head.id), "restored_rows": len(ids)}


@router.post("/api/memory/{memory_id}/restore")
async def restore_route(memory_id: str, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    result = await restore_memory(db, settings, viewer, memory_id)
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


@router.get("/api/memories/timeline")
async def timeline(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    scope: list[str] | None = Query(default=None),
    project: str | None = Query(default=None, max_length=255),
    entity: str | None = Query(default=None),
    min_weight: float = Query(default=0, ge=0, le=1),
    days: int = Query(default=90, ge=0, le=3650),
    by: str = Query(default="created", pattern="^(created|updated)$"),
    max_items: int = Query(default=600, ge=10, le=2000),
):
    """Memories on a time axis, filtered like the table; ``days=0`` means all time."""
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    col = MemoryNode.created_at if by == "created" else MemoryNode.updated_at
    filters = (
        live_filters(tenant_id)
        + [MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity", MemoryNode.status != "quarantined"]
        + acc.filters()
    )
    if scope:
        filters.append(MemoryNode.scope.in_(scope))
    if min_weight:
        filters.append(MemoryNode.weight >= min_weight)
    if project:
        filters.append(
            or_(
                and_(MemoryNode.scope == "project", MemoryNode.scope_id == project),
                MemoryNode.metadata_["project"].as_string() == project,
            )
        )
    if entity:
        eid = parse_uuid(entity, "entity ID")
        filters.append(
            select(MemoryRelationship.id)
            .where(
                MemoryRelationship.source_id == MemoryNode.id,
                MemoryRelationship.target_id == eid,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
            )
            .exists()
        )
    if days:
        filters.append(col >= now_utc() - timedelta(days=days))
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one()
    nodes = (await db.execute(select(MemoryNode).where(*filters).order_by(col.desc()).limit(max_items))).scalars().all()
    items = [
        {
            "id": str(n.id),
            "stub": clean_stub(n.stub),
            "scope": n.scope,
            "scope_id": n.scope_id,
            "owner_id": n.owner_id,
            "weight": n.weight,
            "version": n.version,
            "domains": list(n.domains or []),
            "created_at": n.created_at,
            "updated_at": n.updated_at,
            "at": n.created_at if by == "created" else n.updated_at,
        }
        for n in nodes
    ]
    first = (await db.execute(select(func.min(col)).where(*filters))).scalar()
    return acc.redact_tree(
        {
            "items": items,
            "total": total,
            "truncated": total > len(items),
            "by": by,
            "days": days,
            "first": first,
            "now": now_utc(),
            "metadata_only": viewer.redacts_content,
        }
    )


# ---------------------------------------------------------------------------
# Entity pages
# ---------------------------------------------------------------------------


async def _entity(db: AsyncSession, tenant_id: str, entity_id: str) -> MemoryNode:
    eid = parse_uuid(entity_id, "entity ID")
    node = (
        await db.execute(
            select(MemoryNode).where(
                MemoryNode.id == eid,
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.scope == "entity",
                MemoryNode.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return node


def _readable_sources(tenant_id: str, acc, entity_id: uuid.UUID):
    """(MemoryRelationship, MemoryNode) rows of readable current memories mentioning the entity."""
    return (
        select(MemoryRelationship, MemoryNode)
        .join(MemoryNode, MemoryNode.id == MemoryRelationship.source_id)
        .where(
            MemoryRelationship.tenant_id == tenant_id,
            MemoryRelationship.target_id == entity_id,
            MemoryRelationship.relationship_type == "mentions",
            MemoryRelationship.valid_until.is_(None),
            *live_filters(tenant_id),
            MemoryNode.parent_id.is_(None),
            MemoryNode.status != "quarantined",
            *acc.filters(),
        )
    )


def _entity_out(node: MemoryNode) -> dict:
    return {
        "id": str(node.id),
        "name": node.content,
        "entity_type": (node.branch_type or "entity:object").removeprefix("entity:"),
        "aliases": list((node.metadata_ or {}).get("aliases", [])),
        "created_at": node.created_at,
    }


@router.get("/api/entities/{entity_id}")
async def entity_detail(entity_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    node = await _entity(db, tenant_id, entity_id)
    rows = (await db.execute(_readable_sources(tenant_id, acc, node.id).order_by(MemoryNode.updated_at.desc()))).all()
    if not rows and acc.grants is not None:
        raise HTTPException(status_code=404, detail="Entity not found")
    memories = [r[1] for r in rows]
    ids = [m.id for m in memories]
    total_mentions = (
        await db.execute(
            select(func.count())
            .select_from(MemoryRelationship)
            .join(MemoryNode, MemoryNode.id == MemoryRelationship.source_id)
            .where(
                MemoryRelationship.target_id == node.id,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
                MemoryNode.deleted_at.is_(None),
                MemoryNode.is_current.is_(True),
            )
        )
    ).scalar_one()

    co: Counter = Counter()
    co_meta: dict[str, dict] = {}
    if ids:
        other = aliased(MemoryNode)
        for target_id, name, branch_type in (
            await db.execute(
                select(other.id, other.content, other.branch_type)
                .select_from(MemoryRelationship)
                .join(other, other.id == MemoryRelationship.target_id)
                .where(
                    MemoryRelationship.source_id.in_(ids),
                    MemoryRelationship.relationship_type == "mentions",
                    MemoryRelationship.valid_until.is_(None),
                    other.scope == "entity",
                    other.deleted_at.is_(None),
                    other.id != node.id,
                )
            )
        ).all():
            co[str(target_id)] += 1
            co_meta[str(target_id)] = {
                "id": str(target_id),
                "name": name,
                "type": (branch_type or "entity:object").removeprefix("entity:"),
            }

    months: Counter = Counter()
    for m in memories:
        if m.created_at:
            months[m.created_at.strftime("%Y-%m")] += 1
    projects = Counter((m.scope_id if m.scope == "project" else (m.metadata_ or {}).get("project")) for m in memories)
    return {
        **_entity_out(node),
        "memory_count": len(memories),
        "hidden_mentions": max(0, total_mentions - len(memories)),
        "first_seen": min((m.created_at for m in memories), default=None),
        "last_seen": max((m.updated_at for m in memories), default=None),
        "scopes": dict(Counter(m.scope for m in memories)),
        "writers": [
            {"value": k, "count": v} for k, v in Counter(m.actor_id or m.owner_id for m in memories).most_common(8)
        ],
        "projects": [{"value": k, "count": v} for k, v in projects.most_common() if k],
        "months": [{"month": k, "count": months[k]} for k in sorted(months)],
        "co_mentions": [{**co_meta[k], "count": c} for k, c in co.most_common(15)],
        "memories": [
            {
                "id": str(m.id),
                "stub": clean_stub(m.stub),
                "scope": m.scope,
                "scope_id": m.scope_id,
                "owner_id": m.owner_id,
                "weight": m.weight,
                "version": m.version,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            }
            for m in memories[:200]
        ],
    }


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    entity_type: str | None = Field(default=None, pattern="^(person|organization|location|object|event)$")
    aliases: list[str] | None = Field(default=None, max_length=50)


def clean_aliases(values: list[str], name: str) -> list[str]:
    out: list[str] = []
    seen = {name.strip().lower()}
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v[:255])
    return out


async def _ensure_entity_access(db, tenant_id, acc, node) -> None:
    if acc.grants is None:
        return
    if not (await db.execute(_readable_sources(tenant_id, acc, node.id).limit(1))).first():
        raise HTTPException(status_code=404, detail="Entity not found")


@router.patch("/api/entities/{entity_id}", dependencies=[LabsDep])
async def update_entity(entity_id: str, body: EntityUpdate, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    node = await _entity(db, tenant_id, entity_id)
    await _ensure_entity_access(db, tenant_id, acc, node)
    meta = dict(node.metadata_ or {})
    before = {"name": node.content, "type": node.branch_type, "aliases": list(meta.get("aliases", []))}
    if body.name is not None and body.name.strip() != node.content:
        meta["aliases"] = clean_aliases([node.content, *meta.get("aliases", [])], body.name)
        node.content = body.name.strip()
        node.stub = node.content
    if body.aliases is not None:
        meta["aliases"] = clean_aliases(body.aliases, node.content)
    if body.entity_type is not None:
        node.branch_type = f"entity:{body.entity_type}"
    node.metadata_ = meta
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="entity.update",
        scope="entity",
        owner_id=node.owner_id,
        memory_id=node.id,
        metadata={"before": before},
    )
    await db.commit()
    return _entity_out(node)


class MergeRequest(BaseModel):
    into: str
    dry_run: bool = True


@router.post("/api/entities/{entity_id}/merge", dependencies=[LabsDep])
async def merge_entity(entity_id: str, body: MergeRequest, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    """Move this entity's mentions onto another entity.

    With ``dry_run`` (default) nothing changes and the response previews the
    result. Only mentions in memories the viewer can read move; if others
    remain, the old entity stays for them.
    """
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    source = await _entity(db, tenant_id, entity_id)
    target = await _entity(db, tenant_id, body.into)
    if source.id == target.id:
        raise HTTPException(status_code=422, detail="Pick a different entity to merge into")
    await _ensure_entity_access(db, tenant_id, acc, source)
    await _ensure_entity_access(db, tenant_id, acc, target)

    moving = (await db.execute(_readable_sources(tenant_id, acc, source.id))).all()
    already = {
        r[0]
        for r in (
            await db.execute(
                select(MemoryRelationship.source_id).where(
                    MemoryRelationship.target_id == target.id,
                    MemoryRelationship.relationship_type == "mentions",
                    MemoryRelationship.valid_until.is_(None),
                )
            )
        ).all()
    }
    all_mentions = (
        await db.execute(
            select(func.count()).where(
                MemoryRelationship.target_id == source.id,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
            )
        )
    ).scalar_one()
    staying = max(0, all_mentions - len(moving))
    aliases = clean_aliases(
        [*(target.metadata_ or {}).get("aliases", []), source.content, *(source.metadata_ or {}).get("aliases", [])],
        target.content,
    )
    preview = {
        "source": _entity_out(source),
        "target": _entity_out(target),
        "moving": len(moving),
        "both": sum(1 for rel, _ in moving if rel.source_id in already),
        "staying": staying,
        "aliases_after": aliases,
        "source_removed": staying == 0,
        "memories": [{"id": str(m.id), "stub": clean_stub(m.stub), "scope": m.scope} for _, m in moving[:12]],
    }
    if body.dry_run:
        return {**preview, "dry_run": True}

    now = now_utc()
    for rel, _ in moving:
        if rel.source_id in already:
            rel.valid_until = now
        else:
            rel.target_id = target.id
    target_meta = dict(target.metadata_ or {})
    target_meta["aliases"] = aliases
    target.metadata_ = target_meta
    if staying == 0:
        source_meta = dict(source.metadata_ or {})
        source_meta["merged_into"] = str(target.id)
        source.metadata_ = source_meta
        source.deleted_at = now
        source.is_current = False
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="entity.merge",
        scope="entity",
        owner_id=target.owner_id,
        memory_id=target.id,
        metadata={"from": str(source.id), "from_name": source.content, "moved": len(moving), "staying": staying},
    )
    await db.commit()
    return {**preview, "dry_run": False}


# ---------------------------------------------------------------------------
# Agent usage signal
# ---------------------------------------------------------------------------

FOLLOW_UP = timedelta(minutes=30)
ACTED = {"memory.read", "memory.update", "memory.relationship_created", "memory.contradiction_reported"}


def usage_from_events(events: list[tuple], full_text_ids: set) -> dict:
    """Classify search hits: did the same agent act on the memory soon after?

    ``events`` are (memory_id, actor_id, event_type, timestamp) sorted by time.
    A hit is *used* when the agent reads, updates, links or reports the memory
    within 30 minutes; otherwise *skipped*. Memories delivered as full text
    (weight ≥ 0.8) need no follow-up read, so they are *served in full*.
    """
    per: dict = defaultdict(lambda: {"served": 0, "used": 0, "skipped": 0, "full": 0, "reads": 0, "last": None})
    pending: dict[tuple, list] = defaultdict(list)
    for mid, actor, kind, at in events:
        stats = per[mid]
        stats["last"] = at
        key = (mid, actor)
        if kind == "memory.search":
            stats["served"] += 1
            if mid in full_text_ids:
                stats["full"] += 1
            else:
                pending[key].append(at)
        elif kind in ACTED:
            if kind == "memory.read":
                stats["reads"] += 1
            hits = pending.get(key, [])
            matched = [t for t in hits if at - t <= FOLLOW_UP]
            stats["used"] += len(matched)
            stats["skipped"] += len(hits) - len(matched)
            pending[key] = []
    for (mid, _), hits in pending.items():
        per[mid]["skipped"] += len(hits)
    for stats in per.values():
        measured = stats["used"] + stats["skipped"]
        stats["use_rate"] = round(stats["used"] / measured, 2) if measured else None
    return dict(per)


async def _usage(db: AsyncSession, tenant_id: str, ids: list, days: int) -> dict:
    if not ids:
        return {}
    since = now_utc() - timedelta(days=days)
    rows = (
        await db.execute(
            select(AuditLog.memory_id, AuditLog.actor_id, AuditLog.event_type, AuditLog.timestamp)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.memory_id.in_(ids),
                AuditLog.timestamp >= since,
                AuditLog.event_type.in_(["memory.search", *ACTED]),
                or_(AuditLog.event_metadata.is_(None), AuditLog.event_metadata["via"].as_string().is_(None)),
            )
            .order_by(AuditLog.timestamp)
        )
    ).all()
    full = {
        r[0]
        for r in (await db.execute(select(MemoryNode.id).where(MemoryNode.id.in_(ids), MemoryNode.weight >= 0.8))).all()
    }
    return usage_from_events([tuple(r) for r in rows], full)


@router.get("/api/memory/{memory_id}/usage")
async def memory_usage(
    memory_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep, days: int = Query(30, ge=1, le=365)
):
    from src.routes_dashboard import _load_memory

    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    (await access_for(db, settings, viewer)).ensure_readable(node)
    stats = (await _usage(db, settings.ui_tenant_id, [node.id], days)).get(node.id)
    empty = {"served": 0, "used": 0, "skipped": 0, "full": 0, "reads": 0, "last": None, "use_rate": None}
    return {"days": days, "full_text": node.weight >= 0.8, **(stats or empty)}


@router.get("/api/usage/summary")
async def usage_summary(db: DbDep, settings: SettingsDep, viewer: ViewerDep, days: int = Query(30, ge=1, le=365)):
    """Across readable memories: how often agents act on what search returns,
    and the memories they keep skipping (candidates to rewrite or fade)."""
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    filters = live_filters(tenant_id) + [MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity"] + acc.filters()
    since = now_utc() - timedelta(days=days)
    served_ids = [
        r[0]
        for r in (
            await db.execute(
                select(AuditLog.memory_id)
                .join(MemoryNode, MemoryNode.id == AuditLog.memory_id)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.event_type == "memory.search",
                    AuditLog.timestamp >= since,
                    *filters,
                )
                .group_by(AuditLog.memory_id)
                .order_by(func.count().desc())
                .limit(500)
            )
        ).all()
    ]
    per = await _usage(db, tenant_id, served_ids, days)
    nodes = (
        {n.id: n for n in (await db.execute(select(MemoryNode).where(MemoryNode.id.in_(served_ids)))).scalars()}
        if served_ids
        else {}
    )
    totals = Counter()
    for stats in per.values():
        for k in ("served", "used", "skipped", "full"):
            totals[k] += stats[k]
    measured = totals["used"] + totals["skipped"]
    skipped = sorted(
        (
            {
                "id": str(mid),
                "stub": clean_stub(nodes[mid].stub),
                "scope": nodes[mid].scope,
                "weight": nodes[mid].weight,
                **{k: s[k] for k in ("served", "used", "skipped", "use_rate")},
            }
            for mid, s in per.items()
            if mid in nodes and s["skipped"] >= 2 and (s["use_rate"] or 0) <= 0.25
        ),
        key=lambda x: -x["skipped"],
    )[:8]
    return acc.redact_tree(
        {
            "days": days,
            "served": totals["served"],
            "used": totals["used"],
            "skipped": totals["skipped"],
            "full": totals["full"],
            "use_rate": round(totals["used"] / measured, 2) if measured else None,
            "memories_served": len(per),
            "skipped_most": skipped,
        }
    )
