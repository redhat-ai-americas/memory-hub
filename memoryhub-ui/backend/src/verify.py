"""Connection check: is MemoryHub set up correctly for this person? (R1-024)

One result model for every source of checks, so the UI never reimplements a
test — it renders results:

* ``dashboard`` — checks the dashboard can run itself on the person's behalf:
  the MCP endpoint answers, the person is signed in, their identities, tenant
  and projects, a write → read round-trip in their own user scope and cleanup
  of that test memory.
* ``host`` — results produced on the agent host by a verifier command and
  uploaded here (tool discovery and cross-session recall can only be checked
  from the host). No such command ships in upstream yet (R1-026); the model
  below is the contract it can emit (``memoryhub.verify/v1``).

Every failed check carries a stable ``category`` (R1-029 failure model), a
machine-readable ``code``, an explanation and the next action. Secrets are
stripped from uploads before they are stored.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from memoryhub_core.models.memory import MemoryNode
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep, load_grants
from src.authz import read_clause
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, _timed_http, now_utc

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TABLE = "memoryhub_ui_verify_results"
SCHEMA = "memoryhub.verify/v1"
KEEP = 20
MAX_UPLOAD = 64_000

STATUSES = ("pass", "warn", "fail", "not_run")

# R1-029: every failure falls in exactly one of these categories.
CATEGORIES = {
    "missing_endpoint": "Missing endpoint",
    "auth_failed": "Authentication failed",
    "insufficient_permission": "Insufficient permission",
    "wrong_identity": "Wrong identity",
    "wrong_project": "Wrong project",
    "missing_tool": "Missing tool",
    "host_integration_failed": "Host integration failure",
    "extraction_failed": "Extraction failure",
    "service_unavailable": "Service unavailable",
    "cleanup_failed": "Cleanup failure",
}

# The checks R1-024 asks to show separately, in display order.
CHECKS = {
    "endpoint": "MCP endpoint",
    "auth": "Authentication",
    "tool_discovery": "Tool discovery",
    "identity": "Identity",
    "tenant": "Tenant",
    "project": "Project",
    "round_trip": "Write and read back",
    "cross_session": "Recall in a new session",
    "cleanup": "Cleanup",
}

SECRET_KEY = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|cookie|credential|bearer)", re.I)
SECRET_VALUE = re.compile(r"(Bearer\s+\S+|mh-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")


def check(
    id: str,
    status: str,
    explanation: str,
    *,
    category: str | None = None,
    code: str | None = None,
    next_action: str | None = None,
    source: str = "dashboard",
    duration_ms: int | None = None,
) -> dict:
    return {
        "id": id,
        "title": CHECKS.get(id, id.replace("_", " ").capitalize()),
        "status": status,
        "category": category,
        "category_label": CATEGORIES.get(category or ""),
        "code": code,
        "explanation": explanation,
        "next_action": next_action,
        "source": source,
        "duration_ms": duration_ms,
    }


def summarize(checks: list[dict]) -> dict:
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in STATUSES}
    state = "fail" if counts["fail"] else "partial" if counts["not_run"] else "warn" if counts["warn"] else "pass"
    return {**counts, "state": state}


def redact(value: Any) -> Any:
    """Drop anything that looks like a credential, by key or by shape."""
    if isinstance(value, dict):
        return {k: "[redacted]" if SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub("[redacted]", value)
    return value


def _not_run_from_host(id: str, what: str) -> dict:
    return check(
        id,
        "not_run",
        f"{what} can only be checked from the agent host, through the agent's own MCP connection.",
        source="host",
        next_action="Run the connection check on the machine where your agent runs and upload its JSON result here.",
    )


async def run_dashboard_checks(db: AsyncSession, settings: Settings, viewer: Viewer) -> dict:
    started = now_utc()
    tenant = settings.ui_tenant_id
    checks: list[dict] = []

    # Endpoint -----------------------------------------------------------
    if not settings.mcp_server_url:
        checks.append(
            check(
                "endpoint",
                "fail",
                "This deployment has no MCP server address configured.",
                category="missing_endpoint",
                code="endpoint.not_configured",
                next_action="Ask your platform operator to set MEMORYHUB_MCP_SERVER_URL for the dashboard.",
            )
        )
    else:
        code, ms = await _timed_http("GET", settings.mcp_server_url)
        if code is None or code >= 500:
            checks.append(
                check(
                    "endpoint",
                    "fail",
                    "The MCP server did not answer from inside the cluster."
                    if code is None
                    else f"The MCP server answered with HTTP {code}.",
                    category="service_unavailable",
                    code="endpoint.unreachable" if code is None else "endpoint.server_error",
                    next_action=(
                        "MemoryHub itself is down or restarting. Try again in a few minutes; "
                        "if it persists, tell your platform operator."
                    ),
                    duration_ms=ms,
                )
            )
        else:
            checks.append(
                check(
                    "endpoint",
                    "pass",
                    f"The MCP server answers ({ms} ms). Agents connect to {settings.public_mcp_url}.",
                    code="endpoint.ok",
                    duration_ms=ms,
                )
            )

    # Authentication -----------------------------------------------------
    if viewer.source == "anonymous":
        checks.append(
            check(
                "auth",
                "warn",
                "The dashboard runs in open mode, so nobody is signed in. Agents still need their own credentials.",
                category="auth_failed",
                code="auth.open_mode",
                next_action="Sign in, then run memoryhub login on the agent host.",
            )
        )
    else:
        how = {"oauth-proxy": "OpenShift", "account": "a MemoryHub account", "api-key": "an API key"}.get(
            viewer.source, viewer.source
        )
        checks.append(
            check(
                "auth",
                "pass",
                f"You are signed in to the dashboard as {viewer.username} through {how}. "
                "The agent's own sign-in is checked on the host.",
                code="auth.dashboard_session",
            )
        )

    checks.append(_not_run_from_host("tool_discovery", "Whether the agent sees the memory tools"))

    # Identity, tenant, project -----------------------------------------
    grants = await load_grants(db, tenant, viewer.username)
    if grants.agents:
        since = now_utc() - timedelta(days=7)
        from memoryhub_core.models.audit import AuditLog

        recent = (
            await db.execute(
                select(AuditLog.actor_id, func.count())
                .where(
                    AuditLog.tenant_id == tenant,
                    AuditLog.actor_id.in_(sorted(grants.agents)),
                    AuditLog.timestamp >= since,
                )
                .group_by(AuditLog.actor_id)
            )
        ).all()
        active = {a: n for a, n in recent}
        names = ", ".join(sorted(grants.agents))
        if active:
            busy = ", ".join(f"{a} ({n})" for a, n in sorted(active.items()))
            checks.append(
                check(
                    "identity",
                    "pass",
                    f"Linked agents: {names}. Active in the last 7 days: {busy}.",
                    code="identity.linked_active",
                )
            )
        else:
            checks.append(
                check(
                    "identity",
                    "warn",
                    f"Linked agents: {names}, but none of them used MemoryHub in the last 7 days.",
                    category="wrong_identity",
                    code="identity.linked_idle",
                    next_action=(
                        "Check the agent signs in with the client ID you linked; an agent using another "
                        "identity writes memories you will not see as yours."
                    ),
                )
            )
    else:
        checks.append(
            check(
                "identity",
                "warn",
                "No agent is linked to you, so memories your agents write are not counted as yours.",
                category="wrong_identity",
                code="identity.no_agents",
                next_action="Link the agents you use in Users & agents.",
            )
        )
    checks.append(
        check(
            "tenant",
            "pass",
            f"This dashboard serves tenant {tenant}. Your agent must use the same tenant.",
            code="tenant.ok",
        )
    )
    if grants.projects:
        checks.append(
            check(
                "project",
                "pass",
                f"You are a member of {', '.join(sorted(grants.projects))}; agents can share project memories there.",
                code="project.member",
            )
        )
    else:
        checks.append(
            check(
                "project",
                "warn",
                "You are not a member of any project, so agents can only keep user memories for you.",
                category="wrong_project",
                code="project.none",
                next_action="Join a project, or ask a project owner to add you, in Projects & teams.",
            )
        )

    # Round-trip and cleanup --------------------------------------------
    if viewer.redacts_content:
        checks.append(
            check(
                "round_trip",
                "not_run",
                "Platform admins do not write memories, so the write-and-read check is skipped.",
                code="round_trip.admin",
            )
        )
        checks.append(check("cleanup", "not_run", "Nothing was written.", code="cleanup.nothing"))
    else:
        checks.extend(await _round_trip(db, settings, viewer, grants))

    checks.append(_not_run_from_host("cross_session", "Whether a memory written in one session comes back in the next"))
    return {
        "schema": SCHEMA,
        "source": "dashboard",
        "produced_by": {"tool": "memoryhub-ui", "check": "dashboard", "profile_version": None},
        "started_at": started.isoformat(),
        "finished_at": now_utc().isoformat(),
        "context": {
            "endpoint": settings.public_mcp_url,
            "tenant": tenant,
            "identity": viewer.username,
            "projects": sorted(grants.projects),
        },
        "checks": checks,
        "summary": summarize(checks),
    }


async def _round_trip(db: AsyncSession, settings: Settings, viewer: Viewer, grants) -> list[dict]:
    from fastapi import HTTPException as _HTTP

    from src.routes_dashboard import WriteMemoryRequest, create_dashboard_memory

    marker = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    try:
        written = await create_dashboard_memory(
            db,
            settings,
            viewer,
            WriteMemoryRequest(
                content=f"MemoryHub connection check {marker}. Written and removed automatically.",
                scope="user",
                weight=0.1,
                domains=["memoryhub-connection-check"],
            ),
            metadata={"connection_check": marker},
        )
    except _HTTP as exc:
        await db.rollback()
        category, code, action = {
            503: (
                "service_unavailable",
                "round_trip.embeddings_unavailable",
                "The embedding service is not configured or down; tell your platform operator.",
            ),
            409: (
                "insufficient_permission",
                "round_trip.blocked_by_rule",
                "A curation rule blocked the test memory. Your platform operator can check the rules.",
            ),
            403: (
                "insufficient_permission",
                "round_trip.forbidden",
                "You may not write user memories here; ask your platform operator.",
            ),
        }.get(
            exc.status_code,
            ("service_unavailable", "round_trip.error", "Try again; if it persists, tell your platform operator."),
        )
        ms = int((time.perf_counter() - t0) * 1000)
        return [
            check(
                "round_trip",
                "fail",
                f"Writing a test memory failed: {exc.detail}",
                category=category,
                code=code,
                next_action=action,
                duration_ms=ms,
            ),
            check("cleanup", "not_run", "Nothing was written.", code="cleanup.nothing"),
        ]
    mid = uuid.UUID(written["id"])
    node = (
        await db.execute(
            select(MemoryNode).where(MemoryNode.id == mid, read_clause(grants, settings.ui_tenant_id, MemoryNode))
        )
    ).scalar_one_or_none()
    ms = int((time.perf_counter() - t0) * 1000)
    out = [
        check(
            "round_trip",
            "pass",
            f"A test memory was written to your user scope and read back with your access ({ms} ms).",
            code="round_trip.ok",
            duration_ms=ms,
        )
        if node is not None
        else check(
            "round_trip",
            "fail",
            "The test memory was written but your own access did not return it.",
            category="wrong_identity",
            code="round_trip.not_readable",
            next_action="Your dashboard identity and memory ownership disagree; tell your platform operator.",
            duration_ms=ms,
        )
    ]
    try:
        await db.execute(delete(MemoryNode).where(MemoryNode.id == mid))
        await db.commit()
        out.append(check("cleanup", "pass", "The test memory was removed; nothing is left behind.", code="cleanup.ok"))
    except Exception as exc:  # pragma: no cover - needs a database failure
        await db.rollback()
        out.append(
            check(
                "cleanup",
                "fail",
                f"The test memory could not be removed ({type(exc).__name__}).",
                category="cleanup_failed",
                code="cleanup.delete_failed",
                next_action=f"Delete the memory {mid} from the Memory browser.",
            )
        )
    return out


def normalize_upload(body: dict) -> dict:
    """Validate a host verifier result against ``memoryhub.verify/v1``."""
    if body.get("schema") != SCHEMA:
        raise HTTPException(status_code=422, detail=f"Expected a {SCHEMA} result (the 'schema' field)")
    raw = body.get("checks")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=422, detail="The result has no checks")
    checks = []
    for i, c in enumerate(raw[:50]):
        if not isinstance(c, dict) or not c.get("id") or c.get("status") not in STATUSES:
            raise HTTPException(
                status_code=422, detail=f"Check {i + 1} needs an id and a status of {', '.join(STATUSES)}"
            )
        cat = c.get("category")
        if cat is not None and cat not in CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Unknown failure category {cat!r}")
        item = check(
            str(c["id"])[:64],
            c["status"],
            str(c.get("explanation") or "")[:1000],
            category=cat,
            code=(str(c["code"])[:120] if c.get("code") else None),
            next_action=(str(c["next_action"])[:500] if c.get("next_action") else None),
            source="host",
            duration_ms=c.get("duration_ms") if isinstance(c.get("duration_ms"), int) else None,
        )
        if c.get("title"):
            item["title"] = str(c["title"])[:120]
        checks.append(redact(item))
    produced = body.get("produced_by") if isinstance(body.get("produced_by"), dict) else {}
    return {
        "schema": SCHEMA,
        "source": "host",
        "produced_by": redact({k: produced.get(k) for k in ("tool", "version", "command", "host", "profile_version")}),
        "started_at": body.get("started_at"),
        "finished_at": body.get("finished_at"),
        "context": redact(
            {
                k: v
                for k, v in (body.get("context") or {}).items()
                if k in ("endpoint", "tenant", "identity", "project", "projects", "host")
            }
        ),
        "checks": checks,
        "summary": summarize(checks),
    }


async def _store(db: AsyncSession, settings: Settings, viewer: Viewer, result: dict) -> dict:
    from src.schema import require

    await require(db)
    rid = uuid.uuid4()
    await db.execute(
        text(f"INSERT INTO {TABLE} (id, tenant_id, owner, source, result) VALUES (:i, :t, :o, :s, CAST(:r AS JSONB))"),
        {"i": rid, "t": settings.ui_tenant_id, "o": viewer.username, "s": result["source"], "r": json.dumps(result)},
    )
    await db.execute(
        text(
            f"""DELETE FROM {TABLE} WHERE tenant_id = :t AND owner = :o AND id NOT IN (
                SELECT id FROM {TABLE} WHERE tenant_id = :t AND owner = :o ORDER BY created_at DESC LIMIT {KEEP})"""
        ),
        {"t": settings.ui_tenant_id, "o": viewer.username},
    )
    await db.commit()
    return {"id": str(rid), "created_at": now_utc().isoformat(), **result}


def _signed_in(viewer: Viewer) -> None:
    if viewer.source == "anonymous" and viewer.role == "operator":
        raise HTTPException(status_code=403, detail="Sign in to keep connection check results")


@router.get("/api/verify")
async def list_results(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    from src.schema import require

    await require(db)
    rows = (
        await db.execute(
            text(
                f"SELECT id, created_at, result FROM {TABLE} WHERE tenant_id = :t AND owner = :o "
                f"ORDER BY created_at DESC LIMIT {KEEP}"
            ),
            {"t": settings.ui_tenant_id, "o": viewer.username},
        )
    ).all()
    results = []
    for rid, created, result in rows:
        r = json.loads(result) if isinstance(result, str) else result
        results.append({"id": str(rid), "created_at": created.isoformat(), **r})
    return {
        "schema": SCHEMA,
        "checks": [{"id": k, "title": v} for k, v in CHECKS.items()],
        "categories": [{"id": k, "label": v} for k, v in CATEGORIES.items()],
        "host_command": None,  # R1-026: no host verifier command ships yet
        "results": results,
    }


@router.post("/api/verify/run", status_code=201)
async def run(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    _signed_in(viewer)
    return await _store(db, settings, viewer, await run_dashboard_checks(db, settings, viewer))


class Upload(BaseModel):
    result: dict


@router.post("/api/verify/results", status_code=201)
async def upload(body: Upload, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    _signed_in(viewer)
    if len(json.dumps(body.result)) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="The result is too large (64 KB at most)")
    return await _store(db, settings, viewer, normalize_upload(body.result))


@router.get("/api/connect")
async def connect_info(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    """What a person needs to point an agent host at this MemoryHub (no secrets)."""
    grants = await load_grants(db, settings.ui_tenant_id, viewer.username)
    return {
        "mcp_url": settings.public_mcp_url,
        "auth_url": settings.public_auth_url,
        "tenant": settings.ui_tenant_id,
        "agents": sorted(grants.agents),
        "projects": sorted(grants.projects),
    }
