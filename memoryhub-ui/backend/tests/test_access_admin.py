"""Read-only dashboard access assignments for Admins (#744)."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import src.access_admin as access_admin
from src.authorization import Principal, get_principal
from src.config import Settings, get_settings
from src.kube import KubeUnavailable
from src.main import app

BINDINGS = [
    {"metadata": {"name": "mh-user-group-corp-1", "annotations": {"memoryhub.io/granted-by": "katya",
                                                                  "memoryhub.io/granted-at": "2026-11-25T00:00:00Z"}},
     "roleRef": {"kind": "Role", "name": "memoryhub-dashboard-user"},
     "subjects": [{"kind": "Group", "name": "corp"}]},
    {"metadata": {"name": "hand-made"},
     "roleRef": {"kind": "Role", "name": "memoryhub-dashboard-admin"},
     "subjects": [{"kind": "User", "name": "alice"}, {"kind": "Group", "name": "ops"}]},
    {"metadata": {"name": "unrelated"}, "roleRef": {"kind": "ClusterRole", "name": "memoryhub-dashboard-admin"},
     "subjects": [{"kind": "User", "name": "mallory"}]},
    {"metadata": {"name": "other"}, "roleRef": {"kind": "Role", "name": "view"},
     "subjects": [{"kind": "User", "name": "bob"}]},
]


@pytest.fixture(autouse=True)
def clean():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


async def _get(role, settings, monkeypatch, items=None, error=None):
    client = AsyncMock()
    client.role_bindings = AsyncMock(return_value=items or [], side_effect=error)
    monkeypatch.setattr(access_admin, "kube_client_for", lambda _s: client)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_principal] = lambda: Principal("katya", role, "tenant-a")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.get("/api/admin/access"), client


@pytest.mark.asyncio
async def test_admin_sees_only_bindings_to_the_dashboard_roles(monkeypatch):
    settings = Settings(ui_role_source="openshift-rbac", ui_rbac_namespace="ns")
    response, client = await _get("admin", settings, monkeypatch, items=BINDINGS)
    assert response.status_code == 200
    body = response.json()
    client.role_bindings.assert_awaited_once_with("ns")
    assert body["source"] == "openshift-rbac" and "not expanded" in body["note"]
    assert [(a["role"], a["kind"], a["name"]) for a in body["assignments"]] == [
        ("admin", "Group", "ops"), ("admin", "User", "alice"), ("user", "Group", "corp")]
    assert body["assignments"][2]["granted_by"] == "katya"


@pytest.mark.asyncio
async def test_users_cannot_read_assignments(monkeypatch):
    response, client = await _get("user", Settings(ui_role_source="openshift-rbac"), monkeypatch)
    assert response.status_code == 403
    client.role_bindings.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_outage_is_503(monkeypatch):
    settings = Settings(ui_role_source="openshift-rbac", ui_rbac_namespace="ns")
    response, _ = await _get("admin", settings, monkeypatch, error=KubeUnavailable("down"))
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_lists_mode_shows_the_lists(monkeypatch):
    settings = Settings(ui_role_source="lists", ui_admin_users="alice", ui_allowed_users="alice,bob")
    response, client = await _get("admin", settings, monkeypatch)
    assert response.json()["source"] == "lists"
    assert [(a["role"], a["name"]) for a in response.json()["assignments"]] == [("admin", "alice"), ("user", "bob")]
    client.role_bindings.assert_not_awaited()


def test_dashboard_admin_role_never_grants_memory_admin_to_clients():
    """A dashboard Admin is not a technical scope (docs/auth/human-role-resolution.md)."""
    from fastapi import HTTPException

    from src.authorization import Access
    from src.routes import _client_capabilities, _client_scopes_allowed

    admin = Access(Principal("katya", "admin", "tenant-a"),
                   moderation_scopes={"project", "campaign", "role", "organizational"})
    assert not any("admin" in scope for scope in _client_capabilities(admin)["scopes"])
    for identity_type in ("service", "user"):
        with pytest.raises(HTTPException):
            _client_scopes_allowed(admin, ["memory:admin"], identity_type)
