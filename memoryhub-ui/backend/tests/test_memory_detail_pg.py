"""Memory detail page against a real PostgreSQL + pgvector database.

Covers what mocked sessions cannot check: the version chain by logical_id,
JSONB containment over audit_log, and the restore of a deleted version chain.

Uses the repository's integration database (tests/integration/compose.yaml,
localhost:15433) and skips when it is not reachable:

    podman compose -f tests/integration/compose.yaml up -d
    cd memoryhub-ui/backend && pytest tests/test_memory_detail_pg.py
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

from src.authorization import Access, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import get_embedding_service
from src.main import app

TENANT = "tenant-detail"
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
        for table in ("audit_log", "contradiction_reports", "memory_relationships", "memory_nodes"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": TENANT})
        await conn.execute(text("delete from project_memberships where project_id = 'atlas-d'"))
        await conn.execute(text("delete from projects where name = 'atlas-d'"))
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as db:
        db.add(Project(name="atlas-d", tenant_id=TENANT, created_by="bob"))
        await db.flush()
        for user, role in (("alice", "member"), ("bob", "admin"), ("carol", "member")):
            db.add(ProjectMembership(project_id="atlas-d", user_id=user, role=role, joined_by="bob"))
        await db.commit()
    embedding = MockEmbeddingService()
    who = {"access": None}

    async def db_dep():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_access] = lambda: who["access"]
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id=TENANT, embedding_url="mock")
    app.dependency_overrides[get_embedding_service] = lambda: embedding

    def act_as(name: str, role: str = "user") -> None:
        grants = {
            "alice": {"human_projects": {"atlas-d"}, "agents": {"alice-agent"}},
            "bob": {"human_projects": {"atlas-d"}, "human_project_admins": {"atlas-d"}},
            "carol": {"human_projects": {"atlas-d"}},
            "admin": {"human_projects": {"atlas-d"}, "human_project_admins": {"atlas-d"},
                      "moderation_scopes": {"project", "organizational"}},
        }[name]
        who["access"] = Access(principal=Principal(name, role, TENANT), **grants)

    async def seed(content: str, *, scope: str = "project", owner: str = "alice", actor: str = "alice-agent",
                   weight: float = 0.5, parent: uuid.UUID | None = None, branch: str | None = None) -> MemoryNode:
        async with sessions() as db:
            created, _ = await create_memory(MemoryNodeCreate(
                content=content, scope=scope, owner_id=owner, actor_id=actor, weight=weight,
                scope_id="atlas-d" if scope == "project" else None, parent_id=parent, branch_type=branch,
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

    act_as("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield {"http": http, "act_as": act_as, "seed": seed, "new_version": new_version, "audit": audit,
               "fetch": fetch}
    app.dependency_overrides.clear()


async def test_access_log_covers_every_version_and_searches_and_is_for_authors_and_admins(env):
    http, seed, audit = env["http"], env["seed"], env["audit"]
    v1 = await seed("Torque limit 11 Nm")
    v2 = await env["new_version"](v1.id, "Torque limit 11.5 Nm")
    other = await seed("Unrelated memory")
    await audit("memory.read", "bob-agent", v1.id, minutes_ago=90)
    await audit("memory.read", "carol-agent", v2.id, minutes_ago=10, purpose="answering_question")
    await audit("memory.served", "carol-agent", minutes_ago=12, result_ids=[str(v2.id), str(other.id)],
                full_ids=[], query="secret question")
    await audit("memory.served", "dave-agent", minutes_ago=5, result_ids=[str(other.id)])

    body = (await http.get(f"/api/memory/{v2.id}/access-log")).json()
    assert body["total"] == 3
    # the page's "Access log N" badge counts the same events the log lists
    assert (await http.get(f"/api/memory/{v2.id}/context")).json()["access_count"] == 3
    assert [(e["operation"], e["actor_id"]) for e in body["items"]] == [
        ("memory.read", "carol-agent"), ("memory.search", "carol-agent"), ("memory.read", "bob-agent"),
    ]
    assert body["items"][0]["metadata"] == {"purpose": "answering_question"}
    assert body["items"][1]["metadata"] == {"full": False}  # the search text never leaves the log
    assert body["items"][2]["memory_version"] == 1

    reads = (await http.get(f"/api/memory/{v2.id}/access-log", params={"reads_only": True, "days": 1})).json()
    assert {e["event_type"] for e in reads["items"]} == {"memory.read", "memory.served"}

    env["act_as"]("carol")  # a member reads the memory but not who else did
    assert (await http.get(f"/api/memory/{v2.id}/access-log")).status_code == 403
    context = (await http.get(f"/api/memory/{v2.id}/context")).json()
    assert context["memory"]["can_view_access"] is False
    env["act_as"]("bob")  # the project admin does
    assert (await http.get(f"/api/memory/{v2.id}/access-log")).status_code == 200


async def test_usage_counts_served_used_skipped_and_full(env):
    http, seed, audit = env["http"], env["seed"], env["audit"]
    memory = await seed("Deploy window is Wednesday", weight=0.5)
    mid = str(memory.id)
    await audit("memory.served", "a1", minutes_ago=60, result_ids=[mid], full_ids=[])
    await audit("memory.read", "a1", memory.id, minutes_ago=50)  # acted on within 30 minutes
    await audit("memory.served", "a2", minutes_ago=40, result_ids=[mid], full_ids=[])  # skipped
    await audit("memory.served", "a3", minutes_ago=20, result_ids=[mid], full_ids=[mid])  # full text
    await audit("memory.served", "a4", minutes_ago=60 * 24 * 40, result_ids=[mid])  # outside 30 days
    env["act_as"]("carol")  # counts are for everyone who reads the memory
    body = (await http.get(f"/api/memory/{mid}/usage")).json()
    assert (body["served"], body["used"], body["skipped"], body["full"]) == (3, 1, 1, 1)
    assert body["use_rate"] == 0.5 and body["full_text"] is False and body["last"] is not None


async def test_deleted_memory_page_and_restore(env):
    http, seed = env["http"], env["seed"]
    v1 = await seed("Calibration procedure v1")
    v2 = await env["new_version"](v1.id, "Calibration procedure v2")
    branch = await seed("Rationale: sensor drift", parent=v2.id, branch="rationale", actor="alice")
    assert (await http.delete(f"/api/memory/{v2.id}")).status_code in (200, 204)

    context = (await http.get(f"/api/memory/{v2.id}/context")).json()
    memory = context["memory"]
    assert memory["deleted_at"] and memory["can_restore"] is True and memory["redacted"] is False
    assert memory["capabilities"] == {"write": False, "moderate": False} and memory["can_delete"] is False
    assert [v["version"] for v in context["versions"]] == [2, 1]
    assert [b["id"] for b in context["branches"]] == [str(branch.id)]

    env["act_as"]("carol")  # a member who did not write it cannot see the deleted memory
    assert (await http.get(f"/api/memory/{v2.id}/context")).status_code == 404
    assert (await http.post(f"/api/memory/{v2.id}/restore")).status_code == 404

    env["act_as"]("alice")
    response = await http.post(f"/api/memory/{v2.id}/restore")
    assert response.json() == {"id": str(v2.id), "restored_rows": 3}
    assert (await env["fetch"](v2.id)).is_current is True
    assert (await env["fetch"](v1.id)).is_current is False
    assert (await env["fetch"](branch.id)).is_current is True
    assert (await http.post(f"/api/memory/{v2.id}/restore")).status_code == 409
    context = (await http.get(f"/api/memory/{v2.id}/context")).json()
    assert context["memory"]["deleted_at"] is None and context["memory"]["capabilities"]["write"] is True
