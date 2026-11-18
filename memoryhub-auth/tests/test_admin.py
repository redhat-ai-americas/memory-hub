"""Tests for the admin CRUD API."""
import os

# Set admin key before any src imports so AuthSettings picks it up.
os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from src.models import AgentOwnerBinding, OAuthClient  # noqa: E402

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
    async def test_owner_binding_is_committed_with_client(self, client, db_session):
        resp = await client.post(
            "/admin/clients",
            json={"client_id": "owned-agent", "client_name": "Owned Agent", "tenant_id": "tenant-1", "owner": "alice"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        binding = (await db_session.execute(select(AgentOwnerBinding).where(
            AgentOwnerBinding.client_id == "owned-agent",
        ))).scalar_one()
        assert (binding.tenant_id, binding.owner) == ("tenant-1", "alice")

    async def test_owner_binding_conflict_rolls_back_client(self, client, db_session):
        db_session.add(AgentOwnerBinding(tenant_id="tenant-1", client_id="orphan-id", owner="bob"))
        await db_session.commit()
        resp = await client.post(
            "/admin/clients",
            json={
                "client_id": "orphan-id", "client_name": "Should Roll Back",
                "tenant_id": "tenant-1", "owner": "alice",
            },
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 409, resp.text
        client_row = (await db_session.execute(select(OAuthClient).where(
            OAuthClient.client_id == "orphan-id",
        ))).scalar_one_or_none()
        assert client_row is None

    async def test_owner_filter_applies_to_each_client_operation(self, client):
        created = await client.post(
            "/admin/clients",
            json={"client_id": "alice-agent", "client_name": "Alice", "tenant_id": "tenant-1", "owner": "alice"},
            headers=ADMIN_HEADERS,
        )
        assert created.status_code == 201, created.text

        alice_list = await client.get(
            "/admin/clients", params={"tenant_id": "tenant-1", "owner": "alice"}, headers=ADMIN_HEADERS,
        )
        bob_list = await client.get(
            "/admin/clients", params={"tenant_id": "tenant-1", "owner": "bob"}, headers=ADMIN_HEADERS,
        )
        assert [row["client_id"] for row in alice_list.json()] == ["alice-agent"]
        assert bob_list.json() == []

        for method, path, body in (
            ("GET", "/admin/clients/alice-agent", None),
            ("PATCH", "/admin/clients/alice-agent", {"active": False}),
            ("POST", "/admin/clients/alice-agent/rotate-secret", None),
            ("POST", "/admin/clients/alice-agent/rotate-api-key", None),
        ):
            denied = await client.request(
                method, path, params={"tenant_id": "tenant-1", "owner": "bob"},
                json=body, headers=ADMIN_HEADERS,
            )
            assert denied.status_code == 404, (method, path, denied.text)

        wrong_tenant = await client.get(
            "/admin/clients/alice-agent",
            params={"tenant_id": "tenant-2", "owner": "alice"}, headers=ADMIN_HEADERS,
        )
        no_key = await client.patch(
            "/admin/clients/alice-agent", params={"tenant_id": "tenant-1", "owner": "alice"},
            json={"active": False},
        )
        still_active = await client.get(
            "/admin/clients/alice-agent", params={"tenant_id": "tenant-1", "owner": "alice"},
            headers=ADMIN_HEADERS,
        )
        assert wrong_tenant.status_code == 404
        assert no_key.status_code == 401
        assert still_active.status_code == 200 and still_active.json()["active"] is True

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
class TestCreateClientApiKey:
    async def test_create_includes_api_key(self, client):
        body = {
            "client_id": "apikey-agent",
            "client_name": "API Key Agent",
            "tenant_id": "tenant-1",
        }
        resp = await client.post(
            "/admin/clients", json=body, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "api_key" in data, "Response should include api_key"
        assert data["api_key"].startswith("mh-dev-"), (
            f"API key should start with 'mh-dev-', got: {data['api_key']}"
        )

    async def test_api_key_not_in_get(self, client, sample_client):
        resp = await client.get(
            "/admin/clients/test-agent", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "api_key" not in data, "GET should not expose api_key"


@pytest.mark.asyncio
class TestRotateApiKey:
    async def test_rotate_api_key(self, client, sample_client):
        resp = await client.post(
            "/admin/clients/test-agent/rotate-api-key",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["client_id"] == "test-agent"
        assert "api_key" in data
        assert data["api_key"].startswith("mh-dev-"), (
            f"Rotated API key should start with 'mh-dev-', got: {data['api_key']}"
        )

    async def test_rotate_api_key_not_found(self, client):
        resp = await client.post(
            "/admin/clients/no-such-agent/rotate-api-key",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
class TestTenantFiltering:
    """Cross-tenant isolation tests for admin endpoints (#105)."""

    async def _create_in_tenant(self, client, client_id: str, tenant: str) -> dict:
        """Helper: create a client in a specific tenant, return the response."""
        body = {
            "client_id": client_id,
            "client_name": f"{client_id} name",
            "tenant_id": tenant,
        }
        resp = await client.post("/admin/clients", json=body, headers=ADMIN_HEADERS)
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_list_clients_filters_by_tenant(self, client):
        """GET /admin/clients?tenant_id=X returns only that tenant's clients."""
        await self._create_in_tenant(client, "tenant-a-agent", "tenant-a")
        await self._create_in_tenant(client, "tenant-b-agent", "tenant-b")

        resp = await client.get(
            "/admin/clients", params={"tenant_id": "tenant-a"}, headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert all(c["tenant_id"] == "tenant-a" for c in data), (
            f"Expected all clients to be in tenant-a, got: {data}"
        )
        ids = [c["client_id"] for c in data]
        assert "tenant-a-agent" in ids
        assert "tenant-b-agent" not in ids

    async def test_list_clients_without_tenant_returns_all(self, client):
        """GET /admin/clients without tenant_id returns all (backward compat)."""
        await self._create_in_tenant(client, "compat-agent-a", "compat-tenant-a")
        await self._create_in_tenant(client, "compat-agent-b", "compat-tenant-b")

        resp = await client.get("/admin/clients", headers=ADMIN_HEADERS)
        assert resp.status_code == 200, resp.text
        ids = [c["client_id"] for c in resp.json()]
        assert "compat-agent-a" in ids
        assert "compat-agent-b" in ids

    async def test_get_client_rejects_cross_tenant(self, client):
        """GET /admin/clients/{id}?tenant_id=wrong returns 404."""
        await self._create_in_tenant(client, "ct-get-agent", "tenant-a")

        resp = await client.get(
            "/admin/clients/ct-get-agent",
            params={"tenant_id": "tenant-b"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text

    async def test_patch_client_rejects_cross_tenant(self, client):
        """PATCH /admin/clients/{id}?tenant_id=wrong returns 404."""
        await self._create_in_tenant(client, "ct-patch-agent", "tenant-a")

        resp = await client.patch(
            "/admin/clients/ct-patch-agent",
            params={"tenant_id": "tenant-b"},
            json={"client_name": "Should Not Update"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text

    async def test_rotate_secret_rejects_cross_tenant(self, client):
        """POST /admin/clients/{id}/rotate-secret?tenant_id=wrong returns 404."""
        await self._create_in_tenant(client, "ct-rotate-agent", "tenant-a")

        resp = await client.post(
            "/admin/clients/ct-rotate-agent/rotate-secret",
            params={"tenant_id": "tenant-b"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text

    async def test_rotate_api_key_rejects_cross_tenant(self, client):
        """POST /admin/clients/{id}/rotate-api-key?tenant_id=wrong returns 404."""
        await self._create_in_tenant(client, "ct-apikey-agent", "tenant-a")

        resp = await client.post(
            "/admin/clients/ct-apikey-agent/rotate-api-key",
            params={"tenant_id": "tenant-b"},
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 404, resp.text


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
        assert data["api_key"].startswith("mh-dev-")

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
