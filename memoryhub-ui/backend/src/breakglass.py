"""Super-user incident access to user-scope memories (#667 tier 3).

A super-user (``MEMORYHUB_UI_SUPERUSER_GROUP`` / ``MEMORYHUB_UI_SUPERUSER_USERS``,
never self-service) starts a *grant* by giving an incident reference and a
justification. While the grant is active — ``privacy.break_glass_hours`` at
most — ``access.access_for`` lets them read user-scope content. Nothing else
about their access changes.

Every user memory revealed under a grant is written to the audit log as a
``memory.read`` with ``break_glass``, the incident reference, the
justification and HIGH severity; owners see it in their notifications and in
*Who read my memories* (unless ``privacy.notify_owner`` is off). Reveals are
collected during the request (``record_reveal``) and written once the
response is ready by ``BreakGlassAuditMiddleware``, on their own session, so
a failure in the endpoint cannot lose them.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, audit, load_tenant_settings, now_utc

logger = logging.getLogger(__name__)
router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TABLE = "memoryhub_ui_break_glass"
DEFAULT_PATTERN = r"^[A-Za-z][A-Za-z0-9]{1,15}-[0-9]{1,10}$"
SEVERITY = "HIGH"

# Per-request collection of user memories revealed under a grant.
_request: ContextVar[dict | None] = ContextVar("memoryhub_break_glass", default=None)


def start_request() -> dict:
    state: dict = {"viewer": None, "grant": None, "tenant": None, "reveals": {}}
    _request.set(state)
    return state


def bind_request(viewer: Viewer, grant: dict, tenant_id: str) -> None:
    state = _request.get()
    if state is not None:
        state.update(viewer=viewer, grant=grant, tenant=tenant_id)


def record_reveal(memory_id: str, owner_id: str | None) -> None:
    state = _request.get()
    if state is not None and state.get("grant"):
        state["reveals"].setdefault(memory_id, owner_id)


async def flush(state: dict) -> int:
    """Write one HIGH-severity audit event per revealed user memory."""
    if not state or not state.get("grant") or not state["reveals"]:
        return 0
    from memoryhub_core.models.audit import AuditLog

    from src.config import get_settings as _settings
    from src.database import _get_session_factory

    grant, viewer = state["grant"], state["viewer"]
    async with _get_session_factory(_settings())() as db:
        for raw_id, owner in state["reveals"].items():
            try:
                memory_id = uuid.UUID(raw_id)
            except ValueError:
                continue
            db.add(
                AuditLog(
                    event_type="memory.read",
                    actor_id=viewer.username,
                    driver_id=viewer.real_username or viewer.username,
                    scope="user",
                    owner_id=owner or "unknown",
                    memory_id=memory_id,
                    decision="allowed",
                    event_metadata={
                        "via": "dashboard",
                        "break_glass": True,
                        "privacy_invasive": True,
                        "severity": SEVERITY,
                        "grant_id": grant["id"],
                        "incident_ref": grant["incident_ref"],
                        "justification": grant["justification"],
                    },
                    tenant_id=state["tenant"],
                )
            )
        await db.commit()
    return len(state["reveals"])


class BreakGlassAuditMiddleware:
    """Pure ASGI middleware: one collection per request, flushed after the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        state = start_request()
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                await flush(state)
            except Exception:  # pragma: no cover - needs a database failure
                logger.exception(
                    "Could not audit break-glass reads for incident %s", (state.get("grant") or {}).get("incident_ref")
                )


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------


def _row(r: Any) -> dict:
    now = now_utc()
    active = r.ended_at is None and r.expires_at > now
    return {
        "id": str(r.id),
        "username": r.username,
        "incident_ref": r.incident_ref,
        "justification": r.justification,
        "created_at": r.created_at.isoformat(),
        "expires_at": r.expires_at.isoformat(),
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "active": active,
    }


async def active_grant(db: AsyncSession, tenant_id: str, username: str) -> dict | None:
    from src.schema import require

    try:
        await require(db)
        row = (
            await db.execute(
                text(
                    f"SELECT * FROM {TABLE} WHERE tenant_id = :t AND username = :u AND ended_at IS NULL "
                    "AND expires_at > now() ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": tenant_id, "u": username},
            )
        ).first()
    except Exception as exc:  # pragma: no cover - needs a database
        logger.info("Break-glass grants unavailable: %s", exc)
        await db.rollback()
        return None
    return _row(row) if row else None


def _superuser(viewer: Viewer) -> None:
    if not viewer.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Incident access to user memories is for super-users only. Super-users are set by the deployment.",
        )


async def _policy(db: AsyncSession, settings: Settings) -> dict:
    privacy = (await load_tenant_settings(db, settings.ui_tenant_id)).get("privacy", {})
    return {
        "enabled": bool(privacy.get("break_glass", True)),
        "hours": int(privacy.get("break_glass_hours", 24)),
        "pattern": str(privacy.get("incident_pattern") or DEFAULT_PATTERN),
        "notify_owner": bool(privacy.get("notify_owner", True)),
    }


@router.get("/api/break-glass")
async def get_break_glass(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    _superuser(viewer)
    from src.schema import require

    await require(db)
    rows = (
        await db.execute(
            text(f"SELECT * FROM {TABLE} WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 50"),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    grants = [_row(r) for r in rows]
    counts = await _reveal_counts(db, settings.ui_tenant_id, [g["id"] for g in grants])
    for g in grants:
        g.update(counts.get(g["id"], {"reads": 0, "owners": 0}))
    return {
        "policy": await _policy(db, settings),
        "active": next((g for g in grants if g["active"] and g["username"] == viewer.username), None),
        "grants": grants,
    }


async def _reveal_counts(db: AsyncSession, tenant_id: str, grant_ids: list[str]) -> dict:
    if not grant_ids:
        return {}
    rows = (
        await db.execute(
            text(
                "SELECT metadata->>'grant_id' AS g, count(*) AS n, count(DISTINCT owner_id) AS o FROM audit_log "
                "WHERE tenant_id = :t AND (metadata->>'break_glass')::boolean IS TRUE "
                "AND metadata->>'grant_id' = ANY(:ids) GROUP BY 1"
            ),
            {"t": tenant_id, "ids": grant_ids},
        )
    ).all()
    return {r.g: {"reads": int(r.n), "owners": int(r.o)} for r in rows}


class GrantRequest(BaseModel):
    incident_ref: str = Field(min_length=3, max_length=64)
    justification: str = Field(min_length=20, max_length=2000)
    hours: int | None = Field(default=None, ge=1, le=72)


@router.post("/api/break-glass", status_code=201)
async def start_grant(body: GrantRequest, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    _superuser(viewer)
    policy = await _policy(db, settings)
    if not policy["enabled"]:
        raise HTTPException(
            status_code=403, detail="Incident access is switched off for this tenant (Settings → Privacy)"
        )
    ref = body.incident_ref.strip()
    if not re.fullmatch(policy["pattern"], ref):
        raise HTTPException(
            status_code=422, detail="Use the incident reference from your incident tracker, e.g. INC-1234"
        )
    if await active_grant(db, settings.ui_tenant_id, viewer.username):
        raise HTTPException(status_code=409, detail="You already have an active incident grant; end it first")
    hours = min(body.hours or policy["hours"], policy["hours"])
    gid = uuid.uuid4()
    expires = now_utc() + timedelta(hours=hours)
    await db.execute(
        text(
            f"INSERT INTO {TABLE} (id, tenant_id, username, incident_ref, justification, expires_at) "
            "VALUES (:i, :t, :u, :r, :j, :e)"
        ),
        {
            "i": gid,
            "t": settings.ui_tenant_id,
            "u": viewer.username,
            "r": ref,
            "j": body.justification.strip(),
            "e": expires,
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="break_glass.start",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={
            "severity": SEVERITY,
            "privacy_invasive": True,
            "grant_id": str(gid),
            "incident_ref": ref,
            "hours": hours,
        },
    )
    await db.commit()
    return await active_grant(db, settings.ui_tenant_id, viewer.username)


@router.post("/api/break-glass/end")
async def end_grant(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    _superuser(viewer)
    grant = await active_grant(db, settings.ui_tenant_id, viewer.username)
    if not grant:
        raise HTTPException(status_code=409, detail="No active incident grant")
    await db.execute(text(f"UPDATE {TABLE} SET ended_at = now() WHERE id = :i"), {"i": uuid.UUID(grant["id"])})
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="break_glass.end",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"severity": SEVERITY, "grant_id": grant["id"], "incident_ref": grant["incident_ref"]},
    )
    await db.commit()
    return {"ended": grant["id"]}


@router.get("/api/break-glass/report")
async def monthly_report(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
):
    """Every super-user access to user-scope memory in one month (#667 monthly review)."""
    _superuser(viewer)
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=now_utc().tzinfo) if month else now_utc().replace(day=1)
    start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    rows = (
        await db.execute(
            text(
                "SELECT actor_id, metadata->>'incident_ref' AS incident, owner_id, count(*) AS n, "
                "min(timestamp) AS first, max(timestamp) AS last FROM audit_log "
                "WHERE tenant_id = :t AND (metadata->>'break_glass')::boolean IS TRUE AND event_type = 'memory.read' "
                "AND timestamp >= :s AND timestamp < :e GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
            ),
            {"t": settings.ui_tenant_id, "s": start, "e": end},
        )
    ).all()
    from src.schema import require

    await require(db)
    grants = (
        await db.execute(
            text(
                f"SELECT * FROM {TABLE} WHERE tenant_id = :t "
                "AND created_at >= :s AND created_at < :e ORDER BY created_at"
            ),
            {"t": settings.ui_tenant_id, "s": start, "e": end},
        )
    ).all()
    return {
        "month": start.strftime("%Y-%m"),
        "grants": [_row(g) for g in grants],
        "accesses": [
            {
                "actor": r.actor_id,
                "incident_ref": r.incident,
                "owner": r.owner_id,
                "reads": int(r.n),
                "first": r.first.isoformat(),
                "last": r.last.isoformat(),
            }
            for r in rows
        ],
        "totals": {
            "grants": len(grants),
            "reads": sum(int(r.n) for r in rows),
            "owners": len({r.owner_id for r in rows}),
        },
    }
