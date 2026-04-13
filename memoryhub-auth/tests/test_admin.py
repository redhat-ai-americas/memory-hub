"""Tests for the admin CRUD API."""
import os

# Set admin key before any src imports so AuthSettings picks it up.
os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")

import pytest  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
class TestAdminKeyValidation:
    async def test_missing_admin_key_returns_401(self, client):
        resp = await client.get("/admin/clients")
        assert resp.status_code == 401, resp.text

    async def test_wrong_admin_key_returns_401(self, client):
        resp = await client.get(
            "/admin/clients", headers={"X-Admin-Key": "wrong-key"}
        )
        assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
class TestListClients:
    async def test_empty_list(self, client):
        resp = await client.get("/admin/clients", headers=ADMIN_HEADERS)
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    async def test_list_with_data(self, client, sample_client):
        resp = await client.get("/admin/clients", headers=ADMIN_HEADERS)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) >= 1
        ids = [c["client_id"] for c in data]
        assert "test-agent" in ids


@pytest.mark.asyncio
class TestCreateClient:
    async def test_create_success(self, client):
        body = {
            "client_id": "new-agent",
            "client_name": "New Agent",
            "tenant_id": "tenant-1",
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["client_id"] == "new-agent"
        assert data["client_name"] == "New Agent"
        assert data["identity_type"] == "user"
        assert data["tenant_id"] == "tenant-1"
        assert data["default_scopes"] == ["memory:read"]
        assert data["active"] is True
        assert "client_secret" in data
        assert len(data["client_secret"]) > 0

    async def test_create_with_custom_fields(self, client):
        body = {
            "client_id": "svc-agent",
            "client_name": "Service Agent",
            "identity_type": "service",
            "tenant_id": "tenant-2",
            "default_scopes": ["memory:read", "memory:write:user"],
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["identity_type"] == "service"
        assert data["default_scopes"] == ["memory:read", "memory:write:user"]

    async def test_duplicate_client_id_returns_409(self, client, sample_client):
        body = {
            "client_id": "test-agent",  # already exists via sample_client
            "client_name": "Duplicate",
            "tenant_id": "tenant-1",
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 409, resp.text

    async def test_missing_required_fields_returns_422(self, client):
        resp = await client.post(
            "/admin/clients", json={}, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 422, resp.text

    async def test_create_with_redirect_uris_and_public(self, client):
        body = {
            "client_id": "spa-client",
            "client_name": "SPA Client",
            "tenant_id": "tenant-spa",
            "redirect_uris": ["https://app.example.com/callback", "https://app.example.com/silent"],
            "public": True,
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["redirect_uris"] == ["https://app.example.com/callback", "https://app.example.com/silent"]
        assert data["public"] is True

    async def test_create_defaults_redirect_uris_null_and_public_false(self, client):
        body = {
            "client_id": "basic-client",
            "client_name": "Basic Client",
            "tenant_id": "tenant-1",
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["redirect_uris"] is None
        assert data["public"] is False


@pytest.mark.asyncio
class TestGetClient:
    async def test_get_existing_client(self, client, sample_client):
        resp = await client.get(
            "/admin/clients/test-agent", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["client_id"] == "test-agent"
        assert data["client_name"] == "Test Agent"
        assert "client_secret" not in data  # should not leak secret

    async def test_get_nonexistent_returns_404(self, client):
        resp = await client.get(
            "/admin/clients/no-such-agent", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
class TestUpdateClient:
    async def test_deactivate_client(self, client, sample_client):
        resp = await client.patch(
            "/admin/clients/test-agent",
            json={"active": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["active"] is False

    async def test_change_scopes(self, client, sample_client):
        new_scopes = ["memory:read", "memory:write:user", "memory:admin"]
        resp = await client.patch(
            "/admin/clients/test-agent",
            json={"default_scopes": new_scopes},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_scopes"] == new_scopes

    async def test_update_preserves_unchanged_fields(self, client, sample_client):
        resp = await client.patch(
            "/admin/clients/test-agent",
            json={"client_name": "Renamed Agent"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["client_name"] == "Renamed Agent"
        # Other fields unchanged
        assert data["active"] is True
        assert data["tenant_id"] == "test-tenant"

    async def test_update_nonexistent_returns_404(self, client):
        resp = await client.patch(
            "/admin/clients/no-such-agent",
            json={"active": False},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text

    async def test_update_redirect_uris(self, client, sample_client):
        new_uris = ["https://myapp.example.com/cb"]
        resp = await client.patch(
            "/admin/clients/test-agent",
            json={"redirect_uris": new_uris},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["redirect_uris"] == new_uris
        # Other fields unchanged
        assert data["active"] is True
        assert data["tenant_id"] == "test-tenant"

    async def test_update_public_flag(self, client, sample_client):
        resp = await client.patch(
            "/admin/clients/test-agent",
            json={"public": True},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["public"] is True

    async def test_client_response_includes_redirect_uris_and_public(self, client, sample_client):
        resp = await client.get(
            "/admin/clients/test-agent", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "redirect_uris" in data
        assert "public" in data


@pytest.mark.asyncio
class TestRotateSecret:
    async def test_rotate_returns_new_secret(self, client, sample_client):
        resp = await client.post(
            "/admin/clients/test-agent/rotate-secret",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["client_id"] == "test-agent"
        assert "client_secret" in data
        assert len(data["client_secret"]) > 0

    async def test_rotated_secret_works_for_token_grant(self, client, sample_client):
        # Rotate the secret
        rotate_resp = await client.post(
            "/admin/clients/test-agent/rotate-secret",
            headers=ADMIN_HEADERS,
        )
        new_secret = rotate_resp.json()["client_secret"]

        # Use the new secret to get a token
        token_resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": new_secret,
            },
        )
        assert token_resp.status_code == 200, (
            f"New secret should authenticate successfully, got {token_resp.status_code}: "
            f"{token_resp.text}"
        )
        assert "access_token" in token_resp.json()

    async def test_old_secret_fails_after_rotation(self, client, sample_client):
        # Rotate the secret
        await client.post(
            "/admin/clients/test-agent/rotate-secret",
            headers=ADMIN_HEADERS,
        )

        # Old secret should no longer work
        from tests.conftest import TEST_CLIENT_SECRET

        token_resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
            },
        )
        assert token_resp.status_code == 401, (
            f"Old secret should be rejected after rotation, got {token_resp.status_code}"
        )

    async def test_rotate_nonexistent_returns_404(self, client):
        resp = await client.post(
            "/admin/clients/no-such-agent/rotate-secret",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text
