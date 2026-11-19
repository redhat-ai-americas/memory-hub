"""Memory browser against a real PostgreSQL + pgvector database.

The other BFF tests mock the session, which cannot check SQL that only
PostgreSQL runs: cosine distance, array overlap, the deleted-head filter, the
restore of a version chain. These tests run every browser route end to end.

They use the repository's integration database (tests/integration/compose.yaml,
localhost:15433) and skip when it is not reachable:

    podman compose -f tests/integration/compose.yaml up -d
    cd memoryhub-ui/backend && pytest tests/test_memory_browser_pg.py

Override the connection with MEMORYHUB_DB_HOST / _PORT / _USER / _PASSWORD / _NAME.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.schemas import MemoryNodeCreate
from memoryhub_core.services.admin import quarantine_memory
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import create_memory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.authorization import Access, Principal, get_access
from src.browse_filters import get_optional_embedding
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import get_embedding_service
from src.main import app

TENANT = "tenant-browser"
REPO = Path(__file__).resolve().parents[3]


def _url(driver: str) -> str:
    env = os.environ.get
    return (f"postgresql+{driver}://{env('MEMORYHUB_DB_USER', 'memoryhub')}:"
            f"{env('MEMORYHUB_DB_PASSWORD', 'memoryhub-test')}@{env('MEMORYHUB_DB_HOST', 'localhost')}:"
            f"{env('MEMORYHUB_DB_PORT', '15433')}/{env('MEMORYHUB_DB_NAME', 'memoryhub')}")


@pytest.fixture(scope="module")
def database():
    engine = create_async_engine(_url("asyncpg"), poolclass=NullPool)

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
    """A clean tenant, a project 'atlas' (alice member, bob admin) and an API client."""
    async with database.begin() as conn:
        for table in ("contradiction_reports", "memory_relationships", "memory_nodes"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": TENANT})
        await conn.execute(text("delete from project_memberships where project_id in ('atlas', 'other')"))
        await conn.execute(text("delete from projects where name in ('atlas', 'other')"))
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as db:
        for name in ("atlas", "other"):
            db.add(Project(name=name, tenant_id=TENANT, created_by="bob"))
        await db.flush()
        db.add(ProjectMembership(project_id="atlas", user_id="alice", role="member", joined_by="bob"))
        db.add(ProjectMembership(project_id="atlas", user_id="bob", role="admin", joined_by="bob"))
        db.add(ProjectMembership(project_id="other", user_id="bob", role="admin", joined_by="bob"))
        await db.commit()

    embedding = MockEmbeddingService()
    who = {"access": None}

    async def db_dep():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_access] = lambda: who["access"]
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id=TENANT, embedding_url="mock")
    app.dependency_overrides[get_optional_embedding] = lambda: embedding
    app.dependency_overrides[get_embedding_service] = lambda: embedding

    def act_as(name: str, role: str = "user", **grants) -> None:
        defaults = {"alice": {"human_projects": {"atlas"}, "agents": {"alice-agent"}},
                    "bob": {"human_projects": {"atlas", "other"}, "human_project_admins": {"atlas", "other"}},
                    "admin": {"human_projects": {"atlas"}, "human_project_admins": {"atlas"},
                              "moderation_scopes": {"project", "organizational"}}}
        who["access"] = Access(principal=Principal(name, role, TENANT), **{**defaults.get(name, {}), **grants})

    async def seed(content: str, *, scope: str = "user", owner: str = "alice", scope_id: str | None = None,
                   actor: str | None = None, weight: float = 0.7, domains: list[str] | None = None,
                   parent: uuid.UUID | None = None, branch: str | None = None) -> uuid.UUID:
        async with sessions() as db:
            created, _ = await create_memory(MemoryNodeCreate(
                content=content, scope=scope, owner_id=owner, scope_id=scope_id, actor_id=actor or owner,
                weight=weight, domains=domains, parent_id=parent, branch_type=branch,
            ), db, embedding, tenant_id=TENANT, skip_curation=True)
            return created.id

    async def fetch(memory_id: uuid.UUID) -> MemoryNode:
        async with sessions() as db:
            return (await db.execute(select(MemoryNode).where(MemoryNode.id == memory_id))).scalar_one()

    act_as("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield {"http": http, "act_as": act_as, "seed": seed, "fetch": fetch, "sessions": sessions}
    app.dependency_overrides.clear()


async def test_semantic_search_ranks_by_meaning_and_text_mode_matches_words(env):
    http, seed = env["http"], env["seed"]
    torque = await seed("Atlas gripper torque limit is 11.5 Nm for the left arm")
    await seed("Team lunch on Friday is pasta at the canteen")
    await seed("Bob's private gripper torque notes", owner="bob")  # not Alice's

    body = (await http.get("/api/memories/browse", params={"q": "gripper torque limit", "sort": "relevance"})).json()
    assert body["search_mode"] == "semantic"
    assert [item["id"] for item in body["items"]] == [str(torque)]
    assert body["items"][0]["score"] >= 0.3  # SEMANTIC_MIN_SIMILARITY; the lunch note scores below it

    body = (await http.get("/api/memories/browse", params={"q": "pasta", "mode": "text"})).json()
    assert body["search_mode"] == "text"
    assert [item["stub"][:9] for item in body["items"]] == ["Team lunc"]


async def test_sort_by_version_and_bulk_weight_creates_new_versions(env):
    http, seed = env["http"], env["seed"]
    first = await seed("Deploy window is Tuesday 10:00", weight=0.5)
    second = await seed("Release notes live in the wiki", weight=0.5)
    response = await http.post("/api/memories/bulk", json={"action": "weight", "ids": [str(first)], "weight": 0.9})
    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    body = (await http.get("/api/memories/browse", params={"sort": "version"})).json()
    assert [(item["version"], item["weight"]) for item in body["items"]] == [(2, 0.9), (1, 0.5)]
    assert (await env["fetch"](first)).is_current is False

    # A memory Alice cannot write is refused before anything changes.
    foreign = await seed("Bob's memory", owner="bob")
    response = await http.post("/api/memories/bulk", json={
        "action": "weight", "ids": [str(second), str(foreign)], "weight": 0.2,
    })
    assert response.status_code == 404
    assert (await env["fetch"](second)).weight == 0.5


async def test_near_duplicate_flag_facet_and_score(env):
    http, seed = env["http"], env["seed"]
    a = await seed("The staging database password rotates every 30 days")
    b = await seed("The staging database password rotates every 30 days", scope="project", scope_id="atlas",
                   owner="alice")
    await seed("Coffee machine is on floor 3")
    await seed("The staging database password rotates every 30 days", owner="bob")  # invisible to Alice

    body = (await http.get("/api/memories/browse", params={"flag": "near_duplicate"})).json()
    assert sorted(item["id"] for item in body["items"]) == sorted([str(a), str(b)])
    assert all(item["near_duplicate"] >= 0.9 for item in body["items"])
    assert body["facets"]["flags"]["near_duplicate"] == 2

    # An admin never gets a near-duplicate signal for a personal memory.
    env["act_as"]("admin", "admin")
    body = (await http.get("/api/memories/browse", params={"flag": "near_duplicate"})).json()
    assert [item["id"] for item in body["items"]] == []
    body = (await http.get("/api/memories/browse")).json()
    personal = [item for item in body["items"] if item["scope"] == "user"]
    assert personal and all(item["near_duplicate"] is None and item["redacted"] for item in personal)


async def test_delete_reports_closure_and_user_restores_from_deleted_tab(env):
    http, seed = env["http"], env["seed"]
    root = await seed("Gripper calibration procedure v1")
    await http.post("/api/memories/bulk", json={"action": "weight", "ids": [str(root)], "weight": 0.8})
    current = (await http.get("/api/memories/browse")).json()["items"][0]
    head = uuid.UUID(current["id"])
    await seed("Rationale: the old sensor drifted", parent=head, branch="rationale")

    response = await http.post("/api/memories/bulk", json={"action": "delete", "ids": [str(head)]})
    assert response.status_code == 200, response.text
    assert response.json()["forgotten"] == [{
        "id": str(head), "scope": "user", "scope_id": None, "owner_id": "alice",
        "versions": 2, "branches": 1, "rows": 3,
    }]

    body = (await http.get("/api/memories/browse", params={"tab": "deleted"})).json()
    assert body["tab_counts"]["deleted"] == 1
    assert [item["id"] for item in body["items"]] == [str(head)]
    assert body["items"][0]["can_restore"] is True
    assert body["items"][0]["content_preview"].startswith("Gripper calibration")

    # Bob cannot see or restore Alice's personal delete.
    env["act_as"]("bob")
    assert (await http.get("/api/memories/browse", params={"tab": "deleted"})).json()["items"] == []
    assert (await http.post("/api/memories/bulk", json={"action": "restore", "ids": [str(head)]})).status_code == 404

    env["act_as"]("alice")
    response = await http.post("/api/memories/bulk", json={"action": "restore", "ids": [str(head)]})
    assert response.status_code == 200, response.text
    assert response.json()["restored"][0]["rows"] == 3
    body = (await http.get("/api/memories/browse")).json()
    rows = {item["id"]: item for item in body["items"]}
    assert len(rows) == 2  # the memory and its branch are current again
    assert rows[str(head)]["branch_count"] == 1 and rows[str(head)]["version"] == 2
    assert (await env["fetch"](root)).is_current is False  # v1 stays superseded
    assert body["tab_counts"]["deleted"] == 0


async def test_branch_deleted_on_its_own_stays_deleted_when_parent_is_restored(env):
    http, seed = env["http"], env["seed"]
    parent = await seed("Lab access hours are 8 to 18")
    branch = await seed("Exception: weekends need a badge", parent=parent, branch="exception")
    assert (await http.post("/api/memories/bulk", json={"action": "delete", "ids": [str(branch)]})).status_code == 200
    assert (await http.post("/api/memories/bulk", json={"action": "delete", "ids": [str(parent)]})).status_code == 200
    deleted = (await http.get("/api/memories/browse", params={"tab": "deleted"})).json()["items"]
    assert sorted(item["id"] for item in deleted) == sorted([str(parent), str(branch)])
    assert (await http.post("/api/memories/bulk", json={"action": "restore", "ids": [str(parent)]})).status_code == 200
    assert (await env["fetch"](branch)).deleted_at is not None
    assert (await env["fetch"](parent)).deleted_at is None


async def test_user_quarantined_tab_lists_own_writes_only(env):
    http, seed, sessions = env["http"], env["seed"], env["sessions"]
    mine = await seed("My agent wrote a customer contract number", scope="project", scope_id="atlas",
                      owner="alice", actor="alice-agent")
    theirs = await seed("Bob wrote something odd", scope="project", scope_id="atlas", owner="bob")
    async with sessions() as db:
        for memory_id in (mine, theirs):
            await quarantine_memory(db, memory_id=memory_id, tenant_id=TENANT, actor_id="bob", reason="test")
    body = (await http.get("/api/memories/browse", params={"tab": "quarantined"})).json()
    assert [item["id"] for item in body["items"]] == [str(mine)]
    assert body["items"][0]["redacted"] is False
    assert body["tab_counts"]["quarantined"] == 1
    # A user cannot lift a quarantine.
    assert (await http.post("/api/memories/bulk", json={"action": "restore", "ids": [str(mine)]})).status_code == 403


async def test_promote_copies_into_a_project_with_derived_from(env):
    http, seed, sessions = env["http"], env["seed"], env["sessions"]
    source = await seed("Use torque 11.5 Nm on the Atlas gripper")
    refused = await http.post("/api/memories/bulk", json={
        "action": "promote", "ids": [str(source)], "target_scope": "project", "target_scope_id": "other",
    })
    assert refused.status_code == 403
    response = await http.post("/api/memories/bulk", json={
        "action": "promote", "ids": [str(source)], "target_scope": "project", "target_scope_id": "atlas",
    })
    assert response.status_code == 200, response.text
    copy = uuid.UUID(response.json()["done"][0])
    node = await env["fetch"](copy)
    assert (node.scope, node.scope_id, node.owner_id) == ("project", "atlas", "alice")
    async with sessions() as db:
        link = (await db.execute(select(MemoryRelationship).where(
            MemoryRelationship.source_id == copy, MemoryRelationship.target_id == source,
        ))).scalar_one()
    assert link.relationship_type == "derived_from"
    # Bob, an atlas member, now reads it; the personal source stays Alice's.
    env["act_as"]("bob")
    ids = [item["id"] for item in (await http.get("/api/memories/browse")).json()["items"]]
    assert str(copy) in ids and str(source) not in ids


async def test_timeline_window_order_and_truncation(env):
    http, seed, sessions = env["http"], env["seed"], env["sessions"]
    old = await seed("Old decision about the gripper", domains=["hardware"])
    recent = [await seed(f"Recent note {i} about the gripper", domains=["hardware"]) for i in range(3)]
    async with sessions() as db:
        await db.execute(text("update memory_nodes set created_at = now() - interval '60 days' where id = :i"),
                         {"i": old})
        await db.commit()
    body = (await http.get("/api/memories/timeline", params={"days": 30})).json()
    assert body["total"] == 3 and body["truncated"] is False and body["by"] == "created"
    assert {item["id"] for item in body["items"]} == {str(i) for i in recent}
    body = (await http.get("/api/memories/timeline", params={"max_items": 2, "domain": "hardware"})).json()
    assert body["total"] == 4 and body["truncated"] is True and len(body["items"]) == 2
    assert body["first"] is not None and body["first"] < body["items"][-1]["at"]
    assert str(old) not in {item["id"] for item in body["items"]}  # newest first


async def test_graph_and_export_use_the_same_filters(env):
    http, seed = env["http"], env["seed"]
    a = await seed("Shared fact about valves", domains=["plant"])
    await seed("Another fact about pumps", domains=["ops"])
    graph = (await http.get("/api/graph/all", params={"domain": "plant"})).json()
    assert [node["id"] for node in graph["nodes"]] == [str(a)]
    exported = (await http.get("/api/memories/export", params={"q": "valves"})).text.splitlines()
    assert len(exported) == 1 and str(a) in exported[0]
    deleted = (await http.get("/api/graph/all", params={"tab": "deleted"}))
    assert deleted.status_code == 200 and deleted.json()["nodes"] == []
