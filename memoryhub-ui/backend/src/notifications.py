"""The bell in the masthead: what needs the viewer's attention.

Users hear about their own memories: break-glass access by an admin,
contradictions reported against them, other agents reading them, and new
Dreaming suggestions. Platform admins hear about the review queue — never
anything that names what a memory says.

Notifications are derived from the audit log and existing tables at read
time; only the "seen up to" time per viewer is stored.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import clean_stub, load_tenant_settings, now_utc

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

SEEN = "memoryhub_ui_notifications_seen"
WINDOW_DAYS = 14


async def _ensure(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


async def _user_items(db: AsyncSession, settings: Settings, viewer, mine: list[str]) -> list[dict]:
    tenant_id = settings.ui_tenant_id
    since = now_utc() - timedelta(days=WINDOW_DAYS)
    items: list[dict] = []
    owned = and_(
        MemoryNode.id == AuditLog.memory_id,
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.scope == "user",
        MemoryNode.owner_id.in_(mine),
    )

    # Super-user reads under an incident grant (#667), unless the tenant turned owner notices off.
    privacy = (await load_tenant_settings(db, tenant_id)).get("privacy", {})
    break_glass_events = (
        []
        if privacy.get("notify_owner", True) is False
        else (
            await db.execute(
                select(AuditLog, MemoryNode)
                .join(MemoryNode, owned)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.timestamp >= since,
                    AuditLog.event_metadata["break_glass"].as_boolean().is_(True),
                )
                .order_by(AuditLog.timestamp.desc())
                .limit(10)
            )
        ).all()
    )
    for event, node in break_glass_events:
        incident = (event.event_metadata or {}).get("incident_ref")
        items.append(
            {
                "id": f"bg:{event.id}",
                "kind": "break_glass",
                "severity": "danger",
                "title": f"{event.actor_id} opened one of your memories for incident {incident}"
                if incident
                else f"{event.actor_id} opened one of your memories with break-glass access",
                "body": clean_stub(node.stub),
                "at": event.timestamp,
                "href": "/reads",
            }
        )

    # Contradictions reported on memories you own.
    for report, node in (
        await db.execute(
            select(ContradictionReport, MemoryNode)
            .join(MemoryNode, MemoryNode.id == ContradictionReport.memory_id)
            .where(
                ContradictionReport.tenant_id == tenant_id,
                ContradictionReport.resolved.is_(False),
                ContradictionReport.created_at >= since,
                MemoryNode.owner_id.in_(mine),
            )
            .order_by(ContradictionReport.created_at.desc())
            .limit(10)
        )
    ).all():
        items.append(
            {
                "id": f"ct:{report.id}",
                "kind": "contradiction",
                "severity": "warning",
                "title": f"{report.reporter or 'An agent'} reported a contradiction",
                "body": clean_stub(node.stub),
                "at": report.created_at,
                "href": f"/memory/{node.id}",
            }
        )

    # Reads by others in the last day, as one line.
    day = now_utc() - timedelta(days=1)
    others, last = (
        await db.execute(
            select(func.count(), func.max(AuditLog.timestamp))
            .select_from(AuditLog)
            .join(MemoryNode, owned)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.timestamp >= day, AuditLog.actor_id.not_in(mine))
        )
    ).one()
    if others:
        items.append(
            {
                "id": f"rd:{last.date().isoformat() if last else ''}",
                "kind": "reads",
                "severity": "info",
                "title": f"Other agents used your memories {others} time{'s' if others != 1 else ''} today",
                "body": "See who and which memories.",
                "at": last,
                "href": "/reads",
            }
        )

    # Memory hygiene suggestions still waiting (MemoryHub Labs).
    from src.config import get_settings
    from src.dreaming import DREAMS, ensure_tables

    if not get_settings().ui_labs:
        return items

    await ensure_tables(db)
    row = (
        await db.execute(
            text(
                f"SELECT id, started_at, trigger, report FROM {DREAMS} WHERE tenant_id = :t AND owner = :o "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"t": tenant_id, "o": viewer.username},
        )
    ).first()
    if row:
        report = row[3] if not isinstance(row[3], str) else json.loads(row[3])
        waiting = sum(1 for i in report.get("insights", []) if i.get("status") == "proposed")
        if waiting:
            items.append(
                {
                    "id": f"dr:{row[0]}",
                    "kind": "dream",
                    "severity": "info",
                    "title": f"Memory hygiene has {waiting} suggestion{'s' if waiting != 1 else ''} for you",
                    "body": "Scheduled run" if row[2] == "scheduled" else "From your last run",
                    "at": row[1],
                    "href": "/dreaming",
                }
            )
    return items


async def _admin_items(db: AsyncSession, settings: Settings) -> list[dict]:
    from src.routes_dashboard import _review_counts

    tenant_settings = await load_tenant_settings(db, settings.ui_tenant_id)
    queue = await _review_counts(
        db, settings.ui_tenant_id, int(tenant_settings["governance"]["contradiction_threshold"])
    )
    labels = {
        "approvals": "enterprise memories waiting for approval",
        "promotions": "promotion proposals",
        "contradictions": "contradictions over the threshold",
        "quarantine": "quarantined writes",
    }
    newest = (
        await db.execute(select(func.max(MemoryNode.updated_at)).where(MemoryNode.tenant_id == settings.ui_tenant_id))
    ).scalar()
    return [
        {
            "id": f"rq:{key}:{count}",
            "kind": "review",
            "severity": "warning" if key in ("quarantine", "contradictions") else "info",
            "title": f"{count} {labels.get(key, key.replace('_', ' '))}",
            "body": "In the review queue",
            "at": newest or now_utc(),
            "href": "/review",
        }
        for key, count in queue.items()
        if count
    ]


@router.get("/api/notifications")
async def notifications(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    await _ensure(db)
    if viewer.redacts_content:
        items = await _admin_items(db, settings)
    else:
        acc = await access_for(db, settings, viewer)
        mine = sorted(acc.grants.identities) if acc.grants else [viewer.username]
        items = await _user_items(db, settings, viewer, mine)
    items.sort(key=lambda i: i["at"] or now_utc(), reverse=True)
    seen = (
        await db.execute(
            text(f"SELECT seen_at FROM {SEEN} WHERE tenant_id = :t AND username = :u"),
            {"t": settings.ui_tenant_id, "u": viewer.username},
        )
    ).scalar()
    for item in items:
        item["unread"] = seen is None or (item["at"] is not None and item["at"] > seen)
    return {"items": items[:20], "unread": sum(1 for i in items if i["unread"]), "seen_at": seen}


@router.post("/api/notifications/seen")
async def mark_seen(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    await _ensure(db)
    await db.execute(
        text(
            f"""
            INSERT INTO {SEEN} (tenant_id, username, seen_at) VALUES (:t, :u, now())
            ON CONFLICT (tenant_id, username) DO UPDATE SET seen_at = now()
            """
        ),
        {"t": settings.ui_tenant_id, "u": viewer.username},
    )
    await db.commit()
    return {"ok": True}
