"""Read access must never imply write access to shared memories."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src import routes, routes_admin, routes_dashboard, routes_workspace
from src.access import ADMIN_SCOPES, Access, Grants
from src.config import Settings, get_settings
from src.database import get_db
from src.main import app
from src.ui_common import DEFAULT_TENANT_SETTINGS, Viewer


def node(scope="enterprise", **values):
    return SimpleNamespace(
        **{
            "id": uuid.uuid4(),
            "tenant_id": "default",
            "scope": scope,
            "scope_id": "sre",
            "owner_id": "alice",
            "deleted_at": None,
            "previous_version_id": None,
            "parent_id": None,
            "status": "active",
            **values,
        }
    )


@pytest.fixture
def mutation_context(monkeypatch):
    viewer = Viewer("alice", "Alice", None, "account", "user")
    access = Access(viewer, Grants("alice", roles={"sre"}, projects={"p1"}, campaigns={"c1"}), ())
    memory = node()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = memory
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    for module in [routes, routes_dashboard, routes_admin, routes_workspace]:
        monkeypatch.setattr(module, "viewer_from_request", lambda *a: viewer)
        monkeypatch.setattr(module, "access_for", AsyncMock(return_value=access))
    monkeypatch.setattr(routes_dashboard, "_load_memory", AsyncMock(return_value=memory))
    monkeypatch.setattr(routes_admin, "_load_memory", AsyncMock(return_value=memory))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings()
    yield SimpleNamespace(viewer=viewer, access=access, node=memory, db=db)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("scope", ["enterprise", "organizational", "role"])
async def test_readable_shared_memories_cannot_be_mutated(mutation_context, scope):
    c = mutation_context
    c.node.scope = scope
    assert c.access.can_read_row(c.node)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.delete(f"/api/memory/{c.node.id}")).status_code == 403
        for action in ["delete", "quarantine", "weight", "promote", "relate"]:
            response = await client.post(
                "/api/memories/bulk", json={"ids": [str(c.node.id)], "action": action, "weight": 0.5}
            )
            assert response.status_code == 200
            assert response.json()["done"] == []
            assert response.json()["errors"]
        assert (await client.post(f"/api/review/{c.node.id}/decision", json={"decision": "reject"})).status_code == 403
        c.node.deleted_at = "2026-01-01"
        assert (await client.post(f"/api/memory/{c.node.id}/restore")).status_code == 403
    c.db.add.assert_not_called()


def test_write_permissions_cover_ownership_membership_and_tenant(mutation_context):
    access = mutation_context.access
    assert access.can_write(node("user"))
    assert not access.can_write(node("user", owner_id="bob"))
    assert not access.can_write(node("user", tenant_id="other"))
    assert access.can_write(node("project", scope_id="p1"))
    assert not access.can_write(node("project", scope_id="other"))
    assert access.can_write(node("campaign", owner_id="c1"))
    assert not access.can_write(node("campaign", owner_id="other"))


async def test_delete_audits_incident_before_commit(mutation_context):
    c = mutation_context
    c.viewer.role = "superuser"
    c.node.scope = "user"
    c.access.open_scopes = ("user", *ADMIN_SCOPES)
    c.access.break_glass = {"id": "grant-1", "incident_ref": "INC-123", "justification": "Investigate a data exposure"}

    async def committed():
        event = c.db.add.call_args.args[0]
        assert event.event_type == "memory.delete"
        assert event.actor_id == "alice" and event.memory_id == c.node.id
        assert event.event_metadata["incident_ref"] == "INC-123"
        assert event.event_metadata["grant_id"] == "grant-1"
        assert event.event_metadata["severity"] == "HIGH"
        assert event.event_metadata["justification"]
        assert event.event_metadata["affected_ids"] == [str(c.node.id)]
        assert event.event_metadata["affected_owners"] == ["alice"]

    c.db.commit.side_effect = committed
    await routes.forget_memory(str(c.node.id), c.db, Settings(), c.viewer)
    c.db.commit.assert_awaited_once()
    c.db.add.assert_called_once()


async def test_delete_cannot_commit_when_audit_fails(mutation_context):
    c = mutation_context
    c.node.scope = "user"
    c.db.add.side_effect = RuntimeError("Audit unavailable")
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        await routes.forget_memory(str(c.node.id), c.db, Settings(), c.viewer)
    c.db.commit.assert_not_awaited()


async def test_personal_audit_is_available_and_all_queries_are_scoped(mutation_context, monkeypatch):
    c = mutation_context
    c.access.grants.agents.add("alice-agent")
    monkeypatch.setattr("src.access.viewer_from_request", lambda *a: c.viewer)
    monkeypatch.setattr(routes_admin, "load_tenant_settings", AsyncMock(return_value=DEFAULT_TENANT_SETTINGS))
    result = MagicMock()
    result.scalar_one.return_value = 0
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    c.db.execute.return_value = result
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/audit")
        assert response.status_code == 200
        assert response.json()["items"] == []
        for call in c.db.execute.call_args_list:
            statement = call.args[0].compile()
            assert "audit_log.tenant_id =" in str(statement)
            assert "audit_log.actor_id IN" in str(statement) and "audit_log.driver_id IN" in str(statement)
            values = list(statement.params.values())
            assert "default" in values
            assert any(isinstance(v, list) and set(v) == {"alice", "alice-agent"} for v in values)
        c.db.execute.reset_mock()
        assert (await client.get("/api/audit?actor=bob")).status_code == 200
        assert all("WHERE false" in str(call.args[0]) for call in c.db.execute.call_args_list)
