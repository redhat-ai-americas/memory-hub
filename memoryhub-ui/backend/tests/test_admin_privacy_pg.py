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
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.entity import find_or_create_entity
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
        # CI sets MEMORYHUB_REQUIRE_PG=1: there the privacy boundary must be proven, never skipped.
        if os.environ.get("MEMORYHUB_REQUIRE_PG") == "1":
            pytest.fail("MEMORYHUB_REQUIRE_PG=1 but PostgreSQL is not reachable")
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
        for table in ("audit_log", "contradiction_reports", "memory_relationships", "memory_nodes",
                      "curator_rules"):
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
        private_entity, _ = await find_or_create_entity(
            "Dana private medical contact", "person", db, MockEmbeddingService(), tenant_id=TENANT, owner_id="dana",
        )
        db.add(MemoryRelationship(source_id=personal.id, target_id=private_entity.id,
                                  relationship_type="mentions", created_by="dana", tenant_id=TENANT))
        for src, dst in ((personal.id, shared.id), (shared.id, org.id)):
            db.add(MemoryRelationship(source_id=src, target_id=dst, relationship_type="related_to",
                                      created_by="dana", tenant_id=TENANT))
        # A personal curation rule: its name and pattern are personal data too.
        db.add(CuratorRule(name="dana-private-rule", trigger="on_write", tier="regex",
                           config={"pattern": "salary"}, action="flag", layer="user",
                           owner_id="dana", tenant_id=TENANT, priority=5, edited_by="dana"))
        await db.commit()

    act_as("admin", "admin")
    leaks = (str(personal.id), str(private_entity.id), "dana", "Dana private")
    checks = {
        "stats": await http.get("/api/stats"),
        "nav-counts": await http.get("/api/nav-counts"),
        "graph": await http.get("/api/graph/all"),
        "legacy graph": await http.get("/api/graph"),
        "graph search": await http.get("/api/graph/search", params={"q": "salary"}),
        "browse": await http.get("/api/memories/browse", params={"tab": "all", "per_page": 100}),
        "browse text": await http.get("/api/memories/browse", params={"q": "salary", "mode": "text"}),
        "export": await http.get("/api/memories/export", params={"tab": "all"}),
        "search": await http.post("/api/search", json={"query": "salary note"}),
        "contradictions": await http.get("/api/contradictions"),
        "entities": await http.get("/api/entities"),
        "rules": await http.get("/api/rules"),
        "personal rules": await http.get("/api/rules", params={"layer": "user"}),
    }
    with patch("src.routes._admin_request", new_callable=AsyncMock, return_value=_Clients()):
        checks["users"] = await http.get("/api/users")
    for name, response in checks.items():
        # Entities are not an admin view at all (403); every other path answers without the memory.
        assert response.status_code in ((403,) if name == "entities" else (200,)), (name, response.text[:200])
        for leak in leaks:
            assert leak not in response.text, f"{name} reveals {leak!r}"

    for path in (f"/api/memory/{personal.id}", f"/api/memory/{personal.id}/history",
                 f"/api/memory/{personal.id}/context", f"/api/graph/neighbourhood?focus={personal.id}",
                 f"/api/memory/{private_entity.id}", f"/api/memory/{private_entity.id}/context"):
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
    assert "dana-private-rule" in (await http.get("/api/rules")).text


async def test_admin_sees_no_individual_activity(env):
    """No per-person counts, last-active times, recent-activity authors or per-person filters (#667)."""
    http, seed, act_as = env["http"], env["seed"], env["act_as"]
    await seed("Atlas gripper torque limit is 11.5 Nm", owner="alice", actor="alice")
    await seed("Atlas camera mount moved to rail B", owner="carol", actor="carol")

    act_as("admin", "admin")
    with patch("src.routes._admin_request", new_callable=AsyncMock, return_value=_Clients()):
        users = await http.get("/api/users")
    assert users.status_code == 200
    assert all(u["memory_count"] is None and u["last_active"] is None for u in users.json())

    browse = (await http.get("/api/memories/browse", params={"tab": "all"})).json()
    assert browse["total"] == 2
    assert browse["facets"]["writers"] == []
    by_owner = (await http.get("/api/memories/browse", params={"q": "alice", "mode": "metadata"})).json()
    assert by_owner["total"] == 0
    graph_by_owner = (await http.get("/api/graph/all", params={"q": "alice", "mode": "metadata"})).json()
    assert graph_by_owner["total"] == 0

    stats = (await http.get("/api/stats")).json()
    assert stats["recent_activity"] and all(a["owner_id"] is None for a in stats["recent_activity"])

    for response in (
        await http.get("/api/memories/browse", params={"actor": "alice"}),
        await http.get("/api/graph/all", params={"actor": "alice"}),
        await http.get("/api/memories/export", params={"actor": "alice"}),
        await http.get("/api/graph", params={"owner_id": "alice"}),
        await http.post("/api/search", json={"query": "gripper", "identity": "alice"}),
    ):
        assert response.status_code == 403, response.request.url

    # A user still sees their own activity.
    act_as("alice")
    mine = (await http.get("/api/memories/browse", params={"tab": "all"})).json()
    assert {"value": "alice", "count": 1} in mine["facets"]["writers"]
    assert (await http.get("/api/memories/browse", params={"actor": "alice"})).status_code == 200


async def test_admin_memory_attribution_is_redacted_across_projections(env):
    http, seed = env["http"], env["seed"]
    shared = await seed("Gripper torque specification", weight=0.9)
    other = await seed("Camera mount specification", owner="carol", actor="carol", weight=0.9)
    await seed("Supporting evidence", parent=shared.id, branch="evidence")
    async with env["sessions"]() as db:
        db.add(MemoryRelationship(source_id=shared.id, target_id=other.id, relationship_type="related_to",
                                  created_by="carol", tenant_id=TENANT))
        db.add(ContradictionReport(memory_id=shared.id, observed_behavior="Conflicting measurement",
                                   confidence=0.9, reporter="carol", tenant_id=TENANT))
        policy = CuratorRule(name="Shared policy", trigger="on_write", tier="regex", config={}, action="flag",
                             layer="organizational", tenant_id=TENANT, priority=5, edited_by="carol")
        db.add(policy)
        await db.commit()
        policy_id = policy.id
    env["act_as"]("admin", "admin")
    paths = ["/api/graph", "/api/graph/all", "/api/stats", "/api/memories/browse", "/api/memories/export",
             "/api/contradictions", "/api/rules", f"/api/rules/{policy_id}/history",
             f"/api/memory/{shared.id}", f"/api/memory/{shared.id}/history", f"/api/memory/{shared.id}/context",
             f"/api/graph/neighbourhood?focus={shared.id}"]
    responses = [await http.get(path) for path in paths]
    responses.append(await http.post("/api/search", json={"query": "specification"}))
    for response in responses:
        assert response.status_code == 200, (response.request.url, response.text)
        for identity in ("alice", "carol"):
            assert identity not in response.text, (response.request.url, identity)
    env["act_as"]("alice")
    response = await http.get(f"/api/memory/{shared.id}/context")
    assert response.status_code == 200 and response.json()["memory"]["owner_id"] == "alice"


async def test_parent_versioning_skips_retired_and_deleted_branches(env):
    http = env["http"]
    parent = await env["seed"]("Original specification")
    branch = await http.post(f"/api/memory/{parent.id}/branches",
                             json={"branch_type": "evidence", "content": "Original evidence"})
    assert branch.status_code == 201, branch.text
    revised = await http.post(f"/api/memory/{branch.json()['id']}/versions", json={"content": "Revised evidence"})
    assert revised.status_code == 201, revised.text
    removed = await env["seed"]("Removed evidence", parent=parent.id, branch="evidence")
    deleted = await http.delete(f"/api/memory/{removed.id}")
    assert deleted.status_code == 204, deleted.text
    context = await http.get(f"/api/memory/{parent.id}/context")
    assert [row["id"] for row in context.json()["branches"]] == [revised.json()["id"]]
    detail = await http.get(f"/api/memory/{parent.id}")
    assert detail.json()["children_count"] == 1
    browse = await http.get("/api/memories/browse")
    row = next(item for item in browse.json()["items"] if item["id"] == str(parent.id))
    assert row["branch_count"] == 1
    updated = await http.post(f"/api/memory/{parent.id}/versions", json={"content": "Revised specification"})
    assert updated.status_code == 201, updated.text
    async with env["sessions"]() as db:
        children = (await db.execute(select(MemoryNode).where(
            MemoryNode.parent_id == uuid.UUID(updated.json()["id"]),
        ))).scalars().all()
    assert len(children) == 1
    assert children[0].content == "Revised evidence"
    assert children[0].scope_id == "atlas-p" and children[0].is_current
    old_context = await http.get(f"/api/memory/{parent.id}/context")
    assert old_context.json()["branches"] == []
    for path in ("/api/memories/browse", "/api/graph/all"):
        for selection in ({"branch_type": "evidence"}, {"flag": "has_branches"}):
            filtered = await http.get(path, params={"tab": "all", **selection})
            assert filtered.status_code == 200, filtered.text
            rows = filtered.json().get("items", filtered.json().get("nodes"))
            assert {item["id"] for item in rows} == {updated.json()["id"]}
    browse = await http.get("/api/memories/browse", params={"tab": "all"})
    old = next(item for item in browse.json()["items"] if item["id"] == str(parent.id))
    assert old["branch_count"] == 0
