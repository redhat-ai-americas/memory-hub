"""Regressions for the User/Admin review, including the shipped UI contract."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.authorization import Access, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.main import app
from src.routes import _client_scopes_allowed

TENANT = "review-tenant"


def query_result(*, value=None, rows=()):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    result.fetchall.return_value = list(rows)
    return result


def rule(*, owner="alice", layer="user", tenant=TENANT, version=1):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, layer=layer, owner_id=owner,
        version=version, is_current=version == 2, name="A visible policy",
        edited_by=owner, created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
async def dashboard():
    state = {"access": Access(Principal("alice", "user", TENANT))}
    db = AsyncMock()
    app.dependency_overrides[get_access] = lambda: state["access"]
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id=TENANT)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://dashboard") as http:
            yield http, db, state
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_session_client_defaults_can_create_a_client(dashboard, role):
    """The form's defaults must survive the actual BFF authorization path."""
    http, db, state = dashboard
    state["access"] = Access(Principal("alice", role, TENANT), moderation_scopes={"project", "organizational"})
    session = (await http.get("/api/me")).json()
    policy = session["capabilities"]["clients"]
    assert policy["can_create"]
    assert session["capabilities"]["individual_activity"] == (role == "user")
    assert policy["identity_types"] == (["service"] if role == "admin" else ["user"])
    for scope in policy["scopes"]:
        _client_scopes_allowed(state["access"], [scope], policy["identity_types"][0])
    payload = {
        "client_id": "new-agent", "client_name": "New agent", "tenant_id": session["tenant_id"],
        "identity_type": policy["identity_types"][0], "default_scopes": policy["default_scopes"],
    }
    created = {**payload, "active": True, "client_secret": "test-secret", "api_key": "test-key",
               "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}
    db.execute.return_value = query_result(value=False)
    with patch("src.routes._admin_request", new=AsyncMock(return_value=MagicMock(json=lambda: created))):
        response = await http.post("/api/clients", json=payload)
    assert response.status_code == 201, response.text


async def test_admin_without_client_scopes_has_no_creation_capability(dashboard):
    http, _db, state = dashboard
    state["access"] = Access(Principal("alice", "admin", TENANT))
    policy = (await http.get("/api/me")).json()["capabilities"]["clients"]
    assert not policy["can_create"] and policy["default_scopes"] == []


@pytest.mark.parametrize("role,layer,owner", [("user", "user", "alice"),
                                              ("admin", "organizational", "bob")])
async def test_human_can_read_authorized_rule_history_without_a_service_key(dashboard, role, layer, owner):
    http, db, state = dashboard
    state["access"] = Access(Principal("alice", role, TENANT))
    versions = [rule(owner=owner, layer=layer, version=2), rule(owner=owner, layer=layer)]
    db.execute.side_effect = [query_result(value=versions[0]), query_result(rows=versions)]
    response = await http.get(f"/api/rules/{versions[0].id}/history")
    assert response.status_code == 200, response.text
    assert [entry["version"] for entry in response.json()] == [2, 1]
    assert response.json()[0]["edited_by"] == (owner if role == "user" else None)


async def test_rule_history_reauthorizes_each_version(dashboard):
    http, db, _state = dashboard
    visible = rule(version=2)
    hidden = rule(owner="bob")
    db.execute.side_effect = [query_result(value=visible), query_result(rows=[visible, hidden])]
    response = await http.get(f"/api/rules/{visible.id}/history")
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()] == [str(visible.id)]


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_foreign_personal_rule_history_is_hidden(dashboard, role):
    http, db, state = dashboard
    state["access"] = Access(Principal("alice", role, TENANT))
    hidden = rule(owner="bob")
    db.execute.return_value = query_result(value=hidden)
    response = await http.get(f"/api/rules/{hidden.id}/history")
    assert response.status_code == 404
    db.execute.assert_awaited_once()
