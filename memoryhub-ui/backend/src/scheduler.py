"""Background scheduler: runs due dreams and refreshes knowledge pages.

Dreaming used to rely on the Dreaming page being open to catch up on a missed
run. This loop runs inside the BFF instead. Every ``ui_scheduler_interval_s``
seconds it looks at each user's dream schedule (nightly or weekly, at the
stored window, read as UTC) and runs the dreams that are due, then rebuilds
that user's stale knowledge pages.

With several replicas only one does the work: each tick takes a Postgres
advisory lock and skips the tick when another replica holds it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from src.config import Settings, get_settings
from src.ui_common import Viewer, now_utc

logger = logging.getLogger(__name__)

LOCK_KEY = 7_301_244_019  # arbitrary, constant across replicas
_task: asyncio.Task | None = None


def is_due(schedule: str, window: str, last_run: datetime | None, now: datetime) -> bool:
    """Whether a schedule has a slot that started after the last run."""
    if schedule not in ("nightly", "weekly"):
        return False
    try:
        hour, minute = (int(x) for x in (window or "02:00").split(":", 1))
    except ValueError:
        hour, minute = 2, 0
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=1)
    if last_run is None:
        return True
    if schedule == "weekly":
        return last_run < slot - timedelta(days=6)
    return last_run < slot


async def due_owners(db, settings: Settings, now: datetime) -> list[str]:
    from src.dreaming import DEFAULT_SETTINGS, DREAMS, SETTINGS, ensure_tables

    await ensure_tables(db)
    tenant_id = settings.ui_tenant_id
    stored = {
        r[0]: (r[1] if not isinstance(r[1], str) else json.loads(r[1]))
        for r in (
            await db.execute(text(f"SELECT owner, settings FROM {SETTINGS} WHERE tenant_id = :t"), {"t": tenant_id})
        ).all()
    }
    last = {
        r[0]: r[1]
        for r in (
            await db.execute(
                text(f"SELECT owner, max(started_at) FROM {DREAMS} WHERE tenant_id = :t GROUP BY owner"),
                {"t": tenant_id},
            )
        ).all()
    }
    out = []
    for owner in sorted(set(stored) | set(last)):
        prefs = {**DEFAULT_SETTINGS, **(stored.get(owner) or {})}
        if is_due(prefs.get("schedule", "nightly"), prefs.get("window", "02:00"), last.get(owner), now):
            out.append(owner)
    return out


async def tick(settings: Settings | None = None) -> dict:
    """One pass: due dreams (+ knowledge pages), then retrieval checks older than a day.

    Every piece of work is a job in Operations; jobs of one tick share a
    correlation ID, and the tick itself is recorded when it did anything.
    """
    from src.database import _get_session_factory
    from src.dreaming import run_for
    from src.jobs import record_done, run_job
    from src.knowledge import refresh_all_for
    from src.quality import owners_with_checks, run_checks

    settings = settings or get_settings()
    factory = _get_session_factory(settings)
    done: dict[str, dict] = {}
    failed: list[str] = []
    correlation = uuid.uuid4()
    started = time.perf_counter()
    async with factory() as db:
        locked = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY})).scalar()
        if not locked:
            return {"skipped": "another replica holds the scheduler lock"}
        try:
            for owner in await due_owners(db, settings, now_utc()):
                viewer = Viewer(username=owner, name=owner, email=None, source="scheduler", role="user")

                async def dream_work(v=viewer):
                    report = await run_for(db, settings, v, "scheduled")
                    pages = await refresh_all_for(db, settings, v)
                    return {"dream_id": report["id"], "insights": len(report.get("insights", [])), "pages": pages}

                try:
                    done[owner] = await run_job(
                        settings,
                        kind="dream",
                        owner=owner,
                        work=dream_work,
                        trigger="scheduled",
                        correlation_id=correlation,
                    )
                except Exception as exc:  # keep going for the other users
                    logger.warning("Scheduled dream for %s failed: %s", owner, exc)
                    failed.append(owner)
                    await db.rollback()
            for owner in await owners_with_checks(db, settings):
                viewer = Viewer(username=owner, name=owner, email=None, source="scheduler", role="user")

                async def check_work(v=viewer):
                    run = await run_checks(db, settings, v, trigger="scheduled")
                    return {"run_id": run["id"], **run["summary"]}

                try:
                    out = await run_job(
                        settings,
                        kind="eval.run",
                        owner=owner,
                        work=check_work,
                        trigger="scheduled",
                        correlation_id=correlation,
                    )
                    done.setdefault(owner, {})["checks"] = out.get("checks", 0)
                except Exception as exc:
                    logger.warning("Scheduled checks for %s failed: %s", owner, exc)
                    failed.append(owner)
                    await db.rollback()
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            await db.commit()
    if done or failed:
        logger.info("Scheduler ran for %s", ", ".join(done) or "-")
        await record_done(
            settings,
            kind="scheduler.tick",
            owner="scheduler",
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail={"users": sorted(done), "failed": failed},
            trigger="scheduled",
            correlation_id=correlation,
        )
    return {"ran": done, "failed": failed}


async def _loop(interval: int) -> None:
    await asyncio.sleep(min(30, interval))
    while True:
        try:
            await tick()
        except Exception as exc:  # database down, etc. — try again next tick
            logger.info("Scheduler tick failed: %s", exc)
        await asyncio.sleep(interval)


def start(settings: Settings) -> None:
    global _task
    # Everything the scheduler runs (memory hygiene, knowledge pages, checks) is Labs.
    if not settings.ui_scheduler_enabled or not settings.ui_labs or _task is not None:
        return
    _task = asyncio.create_task(_loop(max(60, settings.ui_scheduler_interval_s)))
    logger.info("Background scheduler started (every %ss)", settings.ui_scheduler_interval_s)


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
