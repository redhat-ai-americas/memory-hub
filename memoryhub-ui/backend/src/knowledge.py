"""Knowledge pages: a living summary of what memory says about one subject.

A page is built from the memories the viewer can read about a subject (the
viewer themself, or a project). It is deterministic — no LLM — so every line
on the page cites the memories it came from:

* facts grouped into sections by domain tag, near-duplicates folded together;
* the people, organisations and things those memories mention;
* what changed recently and since the previous version of the page;
* open questions — unresolved contradictions — and facts that went stale.

Pages are stored per viewer (two people with different access get different
pages) and rebuild themselves whenever their source memories change: on open,
and by the background scheduler. Platform admins never get a page; it is
memory content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import Access, ContentDep, LabsDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, clean_stub, live_filters, now_utc, preview

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[LabsDep])

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TABLE = "memoryhub_ui_knowledge"
MAX_SOURCES = 400
SAME_FACT = 0.92
RECENT_DAYS = 14
GENERAL = "General"


async def _ensure(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


def _subject_filters(acc: Access, viewer: Viewer, kind: str, sid: str) -> list:
    if kind == "me":
        mine = sorted(acc.grants.identities) if acc.grants else [viewer.username]
        return [MemoryNode.scope == "user", MemoryNode.owner_id.in_(mine)]
    if kind == "project":
        if acc.grants is not None and sid not in acc.grants.projects:
            raise HTTPException(status_code=404, detail="Project not found")
        return [
            or_(
                (MemoryNode.scope == "project") & (MemoryNode.scope_id == sid),
                MemoryNode.metadata_["project"].as_string() == sid,
            )
        ]
    raise HTTPException(status_code=404, detail="Unknown knowledge subject")


def _base(settings: Settings, acc: Access) -> list:
    return (
        live_filters(settings.ui_tenant_id)
        + [MemoryNode.parent_id.is_(None), MemoryNode.scope != "entity", MemoryNode.status != "quarantined"]
        + acc.filters()
    )


async def _projects(db: AsyncSession, settings: Settings, acc: Access) -> list[str]:
    if acc.grants is not None:
        return sorted(acc.grants.projects)
    rows = (
        await db.execute(
            select(func.distinct(MemoryNode.scope_id)).where(
                *live_filters(settings.ui_tenant_id), MemoryNode.scope == "project", MemoryNode.scope_id.is_not(None)
            )
        )
    ).all()
    return sorted(r[0] for r in rows if r[0])


async def _fingerprint(db: AsyncSession, filters: list) -> tuple[int, str]:
    """Cheap change detector: number of sources and their latest change."""
    count, latest, versions = (
        await db.execute(
            select(func.count(), func.max(MemoryNode.updated_at), func.coalesce(func.sum(MemoryNode.version), 0)).where(
                *filters
            )
        )
    ).one()
    raw = f"{count}|{latest.isoformat() if latest else '-'}|{versions}"
    return int(count), hashlib.sha1(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Building a page
# ---------------------------------------------------------------------------


def _fact_text(n: MemoryNode) -> str:
    stub = clean_stub(n.stub)
    return stub if stub else preview(n.content, 220)


def build_page(
    nodes: list[MemoryNode],
    *,
    entities: dict[Any, list[dict]],
    contradictions: dict[Any, int],
    same: list[tuple[Any, Any, float]],
    previous: dict | None,
    fade_days: int,
) -> dict:
    """Pure function: memories in, page out (unit-tested without a database)."""
    now = now_utc()
    by_id = {n.id: n for n in nodes}

    # Fold near-duplicates into the strongest memory of each group.
    parent: dict[Any, Any] = {n.id: n.id for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, _ in same:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[Any, list[MemoryNode]] = defaultdict(list)
    for n in nodes:
        groups[find(n.id)].append(n)

    sections: dict[str, list[dict]] = defaultdict(list)
    for members in groups.values():
        members.sort(key=lambda m: (-(m.weight or 0), -(m.updated_at.timestamp() if m.updated_at else 0)))
        lead = members[0]
        updated = max((m.updated_at for m in members if m.updated_at), default=lead.updated_at)
        domain = (lead.domains or [GENERAL])[0] or GENERAL
        sections[domain].append(
            {
                "text": _fact_text(lead),
                "memory_id": str(lead.id),
                "memory_ids": [str(m.id) for m in members],
                "similar": len(members) - 1,
                "scope": lead.scope,
                "weight": lead.weight,
                "updated_at": updated,
                "stale": bool(updated and updated < now - timedelta(days=fade_days)),
                "contradicted": sum(contradictions.get(m.id, 0) for m in members),
            }
        )

    ordered = sorted(sections.items(), key=lambda kv: (kv[0] == GENERAL, -len(kv[1]), kv[0].lower()))
    out_sections = []
    for title, facts in ordered:
        facts.sort(key=lambda f: (-(f["weight"] or 0), f["text"].lower()))
        out_sections.append({"title": title, "facts": facts})

    all_facts = [f for _, facts in ordered for f in facts]

    def score(f: dict) -> float:
        age_days = (now - f["updated_at"]).days if f["updated_at"] else 365
        return (f["weight"] or 0) + max(0.0, 0.3 - age_days / 200) + 0.05 * f["similar"]

    highlights = sorted((f for f in all_facts if not f["contradicted"]), key=score, reverse=True)[:5]

    mention_count: Counter = Counter()
    entity_meta: dict[str, dict] = {}
    for n in nodes:
        for e in entities.get(n.id, []):
            mention_count[e["id"]] += 1
            entity_meta[e["id"]] = e
    top_entities = [{**entity_meta[eid], "count": c} for eid, c in mention_count.most_common(12)]

    recent_cut = now - timedelta(days=RECENT_DAYS)
    recent = sorted(
        (
            {
                "memory_id": str(n.id),
                "text": _fact_text(n),
                "updated_at": n.updated_at,
                "change": "new" if (n.version or 1) == 1 else "updated",
                "version": n.version,
            }
            for n in nodes
            if n.updated_at and n.updated_at >= recent_cut
        ),
        key=lambda r: r["updated_at"],
        reverse=True,
    )[:10]

    questions = [
        {"kind": "contradiction", "memory_id": str(mid), "text": _fact_text(by_id[mid]), "count": c}
        for mid, c in sorted(contradictions.items(), key=lambda kv: -kv[1])
        if mid in by_id and c > 0
    ]
    stale = [f for f in all_facts if f["stale"]]

    leads = {f["memory_id"]: f["text"] for f in all_facts}
    changes = None
    if previous:
        before = previous.get("facts_index") or {}
        changes = {
            "since": previous.get("generated_at"),
            "added": [{"memory_id": k, "text": v} for k, v in leads.items() if k not in before][:12],
            "removed": [{"memory_id": k, "text": v} for k, v in before.items() if k not in leads][:12],
        }

    return {
        "generated_at": now,
        "source_count": len(nodes),
        "last_source_change": max((n.updated_at for n in nodes if n.updated_at), default=None),
        "summary": {
            "facts": len(all_facts),
            "folded": len(nodes) - len(all_facts),
            "sections": len(out_sections),
            "entities": len(mention_count),
            "open_questions": len(questions),
            "stale": len(stale),
        },
        "highlights": highlights,
        "sections": out_sections,
        "entities": top_entities,
        "recent": recent,
        "questions": questions[:10],
        "stale": stale[:10],
        "changes": changes,
        "facts_index": leads,
        "scopes": dict(Counter(n.scope for n in nodes)),
    }


async def _fade_days(db: AsyncSession, settings: Settings, viewer: Viewer) -> int:
    from src.me import load_prefs

    prefs = await load_prefs(db, settings.ui_tenant_id, viewer.username)
    return int(prefs.get("dreaming_fade_days") or 60)


async def refresh_page(
    db: AsyncSession, settings: Settings, viewer: Viewer, kind: str, sid: str, *, force: bool = False
) -> tuple[dict, bool]:
    """Return the page, rebuilding it when its sources changed. (page, rebuilt)."""
    from src.dreaming import _pairs
    from src.routes_dashboard import _entities_for

    await _ensure(db)
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    filters = _base(settings, acc) + _subject_filters(acc, viewer, kind, sid)
    _, fingerprint = await _fingerprint(db, filters)
    subject = f"{kind}:{sid}"
    row = (
        await db.execute(
            text(f"SELECT page, source_hash FROM {TABLE} WHERE tenant_id = :t AND owner = :o AND subject = :s"),
            {"t": tenant_id, "o": viewer.username, "s": subject},
        )
    ).first()
    stored = None
    if row:
        stored = row[0] if not isinstance(row[0], str) else json.loads(row[0])
        if row[1] == fingerprint and not force:
            return stored, False

    started = time.perf_counter()
    nodes = (
        (
            await db.execute(
                select(MemoryNode)
                .where(*filters)
                .order_by(MemoryNode.weight.desc(), MemoryNode.updated_at.desc())
                .limit(MAX_SOURCES)
            )
        )
        .scalars()
        .all()
    )
    ids = [n.id for n in nodes]
    contradictions: dict[Any, int] = {}
    if ids:
        for mid, c in (
            await db.execute(
                select(ContradictionReport.memory_id, func.count())
                .where(
                    ContradictionReport.tenant_id == tenant_id,
                    ContradictionReport.resolved.is_(False),
                    ContradictionReport.memory_id.in_(ids),
                )
                .group_by(ContradictionReport.memory_id)
            )
        ).all():
            contradictions[mid] = int(c)
    page = build_page(
        list(nodes),
        entities=await _entities_for(db, tenant_id, ids),
        contradictions=contradictions,
        same=await _pairs(db, tenant_id, ids, SAME_FACT, 1.01, 400),
        previous=stored,
        fade_days=await _fade_days(db, settings, viewer),
    )
    page["subject"] = {"kind": kind, "id": sid, "title": _title(viewer, kind, sid)}
    page["truncated"] = len(nodes) >= MAX_SOURCES
    await db.execute(
        text(
            f"""
            INSERT INTO {TABLE} (tenant_id, owner, subject, generated_at, source_hash, page)
            VALUES (:t, :o, :s, now(), :h, CAST(:p AS JSONB))
            ON CONFLICT (tenant_id, owner, subject)
            DO UPDATE SET page = EXCLUDED.page, source_hash = EXCLUDED.source_hash, generated_at = now()
            """
        ),
        {"t": tenant_id, "o": viewer.username, "s": subject, "h": fingerprint, "p": json.dumps(page, default=str)},
    )
    await db.commit()
    from src.jobs import record_done

    await record_done(
        settings,
        kind="knowledge.rebuild",
        owner=viewer.username,
        duration_ms=int((time.perf_counter() - started) * 1000),
        detail={"subject_kind": kind, "subject_id": sid, "sources": len(nodes), "forced": force},
        trigger="manual" if force else "auto",
    )
    return json.loads(json.dumps(page, default=str)), True


def _title(viewer: Viewer, kind: str, sid: str) -> str:
    return f"What memory knows about {viewer.name or viewer.username}" if kind == "me" else f"Project {sid}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/knowledge")
async def knowledge_index(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    """The subjects the viewer has a page for, with size and freshness."""
    await _ensure(db)
    acc = await access_for(db, settings, viewer)
    stored = {
        r[0]: {
            "generated_at": r[1],
            "source_hash": r[2],
            "page": r[3] if not isinstance(r[3], str) else json.loads(r[3]),
        }
        for r in (
            await db.execute(
                text(
                    f"SELECT subject, generated_at, source_hash, page FROM {TABLE} WHERE tenant_id = :t AND owner = :o"
                ),
                {"t": settings.ui_tenant_id, "o": viewer.username},
            )
        ).all()
    }
    subjects = [("me", viewer.username)] + [("project", p) for p in await _projects(db, settings, acc)]
    items = []
    for kind, sid in subjects:
        filters = _base(settings, acc) + _subject_filters(acc, viewer, kind, sid)
        count, fingerprint = await _fingerprint(db, filters)
        snap = stored.get(f"{kind}:{sid}")
        page = snap["page"] if snap else None
        items.append(
            {
                "kind": kind,
                "id": sid,
                "title": _title(viewer, kind, sid),
                "source_count": count,
                "generated_at": snap["generated_at"] if snap else None,
                "fresh": bool(snap and snap["source_hash"] == fingerprint),
                "summary": page.get("summary") if page else None,
                "sections": [s["title"] for s in page.get("sections", [])][:6] if page else [],
            }
        )
    return {"items": items}


@router.get("/api/knowledge/{kind}/{sid}")
async def knowledge_page(
    kind: str,
    sid: str,
    db: DbDep,
    settings: SettingsDep,
    viewer: ContentDep,
    refresh: bool = Query(default=False),
):
    if kind == "me":
        sid = viewer.username
    page, rebuilt = await refresh_page(db, settings, viewer, kind, sid, force=refresh)
    page.pop("facts_index", None)
    return {**page, "rebuilt": rebuilt}


async def refresh_all_for(db: AsyncSession, settings: Settings, viewer: Viewer) -> int:
    """Rebuild every stale page of one viewer (used by the scheduler)."""
    await _ensure(db)
    acc = await access_for(db, settings, viewer)
    rebuilt = 0
    for kind, sid in [("me", viewer.username)] + [("project", p) for p in await _projects(db, settings, acc)]:
        try:
            _, did = await refresh_page(db, settings, viewer, kind, sid)
            rebuilt += int(did)
        except HTTPException:
            continue
    return rebuilt
