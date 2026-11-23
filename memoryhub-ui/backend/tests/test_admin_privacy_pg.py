"""Admin privacy boundary (#667, PR 710 review) against a real PostgreSQL + pgvector database.

A personal (user-scope) memory must not reach an administrator through any
dashboard path: no content, and no metadata either (ID, owner, timestamps,
counts, graph nodes or edges, browse or export rows).

Uses the repository's integration database (tests/integration/compose.yaml,
localhost:15433) and skips when it is not reachable:

    podman compose -f tests/integration/compose.yaml up -d
    cd memoryhub-ui/backend && pytest tests/test_admin_privacy_pg.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
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

TENANT = "tenant-privacy"
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
        await conn.execute(text("delete from project_memberships where project_id = 'atlas-p'"))
        await conn.execute(text("delete from projects where name = 'atlas-p'"))
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as db:
        db.add(Project(name="atlas-p", tenant_id=TENANT, created_by="bob"))
        await db.flush()
        for user, role in (("alice", "member"), ("bob", "admin"), ("carol", "member")):
            db.add(ProjectMembership(project_id="atlas-p", user_id=user, role=role, joined_by="bob"))
        await db.commit()
    embedding = MockEmbeddingService()
    who = {"access": None}

    async def db_dep():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_access] = lambda: who["access"]
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id=TENANT, embedding_url="mock", mcp_server_url="http://127.0.0.1:9/")
    app.dependency_overrides[get_embedding_service] = lambda: embedding

    def act_as(name: str, role: str = "user") -> None:
        grants = {
            "alice": {"human_projects": {"atlas-p"}, "agents": {"alice-agent"}},
            "dana": {},
            "bob": {"human_projects": {"atlas-p"}, "human_project_admins": {"atlas-p"}},
            "carol": {"human_projects": {"atlas-p"}},
            "admin": {"human_projects": {"atlas-p"}, "human_project_admins": {"atlas-p"},
                      "moderation_scopes": {"project", "organizational"}},
        }[name]
        who["access"] = Access(principal=Principal(name, role, TENANT), **grants)

    async def seed(content: str, *, scope: str = "project", owner: str = "alice", actor: str = "alice-agent",
                   weight: float = 0.5, parent: uuid.UUID | None = None, branch: str | None = None) -> MemoryNode:
        async with sessions() as db:
            created, _ = await create_memory(MemoryNodeCreate(
                content=content, scope=scope, owner_id=owner, actor_id=actor, weight=weight,
                scope_id="atlas-p" if scope == "project" else None, parent_id=parent, branch_type=branch,
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
               "fetch": fetch, "sessions": sessions}
class _Clients:
    def json(self):
        return []


async def test_no_admin_path_reveals_a_personal_memory(env):
    http, seed, act_as = env["http"], env["seed"], env["act_as"]
    personal = await seed("Dana private salary note", scope="user", owner="dana", actor="dana", weight=0.9)
    await env["new_version"](personal.id, "Dana private salary note, revised")
    shared = await seed("Atlas gripper torque limit is 11.5 Nm", weight=0.9)
    org = await seed("All deploys need a change ticket", scope="organizational", owner="admin", actor="admin")
    async with env["sessions"]() as db:
        for src, dst in ((personal.id, shared.id), (shared.id, org.id)):
            db.add(MemoryRelationship(source_id=src, target_id=dst, relationship_type="related_to",
                                      created_by="dana", tenant_id=TENANT))
        await db.commit()

    act_as("admin", "admin")
    leaks = (str(personal.id), "dana", "Dana private")
    checks = {
        "stats": await http.get("/api/stats"),
        "nav-counts": await http.get("/api/nav-counts"),
        "graph": await http.get("/api/graph/all"),
        "graph search": await http.get("/api/graph/search", params={"q": "salary"}),
        "browse": await http.get("/api/memories/browse", params={"tab": "all", "per_page": 100}),
        "browse text": await http.get("/api/memories/browse", params={"q": "salary", "mode": "text"}),
        "export": await http.get("/api/memories/export", params={"tab": "all"}),
        "search": await http.post("/api/search", json={"query": "salary note"}),
        "contradictions": await http.get("/api/contradictions"),
        "entities": await http.get("/api/entities"),
    }
    with patch("src.routes._admin_request", new_callable=AsyncMock, return_value=_Clients()):
        checks["users"] = await http.get("/api/users")
    for name, response in checks.items():
        # Entities are not an admin view at all (403); every other path answers without the memory.
        assert response.status_code in ((403,) if name == "entities" else (200,)), (name, response.text[:200])
        for leak in leaks:
            assert leak not in response.text, f"{name} reveals {leak!r}"

    for path in (f"/api/memory/{personal.id}", f"/api/memory/{personal.id}/history",
                 f"/api/memory/{personal.id}/context", f"/api/graph/neighbourhood?focus={personal.id}"):
        response = await http.get(path)
        assert response.status_code == 404, path
        assert "dana" not in response.text

    stats = checks["stats"].json()
    assert "user" not in {row["scope"] for row in stats["scope_counts"]}
    assert stats["total_memories"] == 2
    graph = checks["graph"].json()
    assert {n["id"] for n in graph["nodes"]} == {str(shared.id), str(org.id)}
    assert all(str(personal.id) not in (e["source"], e["target"]) for e in graph["edges"])

    # The owner still sees it all.
    act_as("alice")
    assert str(personal.id) not in (await http.get("/api/memories/browse", params={"tab": "all"})).text
    act_as("dana")
    mine = await http.get("/api/memories/browse", params={"tab": "all"})
    assert str(personal.id) in mine.text
