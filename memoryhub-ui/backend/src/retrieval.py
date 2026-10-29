"""The search pipeline the playground, retrieval checks and context packs share.

Same stages as the agent-facing ``search_memory``: candidates (pgvector top
50, or full text), RBAC for the run-as identity, session focus, reciprocal
rank fusion, cross-encoder rerank, weight threshold, ``max_results`` and the
token budget. On top of the results it explains itself:

* ``funnel`` — how many memories survived each stage;
* ``dropped`` — every memory that matched but did not come back, with the
  stage and reason (only memories the viewer may read; the rest are counted);
* ``explain`` — the fate of memories the caller asks about, even ones that
  never made the top-50 candidate list ("why didn't X come back?").

Every run records its counts and timings — never the query text or content —
in ``memoryhub_ui_search_runs``; platform admins see those aggregates as
retrieval health.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import LabsDep, ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import clean_stub, cosine, embed, load_tenant_settings, now_utc, parse_uuid, rerank

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

RUNS = "memoryhub_ui_search_runs"
TOP_K = 50

STAGE_LABEL = {
    "filters": "Version, branch and status filters",
    "rbac": "Access for the run-as identity",
    "weight": "Weight threshold",
    "limit": "Max results",
    "budget": "Token budget",
}


async def _ensure(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _relaxed_reason(n: MemoryNode, body) -> tuple[str, str] | None:
    """Why a memory that matched was excluded before ranking (version/branch/status)."""
    if n.status == "quarantined":
        return "quarantined", "Held by a quarantine rule; agents never receive it until it is restored."
    if n.status == "pending":
        return "pending", "Waiting for review (enterprise approval or promotion)."
    if n.status != "active":
        return "status", f"Status is {n.status}."
    if body.current_only and not n.is_current:
        return "superseded", f"An older version (v{n.version}); Current versions only is on."
    if not body.include_branches and n.parent_id is not None:
        return "branch", "A branch of another memory; Include branches is off."
    return None


def _brief(n: MemoryNode, **extra) -> dict:
    return {
        "id": str(n.id),
        "stub": clean_stub(n.stub),
        "scope": n.scope,
        "scope_id": n.scope_id,
        "owner_id": n.owner_id,
        "weight": n.weight,
        "version": n.version,
        **extra,
    }


async def run_search(
    db: AsyncSession,
    settings: Settings,
    viewer,
    body,
    *,
    explain_ids: list[str] | None = None,
    source: str = "playground",
) -> dict:
    from src.routes_dashboard import _visible_predicate

    if viewer.restricted:
        body.identity = viewer.username  # users can only search as themselves
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    tenant_settings = await load_tenant_settings(db, tenant_id)
    full_threshold = float(tenant_settings["retrieval"]["full_content_threshold"])
    stages: list[dict] = []

    def stage(name: str, started: float, **extra):
        stages.append({"name": name, "ms": round((time.perf_counter() - started) * 1000, 1), **extra})

    base = [MemoryNode.tenant_id == tenant_id, MemoryNode.deleted_at.is_(None), MemoryNode.scope != "entity"]
    strict = [MemoryNode.status == "active"]
    if body.current_only:
        strict.append(MemoryNode.is_current.is_(True))
    if not body.include_branches:
        strict.append(MemoryNode.parent_id.is_(None))

    t0 = time.perf_counter()
    qvec = await embed(body.query, settings.embedding_url)
    stage("embed", t0)

    retrieval = "vector" if qvec is not None else "text"
    t0 = time.perf_counter()
    if qvec is not None:
        distance = MemoryNode.embedding.cosine_distance(qvec)
        score_col = (1 - distance).label("score")

        def ranked(extra):
            return (
                select(MemoryNode, score_col).where(*base, *extra, MemoryNode.embedding.is_not(None)).order_by(distance)
            )
    else:
        tsq = func.plainto_tsquery("english", body.query)
        rank_col = func.ts_rank(literal_column("search_vector"), tsq).label("score")

        def ranked(extra):
            return (
                select(MemoryNode, rank_col)
                .where(*base, *extra, literal_column("search_vector").op("@@")(tsq))
                .order_by(rank_col.desc())
            )

    rows = (await db.execute(ranked(strict).limit(TOP_K))).all()
    if not rows and qvec is None:
        pattern = f"%{body.query}%"
        rows = (
            await db.execute(
                select(MemoryNode, literal_column("0.0"))
                .where(*base, *strict, or_(MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern)))
                .limit(TOP_K)
            )
        ).all()
    candidates = [(r[0], float(r[1])) for r in rows]
    stage("pgvector" if qvec is not None else "full-text", t0, detail=f"top-{TOP_K}")

    # What the version/branch/status filters kept out of the same top-50.
    dropped: list[dict] = []
    hidden: dict[str, int] = {}

    def drop(n: MemoryNode, stage_key: str, reason: str, detail: str, **extra):
        if acc.can_read_row(n):
            dropped.append(_brief(n, stage=stage_key, reason=reason, detail=detail, **extra))
        else:
            hidden[stage_key] = hidden.get(stage_key, 0) + 1

    strict_ids = {n.id for n, _ in candidates}
    relaxed_rows = (await db.execute(ranked([]).limit(TOP_K))).all()
    relaxed_dropped = 0
    for n, score in relaxed_rows:
        if n.id in strict_ids:
            continue
        why = _relaxed_reason(n, body)
        if why:
            relaxed_dropped += 1
            drop(n, "filters", why[0], why[1], score=round(float(score), 4))

    t0 = time.perf_counter()
    visible, run_as = await _visible_predicate(db, tenant_id, body.identity, body.project)
    allowed = []
    for n, s in candidates:
        if visible(n):
            allowed.append((n, s))
        else:
            drop(n, "rbac", "no_access", f"Outside what {run_as} can read.", score=round(s, 4))
    rbac_dropped = len(candidates) - len(allowed)
    stage("rbac", t0)

    focus_scores: dict[uuid.UUID, float] = {}
    if body.focus and body.session_focus_weight > 0 and allowed:
        t0 = time.perf_counter()
        fvec = await embed(body.focus, settings.embedding_url)
        if fvec is not None:
            for n, _ in allowed:
                if n.embedding is not None:
                    focus_scores[n.id] = cosine(list(n.embedding), fvec)
        stage("focus", t0)

    t0 = time.perf_counter()
    k = 60
    w = body.session_focus_weight if focus_scores else 0.0
    by_query = sorted(allowed, key=lambda x: x[1] or 0, reverse=True)
    q_rank = {n.id: i + 1 for i, (n, _) in enumerate(by_query)}
    f_rank = {nid: i + 1 for i, nid in enumerate(sorted(focus_scores, key=lambda x: focus_scores[x], reverse=True))}
    rrf = {}
    for n, _ in allowed:
        score = (1 - w) / (k + q_rank[n.id])
        if w:
            score += w / (k + f_rank.get(n.id, len(allowed) + 1))
        rrf[n.id] = score * 2
    fused = sorted(allowed, key=lambda x: rrf[x[0].id], reverse=True)
    stage("rrf", t0)

    rerank_scores: dict[uuid.UUID, float] = {}
    rerank_status = "off"
    if body.rerank and fused:
        if settings.reranker_url:
            t0 = time.perf_counter()
            top = fused[: min(len(fused), 25)]
            scores = await rerank(body.query, [n.content for n, _ in top], settings.reranker_url)
            if scores is not None:
                rerank_scores = {n.id: s for (n, _), s in zip(top, scores, strict=False)}
                fused = sorted(fused, key=lambda x: rerank_scores.get(x[0].id, -1e9), reverse=True)
                rerank_status = "on"
            else:
                rerank_status = "unavailable"
            stage("rerank", t0)
        else:
            rerank_status = "not_configured"

    t0 = time.perf_counter()
    position = {n.id: i + 1 for i, (n, _) in enumerate(fused)}
    weight_kept = []
    for n, s in fused:
        if n.weight >= body.weight_threshold:
            weight_kept.append((n, s))
        else:
            drop(
                n,
                "weight",
                "below_threshold",
                f"Weight {n.weight:.2f} is below the threshold {body.weight_threshold:.2f}.",
                score=round(s, 4),
                rank=position[n.id],
            )
    selected = weight_kept[: body.max_results]
    for i, (n, s) in enumerate(weight_kept[body.max_results :], start=body.max_results + 1):
        drop(
            n,
            "limit",
            "beyond_max_results",
            f"Ranked #{i}; only the top {body.max_results} come back.",
            score=round(s, 4),
            rank=i,
        )

    results = []
    tokens_used = 0
    full_count = 0
    downgraded = 0
    budget_cut = 0
    for rank_pos, (n, vscore) in enumerate(selected, start=1):
        if body.mode == "index":
            delivery = "stub"
        elif body.mode == "full_only":
            delivery = "full"
        else:
            delivery = "full" if n.weight >= full_threshold else "stub"
        text_value = n.content if delivery == "full" else (n.stub or n.content[:80])
        tokens = max(1, len(text_value) // 4)
        reason = None
        if tokens_used + tokens > body.max_response_tokens and delivery == "full":
            delivery, text_value = "stub", (n.stub or n.content[:80])
            tokens = max(1, len(text_value) // 4)
            reason = "downgraded"
            downgraded += 1
        if tokens_used + tokens > body.max_response_tokens:
            budget_cut += 1
            drop(
                n,
                "budget",
                "token_budget",
                f"Ranked #{rank_pos}, but the {body.max_response_tokens}-token budget was used up.",
                score=round(vscore, 4),
                rank=rank_pos,
            )
            continue
        tokens_used += tokens
        full_count += delivery == "full"
        results.append(
            {
                "rank": rank_pos,
                "id": str(n.id),
                "scope": n.scope,
                "scope_id": n.scope_id,
                "owner_id": n.owner_id,
                "stub": clean_stub(n.stub),
                "content": n.content if delivery == "full" else None,
                "delivery": delivery,
                "downgraded": reason == "downgraded",
                "weight": n.weight,
                "version": n.version,
                "scores": {
                    "vector": round(vscore, 4) if vscore is not None and retrieval == "vector" else None,
                    "text": round(vscore, 4) if vscore is not None and retrieval == "text" else None,
                    "focus": round(focus_scores[n.id], 4) if n.id in focus_scores else None,
                    "rrf": round(rrf[n.id], 4),
                    "rerank": round(rerank_scores[n.id], 4) if n.id in rerank_scores else None,
                    "weight": n.weight,
                },
                "tokens": tokens,
            }
        )
    assembled = "\n\n".join(f"[{r['scope']}] {r['content'] if r['delivery'] == 'full' else r['stub']}" for r in results)
    stage("assemble", t0)

    funnel = [
        {"key": "matched", "label": f"Matched (top {TOP_K} by similarity)", "count": len(candidates) + relaxed_dropped},
        {"key": "filters", "label": STAGE_LABEL["filters"], "count": len(candidates), "dropped": relaxed_dropped},
        {"key": "rbac", "label": STAGE_LABEL["rbac"], "count": len(allowed), "dropped": rbac_dropped},
        {
            "key": "weight",
            "label": STAGE_LABEL["weight"],
            "count": len(weight_kept),
            "dropped": len(fused) - len(weight_kept),
        },
        {
            "key": "limit",
            "label": STAGE_LABEL["limit"],
            "count": len(selected),
            "dropped": len(weight_kept) - len(selected),
        },
        {
            "key": "budget",
            "label": STAGE_LABEL["budget"],
            "count": len(results),
            "dropped": budget_cut,
            "downgraded": downgraded,
        },
    ]

    explain = []
    returned_ids = {r["id"] for r in results}
    dropped_by_id = {d["id"]: d for d in dropped}
    for raw in explain_ids or []:
        explain.append(
            await _explain(
                db,
                settings,
                acc,
                body,
                raw,
                qvec,
                retrieval,
                returned_ids,
                dropped_by_id,
                visible,
                run_as,
                ranked,
                strict,
            )
        )

    out = {
        "run_as": run_as,
        "retrieval": retrieval,
        "rerank": rerank_status,
        "stages": stages,
        "total_ms": round(sum(s["ms"] for s in stages), 1),
        "candidates": len(candidates),
        "omitted_count": rbac_dropped,
        "weight_filtered": len(fused) - len(weight_kept),
        "returned": len(results),
        "full_count": full_count,
        "stub_count": len(results) - full_count,
        "tokens": tokens_used,
        "results": results,
        "assembled_context": assembled,
        "funnel": funnel,
        "dropped": dropped,
        "hidden_dropped": hidden,
        "explain": explain,
    }
    await _record(db, settings, viewer, body, out, source)
    return out


async def _explain(
    db, settings, acc, body, raw, qvec, retrieval, returned_ids, dropped_by_id, visible, run_as, ranked, strict
):
    """Where one memory fell out of the pipeline."""
    try:
        mid = parse_uuid(raw, "memory ID")
    except Exception:
        return {"id": raw, "found": False, "stage": "missing", "detail": "Not a memory ID."}
    n = (
        await db.execute(select(MemoryNode).where(MemoryNode.id == mid, MemoryNode.tenant_id == settings.ui_tenant_id))
    ).scalar_one_or_none()
    if n is None or not acc.can_read_row(n):
        return {"id": raw, "found": False, "stage": "missing", "detail": "No memory with this ID that you can read."}
    out = _brief(n, found=True)
    if str(n.id) in returned_ids:
        return {**out, "stage": "returned", "detail": "It came back."}
    if str(n.id) in dropped_by_id:
        d = dropped_by_id[str(n.id)]
        return {**out, "stage": d["stage"], "detail": d["detail"], "rank": d.get("rank")}
    if n.deleted_at is not None:
        return {**out, "stage": "deleted", "detail": "It is deleted. Restore it to make it searchable again."}
    if n.scope == "entity":
        return {**out, "stage": "filters", "detail": "It is an entity, not a memory."}
    why = _relaxed_reason(n, body)
    if why:
        return {**out, "stage": "filters", "detail": why[1]}
    if not visible(n):
        return {**out, "stage": "rbac", "detail": f"Outside what {run_as} can read."}
    # Not among the top candidates: how far down the similarity ranking is it?
    if qvec is not None and n.embedding is not None:
        sim = cosine(list(n.embedding), qvec)
        closer = (
            await db.execute(
                select(func.count())
                .select_from(MemoryNode)
                .where(
                    MemoryNode.tenant_id == settings.ui_tenant_id,
                    MemoryNode.deleted_at.is_(None),
                    MemoryNode.scope != "entity",
                    *strict,
                    MemoryNode.embedding.is_not(None),
                    MemoryNode.embedding.cosine_distance(qvec) < 1 - sim,
                )
            )
        ).scalar_one()
        return {
            **out,
            "stage": "matched",
            "rank": int(closer) + 1,
            "similarity": round(sim, 4),
            "detail": f"Similarity {sim:.2f} ranks it #{int(closer) + 1}; only the top {TOP_K} are considered. "
            "Rephrase the query, set a session focus, or rewrite the memory so it says what agents ask for.",
        }
    if n.embedding is None and retrieval == "vector":
        return {**out, "stage": "matched", "detail": "It has no embedding yet, so vector search cannot find it."}
    return {**out, "stage": "matched", "detail": "The full-text search did not match its words."}


async def _record(db: AsyncSession, settings: Settings, viewer, body, out: dict, source: str) -> None:
    try:
        await _ensure(db)
        counts = {f["key"]: f["count"] for f in out["funnel"]}
        counts.update({f"{f['key']}_dropped": f.get("dropped", 0) for f in out["funnel"] if "dropped" in f})
        counts.update(
            {"tokens": out["tokens"], "full": out["full_count"], "downgraded": out["funnel"][-1].get("downgraded", 0)}
        )
        await db.execute(
            text(
                f"INSERT INTO {RUNS} (id, tenant_id, viewer, source, query_hash, retrieval, rerank, total_ms, counts, stage_ms) "  # noqa: E501
                "VALUES (:id, :t, :v, :s, :h, :r, :rr, :ms, CAST(:c AS JSONB), CAST(:sm AS JSONB))"
            ),
            {
                "id": uuid.uuid4(),
                "t": settings.ui_tenant_id,
                "v": viewer.username,
                "s": source,
                "h": hashlib.sha256(body.query.encode()).hexdigest()[:16],
                "r": out["retrieval"],
                "rr": out["rerank"],
                "ms": out["total_ms"],
                "c": json.dumps(counts),
                "sm": json.dumps({s["name"]: s["ms"] for s in out["stages"]}),
            },
        )
        await db.commit()
    except Exception as exc:  # pragma: no cover - needs a database
        logger.info("Search run not recorded: %s", exc)
        await db.rollback()


def summarise_runs(rows: list[tuple]) -> dict:
    """Aggregate recorded runs (pure; unit-tested). rows: (at, source, retrieval, rerank, total_ms, counts, stage_ms)."""  # noqa: E501
    n = len(rows)
    if not n:
        return {"runs": 0}

    def pct(values: list[float], q: float) -> float:
        values = sorted(values)
        return round(values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))], 1)

    def total(key: str) -> int:
        return sum(int((r[5] or {}).get(key, 0)) for r in rows)

    matched = total("matched") or 1
    stage_names = sorted({k for r in rows for k in (r[6] or {})})
    return {
        "runs": n,
        "sources": {s: sum(1 for r in rows if r[1] == s) for s in sorted({r[1] for r in rows})},
        "vector_share": round(sum(1 for r in rows if r[2] == "vector") / n, 2),
        "rerank": {s: sum(1 for r in rows if r[3] == s) for s in sorted({r[3] for r in rows})},
        "latency": {"p50": pct([r[4] for r in rows], 0.5), "p95": pct([r[4] for r in rows], 0.95)},
        "stages": [
            {"name": s, "p50": pct([float((r[6] or {}).get(s, 0)) for r in rows if s in (r[6] or {})], 0.5)}
            for s in stage_names
        ],
        "avg": {
            "matched": round(total("matched") / n, 1),
            "returned": round(total("budget") / n, 1),
            "tokens": round(total("tokens") / n),
        },
        "cut": {
            key: round(total(f"{key}_dropped") / matched, 3) for key in ("filters", "rbac", "weight", "limit", "budget")
        },
        "empty_share": round(sum(1 for r in rows if int((r[5] or {}).get("budget", 0)) == 0) / n, 2),
    }


@router.get("/api/search/health", dependencies=[LabsDep])
async def search_health(db: DbDep, settings: SettingsDep, viewer: ViewerDep, days: int = Query(default=7, ge=1, le=90)):
    """Retrieval health from recorded runs: counts and timings only, never queries or content.

    Admins see the whole tenant; users see their own runs.
    """
    await _ensure(db)
    params: dict[str, Any] = {"t": settings.ui_tenant_id, "since": now_utc() - timedelta(days=days)}
    where = "tenant_id = :t AND at >= :since"
    if viewer.restricted:
        where += " AND viewer = :v"
        params["v"] = viewer.username
    rows = (
        await db.execute(
            text(
                f"SELECT at, source, retrieval, rerank, total_ms, counts, stage_ms FROM {RUNS} WHERE {where} ORDER BY at DESC LIMIT 5000"  # noqa: E501
            ),
            params,
        )
    ).all()
    parsed = [
        (
            r[0],
            r[1],
            r[2],
            r[3],
            float(r[4]),
            r[5] if not isinstance(r[5], str) else json.loads(r[5]),
            r[6] if not isinstance(r[6], str) else json.loads(r[6]),
        )
        for r in rows
    ]
    by_day: dict[str, int] = {}
    for r in parsed:
        key = r[0].date().isoformat()
        by_day[key] = by_day.get(key, 0) + 1
    return {
        "days": days,
        "scope": "own" if viewer.restricted else "tenant",
        **summarise_runs(parsed),
        "by_day": [{"date": k, "runs": v} for k, v in sorted(by_day.items())],
    }
