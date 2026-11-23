"""Search playground (#714) against a real PostgreSQL + pgvector database.

Runs Core retrieval for real (deterministic mock embeddings): the funnel and
its drops, explain, the routing search_memory uses, and the text fallback.

Uses the repository's integration database (tests/integration/compose.yaml,
localhost:15433) and skips when it is not reachable:

    podman compose -f tests/integration/compose.yaml up -d
    cd memoryhub-ui/backend && pytest tests/test_search_playground_pg.py
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
from memoryhub_core.models.audit import AuditLog  # noqa: F401
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

TENANT = "tenant-search"
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
        await conn.execute(text("delete from project_memberships where project_id = 'atlas-s'"))
        await conn.execute(text("delete from projects where name = 'atlas-s'"))
    sessions = async_sessionmaker(database, expire_on_commit=False)
    async with sessions() as db:
        db.add(Project(name="atlas-s", tenant_id=TENANT, created_by="bob"))
        await db.flush()
        for user, role in (("alice", "member"), ("bob", "admin"), ("carol", "member")):
            db.add(ProjectMembership(project_id="atlas-s", user_id=user, role=role, joined_by="bob"))
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
            "alice": {"human_projects": {"atlas-s"}, "agents": {"alice-agent"}},
            "bob": {"human_projects": {"atlas-s"}, "human_project_admins": {"atlas-s"}},
            "carol": {"human_projects": {"atlas-s"}},
            "admin": {"human_projects": {"atlas-s"}, "human_project_admins": {"atlas-s"},
                      "moderation_scopes": {"project", "organizational"}},
        }[name]
        who["access"] = Access(principal=Principal(name, role, TENANT), **grants)

    async def seed(content: str, *, scope: str = "project", owner: str = "alice", actor: str = "alice-agent",
                   weight: float = 0.5, parent: uuid.UUID | None = None, branch: str | None = None,
                   content_type: str = "experiential", domains: list[str] | None = None) -> MemoryNode:
        async with sessions() as db:
            created, _ = await create_memory(MemoryNodeCreate(
                content=content, scope=scope, owner_id=owner, actor_id=actor, weight=weight,
                scope_id="atlas-s" if scope == "project" else None, parent_id=parent, branch_type=branch,
                content_type=content_type, domains=domains,
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
               "fetch": fetch, "embedding": embedding}
class DownEmbedding:
    max_tokens = 512

    async def embed(self, text):
        raise ConnectionError("embedding service down")


async def test_search_runs_core_and_reports_the_funnel(env):
    http, seed = env["http"], env["seed"]
    heavy = await seed("Gripper torque limit is 11.5 Nm on the left arm", weight=0.9)
    light = await seed("Gripper torque was measured at 11 Nm last week", weight=0.4)
    await seed("Gripper notes for the planner", weight=0.9, parent=heavy.id, branch="rationale")
    carol = await seed("Carol gripper torque secret", scope="user", owner="carol", actor="carol", weight=0.9)
    for i in range(4):
        await seed(f"Gripper torque calibration step {i}", weight=0.9)

    body = (await http.post("/api/search", json={"query": "gripper torque limit", "max_results": 3,
                                                 "weight_threshold": 0.8})).json()
    ids = [r["id"] for r in body["results"]]
    assert len(ids) == 3 and str(carol.id) not in ids and str(carol.id) not in str(body["dropped"])
    assert "Carol gripper torque secret" not in str(body)
    assert body["retrieval"] == "vector" and body["rerank"] == "not_configured"
    stages = {s["key"]: s for s in body["funnel"]}
    assert stages["matched"]["count"] >= 6
    assert stages["limit"]["count"] == 3 and stages["budget"]["count"] == 3
    reasons = {d["stage"] for d in body["dropped"]}
    assert {"filters", "limit"} <= reasons          # the branch and everything past max_results
    first = body["results"][0]
    assert first["scores"]["vector"] is not None and first["scores"]["rrf"] > 0 and first["why"]

    stubs = (await http.post("/api/search", json={"query": "measured last week", "weight_threshold": 0.8,
                                                  "max_results": 20})).json()
    low = next(r for r in stubs["results"] if r["id"] == str(light.id))
    assert low["delivery"] == "stub" and low["content"] is None and low["downgraded"]
    only_full = (await http.post("/api/search", json={"query": "measured last week", "mode": "full_only",
                                                      "weight_threshold": 0.8, "max_results": 20})).json()
    assert str(light.id) not in [r["id"] for r in only_full["results"]]
    assert any(d["id"] == str(light.id) and d["stage"] == "weight" for d in only_full["dropped"])
    tiny = (await http.post("/api/search", json={"query": "gripper torque", "max_response_tokens": 15,
                                                 "max_results": 20})).json()
    assert tiny["tokens"] <= 15 and any(d["stage"] == "budget" for d in tiny["dropped"])


async def test_filters_and_explain_say_why_a_memory_did_not_come_back(env):
    http, seed, new_version = env["http"], env["seed"], env["new_version"]
    runbook = await seed("Deploy runbook: drain the arm controller first", content_type="procedural", weight=0.9)
    fact = await seed("Deploy window is Tuesday", weight=0.9)
    newer = await new_version(fact.id, "Deploy window is Wednesday")
    body = (await http.post("/api/search", json={
        "query": "deploy", "content_type": "experiential", "max_results": 20,
        "explain": [str(runbook.id), str(fact.id), str(newer.id), str(uuid.uuid4())]})).json()
    why = {e["id"]: e for e in body["explain"]}
    assert str(runbook.id) not in [r["id"] for r in body["results"]]
    assert "content type is procedural" in why[str(runbook.id)]["detail"]
    assert "old version" in why[str(fact.id)]["detail"]
    assert why[str(newer.id)]["stage"] == "returned"
    assert [e["stage"] for e in body["explain"]][-1] == "missing"
    scoped = (await http.post("/api/search", json={"query": "deploy", "scope": "organizational"})).json()
    assert scoped["results"] == [] and scoped["candidates"] == 0
    personal = (await http.post("/api/search", json={"query": "deploy", "scope": "user"})).json()
    assert all(r["scope"] == "user" for r in personal["results"])


async def test_routing_matches_search_memory(env):
    """A focus selects the focused path with domain and graph boosts; without one they do not apply."""
    http = env["http"]
    await env["seed"]("Arm firmware notes", weight=0.9, domains=["firmware"])
    with patch("src.search_adapter.search_memories_with_focus", new_callable=AsyncMock) as focused, \
            patch("src.search_adapter.search_memories", new_callable=AsyncMock, return_value=[]) as plain:
        focused.return_value = type("B", (), {"results": [], "used_reranker": False, "graph_neighbors_added": 0,
                                              "fallback_reason": None, "pivot_suggested": False,
                                              "pivot_distance": 0.1, "pivot_reason": None})()
        await http.post("/api/search", json={
            "query": "firmware", "focus": "arm release", "session_focus_weight": 0.6, "domains": ["firmware"],
            "domain_boost_weight": 0.5, "graph_depth": 2, "graph_boost_weight": 0.3, "rerank": False,
            "entities": ["Atlas"], "content_type": "knowledge", "mode": "full_only", "weight_threshold": 0.7})
        kw = focused.await_args.kwargs
        assert (kw["focus_string"], kw["session_focus_weight"], kw["domains"], kw["domain_boost_weight"],
                kw["graph_depth"], kw["graph_boost_weight"]) == ("arm release", 0.6, ["firmware"], 0.5, 2, 0.3)
        assert kw["entity_names"] == ["Atlas"] and kw["content_type"] == "knowledge"
        assert kw["disabled_signals"] == {"reranker"} and kw["weight_threshold"] == 0.0  # full_only, as in MCP
        plain.assert_not_awaited()
        no_focus = (await http.post("/api/search", json={"query": "firmware", "domains": ["firmware"],
                                                         "graph_depth": 1})).json()
        assert "domains" not in plain.await_args.kwargs and "graph_depth" not in plain.await_args.kwargs
        assert no_focus["notes"] == ["Domain and graph boosts apply only with a session focus, as in search_memory."]


async def test_text_fallback_and_health_when_embeddings_are_down(env):
    http, seed = env["http"], env["seed"]
    await seed("Gripper torque limit is 11.5 Nm", weight=0.9)
    await seed("Carol gripper torque secret", scope="user", owner="carol", actor="carol", weight=0.9)
    healthy = (await http.get("/api/search/health")).json()
    assert healthy["embedding"]["status"] == "ok" and healthy["search_mode"] == "vector"
    assert healthy["reranker"]["status"] == "not_configured"

    app.dependency_overrides[get_embedding_service] = lambda: DownEmbedding()
    body = (await http.post("/api/search", json={"query": "gripper torque"})).json()
    assert body["retrieval"] == "text" and "text match" in body["fallback_reason"]
    assert [r["stub"] for r in body["results"]] and "Carol" not in str(body)
    down = (await http.get("/api/search/health")).json()
    assert down["embedding"]["status"] == "down" and down["search_mode"] == "text" and down["fallback"]
