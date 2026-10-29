"""Operations: one feed of the background work the dashboard does.

Every dream, knowledge rebuild, retrieval check run, document reprocess and
scheduler tick is a *job* with a status, a duration, attempts, a correlation
ID shared by the jobs of one tick, and pointers to what it read or produced
(``detail``). Jobs are written on their own database session so a failure in
the work itself is still recorded.

Platform admins see every job (metadata only — never memory content); users
see their own. Failed dreams, rebuilds, check runs and reprocesses can be
retried.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TABLE = "memoryhub_ui_jobs"
RETRYABLE = {"dream", "knowledge.rebuild", "eval.run", "document.reprocess"}
KIND_LABEL = {
    "scheduler.tick": "Scheduler tick",
    "dream": "Memory hygiene run",
    "knowledge.rebuild": "Knowledge page rebuild",
    "eval.run": "Retrieval check run",
    "document.reprocess": "Document reprocess",
    "document.extract": "Memories from a document",
}


async def ensure_table(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


async def _write(settings: Settings, sql: str, params: dict) -> None:
    """On a separate session: the job row survives a rollback of the work."""
    from src.database import _get_session_factory

    try:
        async with _get_session_factory(settings)() as session:
            await ensure_table(session)
            await session.execute(text(sql), params)
            await session.commit()
    except Exception as exc:  # pragma: no cover - needs a database
        logger.info("Could not record job: %s", exc)


async def run_job(
    settings: Settings,
    *,
    kind: str,
    owner: str,
    work: Callable[[], Awaitable[dict | None]],
    trigger: str = "manual",
    correlation_id: uuid.UUID | None = None,
    retry_of: uuid.UUID | None = None,
    attempts: int = 1,
    detail: dict | None = None,
) -> Any:
    """Run ``work`` as a recorded job. Its returned dict is merged into ``detail``.

    Exceptions are recorded and re-raised, so callers keep their behaviour.
    """
    job_id = uuid.uuid4()
    started = time.perf_counter()
    base = {
        "id": job_id,
        "t": settings.ui_tenant_id,
        "o": owner,
        "k": kind,
        "tr": trigger,
        "c": correlation_id or job_id,
        "r": retry_of,
        "a": attempts,
        "d": json.dumps(detail or {}, default=str),
    }
    await _write(
        settings,
        f"INSERT INTO {TABLE} (id, tenant_id, owner, kind, status, trigger, correlation_id, retry_of, attempts, detail) "  # noqa: E501
        "VALUES (:id, :t, :o, :k, 'running', :tr, :c, :r, :a, CAST(:d AS JSONB))",
        base,
    )
    try:
        result = await work()
    except Exception as exc:
        await _write(
            settings,
            f"UPDATE {TABLE} SET status = 'failed', finished_at = now(), duration_ms = :ms, error = :e WHERE id = :id",
            {
                "id": job_id,
                "ms": int((time.perf_counter() - started) * 1000),
                "e": str(getattr(exc, "detail", exc))[:2000],
            },
        )
        raise
    out = result if isinstance(result, dict) else {}
    await _write(
        settings,
        f"UPDATE {TABLE} SET status = 'ok', finished_at = now(), duration_ms = :ms, "
        "detail = detail || CAST(:d AS JSONB) WHERE id = :id",
        {
            "id": job_id,
            "ms": int((time.perf_counter() - started) * 1000),
            "d": json.dumps({k: v for k, v in out.items() if k != "_value"}, default=str),
        },
    )
    return out.get("_value", result)


async def record_done(
    settings: Settings,
    *,
    kind: str,
    owner: str,
    duration_ms: int,
    detail: dict,
    trigger: str = "auto",
    correlation_id: uuid.UUID | None = None,
) -> None:
    """Record work that already finished (for work only known to be needed after it ran)."""
    job_id = uuid.uuid4()
    await _write(
        settings,
        f"INSERT INTO {TABLE} (id, tenant_id, owner, kind, status, trigger, started_at, finished_at, duration_ms, "
        "correlation_id, detail) VALUES (:id, :t, :o, :k, 'ok', :tr, now() - make_interval(secs => :s), now(), :ms, :c, "  # noqa: E501
        "CAST(:d AS JSONB))",
        {
            "id": job_id,
            "t": settings.ui_tenant_id,
            "o": owner,
            "k": kind,
            "tr": trigger,
            "s": duration_ms / 1000,
            "ms": duration_ms,
            "c": correlation_id or job_id,
            "d": json.dumps(detail, default=str),
        },
    )


def _row(r: Any) -> dict:
    detail = r[13] if not isinstance(r[13], str) else json.loads(r[13])
    return {
        "id": str(r[0]),
        "owner": r[1],
        "kind": r[2],
        "label": KIND_LABEL.get(r[2], r[2]),
        "status": r[3],
        "trigger": r[4],
        "started_at": r[5],
        "finished_at": r[6],
        "duration_ms": r[7],
        "attempts": r[8],
        "correlation_id": str(r[9]),
        "retry_of": str(r[10]) if r[10] else None,
        "error": r[11],
        "retryable": r[2] in RETRYABLE and r[3] == "failed",
        "stale": r[3] == "running" and r[12],
        "detail": detail or {},
    }


_COLUMNS = (
    "id, owner, kind, status, trigger, started_at, finished_at, duration_ms, attempts, correlation_id, retry_of, error, "  # noqa: E501
    "(status = 'running' AND started_at < now() - interval '30 minutes') AS stale, detail"
)


@router.get("/api/operations")
async def operations(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    days: int = Query(default=7, ge=1, le=90),
    status: str | None = Query(default=None, pattern="^(ok|failed|running)$"),
    kind: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
):
    await ensure_table(db)
    where = ["tenant_id = :t", "started_at >= :since"]
    params: dict[str, Any] = {"t": settings.ui_tenant_id, "since": now_utc() - timedelta(days=days), "l": limit}
    if viewer.restricted:
        where.append("owner = :o")
        params["o"] = viewer.username
    if status:
        where.append("status = :s")
        params["s"] = status
    if kind:
        where.append("kind = :k")
        params["k"] = kind
    clause = " AND ".join(where)
    rows = (
        await db.execute(
            text(f"SELECT {_COLUMNS} FROM {TABLE} WHERE {clause} ORDER BY started_at DESC LIMIT :l"), params
        )
    ).all()
    stats = (
        await db.execute(
            text(
                f"SELECT kind, status, count(*), avg(duration_ms), percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) "  # noqa: E501
                f"FROM {TABLE} WHERE {' AND '.join(w for w in where if not w.startswith(('status', 'kind')))} "
                "GROUP BY kind, status"
            ),
            params,
        )
    ).all()
    by_kind: dict[str, dict] = {}
    for k, s, n, avg_ms, p95 in stats:
        entry = by_kind.setdefault(k, {"kind": k, "label": KIND_LABEL.get(k, k), "ok": 0, "failed": 0, "running": 0})
        entry[s] = entry.get(s, 0) + int(n)
        if s == "ok":
            entry["avg_ms"] = round(float(avg_ms or 0))
            entry["p95_ms"] = round(float(p95 or 0))
    return {
        "items": [_row(r) for r in rows],
        "kinds": sorted(by_kind.values(), key=lambda x: -(x["ok"] + x["failed"] + x["running"])),
        "days": days,
        "scope": "own" if viewer.restricted else "tenant",
    }


@router.post("/api/operations/{job_id}/retry")
async def retry(job_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    await ensure_table(db)
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid job ID") from exc
    row = (
        await db.execute(
            text(f"SELECT {_COLUMNS} FROM {TABLE} WHERE id = :id AND tenant_id = :t"),
            {"id": parsed, "t": settings.ui_tenant_id},
        )
    ).first()
    if row is None or (viewer.restricted and row[1] != viewer.username):
        raise HTTPException(status_code=404, detail="Job not found")
    job = _row(row)
    if not job["retryable"]:
        raise HTTPException(
            status_code=409, detail="Only failed dreams, rebuilds, check runs and reprocesses can be retried"
        )
    owner = Viewer(username=job["owner"], name=job["owner"], email=None, source="retry", role="user")
    detail = job["detail"]

    async def work():
        if job["kind"] == "dream":
            from src.dreaming import run_for

            report = await run_for(db, settings, owner, "manual")
            return {"insights": len(report.get("insights", []))}
        if job["kind"] == "knowledge.rebuild":
            from src.knowledge import refresh_page

            await refresh_page(
                db,
                settings,
                owner,
                detail.get("subject_kind", "me"),
                detail.get("subject_id", owner.username),
                force=True,
            )
            return {}
        if job["kind"] == "eval.run":
            from src.quality import run_checks

            run = await run_checks(db, settings, owner, trigger="manual")
            return {"run_id": run["id"]}
        from src.documents import reprocess

        return await reprocess(db, settings, owner, detail.get("document_id", ""))

    await run_job(
        settings,
        kind=job["kind"],
        owner=job["owner"],
        work=work,
        trigger="retry",
        correlation_id=uuid.UUID(job["correlation_id"]),
        retry_of=parsed,
        attempts=job["attempts"] + 1,
        detail={k: v for k, v in detail.items() if k in ("subject_kind", "subject_id", "document_id")},
    )
    return {"ok": True}
