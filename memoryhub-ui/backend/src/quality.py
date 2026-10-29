"""Saved queries and retrieval checks.

A saved query keeps a search (query plus every setting) on the server, for
its owner or shared with a project. Marking the memories it *should* return
turns it into a retrieval check. Running the checks measures, per query:

* hit — at least one expected memory came back;
* recall — the share of expected memories that came back;
* precision — the share of returned memories that were expected;
* MRR — 1 / rank of the first expected memory;
* latency — the pipeline time.

For each expected memory that did not come back the run stores where it fell
out of the pipeline (the same explanation as the playground). Runs are kept,
so two runs can be compared; the scheduler reruns a user's checks once a day.

Everything here is memory content, so platform admins get none of it; they
see retrieval health (counts and timings) instead.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ContentDep, LabsDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, audit, now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

QUERIES = "memoryhub_ui_saved_queries"
RUNS = "memoryhub_ui_eval_runs"


async def ensure_tables(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _load(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _query_row(r: Any, viewer: Viewer) -> dict:
    return {
        "id": str(r[0]),
        "owner": r[1],
        "name": r[2],
        "request": _load(r[3]),
        "expected": _load(r[4]) or [],
        "visibility": r[5],
        "project": r[6],
        "created_at": r[7],
        "updated_at": r[8],
        "last_result": _load(r[9]),
        "mine": r[1] == viewer.username,
        "is_check": bool(_load(r[4])),
    }


_QCOLS = "id, owner, name, request, expected, visibility, project, created_at, updated_at, last_result"


async def visible_queries(db: AsyncSession, settings: Settings, viewer: Viewer) -> list[dict]:
    await ensure_tables(db)
    acc = await access_for(db, settings, viewer)
    rows = (
        await db.execute(
            text(f"SELECT {_QCOLS} FROM {QUERIES} WHERE tenant_id = :t ORDER BY updated_at DESC"),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    projects = acc.grants.projects if acc.grants is not None else None
    out = []
    for r in rows:
        mine = r[1] == viewer.username
        shared = r[5] == "project" and r[6] and (projects is None or r[6] in projects)
        if mine or shared:
            out.append(_query_row(r, viewer))
    return out


class SavedQueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    request: dict
    expected: list[str] = Field(default_factory=list, max_length=50)
    visibility: str = Field(default="private", pattern="^(private|project)$")
    project: str | None = Field(default=None, max_length=255)


class SavedQueryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    request: dict | None = None
    expected: list[str] | None = Field(default=None, max_length=50)
    visibility: str | None = Field(default=None, pattern="^(private|project)$")
    project: str | None = Field(default=None, max_length=255)


async def _check_share(db, settings, viewer, visibility: str, project: str | None) -> None:
    if visibility != "project":
        return
    if not project:
        raise HTTPException(status_code=422, detail="Pick the project to share with")
    acc = await access_for(db, settings, viewer)
    if acc.grants is not None and project not in acc.grants.projects:
        raise HTTPException(status_code=403, detail="You can only share with projects you are a member of")


def _clean_request(req: dict) -> dict:
    from src.routes_dashboard import SearchRequest

    data = SearchRequest(**{**req, "explain": []}).model_dump()
    data.pop("explain", None)
    return data


@router.get("/api/saved-queries")
async def list_saved(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    items = await visible_queries(db, settings, viewer)
    return {"items": items, "checks": sum(1 for i in items if i["is_check"])}


@router.post("/api/saved-queries", status_code=201)
async def create_saved(body: SavedQueryIn, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    await ensure_tables(db)
    await _check_share(db, settings, viewer, body.visibility, body.project)
    qid = uuid.uuid4()
    await db.execute(
        text(
            f"INSERT INTO {QUERIES} (id, tenant_id, owner, name, request, expected, visibility, project) "
            "VALUES (:id, :t, :o, :n, CAST(:r AS JSONB), CAST(:e AS JSONB), :v, :p)"
        ),
        {
            "id": qid,
            "t": settings.ui_tenant_id,
            "o": viewer.username,
            "n": body.name.strip(),
            "r": json.dumps(_clean_request(body.request)),
            "e": json.dumps(list(dict.fromkeys(body.expected))),
            "v": body.visibility,
            "p": body.project if body.visibility == "project" else None,
        },
    )
    await db.commit()
    return {"id": str(qid)}


async def _own_query(db, settings, viewer, query_id: str) -> Any:
    await ensure_tables(db)
    try:
        parsed = uuid.UUID(query_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid query ID") from exc
    row = (
        await db.execute(
            text(f"SELECT {_QCOLS} FROM {QUERIES} WHERE id = :id AND tenant_id = :t"),
            {"id": parsed, "t": settings.ui_tenant_id},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Saved query not found")
    if row[1] != viewer.username:
        raise HTTPException(status_code=403, detail="Only the owner can change a saved query; save a copy instead")
    return row


@router.patch("/api/saved-queries/{query_id}")
async def update_saved(query_id: str, body: SavedQueryPatch, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    row = await _own_query(db, settings, viewer, query_id)
    current = _query_row(row, viewer)
    visibility = body.visibility or current["visibility"]
    project = body.project if body.project is not None else current["project"]
    await _check_share(db, settings, viewer, visibility, project)
    await db.execute(
        text(
            f"UPDATE {QUERIES} SET name = :n, request = CAST(:r AS JSONB), expected = CAST(:e AS JSONB), "
            "visibility = :v, project = :p, updated_at = now() WHERE id = :id"
        ),
        {
            "id": row[0],
            "n": (body.name or current["name"]).strip(),
            "r": json.dumps(_clean_request(body.request) if body.request is not None else current["request"]),
            "e": json.dumps(list(dict.fromkeys(body.expected)) if body.expected is not None else current["expected"]),
            "v": visibility,
            "p": project if visibility == "project" else None,
        },
    )
    await db.commit()
    return {"ok": True}


@router.delete("/api/saved-queries/{query_id}", status_code=204)
async def delete_saved(query_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    row = await _own_query(db, settings, viewer, query_id)
    await db.execute(text(f"DELETE FROM {QUERIES} WHERE id = :id"), {"id": row[0]})
    await db.commit()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def score(expected: list[str], returned: list[str]) -> dict:
    """Retrieval metrics for one query (pure; unit-tested)."""
    exp = list(dict.fromkeys(expected))
    found = [e for e in exp if e in returned]
    first = next((i + 1 for i, r in enumerate(returned) if r in exp), None)
    return {
        "expected": len(exp),
        "found": len(found),
        "hit": bool(found),
        "recall": round(len(found) / len(exp), 3) if exp else None,
        "precision": round(len(found) / len(returned), 3) if returned else 0.0,
        "mrr": round(1 / first, 3) if first else 0.0,
        "first_rank": first,
    }


def summarise(results: list[dict]) -> dict:
    scored = [r for r in results if r.get("metrics") and r["metrics"]["recall"] is not None]
    n = len(scored)
    if not n:
        return {"checks": 0}

    def avg(key: str) -> float:
        return round(sum(r["metrics"][key] for r in scored) / n, 3)

    lat = sorted(r["total_ms"] for r in scored)
    return {
        "checks": n,
        "hit_rate": round(sum(1 for r in scored if r["metrics"]["hit"]) / n, 3),
        "recall": avg("recall"),
        "precision": avg("precision"),
        "mrr": avg("mrr"),
        "p50_ms": round(lat[len(lat) // 2], 1),
        "failing": sum(1 for r in scored if r["metrics"]["recall"] < 1),
    }


async def run_checks(
    db: AsyncSession, settings: Settings, viewer: Viewer, *, trigger: str = "manual", ids: list[str] | None = None
) -> dict:
    from src.retrieval import run_search
    from src.routes_dashboard import SearchRequest

    started = time.perf_counter()
    checks = [q for q in await visible_queries(db, settings, viewer) if q["is_check"] and (not ids or q["id"] in ids)]
    results = []
    for q in checks:
        body = SearchRequest(**{**q["request"], "explain": []})
        out = await run_search(db, settings, viewer, body, explain_ids=q["expected"], source="check")
        returned = [r["id"] for r in out["results"]]
        missing = [e for e in out["explain"] if e.get("stage") != "returned"]
        results.append(
            {
                "query_id": q["id"],
                "name": q["name"],
                "query": q["request"].get("query"),
                "returned": returned,
                "metrics": score(q["expected"], returned),
                "missing": missing,
                "total_ms": out["total_ms"],
                "funnel": out["funnel"],
            }
        )
        await db.execute(
            text(f"UPDATE {QUERIES} SET last_result = CAST(:r AS JSONB) WHERE id = :id"),
            {
                "id": uuid.UUID(q["id"]),
                "r": json.dumps({"at": now_utc().isoformat(), **score(q["expected"], returned)}),
            },
        )
    summary = summarise(results)
    run_id = uuid.uuid4()
    duration = int((time.perf_counter() - started) * 1000)
    await db.execute(
        text(
            f"INSERT INTO {RUNS} (id, tenant_id, owner, duration_ms, trigger, summary, results) "
            "VALUES (:id, :t, :o, :d, :tr, CAST(:s AS JSONB), CAST(:r AS JSONB))"
        ),
        {
            "id": run_id,
            "t": settings.ui_tenant_id,
            "o": viewer.username,
            "d": duration,
            "tr": trigger,
            "s": json.dumps(summary),
            "r": json.dumps(results, default=str),
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="eval.run",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata=summary,
    )
    await db.commit()
    return {
        "id": str(run_id),
        "started_at": now_utc(),
        "duration_ms": duration,
        "trigger": trigger,
        "summary": summary,
        "results": results,
    }


def _run_row(r: Any, full: bool) -> dict:
    out = {"id": str(r[0]), "started_at": r[1], "duration_ms": r[2], "trigger": r[3], "summary": _load(r[4])}
    if full:
        out["results"] = _load(r[5])
    return out


@router.get("/api/checks", dependencies=[LabsDep])
async def checks_overview(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    await ensure_tables(db)
    items = await visible_queries(db, settings, viewer)
    runs = (
        await db.execute(
            text(
                f"SELECT id, started_at, duration_ms, trigger, summary, results FROM {RUNS} "
                "WHERE tenant_id = :t AND owner = :o ORDER BY started_at DESC LIMIT 20"
            ),
            {"t": settings.ui_tenant_id, "o": viewer.username},
        )
    ).all()
    return {
        "checks": [i for i in items if i["is_check"]],
        "queries": [i for i in items if not i["is_check"]],
        "last": _run_row(runs[0], True) if runs else None,
        "runs": [_run_row(r, False) for r in runs],
    }


@router.get("/api/checks/runs/{run_id}", dependencies=[LabsDep])
async def check_run(run_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    await ensure_tables(db)
    try:
        parsed = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid run ID") from exc
    row = (
        await db.execute(
            text(
                f"SELECT id, started_at, duration_ms, trigger, summary, results FROM {RUNS} WHERE id = :id AND owner = :o"  # noqa: E501
            ),
            {"id": parsed, "o": viewer.username},
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_row(row, True)


@router.post("/api/checks/run", status_code=201, dependencies=[LabsDep])
async def run_checks_route(
    db: DbDep, settings: SettingsDep, viewer: ContentDep, ids: list[str] | None = Query(default=None)
):
    from src.jobs import run_job

    async def work():
        run = await run_checks(db, settings, viewer, trigger="manual", ids=ids)
        return {"run_id": run["id"], "checks": run["summary"].get("checks", 0), "_value": run}

    return await run_job(settings, kind="eval.run", owner=viewer.username, work=work)


async def owners_with_checks(db: AsyncSession, settings: Settings) -> list[str]:
    """Owners whose checks have not run in the last 24 hours (for the scheduler)."""
    await ensure_tables(db)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT q.owner FROM {QUERIES} q
                WHERE q.tenant_id = :t AND jsonb_array_length(q.expected) > 0
                GROUP BY q.owner
                HAVING NOT EXISTS (
                    SELECT 1 FROM {RUNS} r WHERE r.tenant_id = :t AND r.owner = q.owner
                    AND r.started_at > now() - interval '24 hours'
                )
                """
            ),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    return [r[0] for r in rows]
