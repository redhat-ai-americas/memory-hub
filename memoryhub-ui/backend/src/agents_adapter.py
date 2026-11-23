"""My agents & API keys (#721): connect guide, connection check, identity linking, named API keys.

- ``GET /api/connect``: this deployment's public MCP and auth URLs, the OAuth
  settings an agent needs, the person's agents and projects. No secrets.
- ``POST /api/verify/run``, ``GET /api/verify``, ``POST /api/verify/results``:
  the dashboard part of the connection check (endpoint, auth service, identity,
  agent credentials, tenant, projects, embedding, storage), plus results a host
  verifier produced. Results are kept as ``verify.result`` audit events of the
  person, so history needs no new table; the last 20 are listed.
- ``POST /api/identities/link``: bind an existing agent identity to the person,
  after the auth service confirms the client secret (proof of ownership).
- ``GET|POST /api/clients/{id}/keys``, ``DELETE /api/clients/{id}/keys/{key}``:
  named API keys of an agent the person owns, with when each was last used.
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, AccessDep, AgentOwner
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import EmbeddingDep, _record_human_audit
from src.routes import _admin_request, _authorize_client

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

VERIFY_SCHEMA = "memoryhub.verify/v1"
CHECKS = [
    ("endpoint", "MCP endpoint answers"),
    ("auth_service", "Auth service answers"),
    ("identity", "You have an agent identity"),
    ("credentials", "Your agents have working credentials"),
    ("tenant", "Tenant is configured"),
    ("projects", "Projects you can write to"),
    ("embedding", "Embedding service answers"),
    ("storage", "A memory can be written and read back"),
    ("tool_discovery", "The agent sees the memory tools"),
    ("cross_session", "A new session recalls a memory"),
]
TITLES = dict(CHECKS)
CATEGORIES = [
    ("deployment", "MemoryHub deployment"),
    ("identity", "Identity and credentials"),
    ("host_integration_failed", "Agent host integration"),
]
CATEGORY_LABEL = dict(CATEGORIES)
HOST_ONLY = {"tool_discovery", "cross_session"}
STATUSES = {"pass", "warn", "fail", "not_run"}
HISTORY = 20


# --- connect --------------------------------------------------------------------

async def _my_projects(db: AsyncSession, access: Access) -> list[str]:
    return sorted((await db.execute(select(ProjectMembership.project_id).join(
        Project, Project.name == ProjectMembership.project_id,
    ).where(ProjectMembership.user_id == access.principal.username,
            Project.tenant_id == access.principal.tenant_id))).scalars())


@router.get("/api/connect")
async def connect_info(db: DbDep, settings: SettingsDep, access: AccessDep):
    """What an agent needs to reach this MemoryHub. Never a secret."""
    auth = settings.public_auth_url.rstrip("/")
    return {
        "mcp_url": settings.public_mcp_url,
        "auth_url": auth,
        "tenant": access.principal.tenant_id,
        "agents": sorted(access.agents),
        "projects": await _my_projects(db, access),
        "oauth": {
            "token_endpoint": f"{auth}/token",
            "metadata_url": f"{auth}/.well-known/oauth-authorization-server",
            "grant_types": ["client_credentials", "refresh_token"],
            "api_key_header": "Authorization: Bearer <api key>",
        },
        "cli": {
            "login": f"memoryhub login --url {settings.public_mcp_url} --auth-url {auth} --client-id <client-id>",
            "init": "memoryhub config init [--project <project>] [--format <host>]",
        },
    }


# --- connection check ---------------------------------------------------------------

def _check(check_id: str, status: str, explanation: str, *, category: str | None = None,
           code: str | None = None, next_action: str | None = None, started: float | None = None,
           source: str = "dashboard") -> dict:
    return {
        "id": check_id, "title": TITLES.get(check_id, check_id), "status": status,
        "category": category, "category_label": CATEGORY_LABEL.get(category) if category else None,
        "code": code, "explanation": explanation, "next_action": next_action, "source": source,
        "duration_ms": round((time.monotonic() - started) * 1000) if started is not None else None,
    }


def _summary(checks: list[dict]) -> dict:
    counts = {s: sum(c["status"] == s for c in checks) for s in STATUSES}
    state = "fail" if counts["fail"] else "warn" if counts["warn"] else "partial" if counts["not_run"] else "pass"
    return {**counts, "state": state}


async def _reach(url: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        return False, type(exc).__name__
    return resp.status_code < 500, f"HTTP {resp.status_code}"


async def _dashboard_checks(db: AsyncSession, settings: Settings, access: Access, embedding) -> list[dict]:
    checks = []
    t = time.monotonic()
    ok, how = await _reach(settings.mcp_server_url)
    checks.append(_check(
        "endpoint", "pass" if ok else "fail",
        f"{settings.public_mcp_url} answered ({how})." if ok else f"No answer from the MCP server ({how}).",
        category=None if ok else "deployment", code=None if ok else "endpoint.unreachable",
        next_action=None if ok else "Ask a platform admin whether the MCP server is running.", started=t))
    t = time.monotonic()
    if settings.auth_service_url:
        ok, how = await _reach(f"{settings.auth_service_url.rstrip('/')}/.well-known/oauth-authorization-server")
        checks.append(_check(
            "auth_service", "pass" if ok else "fail",
            f"OAuth metadata is published ({how})." if ok else f"The auth service did not answer ({how}).",
            category=None if ok else "deployment", code=None if ok else "auth.unreachable",
            next_action=None if ok else "Agents cannot get tokens until the auth service answers.", started=t))
    else:
        checks.append(_check("auth_service", "fail", "No auth service is configured for this dashboard.",
                             category="deployment", code="auth.not_configured", started=t))
    agents = sorted(access.agents)
    checks.append(_check(
        "identity", "pass" if agents else "warn",
        f"Agents registered to you: {', '.join(agents)}." if agents else "No agent identity is registered to you yet.",
        category=None if agents else "identity", code=None if agents else "identity.no_agent",
        next_action=None if agents else
        "Create an OAuth client in API keys & OAuth clients, or link an existing agent."))
    t = time.monotonic()
    if agents and settings.auth_service_url:
        try:
            resp = await _admin_request(settings, "GET", "/admin/clients", tenant_id=access.principal.tenant_id,
                                        owner=access.principal.username)
            mine = [c for c in resp.json() if c.get("client_id") in access.agents]
        except HTTPException as exc:
            mine, failed = [], str(exc.detail)
        else:
            failed = None
        active = [c for c in mine if c.get("active")]
        used = [c for c in active if c.get("last_used_at") or c.get("api_key_last_used_at")]
        if failed:
            checks.append(_check("credentials", "fail", f"Could not read your agents' clients: {failed}.",
                                 category="identity", code="credentials.unreadable", started=t))
        elif not active:
            checks.append(_check("credentials", "fail", "None of your agents has an active client.",
                                 category="identity", code="credentials.none_active",
                                 next_action="Create a new client or ask an admin to re-activate one.", started=t))
        elif not used:
            checks.append(_check("credentials", "warn",
                                 f"{len(active)} active client(s), none has been used to get a token yet.",
                                 category="identity", code="credentials.never_used",
                                 next_action="Run memoryhub login on the agent host with the client ID and secret.",
                                 started=t))
        else:
            checks.append(_check("credentials", "pass",
                                 f"{len(used)} of {len(active)} active client(s) have been used.", started=t))
    else:
        checks.append(_check("credentials", "not_run", "Runs once an agent is registered to you.", started=t))
    checks.append(_check(
        "tenant", "pass" if access.principal.tenant_id else "fail",
        f"Tenant {access.principal.tenant_id}.", category=None if access.principal.tenant_id else "deployment"))
    projects = await _my_projects(db, access)
    checks.append(_check("projects", "pass",
                         f"Member of {', '.join(projects)}." if projects
                         else "No project yet: your agents write personal memories only."))
    t = time.monotonic()
    vector = None
    try:
        vector = await embedding.embed("MemoryHub connection check")
        ok = bool(vector)
    except Exception as exc:  # noqa: BLE001 - any failure of the remote service is the finding
        ok, err = False, type(exc).__name__
    checks.append(_check("embedding", "pass" if ok else "fail",
                         f"Embedded a test sentence ({len(vector)} dimensions)." if ok
                         else f"The embedding service failed ({err}).",
                         category=None if ok else "deployment", code=None if ok else "embedding.failed",
                         next_action=None if ok else "Search and new memories need the embedding service.", started=t))
    t = time.monotonic()
    # Written and read back in a transaction that is rolled back: nothing stays behind.
    try:
        probe_id = uuid.uuid4()
        probe = MemoryNode(id=probe_id, logical_id=probe_id, content="MemoryHub connection check",
                           stub="MemoryHub connection check",
                           scope="user", owner_id=access.principal.username, actor_id=access.principal.username,
                           driver_id=access.principal.username, tenant_id=access.principal.tenant_id,
                           weight=0.1, embedding=vector if ok else None)
        nested = await db.begin_nested()
        try:
            db.add(probe)
            await db.flush()
            back = (await db.execute(select(MemoryNode.content).where(MemoryNode.id == probe.id))).scalar_one()
        finally:
            await nested.rollback()
        stored = back == "MemoryHub connection check"
        checks.append(_check("storage", "pass" if stored else "fail",
                             "Wrote a test memory in your personal scope, read it back and removed it."
                             if stored else "The test memory did not read back.", started=t,
                             category=None if stored else "deployment"))
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        checks.append(_check("storage", "fail", f"The memory store refused the test write ({type(exc).__name__}).",
                             category="deployment", code="storage.write_failed", started=t))
    for host_only in sorted(HOST_ONLY):
        checks.append(_check(host_only, "not_run", "Can only be checked on the agent host.",
                             category="host_integration_failed"))
    return checks


def _result(source: str, checks: list[dict], *, produced_by: dict, context: dict,
            started: str | None, finished: str | None) -> dict:
    return {"id": str(uuid.uuid4()), "created_at": datetime.now(UTC).isoformat(), "schema": VERIFY_SCHEMA,
            "source": source, "produced_by": produced_by, "started_at": started, "finished_at": finished,
            "context": context, "checks": checks, "summary": _summary(checks)}


def _keep(db: AsyncSession, access: Access, result: dict) -> None:
    db.add(AuditLog(event_type="verify.result", actor_id=access.principal.username,
                    driver_id=access.principal.username, scope="session", owner_id=access.principal.username,
                    memory_id=None, decision="allowed", tenant_id=access.principal.tenant_id,
                    event_metadata={"result": result}))


@router.post("/api/verify/run")
async def run_verify(db: DbDep, settings: SettingsDep, access: AccessDep, embedding: EmbeddingDep):
    """Run the dashboard's part of the connection check as the signed-in person and keep the result."""
    started = datetime.now(UTC).isoformat()
    checks = await _dashboard_checks(db, settings, access, embedding)
    result = _result("dashboard", checks, produced_by={"tool": "memoryhub-dashboard", "host": None},
                     context={"endpoint": settings.public_mcp_url, "tenant": access.principal.tenant_id,
                              "identity": access.principal.username, "agents": sorted(access.agents)},
                     started=started, finished=datetime.now(UTC).isoformat())
    _keep(db, access, result)
    await db.commit()
    return result


@router.get("/api/verify")
async def list_verify(db: DbDep, access: AccessDep):
    """The person's last connection check results, newest first."""
    rows = (await db.execute(select(AuditLog.event_metadata).where(
        AuditLog.tenant_id == access.principal.tenant_id, AuditLog.event_type == "verify.result",
        AuditLog.actor_id == access.principal.username,
    ).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(HISTORY))).scalars().all()
    return {"schema": VERIFY_SCHEMA, "checks": [{"id": i, "title": t} for i, t in CHECKS],
            "categories": [{"id": i, "label": label} for i, label in CATEGORIES],
            # No host verifier command is released yet; host results are uploaded as JSON.
            "host_command": None,
            "results": [m["result"] for m in rows if isinstance(m, dict) and "result" in m]}


# Token-like strings a host verifier might echo: removed before a result is kept.
_SECRET = re.compile(
    r"(mh-(?:dev|key)-[0-9a-f]{8,})"
    r"|(eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,})"
    r"|(?i:bearer\s+\S+)"
    r"|(?i:(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+)"
)


def _scrub(value: str | None) -> str | None:
    return _SECRET.sub("[removed]", value) if value else value


class HostCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=64)
    status: Literal["pass", "warn", "fail", "not_run"]
    category: str | None = Field(default=None, max_length=64)
    code: str | None = Field(default=None, max_length=128)
    explanation: str = Field(default="", max_length=2000)
    next_action: str | None = Field(default=None, max_length=2000)
    duration_ms: int | None = Field(default=None, ge=0)


class HostResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_: Literal["memoryhub.verify/v1"] = Field(alias="schema")
    produced_by: dict[str, str | int | None] = Field(default_factory=dict)
    context: dict[str, str | int | bool | None] = Field(default_factory=dict)
    started_at: str | None = Field(default=None, max_length=64)
    finished_at: str | None = Field(default=None, max_length=64)
    checks: list[HostCheck] = Field(min_length=1, max_length=50)


class HostUpload(BaseModel):
    result: HostResult


@router.post("/api/verify/results")
async def upload_verify(body: HostUpload, db: DbDep, access: AccessDep):
    """Keep a result a host verifier produced. Unknown fields are dropped; values are length-limited."""
    r = body.result
    checks = [_check(c.id, c.status, _scrub(c.explanation), category=c.category, code=c.code,
                     next_action=_scrub(c.next_action), source="host") | {"duration_ms": c.duration_ms}
              for c in r.checks]
    produced = {k: (_scrub(str(v)[:200]) if v is not None else None) for k, v in list(r.produced_by.items())[:10]}
    context = {k: (_scrub(str(v)[:200]) if v is not None else None) for k, v in list(r.context.items())[:10]}
    result = _result("host", checks, produced_by=produced, context=context, started=r.started_at,
                     finished=r.finished_at)
    _keep(db, access, result)
    await db.commit()
    return result


# --- link an existing agent identity --------------------------------------------------

class LinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=512)


@router.post("/api/identities/link")
async def link_agent(body: LinkBody, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Register an existing user agent to the person. The client secret proves they hold it."""
    tenant = access.principal.tenant_id
    humans = {n.strip() for raw in (settings.ui_allowed_users, settings.ui_admin_users)
              for n in raw.split(",") if n.strip()}
    if body.client_id in humans:
        raise HTTPException(status_code=409, detail="That identity is a person, not an agent")
    path = f"/admin/clients/{quote(body.client_id, safe='')}"
    client = (await _admin_request(settings, "GET", path, tenant_id=tenant)).json()
    if client.get("tenant_id") != tenant:
        raise HTTPException(status_code=404, detail="Client not found")
    if client.get("identity_type") != "user":
        raise HTTPException(status_code=403, detail="Only user agents can be linked to a person")
    bound = (await db.execute(select(AgentOwner).where(
        AgentOwner.tenant_id == tenant, AgentOwner.client_id == body.client_id).with_for_update())).scalar_one_or_none()
    if bound is not None:
        raise HTTPException(status_code=409, detail="This agent is already registered to someone"
                            if bound.owner != access.principal.username else "This agent is already yours")
    proof = (await _admin_request(settings, "POST", f"{path}/verify-secret",
                                  json_body={"client_secret": body.client_secret}, tenant_id=tenant)).json()
    if not proof.get("valid"):
        _record_human_audit(db, access, "agent.link_denied", "session", access.principal.username,
                            metadata={"client_id": body.client_id})
        await db.commit()
        raise HTTPException(status_code=403, detail="The client secret does not match")
    db.add(AgentOwner(tenant_id=tenant, client_id=body.client_id, owner=access.principal.username))
    _record_human_audit(db, access, "agent.linked", "session", access.principal.username,
                        metadata={"client_id": body.client_id})
    await db.commit()
    return {"ok": True, "client_id": body.client_id, "owner": access.principal.username}


# --- named API keys ------------------------------------------------------------------

class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


def _keys_path(client_id: str) -> str:
    return f"/admin/clients/{quote(client_id, safe='')}/keys"


@router.get("/api/clients/{client_id}/keys")
async def list_keys(client_id: str, settings: SettingsDep, access: AccessDep):
    """Named keys of an agent: its owner sees them; an admin sees metadata of tenant clients."""
    await _authorize_client(settings, access, client_id)
    owner = access.principal.username if access.principal.role == "user" else None
    resp = await _admin_request(settings, "GET", _keys_path(client_id), tenant_id=access.principal.tenant_id,
                                owner=owner)
    return {"items": resp.json(), "can_manage": client_id in access.agents}


@router.post("/api/clients/{client_id}/keys", status_code=201)
async def create_key(client_id: str, body: KeyBody, db: DbDep, settings: SettingsDep, access: AccessDep):
    """A new key for an agent the person owns. The key is shown once."""
    await _authorize_client(settings, access, client_id)
    if client_id not in access.agents:
        raise HTTPException(status_code=403, detail="Only the agent's owner creates keys")
    resp = await _admin_request(settings, "POST", _keys_path(client_id),
                                json_body={"name": body.name, "created_by": access.principal.username},
                                tenant_id=access.principal.tenant_id, owner=access.principal.username)
    key = resp.json()
    _record_human_audit(db, access, "agent.key_created", "session", access.principal.username,
                        metadata={"client_id": client_id, "key_id": key.get("id"), "name": body.name})
    await db.commit()
    return key


@router.delete("/api/clients/{client_id}/keys/{key_id}")
async def revoke_key(client_id: str, key_id: str, db: DbDep, settings: SettingsDep, access: AccessDep):
    """Revoke a key of an agent the person owns, at once."""
    await _authorize_client(settings, access, client_id)
    if client_id not in access.agents:
        raise HTTPException(status_code=403, detail="Only the agent's owner revokes keys")
    resp = await _admin_request(settings, "DELETE", f"{_keys_path(client_id)}/{quote(key_id, safe='')}",
                                tenant_id=access.principal.tenant_id, owner=access.principal.username)
    _record_human_audit(db, access, "agent.key_revoked", "session", access.principal.username,
                        metadata={"client_id": client_id, "key_id": key_id})
    await db.commit()
    return resp.json()
