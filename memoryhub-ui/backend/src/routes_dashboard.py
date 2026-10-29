"""Dashboard endpoints for the redesigned UI: overview, memory browser,
memory detail, graph neighbourhood and the search playground.

All reads are tenant-scoped by ``settings.ui_tenant_id``. Writes go through
``memoryhub_core`` services (same curation, versioning and audit semantics as
the MCP tools) and every dashboard action is appended to ``audit_log``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.campaign import CampaignMembership
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Float, String, and_, case, cast, exists, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.access import ContentDep, ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import (
    SCOPES,
    SEARCH_EVENTS,
    WRITE_EVENTS,
    audit,
    clean_stub,
    embed,
    live_filters,
    load_tenant_settings,
    now_utc,
    parse_uuid,
    preview,
    probe_components,
    viewer_from_request,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TOOL_NAMES = {
    "project.create": "manage_project",
    "project.update": "manage_project",
    "project.member_added": "manage_project",
    "project.member_removed": "manage_project",
    "campaign.create": "manage_campaign",
    "campaign.update": "manage_campaign",
    "campaign.enroll": "manage_campaign",
    "role.assign": "assign_role",
    "settings.update": "update_settings",
    "curation.batch_scan": "curation_scan",
    "curation.scan_match": "curation_scan",
    "review.approve": "approve",
    "review.reject": "reject",
    "review.request_changes": "request_changes",
    "review.restore": "restore",
    "review.promotion_proposed": "promote",
    "memory.write": "write_memory",
    "memory.update": "update_memory",
    "memory.read": "read_memory",
    "memory.search": "search_memory",
    "memory.delete": "delete_memory",
    "memory.contradiction_reported": "report_contradiction",
    "memory.relationship_created": "create_relationship",
    "session.registered": "register_session",
    "session.denied": "register_session",
    "admin.quarantine": "quarantine",
    "admin.restore": "restore",
    "admin.hard_delete": "hard_delete",
}


def tool_name(event_type: str) -> str:
    if event_type in TOOL_NAMES:
        return TOOL_NAMES[event_type]
    return event_type.split(".", 1)[-1]


async def _auth_clients(settings: Settings) -> list[dict] | None:
    """Clients from the auth service, or None when it is unreachable."""
    from src.routes import _admin_request

    try:
        resp = await _admin_request(settings, "GET", "/admin/clients", tenant_id=settings.ui_tenant_id)
        data = resp.json()
        return data if isinstance(data, list) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------


@router.get("/api/me")
async def me(request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    access = None
    if viewer.redacts_content:
        try:
            acc = await access_for(db, settings, viewer)
            access = {"hidden_scopes": list(acc.hidden_scopes), "break_glass": acc.break_glass}
        except Exception:  # pragma: no cover - needs a database
            await db.rollback()
    return {
        # #667 tier: user, admin (no user-scope content) or superuser (incident grants).
        "access": access,
        "username": viewer.username,
        "name": viewer.name,
        "email": viewer.email,
        "initials": viewer.initials,
        "source": viewer.source,
        "role": viewer.role,
        "real_username": viewer.real_username,
        "real_role": viewer.real_role,
        "test_mode": settings.ui_test_mode,
        "labs": settings.ui_labs,
        "tenant_id": settings.ui_tenant_id,
    }


# ---------------------------------------------------------------------------
# Overview (screen 01)
# ---------------------------------------------------------------------------


def _event_row(event: AuditLog, memory: MemoryNode | None, identity_types: dict[str, str]) -> dict:
    meta = event.event_metadata or {}
    return {
        "id": event.id,
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "operation": tool_name(event.event_type),
        "actor_id": event.actor_id,
        "driver_id": event.driver_id,
        "actor_type": identity_types.get(event.actor_id),
        "scope": event.scope,
        "owner_id": event.owner_id,
        "memory_id": str(event.memory_id) if event.memory_id else None,
        "memory_stub": clean_stub(memory.stub) if memory else None,
        "memory_version": memory.version if memory else None,
        "decision": event.decision,
        "metadata": meta,
    }


async def _recent_events(
    db: AsyncSession, tenant_id: str, limit: int, identities: set[str] | None = None
) -> list[tuple[AuditLog, MemoryNode | None]]:
    where = [AuditLog.tenant_id == tenant_id]
    if identities is not None:
        where.append(or_(AuditLog.actor_id.in_(identities), AuditLog.driver_id.in_(identities)))
    stmt = (
        select(AuditLog, MemoryNode)
        .outerjoin(MemoryNode, and_(MemoryNode.id == AuditLog.memory_id, MemoryNode.tenant_id == tenant_id))
        .where(*where)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    return [(row[0], row[1]) for row in (await db.execute(stmt)).all()]


async def _account_start(
    db: AsyncSession,
    tenant_id: str,
    viewer,
    visible_memory_filters: list,
    activity_scope: list,
) -> datetime:
    """Find the start of the viewer's history without crossing account boundaries.

    Local accounts have an explicit creation timestamp. OpenShift identities do
    not, so the first event or visible memory for that identity is the safe
    fallback. Platform admins and the open operator retain the tenant-wide
    history because they are not row-restricted.
    """
    candidates: list[datetime] = []
    if viewer.restricted:
        if viewer.source == "account":
            try:
                row = (
                    await db.execute(
                        text(
                            "SELECT created_at FROM memoryhub_ui_accounts "
                            "WHERE tenant_id = :tenant_id AND username = :username"
                        ),
                        {"tenant_id": tenant_id, "username": viewer.username},
                    )
                ).first()
                if row and row[0] is not None:
                    candidates.append(row[0])
            except Exception:
                # The local-account table is optional on OpenShift deployments.
                await db.rollback()
        first_event = (await db.execute(select(func.min(AuditLog.timestamp)).where(*activity_scope))).scalar_one()
        first_memory = (
            await db.execute(select(func.min(MemoryNode.created_at)).where(*visible_memory_filters))
        ).scalar_one()
        candidates.extend(value for value in (first_event, first_memory) if value is not None)
    else:
        first_event = (
            await db.execute(select(func.min(AuditLog.timestamp)).where(AuditLog.tenant_id == tenant_id))
        ).scalar_one()
        first_memory = (
            await db.execute(select(func.min(MemoryNode.created_at)).where(MemoryNode.tenant_id == tenant_id))
        ).scalar_one()
        candidates.extend(value for value in (first_event, first_memory) if value is not None)
    return min(candidates, default=now_utc())


# Overview activity windows: range -> (window seconds, bucket seconds).
ACTIVITY_RANGES: dict[str, tuple[int, int]] = {
    "all": (0, 0),
    "1h": (3600, 300),
    "12h": (12 * 3600, 1800),
    "1d": (86400, 3600),
    # Seven days is intentionally daily: the overview's x-axis is a date
    # series for this range, while the tooltip can still show finer-grained
    # timestamps when the backend has them.
    "7d": (7 * 86400, 86400),
    "30d": (30 * 86400, 86400),
}
# Candidate bucket sizes for "all time", smallest first; the first one that
# keeps the chart at <= 90 points wins.
ALL_TIME_BUCKETS = (3600, 6 * 3600, 86400, 7 * 86400, 30 * 86400)


@router.get("/api/overview")
async def overview(
    db: DbDep, settings: SettingsDep, viewer: ViewerDep, activity_range: str = Query("7d", alias="range")
):
    if activity_range not in ACTIVITY_RANGES:
        raise HTTPException(status_code=422, detail=f"range must be one of: {', '.join(ACTIVITY_RANGES)}")
    tenant_id = settings.ui_tenant_id
    now = now_utc()
    tenant_settings = await load_tenant_settings(db, tenant_id)
    threshold = int(tenant_settings["governance"]["contradiction_threshold"])
    # Users get "my overview": only memories and activity they may see.
    acc = await access_for(db, settings, viewer)
    mine = list(acc.grants.identities) if acc.grants is not None else None
    audit_scope = [or_(AuditLog.actor_id.in_(mine), AuditLog.driver_id.in_(mine))] if mine is not None else []
    base = live_filters(tenant_id) + [MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity"] + acc.filters()

    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*base))).scalar_one()
    new_7d = (
        await db.execute(
            select(func.count()).select_from(MemoryNode).where(*base, MemoryNode.created_at >= now - timedelta(days=7))
        )
    ).scalar_one()
    week_ago_total = total - new_7d
    growth_pct = round(new_7d / week_ago_total * 100, 1) if week_ago_total > 0 else None

    scope_rows = (
        await db.execute(select(MemoryNode.scope, func.count()).where(*base).group_by(MemoryNode.scope))
    ).all()
    scope_counts = {row[0]: row[1] for row in scope_rows}
    pending_rows = (
        await db.execute(
            select(MemoryNode.scope, func.count())
            .where(*base, MemoryNode.status == "pending")
            .group_by(MemoryNode.scope)
        )
    ).all()
    pending = {row[0]: row[1] for row in pending_rows}
    scopes = [{"scope": s, "count": scope_counts.get(s, 0), "pending": pending.get(s, 0)} for s in SCOPES] + [
        {"scope": s, "count": c, "pending": pending.get(s, 0)} for s, c in scope_counts.items() if s not in SCOPES
    ]

    # Domain tags are the dashboard's category vocabulary. Count distinct
    # memories for every tag rather than partitioning memories into one bucket:
    # a memory can legitimately belong to several categories.
    category_col = func.unnest(MemoryNode.domains).label("category")
    category_rows = (
        await db.execute(
            select(category_col, func.count(func.distinct(MemoryNode.id)))
            .where(*base)
            .group_by(category_col)
            .order_by(func.count(func.distinct(MemoryNode.id)).desc(), category_col)
            .limit(40)
        )
    ).all()
    categories = [{"name": row[0], "memory_count": row[1]} for row in category_rows if row[0]]

    # Identities: OAuth clients when the auth service answers, otherwise the
    # distinct writers seen in memory.
    clients = await _auth_clients(settings)
    if clients is not None and mine is not None:
        clients = [client for client in clients if client.get("client_id") in acc.grants.identities]
    active_since = now - timedelta(minutes=15)
    active_where = [AuditLog.tenant_id == tenant_id, AuditLog.timestamp >= active_since, *audit_scope]
    active_now = (
        await db.execute(select(func.count(func.distinct(AuditLog.actor_id))).where(*active_where))
    ).scalar_one()
    if clients is not None:
        agents_total = sum(1 for c in clients if c.get("active", True))
        agents_source = "auth"
    else:
        writer = func.coalesce(MemoryNode.actor_id, MemoryNode.owner_id)
        writer_filters = list(live_filters(tenant_id))
        if mine is not None:
            writer_filters.append(writer.in_(acc.grants.identities))
        agents_total = (await db.execute(select(func.count(func.distinct(writer))).where(*writer_filters))).scalar_one()
        agents_source = "memory"

    day_ago = now - timedelta(hours=24)
    search_scope = [
        AuditLog.tenant_id == tenant_id,
        AuditLog.event_type.in_(SEARCH_EVENTS),
        AuditLog.timestamp >= day_ago,
        *audit_scope,
    ]
    searches_24h = (await db.execute(select(func.count()).select_from(AuditLog).where(*search_scope))).scalar_one()
    p95 = None
    try:
        latency = cast(AuditLog.event_metadata["latency_ms"].astext, Float)
        p95 = (
            await db.execute(
                select(func.percentile_cont(0.95).within_group(latency))
                .select_from(AuditLog)
                .where(*search_scope, AuditLog.event_metadata.has_key("latency_ms"))  # type: ignore[attr-defined]
            )
        ).scalar_one()
    except Exception:
        await db.rollback()

    open_contradictions = (
        await db.execute(
            select(func.count())
            .select_from(ContradictionReport)
            .join(MemoryNode, MemoryNode.id == ContradictionReport.memory_id)
            .where(
                ContradictionReport.tenant_id == tenant_id,
                ContradictionReport.resolved.is_(False),
                MemoryNode.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    per_memory = (
        select(ContradictionReport.memory_id, func.count().label("n"))
        .join(MemoryNode, MemoryNode.id == ContradictionReport.memory_id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            ContradictionReport.resolved.is_(False),
            MemoryNode.deleted_at.is_(None),
        )
        .group_by(ContradictionReport.memory_id)
        .subquery()
    )
    over_threshold = (
        await db.execute(select(func.count()).select_from(per_memory).where(per_memory.c.n >= threshold))
    ).scalar_one()

    # Activity from the audit log, bucketed to fit the selected window; fall
    # back to memory timestamps when the MCP server has not written audit
    # events yet. Every bucket in the window is emitted, including empty ones,
    # so the chart never hides gaps in the timeline.
    if activity_range == "all":
        activity_scope = [AuditLog.tenant_id == tenant_id, *audit_scope]
        earliest = await _account_start(db, tenant_id, viewer, base, activity_scope)
        span = max(1.0, (now - earliest).total_seconds())
        bucket = next((b for b in ALL_TIME_BUCKETS if span / b <= 90), ALL_TIME_BUCKETS[-1])
        first_bucket = int(earliest.timestamp()) // bucket * bucket
    else:
        window, bucket = ACTIVITY_RANGES[activity_range]
        first_bucket = (int(now.timestamp()) - window) // bucket * bucket + bucket
    last_bucket = int(now.timestamp()) // bucket * bucket
    activity_start = datetime.fromtimestamp(first_bucket, tz=UTC)

    def bucket_of(col):
        return (func.floor(func.extract("epoch", col) / bucket) * bucket).label("bucket")

    audit_bucket = bucket_of(AuditLog.timestamp)
    activity_rows = (
        await db.execute(
            select(
                audit_bucket,
                func.count().filter(AuditLog.event_type.in_(SEARCH_EVENTS)),
                func.count().filter(AuditLog.event_type.in_(WRITE_EVENTS)),
            )
            .where(AuditLog.tenant_id == tenant_id, AuditLog.timestamp >= activity_start, *audit_scope)
            .group_by(audit_bucket)
        )
    ).all()
    activity_source = "audit"
    by_bucket: dict[int, tuple[int, int]] = {int(row[0]): (row[1], row[2]) for row in activity_rows}
    if not any(w or s for s, w in by_bucket.values()):
        mem_bucket = bucket_of(MemoryNode.created_at)
        mem_rows = (
            await db.execute(
                select(mem_bucket, func.count())
                .where(*base, MemoryNode.created_at >= activity_start)
                .group_by(mem_bucket)
            )
        ).all()
        by_bucket = {int(row[0]): (0, row[1]) for row in mem_rows}
        activity_source = "memory"
    activity = []
    for ts in range(first_bucket, last_bucket + 1, bucket):
        searches, writes = by_bucket.get(ts, (0, 0))
        activity.append(
            {
                "date": datetime.fromtimestamp(ts, tz=UTC).isoformat(),
                "searches": searches,
                "writes": writes,
            }
        )

    identity_types = {c["client_id"]: c.get("identity_type", "user") for c in (clients or [])}
    recent_rows = await _recent_events(db, tenant_id, 6 if acc.grants is None else 40, mine)
    if acc.grants is not None:
        recent_rows = [
            (e, m)
            for e, m in recent_rows
            if (m is not None and acc.can_read_row(m))
            or e.actor_id in acc.grants.identities
            or e.driver_id in acc.grants.identities
        ][:6]
    recent = acc.redact_tree([_event_row(e, m, identity_types) for e, m in recent_rows])
    recent_source = "audit"
    if not recent and total:
        nodes = (
            (await db.execute(select(MemoryNode).where(*base).order_by(MemoryNode.updated_at.desc()).limit(6)))
            .scalars()
            .all()
        )
        recent = [
            {
                "id": str(n.id),
                "timestamp": n.updated_at,
                "event_type": "memory.write" if n.version == 1 else "memory.update",
                "operation": "write_memory" if n.version == 1 else "update_memory",
                "actor_id": n.actor_id or n.owner_id,
                "driver_id": n.driver_id,
                "actor_type": identity_types.get(n.actor_id or n.owner_id),
                "scope": n.scope,
                "owner_id": n.owner_id,
                "memory_id": str(n.id),
                "memory_stub": n.stub,
                "memory_version": n.version,
                "decision": "allowed",
                "metadata": {},
            }
            for n in nodes
        ]
        recent_source = "memory"

    health = await probe_components(db, settings)
    curator_last = (
        await db.execute(
            select(func.max(AuditLog.timestamp)).where(
                AuditLog.tenant_id == tenant_id, AuditLog.actor_id.ilike("%curator%")
            )
        )
    ).scalar_one()
    health.insert(
        6,
        {
            "key": "curator",
            "name": "Curator agents",
            "status": "healthy" if curator_last and curator_last >= now - timedelta(hours=24) else "idle",
            "detail": None if curator_last else "No curator activity recorded",
            "latency_ms": None,
        },
    )

    ctx = None
    try:
        response_tokens = cast(AuditLog.event_metadata["response_tokens"].astext, Float)
        cache_prefix_hit = cast(AuditLog.event_metadata["cache_prefix_hit"].astext, Boolean)
        ctx_filters = [
            AuditLog.tenant_id == tenant_id,
            AuditLog.event_type == "memory.search",
            AuditLog.timestamp >= now - timedelta(days=7),
            *audit_scope,
            or_(
                AuditLog.event_metadata.has_key("response_tokens"),  # type: ignore[attr-defined]
                AuditLog.event_metadata.has_key("cache_prefix_hit"),  # type: ignore[attr-defined]
            ),
        ]
        ctx = (
            await db.execute(
                select(
                    func.avg(response_tokens),
                    func.avg(case((cache_prefix_hit, 1.0), else_=0.0)).filter(
                        AuditLog.event_metadata.has_key("cache_prefix_hit")  # type: ignore[attr-defined]
                    ),
                ).where(*ctx_filters)
            )
        ).first()
    except Exception:
        await db.rollback()

    return {
        "tenant_id": tenant_id,
        "generated_at": now,
        "memories": {"current": total, "new_7d": new_7d, "growth_pct": growth_pct},
        "agents": {"total": agents_total, "active_now": active_now, "source": agents_source},
        "searches": {"last_24h": searches_24h, "p95_latency_ms": round(p95) if p95 else None},
        "contradictions": {"open": open_contradictions, "over_threshold": over_threshold, "threshold": threshold},
        "approvals": {"enterprise_pending": pending.get("enterprise", 0), "pending_total": sum(pending.values())},
        "scopes": scopes,
        "categories": categories,
        "activity": activity,
        "activity_range": activity_range,
        "activity_bucket_seconds": bucket,
        "activity_source": activity_source,
        "recent": recent,
        "recent_source": recent_source,
        "health": health,
        "context_assembly": {
            "avg_tokens": round(ctx[0]) if ctx and ctx[0] is not None else None,
            "prefix_hit_rate": round(ctx[1], 3) if ctx and ctx[1] is not None else None,
        },
    }


@router.get("/api/nav-counts")
async def nav_counts(db: DbDep, settings: SettingsDep):
    """Small payload for the sidebar badge: items waiting in the review queue."""
    tenant_id = settings.ui_tenant_id
    tenant_settings = await load_tenant_settings(db, tenant_id)
    queue = await _review_counts(db, tenant_id, int(tenant_settings["governance"]["contradiction_threshold"]))
    memories = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(*live_filters(tenant_id), MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity")
        )
    ).scalar_one()
    return {"review_queue": sum(queue.values()), "memories": memories}


async def _review_counts(db: AsyncSession, tenant_id: str, threshold: int) -> dict[str, int]:
    pending_rows = (
        await db.execute(
            select(MemoryNode.scope, func.count())
            .where(*live_filters(tenant_id), MemoryNode.status == "pending")
            .group_by(MemoryNode.scope)
        )
    ).all()
    approvals = sum(c for scope, c in pending_rows if scope == "enterprise")
    promotions = sum(c for scope, c in pending_rows if scope != "enterprise")
    per_memory = (
        select(ContradictionReport.memory_id)
        .join(MemoryNode, MemoryNode.id == ContradictionReport.memory_id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            ContradictionReport.resolved.is_(False),
            MemoryNode.deleted_at.is_(None),
        )
        .group_by(ContradictionReport.memory_id)
        .having(func.count() >= threshold)
        .subquery()
    )
    contradictions = (await db.execute(select(func.count()).select_from(per_memory))).scalar_one()
    quarantine = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.deleted_at.is_(None),
                MemoryNode.status == "quarantined",
            )
        )
    ).scalar_one()
    return {
        "approvals": approvals,
        "promotions": promotions,
        "contradictions": contradictions,
        "quarantine": quarantine,
    }


# ---------------------------------------------------------------------------
# Entities (screen 03)
# ---------------------------------------------------------------------------


@router.get("/api/entities")
async def entities(
    db: DbDep,
    settings: SettingsDep,
    viewer: ContentDep,
    q: str | None = Query(default=None, max_length=255),
    entity_type: str = Query(default="all", alias="type", pattern="^(all|person|object|location|event|organization)$"),
    project: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
):
    """List extracted entities and the memories/projects that mention them."""
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    entity_node = aliased(MemoryNode)
    source_node = aliased(MemoryNode)
    mention = aliased(MemoryRelationship)
    project_value = case(
        (source_node.scope == "project", source_node.scope_id),
        else_=source_node.metadata_["project"].as_string(),
    )
    mentions_count = func.count(func.distinct(source_node.id)).label("memory_count")
    projects = func.array_agg(func.distinct(project_value)).filter(project_value.is_not(None)).label("projects")

    entity_base_filters = [
        entity_node.tenant_id == tenant_id,
        entity_node.scope == "entity",
        entity_node.is_current.is_(True),
        entity_node.deleted_at.is_(None),
    ]
    if q:
        pattern = f"%{q.lower()}%"
        entity_base_filters.append(
            or_(func.lower(entity_node.content).ilike(pattern), cast(entity_node.metadata_, String).ilike(pattern))
        )

    source_filters = and_(
        source_node.tenant_id == tenant_id,
        source_node.parent_id.is_(None),
        source_node.is_current.is_(True),
        source_node.deleted_at.is_(None),
        source_node.status != "quarantined",
        source_node.scope != "entity",
        *acc.filters(source_node),
    )
    if acc.grants is not None:
        # Entity names are derived from memory content: only show those that
        # appear in at least one memory this user can read.
        readable_mention = aliased(MemoryRelationship)
        readable_source = aliased(MemoryNode)
        entity_base_filters_extra = exists(
            select(1)
            .select_from(readable_mention)
            .join(readable_source, readable_source.id == readable_mention.source_id)
            .where(
                readable_mention.target_id == entity_node.id,
                readable_mention.relationship_type == "mentions",
                readable_mention.valid_until.is_(None),
                readable_source.deleted_at.is_(None),
                acc.clause(readable_source),
            )
        )
    else:
        entity_base_filters_extra = None
    project_exists = None
    if project:
        project_mention = aliased(MemoryRelationship)
        project_source = aliased(MemoryNode)
        project_value_filter = or_(
            and_(project_source.scope == "project", project_source.scope_id == project),
            project_source.metadata_["project"].as_string() == project,
        )
        project_source_filters = and_(
            project_source.tenant_id == tenant_id,
            project_source.parent_id.is_(None),
            project_source.is_current.is_(True),
            project_source.deleted_at.is_(None),
            project_source.status != "quarantined",
            project_source.scope != "entity",
        )
        project_exists = exists(
            select(1)
            .select_from(project_mention)
            .join(project_source, project_source.id == project_mention.source_id)
            .where(
                project_mention.target_id == entity_node.id,
                project_mention.tenant_id == tenant_id,
                project_mention.relationship_type == "mentions",
                project_mention.valid_until.is_(None),
                project_source_filters,
                project_value_filter,
            )
        )
        entity_base_filters.append(project_exists)

    if entity_base_filters_extra is not None:
        entity_base_filters.append(entity_base_filters_extra)
    entity_filters = list(entity_base_filters)
    if entity_type != "all":
        entity_filters.append(entity_node.branch_type == f"entity:{entity_type}")

    stmt = (
        select(entity_node, mentions_count, func.max(source_node.updated_at), projects)
        .outerjoin(
            mention,
            and_(
                mention.target_id == entity_node.id,
                mention.tenant_id == tenant_id,
                mention.relationship_type == "mentions",
                mention.valid_until.is_(None),
            ),
        )
        .outerjoin(source_node, and_(source_node.id == mention.source_id, source_filters))
        .where(*entity_filters)
        .group_by(entity_node.id)
        .order_by(mentions_count.desc(), func.lower(entity_node.content))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await db.execute(stmt)).all()

    count_stmt = select(func.count()).select_from(entity_node).where(*entity_filters)
    total = (await db.execute(count_stmt)).scalar_one()
    type_rows = (
        await db.execute(
            select(entity_node.branch_type, func.count())
            .select_from(entity_node)
            .where(*entity_base_filters)
            .group_by(entity_node.branch_type)
        )
    ).all()
    type_counts = {str(row[0]).removeprefix("entity:"): row[1] for row in type_rows if row[0]}

    items = []
    for node, count, last_seen, project_list in rows:
        entity_kind = node.branch_type.removeprefix("entity:") if node.branch_type else "unknown"
        items.append(
            {
                "id": str(node.id),
                "name": node.content,
                "entity_type": entity_kind,
                "aliases": list((node.metadata_ or {}).get("aliases", [])),
                "memory_count": int(count or 0),
                "projects": sorted({p for p in (project_list or []) if p}),
                "created_at": node.created_at,
                "last_seen": last_seen,
            }
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": page * per_page < total,
        "counts": {
            "all": total,
            **{kind: type_counts.get(kind, 0) for kind in ("person", "organization", "location", "object", "event")},
        },
    }


# ---------------------------------------------------------------------------
# Memory browser (screen 02)
# ---------------------------------------------------------------------------

_BROWSE_SORTS = {
    "updated": MemoryNode.updated_at,
    "created": MemoryNode.created_at,
    "weight": MemoryNode.weight,
    "version": MemoryNode.version,
}
_SEMANTIC_LIMIT = 200
_NEAR_DUP = 0.90


def _tab_filters(tenant_id: str, tab: str) -> list:
    roots = [MemoryNode.tenant_id == tenant_id, MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity"]
    if tab == "all":
        return roots + [MemoryNode.deleted_at.is_(None)]
    if tab == "quarantined":
        return roots + [MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined"]
    if tab == "deleted":
        newer = aliased(MemoryNode)
        return roots + [
            MemoryNode.deleted_at.is_not(None),
            ~exists().where(newer.previous_version_id == MemoryNode.id),
        ]
    return roots + [
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status != "quarantined",
    ]


def _contradicted_clause(tenant_id: str):
    return exists().where(
        ContradictionReport.memory_id == MemoryNode.id,
        ContradictionReport.tenant_id == tenant_id,
        ContradictionReport.resolved.is_(False),
    )


def _has_branches_clause():
    child = aliased(MemoryNode)
    return exists().where(child.parent_id == MemoryNode.id, child.deleted_at.is_(None))


def _near_dup_clause(tenant_id: str):
    other = aliased(MemoryNode)
    return exists().where(
        other.tenant_id == tenant_id,
        other.id != MemoryNode.id,
        other.is_current.is_(True),
        other.deleted_at.is_(None),
        other.parent_id.is_(None),
        other.embedding.is_not(None),
        MemoryNode.embedding.is_not(None),
        other.embedding.cosine_distance(MemoryNode.embedding) <= 1 - _NEAR_DUP,
    )


async def _entities_for(db: AsyncSession, tenant_id: str, ids: list) -> dict[uuid.UUID, list[dict]]:
    """Entities each memory mentions (``mentions`` edges to entity nodes)."""
    if not ids:
        return {}
    entity_node = aliased(MemoryNode)
    rows = (
        await db.execute(
            select(MemoryRelationship.source_id, entity_node.id, entity_node.content, entity_node.branch_type)
            .join(entity_node, entity_node.id == MemoryRelationship.target_id)
            .where(
                MemoryRelationship.source_id.in_(ids),
                MemoryRelationship.tenant_id == tenant_id,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
                entity_node.scope == "entity",
                entity_node.deleted_at.is_(None),
            )
            .order_by(entity_node.content)
        )
    ).all()
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for source_id, entity_id, name, branch_type in rows:
        kind = (branch_type or "entity:object").removeprefix("entity:")
        out[source_id].append({"id": str(entity_id), "name": name, "type": kind})
    return out


@router.get("/api/memories/browse")
async def browse_memories(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    tab: str = Query(default="current", pattern="^(current|all|quarantined|deleted)$"),
    q: str | None = Query(default=None, max_length=1000),
    mode: str = Query(default="semantic", pattern="^(semantic|text)$"),
    scope: list[str] | None = Query(default=None),
    actor: list[str] | None = Query(default=None),
    project: str | None = Query(default=None, max_length=255),
    domain: list[str] | None = Query(default=None),
    min_weight: float | None = Query(default=None, ge=0, le=1),
    flag: list[str] | None = Query(default=None),
    sort: str = Query(default="updated", pattern="^(relevance|updated|created|weight|version)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    entity: str | None = Query(default=None, max_length=64),
):
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    # #667: admins read and search the scopes they may moderate; the rest stays metadata only.
    metadata_only = viewer.redacts_content and not acc.open_scopes
    readable_only = [MemoryNode.scope.in_(acc.open_scopes)] if viewer.redacts_content else []
    base = _tab_filters(tenant_id, tab) + acc.filters()
    filters = list(base)
    if scope:
        filters.append(MemoryNode.scope.in_(scope))
    if actor:
        filters.append(
            or_(MemoryNode.actor_id.in_(actor), and_(MemoryNode.actor_id.is_(None), MemoryNode.owner_id.in_(actor)))
        )
    if project:
        filters.append(
            or_(
                and_(MemoryNode.scope == "project", MemoryNode.scope_id == project),
                MemoryNode.metadata_["project"].as_string() == project,
            )
        )
    if domain and not metadata_only:
        filters.append(MemoryNode.domains.overlap(domain))
        filters.extend(readable_only)
    if entity:
        entity_id = parse_uuid(entity, "entity ID")
        filters.append(
            exists().where(
                MemoryRelationship.source_id == MemoryNode.id,
                MemoryRelationship.target_id == entity_id,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
            )
        )
    if min_weight is not None:
        filters.append(MemoryNode.weight >= min_weight)
    flags = set(flag or [])
    if "contradicted" in flags:
        filters.append(_contradicted_clause(tenant_id))
    if "has_branches" in flags:
        filters.append(_has_branches_clause())
    if "near_duplicate" in flags:
        filters.append(_near_dup_clause(tenant_id))

    query = (q or "").strip()
    search_mode = "none"
    scores: dict[uuid.UUID, float] = {}
    if query and metadata_only:
        # Admins never search what memories say; only who and where.
        pattern = f"%{query}%"
        filters.append(
            or_(
                MemoryNode.owner_id.ilike(pattern),
                MemoryNode.actor_id.ilike(pattern),
                MemoryNode.scope_id.ilike(pattern),
                cast(MemoryNode.id, String).ilike(f"{query.replace('mem_', '').split('…')[0]}%"),
            )
        )
        search_mode = "metadata"
        query = ""
    if query and readable_only:
        # Cross-owner content search for moderation never reaches user memories.
        filters.extend(readable_only)
    if query:
        vector = await embed(query, settings.embedding_url) if mode == "semantic" else None
        if vector is not None:
            distance = MemoryNode.embedding.cosine_distance(vector)
            ranked = (
                await db.execute(
                    select(MemoryNode.id, (1 - distance).label("score"))
                    .where(*filters, MemoryNode.embedding.is_not(None))
                    .order_by(distance)
                    .limit(_SEMANTIC_LIMIT)
                )
            ).all()
            scores = {row[0]: float(row[1]) for row in ranked}
            filters.append(MemoryNode.id.in_(list(scores) or [uuid.uuid4()]))
            search_mode = "semantic"
        else:
            pattern = f"%{query}%"
            filters.append(or_(MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern)))
            search_mode = "text"

    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one()

    descending = order == "desc"
    if sort == "relevance" and scores:
        ordered_ids = sorted(scores, key=lambda k: scores[k], reverse=descending)
        page_ids = ordered_ids[(page - 1) * per_page : page * per_page]
        rows = (
            (await db.execute(select(MemoryNode).where(MemoryNode.id.in_(page_ids or [uuid.uuid4()])))).scalars().all()
        )
        by_id = {r.id: r for r in rows}
        nodes = [by_id[i] for i in page_ids if i in by_id]
    else:
        column = _BROWSE_SORTS.get(sort, MemoryNode.updated_at)
        nodes = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(*filters)
                    .order_by(column.desc() if descending else column.asc(), MemoryNode.id)
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            )
            .scalars()
            .all()
        )

    ids = [n.id for n in nodes]
    branch_info: dict[uuid.UUID, list[str]] = defaultdict(list)
    contradiction_counts: dict[uuid.UUID, int] = {}
    near_dup: dict[uuid.UUID, float] = {}
    if ids:
        for parent_id, branch_type in (
            await db.execute(
                select(MemoryNode.parent_id, MemoryNode.branch_type).where(
                    MemoryNode.parent_id.in_(ids), MemoryNode.deleted_at.is_(None)
                )
            )
        ).all():
            branch_info[parent_id].append(branch_type or "branch")
        contradiction_counts = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(ContradictionReport.memory_id, func.count())
                    .where(
                        ContradictionReport.memory_id.in_(ids),
                        ContradictionReport.tenant_id == tenant_id,
                        ContradictionReport.resolved.is_(False),
                    )
                    .group_by(ContradictionReport.memory_id)
                )
            ).all()
        }
        try:
            dup_rows = (
                await db.execute(
                    text(
                        """
                        SELECT m.id, nn.score
                        FROM memory_nodes m
                        CROSS JOIN LATERAL (
                          SELECT 1 - (o.embedding <=> m.embedding) AS score
                          FROM memory_nodes o
                          WHERE o.tenant_id = :t AND o.id <> m.id AND o.is_current
                            AND o.deleted_at IS NULL AND o.parent_id IS NULL AND o.embedding IS NOT NULL
                          ORDER BY o.embedding <=> m.embedding
                          LIMIT 1
                        ) nn
                        WHERE m.id = ANY(:ids) AND m.embedding IS NOT NULL
                        """
                    ),
                    {"t": tenant_id, "ids": ids},
                )
            ).all()
            near_dup = {row[0]: float(row[1]) for row in dup_rows if row[1] is not None and row[1] >= _NEAR_DUP}
        except Exception as exc:
            logger.debug("near-duplicate lookup failed: %s", exc)
            await db.rollback()

    entities_by_memory = await _entities_for(db, tenant_id, ids)

    items = []
    for n in nodes:
        branches = branch_info.get(n.id, [])
        counts = Counter(branches)
        items.append(
            {
                "id": str(n.id),
                "stub": clean_stub(n.stub),
                "content_preview": preview(n.content),
                "scope": n.scope,
                "scope_id": n.scope_id,
                "owner_id": n.owner_id,
                "actor_id": n.actor_id,
                "driver_id": n.driver_id,
                "domains": list(n.domains or []),
                "weight": n.weight,
                "version": n.version,
                "is_current": n.is_current,
                "status": n.status,
                "content_type": n.content_type,
                "branch_count": len(branches),
                "branch_summary": [{"type": t, "count": c} for t, c in counts.most_common()],
                "open_contradictions": contradiction_counts.get(n.id, 0),
                "near_duplicate": round(near_dup[n.id], 2) if n.id in near_dup else None,
                "created_at": n.created_at,
                "updated_at": n.updated_at,
                "deleted_at": n.deleted_at,
                "score": round(scores[n.id], 4) if n.id in scores else None,
                "entities": entities_by_memory.get(n.id, []),
            }
        )
    items = [acc.redact(i) for i in items]

    # Tab counts and facets (over the tab base, independent of facet filters).
    tab_counts = {}
    for t in ("current", "all", "quarantined", "deleted"):
        tab_counts[t] = (
            await db.execute(
                select(func.count()).select_from(MemoryNode).where(*_tab_filters(tenant_id, t), *acc.filters())
            )
        ).scalar_one()
    facet_scope = {
        row[0]: row[1]
        for row in (
            await db.execute(select(MemoryNode.scope, func.count()).where(*base).group_by(MemoryNode.scope))
        ).all()
    }
    writer = func.coalesce(MemoryNode.actor_id, MemoryNode.owner_id)
    writer_rows = (
        await db.execute(select(writer, func.count()).where(*base).group_by(writer).order_by(func.count().desc()))
    ).all()
    project_rows = (
        await db.execute(
            select(MemoryNode.scope_id, func.count())
            .where(*base, MemoryNode.scope == "project", MemoryNode.scope_id.is_not(None))
            .group_by(MemoryNode.scope_id)
            .order_by(func.count().desc())
        )
    ).all()
    domain_col = func.unnest(MemoryNode.domains).label("d")
    domain_sub = select(domain_col).where(*base, *readable_only).subquery()
    domain_rows = (
        []
        if metadata_only
        else (
            await db.execute(
                select(domain_sub.c.d, func.count()).group_by(domain_sub.c.d).order_by(func.count().desc()).limit(40)
            )
        ).all()
    )
    contradicted = (
        await db.execute(select(func.count()).select_from(MemoryNode).where(*base, _contradicted_clause(tenant_id)))
    ).scalar_one()
    with_branches = (
        await db.execute(select(func.count()).select_from(MemoryNode).where(*base, _has_branches_clause()))
    ).scalar_one()
    near_dup_count = None
    if tab_counts["current"] <= 5000:
        try:
            near_dup_count = (
                await db.execute(select(func.count()).select_from(MemoryNode).where(*base, _near_dup_clause(tenant_id)))
            ).scalar_one()
        except Exception:
            await db.rollback()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "search_mode": search_mode,
        "metadata_only": metadata_only,
        "hidden_scopes": list(acc.hidden_scopes),
        "break_glass": acc.break_glass,
        "tab_counts": tab_counts,
        "facets": {
            "scopes": [{"value": s, "count": facet_scope.get(s, 0)} for s in SCOPES]
            + [{"value": s, "count": c} for s, c in facet_scope.items() if s not in SCOPES],
            "writers": [{"value": r[0], "count": r[1]} for r in writer_rows],
            "projects": [{"value": r[0], "count": r[1]} for r in project_rows],
            "domains": [{"value": r[0], "count": r[1]} for r in domain_rows],
            "flags": {"contradicted": contradicted, "has_branches": with_branches, "near_duplicate": near_dup_count},
        },
    }


@router.get("/api/memories/export")
async def export_memories(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    scope: list[str] | None = Query(default=None),
    mine: bool = Query(default=False),
):
    """JSONL export of current memories (the browser's "Export JSONL")."""
    from fastapi.responses import StreamingResponse

    acc = await access_for(db, settings, viewer)
    filters = _tab_filters(settings.ui_tenant_id, "current") + acc.filters()
    if scope:
        filters.append(MemoryNode.scope.in_(scope))
    if mine:
        own = list(acc.grants.identities) if acc.grants else [viewer.username]
        filters += [MemoryNode.scope == "user", MemoryNode.owner_id.in_(own)]
    nodes = (
        (await db.execute(select(MemoryNode).where(*filters).order_by(MemoryNode.updated_at.desc()))).scalars().all()
    )

    def lines():
        for n in nodes:
            yield (
                json.dumps(
                    acc.redact(
                        {
                            "id": str(n.id),
                            "scope": n.scope,
                            "scope_id": n.scope_id,
                            "owner_id": n.owner_id,
                            "actor_id": n.actor_id,
                            "weight": n.weight,
                            "version": n.version,
                            "domains": list(n.domains or []),
                            "content": n.content,
                            "metadata": n.metadata_,
                            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
                        },
                        n.scope,
                    ),
                    default=str,
                )
                + "\n"
            )

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="memoryhub-{settings.ui_tenant_id}.jsonl"'},
    )


# ---------------------------------------------------------------------------
# Memory detail (screen 03)
# ---------------------------------------------------------------------------


async def _load_memory(db: AsyncSession, tenant_id: str, memory_id: str) -> MemoryNode:
    parsed = parse_uuid(memory_id, "memory ID")
    node = (
        await db.execute(select(MemoryNode).where(MemoryNode.id == parsed, MemoryNode.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id!r} not found")
    return node


class _Row:
    """Duck-typed node for the Python read predicate on serialised briefs."""

    def __init__(self, d: dict):
        self.scope = d.get("scope")
        self.scope_id = d.get("scope_id")
        self.owner_id = d.get("owner_id")


def _node_brief(n: MemoryNode) -> dict:
    return {
        "id": str(n.id),
        "stub": clean_stub(n.stub),
        "scope": n.scope,
        "scope_id": n.scope_id,
        "owner_id": n.owner_id,
        "weight": n.weight,
        "version": n.version,
        "is_current": n.is_current,
        "status": n.status,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


@router.get("/api/memory/{memory_id}/context")
async def memory_context(memory_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    tenant_id = settings.ui_tenant_id
    node = await _load_memory(db, tenant_id, memory_id)
    acc = await access_for(db, settings, viewer)
    acc.ensure_readable(node)
    tenant_settings = await load_tenant_settings(db, tenant_id)

    # Versions share a logical_id; fall back to walking the chain.
    logical_id = getattr(node, "logical_id", None)
    if logical_id is not None:
        versions = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(
                        MemoryNode.tenant_id == tenant_id,
                        MemoryNode.logical_id == logical_id,
                        MemoryNode.parent_id.is_(None),
                    )
                    .order_by(MemoryNode.version.desc())
                )
            )
            .scalars()
            .all()
        )
    else:
        versions = [node]
    version_ids = [v.id for v in versions] or [node.id]

    branches = (
        (
            await db.execute(
                select(MemoryNode)
                .where(
                    MemoryNode.parent_id == node.id, MemoryNode.tenant_id == tenant_id, MemoryNode.deleted_at.is_(None)
                )
                .order_by(MemoryNode.created_at)
            )
        )
        .scalars()
        .all()
    )

    rels = (
        (
            await db.execute(
                select(MemoryRelationship).where(
                    MemoryRelationship.tenant_id == tenant_id,
                    MemoryRelationship.valid_until.is_(None),
                    or_(MemoryRelationship.source_id == node.id, MemoryRelationship.target_id == node.id),
                )
            )
        )
        .scalars()
        .all()
    )
    other_ids = {r.target_id if r.source_id == node.id else r.source_id for r in rels}
    others = {}
    if other_ids:
        others = {
            o.id: o
            for o in (
                await db.execute(
                    select(MemoryNode).where(MemoryNode.id.in_(list(other_ids)), MemoryNode.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        }
    relationships, omitted = [], 0
    for r in rels:
        outgoing = r.source_id == node.id
        other = others.get(r.target_id if outgoing else r.source_id)
        if other is None or other.deleted_at is not None:
            omitted += 1
            continue
        relationships.append(
            {
                "id": str(r.id),
                "type": r.relationship_type,
                "direction": "out" if outgoing else "in",
                "created_by": r.created_by,
                "created_at": r.created_at,
                "other": _node_brief(other),
            }
        )

    reports = (
        (
            await db.execute(
                select(ContradictionReport)
                .where(ContradictionReport.tenant_id == tenant_id, ContradictionReport.memory_id.in_(version_ids))
                .order_by(ContradictionReport.resolved, ContradictionReport.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    similar = []
    if node.embedding is not None:
        distance = MemoryNode.embedding.cosine_distance(node.embedding)
        rows = (
            await db.execute(
                select(MemoryNode, (1 - distance).label("score"))
                .where(
                    *live_filters(tenant_id),
                    MemoryNode.parent_id.is_(None),
                    MemoryNode.id.not_in(version_ids),
                    MemoryNode.embedding.is_not(None),
                )
                .order_by(distance)
                .limit(5)
            )
        ).all()
        similar = [{**_node_brief(row[0]), "score": round(float(row[1]), 3)} for row in rows if row[1] >= 0.5]

    access_count = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.memory_id.in_(version_ids))
        )
    ).scalar_one()

    dims = None
    if node.embedding is not None:
        try:
            dims = len(node.embedding)
        except TypeError:
            dims = None

    full_threshold = float(tenant_settings["retrieval"]["full_content_threshold"])
    result = {
        "memory": {
            **_node_brief(node),
            "content": node.content,
            "logical_id": str(logical_id) if logical_id else None,
            "parent_id": str(node.parent_id) if node.parent_id else None,
            "branch_type": node.branch_type,
            "actor_id": node.actor_id,
            "driver_id": node.driver_id,
            "tenant_id": node.tenant_id,
            "domains": list(node.domains or []),
            "content_type": node.content_type,
            "source": node.source,
            "metadata": node.metadata_,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "deleted_at": node.deleted_at,
            "expires_at": node.expires_at,
            "embedding_dims": dims,
            "injection": "full" if node.weight >= full_threshold else "stub",
            "full_content_threshold": full_threshold,
        },
        "versions": [
            {
                "id": str(v.id),
                "version": v.version,
                "is_current": v.is_current,
                "content": v.content,
                "weight": v.weight,
                "actor_id": v.actor_id,
                "driver_id": v.driver_id,
                "owner_id": v.owner_id,
                "created_at": v.created_at,
                "deleted_at": v.deleted_at,
            }
            for v in versions
        ],
        "branches": [
            {
                "id": str(b.id),
                "branch_type": b.branch_type,
                "content": b.content,
                "actor_id": b.actor_id or b.owner_id,
                "created_at": b.created_at,
            }
            for b in branches
        ],
        "relationships": relationships,
        "relationships_omitted": omitted,
        "contradictions": [
            {
                "id": str(c.id),
                "observed_behavior": c.observed_behavior,
                "confidence": c.confidence,
                "reporter": c.reporter,
                "created_at": c.created_at,
                "resolved": c.resolved,
            }
            for c in reports
        ],
        "contradiction_threshold": int(tenant_settings["governance"]["contradiction_threshold"]),
        "similar": similar,
        "access_count": access_count,
    }
    if acc.grants is not None:
        result["relationships"] = [r for r in result["relationships"] if acc.can_read_row(_Row(r.get("other", {})))]
        result["similar"] = [x for x in result["similar"] if acc.can_read_row(_Row(x))]
    return acc.redact_tree(result, node.scope)


@router.get("/api/memory/{memory_id}/access-log")
async def memory_access_log(
    memory_id: str,
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
):
    tenant_id = settings.ui_tenant_id
    node = await _load_memory(db, tenant_id, memory_id)
    (await access_for(db, settings, viewer)).ensure_readable(node)
    ids = [node.id]
    if getattr(node, "logical_id", None):
        ids = list(
            (await db.execute(select(MemoryNode.id).where(MemoryNode.logical_id == node.logical_id))).scalars().all()
        )
    where = [AuditLog.tenant_id == tenant_id, AuditLog.memory_id.in_(ids)]
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(*where))).scalar_one()
    events = (
        (
            await db.execute(
                select(AuditLog)
                .where(*where)
                .order_by(AuditLog.timestamp.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    return {"total": total, "items": [_event_row(e, None, {}) for e in events]}


# ---------------------------------------------------------------------------
# Memory writes (dashboard actions)
# ---------------------------------------------------------------------------


class WriteMemoryRequest(BaseModel):
    content: str = Field(min_length=1)
    scope: str = "user"
    weight: float = Field(default=0.7, ge=0, le=1)
    owner_id: str | None = None
    scope_id: str | None = None
    domains: list[str] | None = None
    content_type: str = "experiential"


class NewVersionRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    weight: float | None = Field(default=None, ge=0, le=1)
    domains: list[str] | None = None


class BranchRequest(BaseModel):
    branch_type: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1)


class ContradictionRequest(BaseModel):
    observed_behavior: str = Field(min_length=1)
    confidence: float = Field(default=0.7, ge=0, le=1)


class RelationshipRequest(BaseModel):
    source_id: str
    target_id: str
    relationship_type: str


class BulkRequest(BaseModel):
    action: str = Field(pattern="^(weight|delete|restore|quarantine|promote|relate)$")
    reason: str | None = Field(default=None, max_length=500)
    ids: list[str] = Field(min_length=1, max_length=200)
    weight: float | None = Field(default=None, ge=0, le=1)
    target_scope: str | None = None
    target_scope_id: str | None = None
    relationship_type: str | None = None
    target_id: str | None = None


def _embedding_service(settings: Settings):
    if not settings.embedding_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "The embedding service is not configured (MEMORYHUB_EMBEDDING_URL), "
                "so the dashboard cannot write memories."
            ),
        )
    from memoryhub_core.services.embeddings import HttpEmbeddingService

    return HttpEmbeddingService(settings.embedding_url)


async def _writable(db: AsyncSession, settings: Settings, viewer, node: MemoryNode) -> None:
    """Admins never change memory content; users only touch what they can read."""
    if viewer.redacts_content:
        raise HTTPException(
            status_code=403, detail="Platform admins cannot change memories; their content is confidential"
        )
    if viewer.restricted:
        (await access_for(db, settings, viewer)).ensure_readable(node)


async def _writable_scope(db: AsyncSession, settings: Settings, viewer, scope: str, scope_id: str | None) -> None:
    """New memories follow the MCP server's write rules (``src.authz.authorize_write``)."""
    from src.authz import person_can_write

    if viewer.redacts_content:
        raise HTTPException(status_code=403, detail="Platform admins cannot write memories")
    if not viewer.restricted:
        return
    if scope in ("organizational", "enterprise"):
        raise HTTPException(status_code=403, detail="Write it to your own scope and propose a promotion instead")
    grants = (await access_for(db, settings, viewer)).grants
    owner = viewer.username if scope == "user" else (scope_id or "")
    if not person_can_write(grants, settings.ui_tenant_id, scope, owner, scope_id):
        detail = {
            "role": "Role memories are written by service agents, not people",
            "campaign": "Your project is not enrolled in that campaign",
        }.get(scope, f"You are not a member of that {scope}")
        raise HTTPException(status_code=403, detail=detail)


@router.post("/api/memories", status_code=201)
async def write_memory(body: WriteMemoryRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    return await create_dashboard_memory(db, settings, viewer, body)


async def create_dashboard_memory(
    db: AsyncSession, settings: Settings, viewer, body: WriteMemoryRequest, metadata: dict | None = None
) -> dict:
    """Write one memory through memoryhub_core (curation, embedding, audit)."""
    from memoryhub_core.models.schemas import MemoryNodeCreate
    from memoryhub_core.services.memory import create_memory

    await _writable_scope(db, settings, viewer, body.scope, body.scope_id)
    tenant_id = settings.ui_tenant_id
    owner = body.owner_id or (tenant_id if body.scope in ("organizational", "enterprise") else viewer.username)
    if viewer.restricted:
        owner = viewer.username if body.scope == "user" else (body.scope_id or owner)
    data = MemoryNodeCreate(
        content=body.content,
        scope=body.scope,
        weight=body.weight,
        owner_id=owner,
        actor_id=viewer.username,
        driver_id=viewer.username,
        scope_id=body.scope_id,
        domains=body.domains,
        content_type=body.content_type,
        source="import",
        metadata=metadata,
    )
    memory, curation = await create_memory(data, db, _embedding_service(settings), tenant_id=tenant_id)
    if memory is None:
        await audit(
            db,
            tenant_id=tenant_id,
            viewer=viewer,
            event_type="memory.write",
            scope=body.scope,
            owner_id=owner,
            memory_id=None,
            decision="denied",
            metadata={"reason": curation.get("reason"), "detail": curation.get("detail")},
        )
        await db.commit()
        raise HTTPException(status_code=409, detail=curation.get("detail") or "Blocked by a curation rule")
    if body.scope == "enterprise":
        # Enterprise memories never reach agents until approved (review queue).
        await db.execute(update(MemoryNode).where(MemoryNode.id == memory.id).values(status="pending"))
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="memory.write",
        scope=body.scope,
        owner_id=owner,
        memory_id=memory.id,
    )
    await db.commit()
    return {"id": str(memory.id), "curation": {"flags": curation.get("flags", [])}}


@router.post("/api/memory/{memory_id}/versions", status_code=201)
async def new_version(memory_id: str, body: NewVersionRequest, request: Request, db: DbDep, settings: SettingsDep):
    from memoryhub_core.models.schemas import MemoryNodeUpdate
    from memoryhub_core.services.memory import update_memory

    viewer = viewer_from_request(request, settings)
    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    await _writable(db, settings, viewer, node)
    if not node.is_current or node.deleted_at is not None:
        raise HTTPException(status_code=409, detail="Only the current version can be edited")
    if body.content is None and body.weight is None and body.domains is None:
        raise HTTPException(status_code=422, detail="Nothing to change")
    updated = await update_memory(
        node.id,
        MemoryNodeUpdate(content=body.content, weight=body.weight, domains=body.domains),
        db,
        _embedding_service(settings),
        actor_id=viewer.username,
        driver_id=viewer.username,
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="memory.update",
        scope=node.scope,
        owner_id=node.owner_id,
        memory_id=updated.id,
        metadata={"from_version": node.version, "weight": body.weight},
    )
    await db.commit()
    return {"id": str(updated.id), "version": updated.version}


@router.post("/api/memory/{memory_id}/branches", status_code=201)
async def add_branch(memory_id: str, body: BranchRequest, request: Request, db: DbDep, settings: SettingsDep):
    from memoryhub_core.models.schemas import MemoryNodeCreate
    from memoryhub_core.services.memory import create_memory

    viewer = viewer_from_request(request, settings)
    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    await _writable(db, settings, viewer, node)
    data = MemoryNodeCreate(
        content=body.content,
        scope=node.scope,
        weight=node.weight,
        owner_id=node.owner_id,
        actor_id=viewer.username,
        driver_id=viewer.username,
        scope_id=node.scope_id,
        parent_id=node.id,
        branch_type=body.branch_type,
    )
    branch, curation = await create_memory(
        data, db, _embedding_service(settings), tenant_id=settings.ui_tenant_id, skip_curation=False, force=True
    )
    if branch is None:
        raise HTTPException(status_code=409, detail=curation.get("detail") or "Blocked by a curation rule")
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="memory.write",
        scope=node.scope,
        owner_id=node.owner_id,
        memory_id=branch.id,
        metadata={"branch_type": body.branch_type, "parent": str(node.id)},
    )
    await db.commit()
    return {"id": str(branch.id)}


@router.post("/api/memory/{memory_id}/contradictions", status_code=201)
async def add_contradiction(
    memory_id: str, body: ContradictionRequest, request: Request, db: DbDep, settings: SettingsDep
):
    from memoryhub_core.services.memory import report_contradiction

    viewer = viewer_from_request(request, settings)
    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    await _writable(db, settings, viewer, node)
    count = await report_contradiction(node.id, body.observed_behavior, body.confidence, viewer.username, db)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="memory.contradiction_reported",
        scope=node.scope,
        owner_id=node.owner_id,
        memory_id=node.id,
        metadata={"confidence": body.confidence},
    )
    await db.commit()
    return {"unresolved": count}


async def _relate(db: AsyncSession, settings: Settings, viewer, source_id: str, target_id: str, rel_type: str) -> str:
    from memoryhub_core.models.schemas import RelationshipCreate
    from memoryhub_core.services.graph import create_relationship

    source = await _load_memory(db, settings.ui_tenant_id, source_id)
    target = await _load_memory(db, settings.ui_tenant_id, target_id)
    await _writable(db, settings, viewer, source)
    await _writable(db, settings, viewer, target)
    try:
        rel = await create_relationship(
            RelationshipCreate(
                source_id=source.id, target_id=target.id, relationship_type=rel_type, created_by=viewer.username
            ),
            db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Could not create relationship: {exc}") from None
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="memory.relationship_created",
        scope=source.scope,
        owner_id=source.owner_id,
        memory_id=source.id,
        metadata={"type": rel_type, "target": str(target.id)},
    )
    return str(rel.id)


@router.post("/api/relationships", status_code=201)
async def create_relationship_route(body: RelationshipRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    rel_id = await _relate(db, settings, viewer, body.source_id, body.target_id, body.relationship_type)
    await db.commit()
    return {"id": rel_id}


PROMOTION_ORDER = ["user", "project", "campaign", "role", "organizational", "enterprise"]


async def _propose_promotion(
    db: AsyncSession, settings: Settings, viewer, node: MemoryNode, target_scope: str, target_scope_id: str | None
) -> uuid.UUID:
    if target_scope not in PROMOTION_ORDER or node.scope not in PROMOTION_ORDER:
        raise HTTPException(status_code=422, detail=f"Cannot promote {node.scope} → {target_scope}")
    if PROMOTION_ORDER.index(target_scope) <= PROMOTION_ORDER.index(node.scope):
        raise HTTPException(status_code=422, detail="Promotion must move to a broader scope")
    if node.scope == "user" and node.owner_id != viewer.username:
        from src.me import load_prefs

        owner_prefs = await load_prefs(db, settings.ui_tenant_id, node.owner_id)
        if not owner_prefs["privacy"]["allow_promotion_by_others"]:
            raise HTTPException(
                status_code=403, detail=f"{node.owner_id} does not let others propose promoting their memories"
            )
    tenant_id = settings.ui_tenant_id
    new_id = uuid.uuid4()
    promoted = MemoryNode(
        id=new_id,
        logical_id=new_id,
        content=node.content,
        stub=node.stub,
        storage_type="inline",
        weight=node.weight,
        scope=target_scope,
        scope_id=target_scope_id,
        owner_id=target_scope_id or tenant_id,
        actor_id=viewer.username,
        driver_id=viewer.username,
        tenant_id=tenant_id,
        domains=node.domains,
        content_type=node.content_type,
        status="pending",
        source=node.source or "agent",
        is_current=True,
        version=1,
        embedding=node.embedding,
        metadata_={**(node.metadata_ or {}), "promoted_from": str(node.id), "proposed_by": viewer.username},
    )
    db.add(promoted)
    await db.flush()
    db.add(
        MemoryRelationship(
            source_id=new_id,
            target_id=node.id,
            relationship_type="derived_from",
            created_by=viewer.username,
            tenant_id=tenant_id,
        )
    )
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="review.promotion_proposed",
        scope=target_scope,
        owner_id=promoted.owner_id,
        memory_id=new_id,
        metadata={"source": str(node.id), "from_scope": node.scope},
    )
    return new_id


def _moderation_meta(viewer, node) -> dict:
    """Super-user actions on user memories carry the incident (#667 audit requirements)."""
    if not (viewer.is_superuser and node.scope == "user"):
        return {}
    from src.breakglass import _request

    grant = (_request.get() or {}).get("grant") or {}
    return {
        "break_glass": True,
        "privacy_invasive": True,
        "severity": "HIGH",
        "incident_ref": grant.get("incident_ref"),
        "grant_id": grant.get("id"),
    }


@router.post("/api/memories/bulk")
async def bulk_action(body: BulkRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    tenant_id = settings.ui_tenant_id
    done: list[str] = []
    errors: list[dict] = []
    forgotten: list[dict] = []
    for raw_id in body.ids:
        try:
            node = await _load_memory(db, tenant_id, raw_id)
            if body.action == "restore":
                from src.routes_workspace import restore_memory

                done.append((await restore_memory(db, settings, viewer, raw_id))["id"])
                continue
            if body.action in ("delete", "quarantine") and viewer.redacts_content:
                # #667: admins moderate the scopes they can read, never user memories without a grant.
                (await access_for(db, settings, viewer)).ensure_moderatable(node)
            else:
                await _writable(db, settings, viewer, node)
            if body.action == "quarantine":
                if node.status == "quarantined":
                    raise HTTPException(status_code=409, detail="Already quarantined")
                node.status = "quarantined"
                node.metadata_ = {
                    **(node.metadata_ or {}),
                    "quarantine_reason": body.reason or "Quarantined by a moderator",
                }
                await audit(
                    db,
                    tenant_id=tenant_id,
                    viewer=viewer,
                    event_type="admin.quarantine",
                    scope=node.scope,
                    owner_id=node.owner_id,
                    memory_id=node.id,
                    metadata={"reason": body.reason, **_moderation_meta(viewer, node)},
                )
                done.append(raw_id)
            elif body.action == "weight":
                if body.weight is None:
                    raise HTTPException(status_code=422, detail="weight is required")
                from memoryhub_core.models.schemas import MemoryNodeUpdate
                from memoryhub_core.services.memory import update_memory

                updated = await update_memory(
                    node.id,
                    MemoryNodeUpdate(weight=body.weight),
                    db,
                    _embedding_service(settings),
                    actor_id=viewer.username,
                    driver_id=viewer.username,
                )
                await audit(
                    db,
                    tenant_id=tenant_id,
                    viewer=viewer,
                    event_type="memory.update",
                    scope=node.scope,
                    owner_id=node.owner_id,
                    memory_id=updated.id,
                    metadata={"weight": body.weight},
                )
                done.append(str(updated.id))
            elif body.action == "delete":
                from src.routes import forget_memory

                forgotten.append(await forget_memory(raw_id, db, settings, viewer))
                await audit(
                    db,
                    tenant_id=tenant_id,
                    viewer=viewer,
                    event_type="memory.delete",
                    scope=node.scope,
                    owner_id=node.owner_id,
                    memory_id=node.id,
                    metadata=_moderation_meta(viewer, node) or None,
                )
                done.append(raw_id)
            elif body.action == "promote":
                new_id = await _propose_promotion(
                    db, settings, viewer, node, body.target_scope or "organizational", body.target_scope_id
                )
                done.append(str(new_id))
            elif body.action == "relate":
                if not body.target_id or not body.relationship_type:
                    raise HTTPException(status_code=422, detail="target_id and relationship_type are required")
                done.append(await _relate(db, settings, viewer, raw_id, body.target_id, body.relationship_type))
        except HTTPException as exc:
            errors.append({"id": raw_id, "detail": exc.detail})
    await db.commit()
    return {"done": done, "errors": errors, "forgotten": forgotten}


@router.post("/api/memory/{memory_id}/promote", status_code=201)
async def promote(
    memory_id: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    target_scope: str = Query(default="organizational"),
    target_scope_id: str | None = Query(default=None),
):
    viewer = viewer_from_request(request, settings)
    node = await _load_memory(db, settings.ui_tenant_id, memory_id)
    await _writable(db, settings, viewer, node)
    new_id = await _propose_promotion(db, settings, viewer, node, target_scope, target_scope_id)
    await db.commit()
    return {"id": str(new_id)}


# ---------------------------------------------------------------------------
# Graph neighbourhood (screen 04)
# ---------------------------------------------------------------------------


@router.get("/api/graph/neighbourhood")
async def graph_neighbourhood(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    focus: str | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=4),
    types: list[str] | None = Query(default=None),
    max_nodes: int = Query(default=120, ge=5, le=600),
):
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    visible = live_filters(tenant_id) + [MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity"] + acc.filters()

    if focus:
        focus_node = await _load_memory(db, tenant_id, focus)
        acc.ensure_readable(focus_node)
    else:
        # Default focus: the most connected current memory, else the newest one.
        degree = (
            select(MemoryRelationship.source_id.label("nid"))
            .where(MemoryRelationship.tenant_id == tenant_id, MemoryRelationship.valid_until.is_(None))
            .union_all(
                select(MemoryRelationship.target_id).where(
                    MemoryRelationship.tenant_id == tenant_id, MemoryRelationship.valid_until.is_(None)
                )
            )
            .subquery()
        )
        row = (
            (
                await db.execute(
                    select(MemoryNode)
                    .join(degree, degree.c.nid == MemoryNode.id)
                    .where(*visible)
                    .group_by(MemoryNode.id)
                    .order_by(func.count().desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            row = (
                (await db.execute(select(MemoryNode).where(*visible).order_by(MemoryNode.updated_at.desc()).limit(1)))
                .scalars()
                .first()
            )
        if row is None:
            return {
                "focus": None,
                "nodes": [],
                "edges": [],
                "hidden_count": 0,
                "cut_count": 0,
                "max_nodes": max_nodes,
                "provenance": [],
                "conflicts": [],
            }
        focus_node = row

    rel_types = types or None
    nodes: dict[uuid.UUID, MemoryNode] = {focus_node.id: focus_node}
    node_depth: dict[uuid.UUID, int] = {focus_node.id: 0}
    edges: dict[str, dict] = {}
    hidden: set[uuid.UUID] = set()
    cut: set[uuid.UUID] = set()
    frontier = {focus_node.id}
    for level in range(1, depth + 1):
        if not frontier or len(nodes) >= max_nodes:
            break
        rel_stmt = select(MemoryRelationship).where(
            MemoryRelationship.tenant_id == tenant_id,
            MemoryRelationship.valid_until.is_(None),
            or_(MemoryRelationship.source_id.in_(frontier), MemoryRelationship.target_id.in_(frontier)),
        )
        if rel_types:
            rel_stmt = rel_stmt.where(MemoryRelationship.relationship_type.in_(rel_types))
        rels = (await db.execute(rel_stmt)).scalars().all()
        neighbour_ids = {r.target_id for r in rels} | {r.source_id for r in rels}
        neighbour_ids -= set(nodes)
        found = {}
        if neighbour_ids:
            found = {
                n.id: n
                for n in (await db.execute(select(MemoryNode).where(MemoryNode.id.in_(list(neighbour_ids)))))
                .scalars()
                .all()
            }
        next_frontier = set()
        for nid in neighbour_ids:
            n = found.get(nid)
            if n is None or n.tenant_id != tenant_id or n.deleted_at is not None or not acc.can_read_row(n):
                hidden.add(nid)
                continue
            if n.scope == "entity":
                continue
            if len(nodes) >= max_nodes:
                cut.add(nid)
                continue
            nodes[nid] = n
            node_depth[nid] = level
            next_frontier.add(nid)
        for r in rels:
            if r.source_id in nodes and r.target_id in nodes:
                edges[str(r.id)] = {
                    "id": str(r.id),
                    "source": str(r.source_id),
                    "target": str(r.target_id),
                    "type": r.relationship_type,
                }
        frontier = next_frontier

    # Provenance chain: follow derived_from from the focus.
    provenance = [_node_brief(focus_node)]
    cursor = focus_node.id
    seen = {cursor}
    for _ in range(6):
        nxt = (
            (
                await db.execute(
                    select(MemoryNode)
                    .join(MemoryRelationship, MemoryRelationship.target_id == MemoryNode.id)
                    .where(
                        MemoryRelationship.source_id == cursor,
                        MemoryRelationship.relationship_type == "derived_from",
                        MemoryRelationship.valid_until.is_(None),
                        MemoryNode.tenant_id == tenant_id,
                        MemoryNode.deleted_at.is_(None),
                    )
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if nxt is None or nxt.id in seen or not acc.can_read_row(nxt):
            break
        provenance.append(_node_brief(nxt))
        seen.add(nxt.id)
        cursor = nxt.id
    provenance.reverse()

    conflicts = []
    for e in edges.values():
        if e["type"] == "conflicts_with" and str(focus_node.id) in (e["source"], e["target"]):
            other_id = uuid.UUID(e["target"] if e["source"] == str(focus_node.id) else e["source"])
            if other_id in nodes:
                conflicts.append(_node_brief(nodes[other_id]))

    focus_degree = sum(1 for e in edges.values() if str(focus_node.id) in (e["source"], e["target"]))
    focus_hidden = (
        await db.execute(
            select(func.count())
            .select_from(MemoryRelationship)
            .outerjoin(
                MemoryNode,
                MemoryNode.id
                == case(
                    (MemoryRelationship.source_id == focus_node.id, MemoryRelationship.target_id),
                    else_=MemoryRelationship.source_id,
                ),
            )
            .where(
                MemoryRelationship.tenant_id == tenant_id,
                MemoryRelationship.valid_until.is_(None),
                or_(MemoryRelationship.source_id == focus_node.id, MemoryRelationship.target_id == focus_node.id),
                or_(MemoryNode.id.is_(None), MemoryNode.deleted_at.is_not(None), MemoryNode.tenant_id != tenant_id),
            )
        )
    ).scalar_one()

    return acc.redact_tree(
        {
            "focus": {
                **_node_brief(focus_node),
                "content": focus_node.content,
                "degree": focus_degree,
                "hidden_degree": focus_hidden,
            },
            "nodes": [{**_node_brief(n), "depth": node_depth[n.id]} for n in nodes.values()],
            "edges": list(edges.values()),
            "hidden_count": len(hidden),
            "cut_count": len(cut),
            "max_nodes": max_nodes,
            "provenance": provenance if len(provenance) > 1 else [],
            "conflicts": conflicts,
        }
    )


GRAPH_MAX_NODES = 1500


@router.get("/api/graph/all")
async def graph_all(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    types: list[str] | None = Query(default=None),
    include_superseded: bool = Query(default=False),
    max_nodes: int = Query(default=300, ge=10, le=GRAPH_MAX_NODES),
    scope: list[str] | None = Query(default=None),
    min_weight: float = Query(default=0, ge=0, le=1),
    project: str | None = Query(default=None, max_length=255),
    entity: str | None = Query(default=None),
    prefer: str = Query(default="connected", pattern="^(connected|recent|weight)$"),
):
    """Every readable memory and the links between them, connected or not.

    Powers the graph's "All memories" focus: separate clusters and memories
    with no relationships at all are returned too (``degree`` 0).

    When there are more memories than ``max_nodes``, ``prefer`` decides which
    ones are kept: ``connected`` (default) keeps the most linked memories so
    clusters stay whole, ``recent`` the newest, ``weight`` the strongest. The
    response says how many matched, how many were left out and how many links
    point outside the drawn set.
    """
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    filters = (
        live_filters(tenant_id, current=not include_superseded)
        + [
            MemoryNode.parent_id.is_(None),
            MemoryNode.scope != "entity",
            MemoryNode.status != "quarantined",
        ]
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
        filters.append(
            exists().where(
                MemoryRelationship.source_id == MemoryNode.id,
                MemoryRelationship.target_id == parse_uuid(entity, "entity ID"),
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
            )
        )
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one()
    stmt = select(MemoryNode).where(*filters)
    if prefer == "connected" and total > max_nodes:
        links = (
            select(func.count())
            .select_from(MemoryRelationship)
            .where(
                MemoryRelationship.tenant_id == tenant_id,
                MemoryRelationship.valid_until.is_(None),
                MemoryRelationship.relationship_type != "mentions",
                or_(MemoryRelationship.source_id == MemoryNode.id, MemoryRelationship.target_id == MemoryNode.id),
            )
            .correlate(MemoryNode)
            .scalar_subquery()
        )
        stmt = stmt.order_by(links.desc(), MemoryNode.updated_at.desc())
    elif prefer == "weight":
        stmt = stmt.order_by(MemoryNode.weight.desc(), MemoryNode.updated_at.desc())
    else:
        stmt = stmt.order_by(MemoryNode.updated_at.desc())
    nodes = (await db.execute(stmt.limit(max_nodes))).scalars().all()
    ids = [n.id for n in nodes]
    edges: list[dict] = []
    hidden_links = 0
    if ids:
        rel_stmt = select(MemoryRelationship).where(
            MemoryRelationship.tenant_id == tenant_id,
            MemoryRelationship.valid_until.is_(None),
            MemoryRelationship.relationship_type != "mentions",
            or_(MemoryRelationship.source_id.in_(ids), MemoryRelationship.target_id.in_(ids)),
        )
        if types:
            rel_stmt = rel_stmt.where(MemoryRelationship.relationship_type.in_(types))
        id_set = set(ids)
        for r in (await db.execute(rel_stmt)).scalars().all():
            if r.source_id in id_set and r.target_id in id_set:
                edges.append(
                    {
                        "id": str(r.id),
                        "source": str(r.source_id),
                        "target": str(r.target_id),
                        "type": r.relationship_type,
                    }
                )
            else:
                hidden_links += 1
    degree: Counter = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    out_nodes = [{**_node_brief(n), "depth": 0, "degree": degree.get(str(n.id), 0)} for n in nodes]
    return acc.redact_tree(
        {
            "nodes": out_nodes,
            "edges": edges,
            "total": total,
            "truncated": total > len(nodes),
            "left_out": max(0, total - len(nodes)),
            "max_nodes": max_nodes,
            "limit_ceiling": GRAPH_MAX_NODES,
            "prefer": prefer,
            "orphan_count": sum(1 for n in out_nodes if n["degree"] == 0),
            "hidden_links": hidden_links,
            "metadata_only": viewer.redacts_content,
        }
    )


# ---------------------------------------------------------------------------
# Search playground (screen 05)
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    focus: str | None = Field(default=None, max_length=2000)
    identity: str | None = Field(default=None, max_length=255)
    project: str | None = Field(default=None, max_length=255)
    mode: str = Field(default="full", pattern="^(full|index|full_only)$")
    max_results: int = Field(default=10, ge=1, le=50)
    session_focus_weight: float = Field(default=0.4, ge=0, le=1)
    weight_threshold: float = Field(default=0.0, ge=0, le=1)
    max_response_tokens: int = Field(default=4000, ge=100, le=100_000)
    current_only: bool = True
    include_branches: bool = False
    rerank: bool = True
    # "Why didn't X come back?" — memory IDs to trace through the pipeline.
    explain: list[str] = Field(default_factory=list, max_length=10)


async def _visible_predicate(db: AsyncSession, tenant_id: str, identity: str | None, project: str | None):
    """Python predicate reproducing the MCP read RBAC for one identity.

    Returns (predicate, description). Organizational and enterprise memories
    are tenant-wide; user memories need ownership; project, role and campaign
    memories need a membership.
    """
    if not identity:
        return (lambda n: True), "dashboard (admin)"
    projects = set(
        (await db.execute(select(ProjectMembership.project_id).where(ProjectMembership.user_id == identity)))
        .scalars()
        .all()
    )
    if project and project not in projects:
        # Open projects enroll an agent on first use, so the declared project
        # context is readable; invite-only projects still need a membership.
        from memoryhub_core.models.project import Project

        invite_only = (
            await db.execute(select(Project.invite_only).where(Project.name == project, Project.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if invite_only is False:
            projects.add(project)
    roles = set(
        (
            await db.execute(
                select(RoleAssignment.role_name).where(
                    RoleAssignment.user_id == identity, RoleAssignment.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    campaigns = set()
    if projects:
        campaigns = {
            str(c)
            for c in (
                await db.execute(
                    select(CampaignMembership.campaign_id).where(CampaignMembership.project_id.in_(list(projects)))
                )
            )
            .scalars()
            .all()
        }

    def visible(n: MemoryNode) -> bool:
        if n.scope in ("organizational", "enterprise"):
            return True
        if n.scope == "user":
            return n.owner_id == identity
        if n.scope == "project":
            return (n.scope_id or n.owner_id) in projects
        if n.scope == "role":
            return (n.scope_id or n.owner_id) in roles
        if n.scope == "campaign":
            return (n.scope_id or n.owner_id) in campaigns
        return False

    return visible, identity


@router.post("/api/search")
async def search_playground(body: SearchRequest, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    """Run search exactly as an agent would, with the funnel and drop reasons."""
    from src.retrieval import run_search

    return await run_search(db, settings, viewer, body, explain_ids=body.explain, source="playground")


# ---------------------------------------------------------------------------
# Utilities shared with routes_admin
# ---------------------------------------------------------------------------


def stub_for(text_value: str) -> str:
    text_value = re.sub(r"\s+", " ", text_value or "").strip()
    return text_value if len(text_value) <= 120 else text_value[:119] + "…"


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}
