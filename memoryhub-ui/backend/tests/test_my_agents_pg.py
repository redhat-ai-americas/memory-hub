"""My agents & API keys (#721) against a real PostgreSQL + pgvector database.

The auth service is replaced by a fake of its admin API; the database parts
(owner bindings, the connection check's rolled-back write, kept results) are real.

Uses the repository's integration database (tests/integration/compose.yaml,
localhost:15433) and skips when it is not reachable:

    podman compose -f tests/integration/compose.yaml up -d
    cd memoryhub-ui/backend && pytest tests/test_my_agents_pg.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import create_memory, update_memory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.authorization import Access, AgentOwner, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import get_embedding_service
from src.main import app

TENANT = "tenant-agents"
REPO = Path(__file__).resolve().parents[3]


def _url() -> str:
    env = os.environ.get
    return (f"postgresql+asyncpg://{env('MEMORYHUB_DB_USER', 'memoryhub')}:"
            f"{env('MEMORYHUB_DB_PASSWORD', 'memoryhub-test')}@{env('MEMORYHUB_DB_HOST', 'localhost')}:"
            f"{env('MEMORYHUB_DB_PORT', '15433')}/{env('MEMORYHUB_DB_NAME', 'memoryhub')}")


@pytest.fixture(scope="module")
def database():
    engine = create_async_engine(_url(), poolclass=NullPool)

    async def reachable() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
            return True
        except Exception:  # noqa: BLE001
            return False

    if not asyncio.run(reachable()):
        pytest.skip("Integration PostgreSQL (localhost:15433) is not running")
    env = {**os.environ, "MEMORYHUB_DB_PORT": os.environ.get("MEMORYHUB_DB_PORT", "15433"),
           "MEMORYHUB_DB_PASSWORD": os.environ.get("MEMORYHUB_DB_PASSWORD", "memoryhub-test")}
    migrated = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=REPO, env=env,
                              capture_output=True, text=True)
    assert migrated.returncode == 0, migrated.stderr
    yield engine


@pytest.fixture
async def env(database):
    """Project 'atlas': alice member, bob admin, carol member. alice owns agent alice-agent."""
    async with database.begin() as conn:
        await conn.execute(text("delete from memoryhub_ui_agent_owners where tenant_id = :t"), {"t": TENANT})
        for table in ("audit_log", "contradiction_reports", "memory_relationships", "memory_nodes"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": TENANT})
        await conn.execute(text("delete from project_memberships where project_id = 'atlas-g'"))
        await conn.execute(text("delete from projects where name = 'atlas-g'"))
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as db:
        db.add(Project(name="atlas-g", tenant_id=TENANT, created_by="bob"))
        await db.flush()
        for user, role in (("alice", "member"), ("bob", "admin"), ("carol", "member")):
            db.add(ProjectMembership(project_id="atlas-g", user_id=user, role=role, joined_by="bob"))
        await db.commit()
    embedding = MockEmbeddingService()
    who = {"access": None}

    async def db_dep():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_access] = lambda: who["access"]
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id=TENANT, embedding_url="mock",
                                                              ui_allowed_users="alice,bob,carol",
                                                              ui_admin_users="admin",
                                                              auth_service_url="http://auth.test",
                                                              public_mcp_url="https://mcp.example/mcp/",
                                                              public_auth_url="https://auth.example")
    app.dependency_overrides[get_embedding_service] = lambda: embedding

    def act_as(name: str, role: str = "user") -> None:
        grants = {
            "alice": {"human_projects": {"atlas-g"}, "agents": {"alice-agent"}},
            "bob": {"human_projects": {"atlas-g"}, "human_project_admins": {"atlas-g"}},
            "carol": {"human_projects": {"atlas-g"}},
            "admin": {"human_projects": {"atlas-g"}, "human_project_admins": {"atlas-g"},
                      "moderation_scopes": {"project", "organizational"}},
        }[name]
        who["access"] = Access(principal=Principal(name, role, TENANT), **grants)

    async def seed(content: str, *, scope: str = "project", owner: str = "alice", actor: str = "alice-agent",
                   weight: float = 0.5, parent: uuid.UUID | None = None, branch: str | None = None) -> MemoryNode:
        async with sessions() as db:
            created, _ = await create_memory(MemoryNodeCreate(
                content=content, scope=scope, owner_id=owner, actor_id=actor, weight=weight,
                scope_id="atlas-g" if scope == "project" else None, parent_id=parent, branch_type=branch,
            ), db, embedding, tenant_id=TENANT, skip_curation=True)
            return created

    async def new_version(memory_id: uuid.UUID, content: str):
        async with sessions() as db:
            return await update_memory(memory_id, MemoryNodeUpdate(content=content), db, embedding,
                                       actor_id="alice", driver_id="alice")

    async def audit(event_type: str, actor: str, memory_id=None, minutes_ago: float = 0, **metadata):
        async with sessions() as db:
            db.add(AuditLog(event_type=event_type, actor_id=actor, driver_id=actor, scope="project",
                            owner_id="alice", memory_id=memory_id, decision="allowed", tenant_id=TENANT,
                            event_metadata=metadata or None,
                            timestamp=datetime.now(UTC) - timedelta(minutes=minutes_ago)))
            await db.commit()

    async def fetch(memory_id) -> MemoryNode:
        async with sessions() as db:
            return (await db.execute(select(MemoryNode).where(MemoryNode.id == memory_id))).scalar_one()

    async def fetch_count():
        async with sessions() as db:
            return (await db.execute(text("select count(*) from memory_nodes where tenant_id = :t"),
                                     {"t": TENANT})).scalar_one()

    async def owner_of(client_id):
        async with sessions() as db:
            return (await db.execute(select(AgentOwner.owner).where(
                AgentOwner.tenant_id == TENANT, AgentOwner.client_id == client_id))).scalar_one_or_none()

    async def events(prefix):
        async with sessions() as db:
            return list((await db.execute(select(AuditLog.event_type).where(
                AuditLog.tenant_id == TENANT, AuditLog.event_type.like(f"{prefix}%")).order_by(AuditLog.id))).scalars())

    act_as("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield {"http": http, "act_as": act_as, "seed": seed, "new_version": new_version, "audit": audit,
               "fetch": fetch, "fetch_count": fetch_count, "owner_of": owner_of, "events": events}
class FakeAuth:
    """The auth service admin API as the BFF uses it."""

    def __init__(self):
        self.clients = {
            "alice-agent": {"client_id": "alice-agent", "tenant_id": TENANT, "identity_type": "user", "active": True,
                            "client_name": "Alice agent", "default_scopes": ["memory:read"],
                            "last_used_at": "2026-11-20T10:00:00Z"},
            "old-laptop": {"client_id": "old-laptop", "tenant_id": TENANT, "identity_type": "user", "active": True,
                           "client_name": "Old laptop", "default_scopes": ["memory:read"]},
            "batch-svc": {"client_id": "batch-svc", "tenant_id": TENANT, "identity_type": "service", "active": True,
                          "client_name": "Batch", "default_scopes": ["memory:read"]},
        }
        self.secrets = {"old-laptop": "s3cret", "batch-svc": "svc"}
        self.keys: list[dict] = []
        self.calls: list[tuple] = []

    async def __call__(self, settings, method, path, json_body=None, tenant_id=None, owner=None):
        self.calls.append((method, path, json_body, owner))
        parts = path.split("/")
        client = self.clients.get(parts[3]) if len(parts) > 3 else None
        if path == "/admin/clients":
            return _Resp(list(self.clients.values()))
        if client is None or client["tenant_id"] != tenant_id:
            raise HTTPException(status_code=404, detail="Client not found")
        if path.endswith("/verify-secret"):
            return _Resp({"client_id": parts[3], "valid": json_body["client_secret"] == self.secrets.get(parts[3])})
        if path.endswith("/keys") and method == "GET":
            return _Resp(self.keys)
        if path.endswith("/keys") and method == "POST":
            key = {"id": "k1", "client_id": parts[3], "name": json_body["name"], "key_prefix": "mh-key-abcd",
                   "created_by": json_body["created_by"], "api_key": "mh-key-abcdef"}
            self.keys.append({k: v for k, v in key.items() if k != "api_key"})
            return _Resp(key)
        if "/keys/" in path and method == "DELETE":
            return _Resp({**self.keys[0], "revoked_at": "now"})
        return _Resp(client)


class _Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def auth(monkeypatch):
    fake = FakeAuth()
    monkeypatch.setattr("src.agents_adapter._admin_request", fake)
    monkeypatch.setattr("src.routes._admin_request", fake)

    async def reach(url):
        return True, "HTTP 200"

    monkeypatch.setattr("src.agents_adapter._reach", reach)
    return fake


async def test_connect_guide_shows_this_deployment_and_no_secret(env, auth):
    body = (await env["http"].get("/api/connect")).json()
    assert body["mcp_url"] == "https://mcp.example/mcp/" and body["auth_url"] == "https://auth.example"
    assert body["oauth"]["token_endpoint"] == "https://auth.example/token"
    assert body["agents"] == ["alice-agent"] and body["projects"] == ["atlas-g"] and body["tenant"] == TENANT
    assert "s3cret" not in str(body) and "secret" not in str(body).lower()


async def test_connection_check_runs_keeps_history_and_leaves_no_memory(env, auth):
    http = env["http"]
    run = await http.post("/api/verify/run")
    assert run.status_code == 200
    result = run.json()
    by_id = {c["id"]: c for c in result["checks"]}
    assert {k: by_id[k]["status"] for k in ("endpoint", "auth_service", "identity", "credentials", "tenant",
                                              "projects", "embedding", "storage")} == dict.fromkeys(
        ("endpoint", "auth_service", "identity", "credentials", "tenant", "projects", "embedding", "storage"), "pass")
    assert by_id["cross_session"]["status"] == "not_run" and result["summary"]["state"] == "partial"
    assert (await env["fetch_count"]()) == 0

    upload = await http.post("/api/verify/results", json={"result": {
        "schema": "memoryhub.verify/v1", "produced_by": {"tool": "memoryhub", "host": "claude-code"},
        "context": {"endpoint": "https://mcp.example/mcp/", "auth": "Bearer eyJabcdefgh.ijklmnopq.rstuvwxyz"},
        "checks": [{"id": "cross_session", "status": "fail", "code": "cross_session.not_recalled",
                    "explanation": "not recalled with key mh-dev-0123456789abcdef", "secret_field": "dropped"}]}})
    assert upload.status_code == 200 and upload.json()["source"] == "host"
    assert "secret_field" not in str(upload.json())
    assert "mh-dev-0123" not in str(upload.json()) and "eyJ" not in str(upload.json())
    assert upload.json()["checks"][0]["explanation"] == "not recalled with key [removed]"
    bad = await http.post("/api/verify/results", json={"result": {"schema": "other/v9", "checks": []}})
    assert bad.status_code == 422

    history = (await http.get("/api/verify")).json()
    assert [r["source"] for r in history["results"]] == ["host", "dashboard"]
    assert history["host_command"] is None and len(history["checks"]) == 10

    env["act_as"]("carol")
    assert (await http.get("/api/verify")).json()["results"] == []
    carol = (await http.post("/api/verify/run")).json()
    assert {c["id"]: c["status"] for c in carol["checks"]}["identity"] == "warn"


async def test_link_needs_the_client_secret(env, auth):
    http, act_as = env["http"], env["act_as"]
    act_as("bob")
    person = {"client_id": "carol", "client_secret": "x"}
    assert (await http.post("/api/identities/link", json=person)).status_code == 409
    assert (await http.post("/api/identities/link",
                            json={"client_id": "batch-svc", "client_secret": "svc"})).status_code == 403
    assert (await http.post("/api/identities/link",
                            json={"client_id": "nobody", "client_secret": "x"})).status_code == 404
    wrong = await http.post("/api/identities/link", json={"client_id": "old-laptop", "client_secret": "guess"})
    assert wrong.status_code == 403
    linked = await http.post("/api/identities/link", json={"client_id": "old-laptop", "client_secret": "s3cret"})
    assert linked.status_code == 200 and linked.json()["owner"] == "bob"
    assert await env["owner_of"]("old-laptop") == "bob"
    assert (await http.post("/api/identities/link",
                            json={"client_id": "old-laptop", "client_secret": "s3cret"})).status_code == 409
    act_as("carol")
    assert (await http.post("/api/identities/link",
                            json={"client_id": "old-laptop", "client_secret": "s3cret"})).status_code == 409
    events = await env["events"]("agent.")
    assert events == ["agent.link_denied", "agent.linked"]


async def test_named_keys_belong_to_the_agents_owner(env, auth):
    http, act_as = env["http"], env["act_as"]
    created = await http.post("/api/clients/alice-agent/keys", json={"name": "laptop"})
    assert created.status_code == 201 and created.json()["api_key"] == "mh-key-abcdef"
    assert ("POST", "/admin/clients/alice-agent/keys", {"name": "laptop", "created_by": "alice"}, "alice") in auth.calls
    listed = (await http.get("/api/clients/alice-agent/keys")).json()
    assert listed["can_manage"] and listed["items"][0]["name"] == "laptop" and "api_key" not in listed["items"][0]
    assert (await http.delete("/api/clients/alice-agent/keys/k1")).json()["revoked_at"] == "now"

    act_as("carol")
    assert (await http.get("/api/clients/alice-agent/keys")).status_code == 404
    assert (await http.post("/api/clients/alice-agent/keys", json={"name": "x"})).status_code == 404
    act_as("admin", "admin")
    assert (await http.post("/api/clients/alice-agent/keys", json={"name": "x"})).status_code == 403
    assert (await http.get("/api/clients/alice-agent/keys")).json()["can_manage"] is False
