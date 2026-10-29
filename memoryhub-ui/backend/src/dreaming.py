"""Dreaming: an offline pass over a user's memories, like sleep for the hub.

A dream reads the memories the user can read and proposes housekeeping the
user approves one by one (or lets run automatically for the safe kinds):

* **duplicates** — near-identical memories (cosine ≥ 0.92): keep the newer,
  link it ``supersedes`` the older and fade the older one;
* **connections** — related memories that are not linked yet (0.78–0.92):
  add a ``related_to`` edge;
* **fading** — weighty memories nobody has read or changed for 60 days:
  lower their weight so they stop crowding retrieval;
* **contradictions** — memories with open contradiction reports: review;
* **themes** — clusters of recent memories sharing a domain tag: write one
  consolidated memory (prefilled draft) instead of many small ones.

Runs on demand ("Dream now") and on the stored schedule (see ``src.scheduler``).
Tables: ``memoryhub_ui_dreams`` (one row per run, report as JSON) and
``memoryhub_ui_dream_settings`` (per user).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ContentDep, LabsDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import audit, clean_stub, live_filters, now_utc

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[LabsDep])

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

DREAMS = "memoryhub_ui_dreams"
SETTINGS = "memoryhub_ui_dream_settings"
DUP = 0.92
LINK = 0.78
STALE_DAYS = 60
DEFAULT_SETTINGS = {
    "schedule": "nightly",  # nightly | weekly | off
    "window": "02:00",
    "auto": {"connections": False, "fading": False},
    "kinds": {"duplicates": True, "connections": True, "fading": True, "contradictions": True, "themes": True},
}


async def ensure_tables(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _brief(n: MemoryNode) -> dict:
    return {
        "id": str(n.id),
        "stub": clean_stub(n.stub),
        "scope": n.scope,
        "owner_id": n.owner_id,
        "weight": n.weight,
        "version": n.version,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


async def _load_settings(db: AsyncSession, tenant_id: str, owner: str) -> dict:
    await ensure_tables(db)
    row = (
        await db.execute(
            text(f"SELECT settings FROM {SETTINGS} WHERE tenant_id = :t AND owner = :o"), {"t": tenant_id, "o": owner}
        )
    ).first()
    stored = row[0] if row else {}
    if isinstance(stored, str):
        stored = json.loads(stored)
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update({k: v for k, v in value.items() if k in merged[key]})
        elif key in merged:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# The dream itself
# ---------------------------------------------------------------------------


async def _pairs(db: AsyncSession, tenant_id: str, ids: list[uuid.UUID], low: float, high: float, limit: int):
    """Most similar other readable memory for each memory, within [low, high)."""
    if not ids:
        return []
    try:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT m.id, nn.id, nn.score
                    FROM memory_nodes m
                    CROSS JOIN LATERAL (
                      SELECT o.id, 1 - (o.embedding <=> m.embedding) AS score
                      FROM memory_nodes o
                      WHERE o.id = ANY(:ids) AND o.id <> m.id AND o.embedding IS NOT NULL
                      ORDER BY o.embedding <=> m.embedding
                      LIMIT 3
                    ) nn
                    WHERE m.id = ANY(:ids) AND m.embedding IS NOT NULL AND m.tenant_id = :t
                    """
                ),
                {"ids": ids, "t": tenant_id},
            )
        ).all()
    except Exception as exc:  # pragma: no cover - needs pgvector
        logger.info("Dream similarity pass unavailable: %s", exc)
        await db.rollback()
        return []
    seen: set[frozenset] = set()
    out = []
    for a, b, score in sorted(rows, key=lambda r: -float(r[2] or 0)):
        if score is None or not (low <= float(score) < high):
            continue
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        out.append((a, b, float(score)))
        if len(out) >= limit:
            break
    return out


async def dream(db: AsyncSession, settings: Settings, viewer, prefs: dict) -> dict:
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    base = (
        live_filters(tenant_id)
        + [
            MemoryNode.parent_id.is_(None),
            MemoryNode.scope != "entity",
            MemoryNode.status != "quarantined",
        ]
        + acc.filters()
    )
    nodes = (
        (await db.execute(select(MemoryNode).where(*base).order_by(MemoryNode.updated_at.desc()).limit(500)))
        .scalars()
        .all()
    )
    by_id = {n.id: n for n in nodes}
    ids = list(by_id)
    kinds = prefs["kinds"]
    insights: list[dict] = []

    def add(
        kind: str, title: str, detail: str, memories: list[MemoryNode], action: dict, confidence: float | None = None
    ):
        insights.append(
            {
                "id": f"{kind}-{len(insights) + 1}",
                "kind": kind,
                "title": title,
                "detail": detail,
                "memories": [_brief(m) for m in memories],
                "action": action,
                "confidence": round(confidence, 3) if confidence is not None else None,
                "status": "proposed",
            }
        )

    linked: set[frozenset] = set()
    if ids:
        for s, t in (
            await db.execute(
                select(MemoryRelationship.source_id, MemoryRelationship.target_id).where(
                    MemoryRelationship.tenant_id == tenant_id,
                    MemoryRelationship.valid_until.is_(None),
                    or_(MemoryRelationship.source_id.in_(ids), MemoryRelationship.target_id.in_(ids)),
                )
            )
        ).all():
            linked.add(frozenset((s, t)))

    if kinds.get("duplicates", True):
        for a, b, score in await _pairs(db, tenant_id, ids, DUP, 1.01, 10):
            if frozenset((a, b)) in linked:
                continue
            na, nb = by_id[a], by_id[b]
            newer, older = (
                (na, nb) if (na.updated_at or na.created_at) >= (nb.updated_at or nb.created_at) else (nb, na)
            )
            add(
                "duplicates",
                "These say the same thing",
                f"{round(score * 100)}% similar. Keep the newer one, link it as superseding the older, fade the older.",
                [newer, older],
                {"type": "merge", "keep": str(newer.id), "fade": str(older.id)},
                score,
            )
    if kinds.get("connections", True):
        for a, b, score in await _pairs(db, tenant_id, ids, LINK, DUP, 12):
            if frozenset((a, b)) in linked:
                continue
            add(
                "connections",
                "Related but not linked",
                f"{round(score * 100)}% similar and no relationship yet. Link them so agents retrieve them together.",
                [by_id[a], by_id[b]],
                {"type": "link", "source": str(a), "target": str(b), "relationship": "related_to"},
                score,
            )
    if kinds.get("fading", True) and ids:
        since = now_utc() - timedelta(days=STALE_DAYS)
        read = set(
            (
                await db.execute(
                    select(AuditLog.memory_id)
                    .where(AuditLog.tenant_id == tenant_id, AuditLog.memory_id.in_(ids), AuditLog.timestamp >= since)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        stale = [n for n in nodes if n.weight >= 0.5 and (n.updated_at or n.created_at) < since and n.id not in read]
        for n in sorted(stale, key=lambda x: -x.weight)[:10]:
            target = round(max(0.1, n.weight - 0.2), 2)
            add(
                "fading",
                "Not used in two months",
                f"Nobody read or changed it in {STALE_DAYS}+ days. Lower its weight {n.weight:.2f} → {target:.2f}.",
                [n],
                {"type": "fade", "memory": str(n.id), "weight": target},
            )
    if kinds.get("contradictions", True) and ids:
        rows = (
            await db.execute(
                select(ContradictionReport.memory_id, func.count())
                .where(
                    ContradictionReport.memory_id.in_(ids),
                    ContradictionReport.tenant_id == tenant_id,
                    ContradictionReport.resolved.is_(False),
                )
                .group_by(ContradictionReport.memory_id)
                .order_by(func.count().desc())
                .limit(8)
            )
        ).all()
        for memory_id, count in rows:
            add(
                "contradictions",
                "Agents disagree with this",
                f"{count} open contradiction report(s). Check whether it is still true.",
                [by_id[memory_id]],
                {"type": "review", "memory": str(memory_id)},
            )
    if kinds.get("themes", True):
        recent = now_utc() - timedelta(days=30)
        groups: dict[str, list[MemoryNode]] = defaultdict(list)
        for n in nodes:
            if (n.updated_at or n.created_at) >= recent:
                for d in n.domains or []:
                    groups[d].append(n)
        for domain, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:4]:
            if len(members) < 3:
                continue
            draft = f"{domain}: " + "; ".join(clean_stub(m.stub) for m in members[:8])
            add(
                "themes",
                f"{len(members)} recent memories about {domain}",
                "Consolidate them into one memory that agents load first; the originals stay as provenance.",
                members[:8],
                {
                    "type": "consolidate",
                    "domain": domain,
                    "draft": draft[:1800],
                    "sources": [str(m.id) for m in members[:8]],
                },
            )

    counts = defaultdict(int)
    for i in insights:
        counts[i["kind"]] += 1
    return {"reviewed": len(nodes), "insights": insights, "counts": dict(counts)}


async def _apply(db: AsyncSession, settings: Settings, viewer, action: dict) -> str:
    from src.routes_dashboard import _embedding_service, _load_memory, _relate, _writable

    if action["type"] == "link":
        await _relate(
            db, settings, viewer, action["source"], action["target"], action.get("relationship", "related_to")
        )
        return "Linked."
    if action["type"] in ("merge", "fade"):
        from memoryhub_core.models.schemas import MemoryNodeUpdate
        from memoryhub_core.services.memory import update_memory

        target_id = action["fade"] if action["type"] == "merge" else action["memory"]
        if action["type"] == "merge":
            await _relate(db, settings, viewer, action["keep"], action["fade"], "supersedes")
        node = await _load_memory(db, settings.ui_tenant_id, target_id)
        await _writable(db, settings, viewer, node)
        weight = float(action.get("weight", 0.2 if action["type"] == "merge" else max(0.1, node.weight - 0.2)))
        await update_memory(
            node.id,
            MemoryNodeUpdate(weight=weight),
            db,
            _embedding_service(settings),
            actor_id=viewer.username,
            driver_id=viewer.username,
        )
        return "Merged." if action["type"] == "merge" else f"Weight lowered to {weight:.2f}."
    return "Noted."


# ---------------------------------------------------------------------------
# Endpoints (users only: dreaming reads content)
# ---------------------------------------------------------------------------


def _row(r: Any) -> dict:
    report = r[4] if not isinstance(r[4], str) else json.loads(r[4])
    return {"id": str(r[0]), "started_at": r[1], "duration_ms": r[2], "trigger": r[3], **report}


@router.get("/api/dreams")
async def dreams(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    prefs = await _load_settings(db, settings.ui_tenant_id, viewer.username)
    rows = (
        await db.execute(
            text(
                f"SELECT id, started_at, duration_ms, trigger, report FROM {DREAMS} "
                "WHERE tenant_id = :t AND owner = :o ORDER BY started_at DESC LIMIT 12"
            ),
            {"t": settings.ui_tenant_id, "o": viewer.username},
        )
    ).all()
    history = [_row(r) for r in rows]
    return {
        "settings": prefs,
        "last": history[0] if history else None,
        "history": [
            {k: h[k] for k in ("id", "started_at", "duration_ms", "trigger", "reviewed", "counts")}
            | {
                "accepted": sum(1 for i in h["insights"] if i["status"] == "accepted"),
                "dismissed": sum(1 for i in h["insights"] if i["status"] == "dismissed"),
                "total": len(h["insights"]),
            }
            for h in history
        ],
    }


@router.post("/api/dreams/run", status_code=201)
async def run_dream(
    db: DbDep,
    settings: SettingsDep,
    viewer: ContentDep,
    trigger: str = Query(default="manual", pattern="^(manual|scheduled)$"),
):
    from src.jobs import run_job

    async def work():
        report = await run_for(db, settings, viewer, trigger)
        return {"dream_id": report["id"], "insights": len(report["insights"]), "_value": report}

    return await run_job(settings, kind="dream", owner=viewer.username, work=work, trigger=trigger)


async def run_for(db: AsyncSession, settings: Settings, viewer, trigger: str) -> dict:
    """One dream for one viewer; the endpoint and the background scheduler share it."""
    prefs = await _load_settings(db, settings.ui_tenant_id, viewer.username)
    started = time.perf_counter()
    report = await dream(db, settings, viewer, prefs)
    # Safe kinds the user let run on their own.
    for insight in report["insights"]:
        if prefs["auto"].get(insight["kind"]) and insight["action"]["type"] in ("link", "fade"):
            try:
                insight["result"] = await _apply(db, settings, viewer, insight["action"])
                insight["status"] = "accepted"
                insight["auto"] = True
            except HTTPException as exc:
                insight["result"] = exc.detail
    dream_id = uuid.uuid4()
    duration = int((time.perf_counter() - started) * 1000)
    await db.execute(
        text(
            f"INSERT INTO {DREAMS} (id, tenant_id, owner, duration_ms, trigger, report) "
            "VALUES (:id, :t, :o, :d, :tr, CAST(:r AS JSONB))"
        ),
        {
            "id": dream_id,
            "t": settings.ui_tenant_id,
            "o": viewer.username,
            "d": duration,
            "tr": trigger,
            "r": json.dumps(report),
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="dream.run",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"reviewed": report["reviewed"], "counts": report["counts"]},
    )
    await db.commit()
    return {"id": str(dream_id), "duration_ms": duration, "trigger": trigger, "started_at": now_utc(), **report}


class DreamSettings(BaseModel):
    schedule: str | None = Field(default=None, pattern="^(nightly|weekly|off)$")
    window: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    auto: dict[str, bool] | None = None
    kinds: dict[str, bool] | None = None


@router.put("/api/dreams/settings")
async def save_dream_settings(body: DreamSettings, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    prefs = await _load_settings(db, settings.ui_tenant_id, viewer.username)
    for key, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, dict):
            prefs[key].update({k: bool(v) for k, v in value.items() if k in prefs[key]})
        else:
            prefs[key] = value
    await db.execute(
        text(
            f"""
            INSERT INTO {SETTINGS} (tenant_id, owner, settings) VALUES (:t, :o, CAST(:s AS JSONB))
            ON CONFLICT (tenant_id, owner) DO UPDATE SET settings = EXCLUDED.settings
            """
        ),
        {"t": settings.ui_tenant_id, "o": viewer.username, "s": json.dumps(prefs)},
    )
    await db.commit()
    return prefs


class Decision(BaseModel):
    decision: str = Field(pattern="^(accept|dismiss)$")


@router.post("/api/dreams/{dream_id}/insights/{insight_id}")
async def decide(
    dream_id: str,
    insight_id: str,
    body: Decision,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    viewer: ContentDep,
):
    await ensure_tables(db)
    try:
        parsed = uuid.UUID(dream_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid dream ID") from exc
    row = (
        await db.execute(
            text(f"SELECT id, started_at, duration_ms, trigger, report FROM {DREAMS} WHERE id = :id AND owner = :o"),
            {"id": parsed, "o": viewer.username},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dream not found")
    report = row[4] if not isinstance(row[4], str) else json.loads(row[4])
    insight = next((i for i in report["insights"] if i["id"] == insight_id), None)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    if insight["status"] != "proposed":
        raise HTTPException(status_code=409, detail=f"Already {insight['status']}")
    if body.decision == "accept":
        insight["result"] = await _apply(db, settings, viewer, insight["action"])
        insight["status"] = "accepted"
    else:
        insight["status"] = "dismissed"
    await db.execute(
        text(f"UPDATE {DREAMS} SET report = CAST(:r AS JSONB) WHERE id = :id"), {"r": json.dumps(report), "id": parsed}
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type=f"dream.{body.decision}",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"insight": insight_id, "kind": insight["kind"]},
    )
    await db.commit()
    return insight
