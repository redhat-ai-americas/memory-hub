"""Exercise client administration through the BFF's actual HTTP endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src import routes
from src.database import get_db
from src.main import app
from src.ui_common import Viewer


@pytest.fixture
def client_user(monkeypatch):
    viewer = Viewer(username="alice", name="Alice", email=None, source="account", role="user")
    monkeypatch.setattr(routes, "viewer_from_request", lambda *args: viewer)
    monkeypatch.setattr(
        routes,
        "access_for",
        AsyncMock(return_value=SimpleNamespace(grants=SimpleNamespace(identities={"alice-agent"}))),
    )
    db = MagicMock()
    db.commit = AsyncMock()

    async def database():
        yield db

    app.dependency_overrides[get_db] = database
    upstream = AsyncMock(
        return_value=SimpleNamespace(
            json=lambda: {
                "client_id": "alice-agent",
                "client_name": "Alice",
                "identity_type": "user",
                "tenant_id": "default",
                "default_scopes": ["memory:read"],
                "active": True,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "client_secret": "test-secret",
            }
        )
    )
    monkeypatch.setattr(routes, "_admin_request", upstream)
    monkeypatch.setattr("src.ownership.set_owner", AsyncMock())
    yield viewer, upstream
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "scope",
    [
        "memory:admin",
        "memory:admin:cross_tenant",
        "memory:write:role",
        "memory:write:organizational",
        "memory:approve:enterprise",
        "unknown",
    ],
)
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_user_cannot_issue_privileged_scopes(client_user, scope, method):
    _, upstream = client_user
    body = {"default_scopes": [scope]}
    if method == "POST":
        body.update(client_id="alice-agent", client_name="Alice", tenant_id="default")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            method, "/api/clients" + ("/alice-agent" if method == "PATCH" else ""), json=body
        )
    assert response.status_code == 403
    upstream.assert_not_awaited()


async def test_user_cannot_reactivate_or_edit_another_client(client_user):
    _, upstream = client_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.patch("/api/clients/alice-agent", json={"active": True})).status_code == 403
        assert (await client.patch("/api/clients/other-agent", json={"client_name": "Hijacked"})).status_code == 404
    upstream.assert_not_awaited()


async def test_safe_registration_and_admin_scope_assignment(client_user):
    viewer, upstream = client_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(
            "/api/clients",
            json={
                "client_id": "alice-agent",
                "client_name": "Alice",
                "tenant_id": "other-tenant",
                "default_scopes": ["memory:read", "memory:write:user", "memory:write:project"],
            },
        )
        assert result.status_code == 201
        assert upstream.call_args.kwargs["json_body"]["tenant_id"] == "default"
        viewer.role = "admin"
        result = await client.patch("/api/clients/alice-agent", json={"default_scopes": ["memory:admin"]})
        assert result.status_code == 200
        assert upstream.call_args.kwargs["json_body"]["default_scopes"] == ["memory:admin"]
