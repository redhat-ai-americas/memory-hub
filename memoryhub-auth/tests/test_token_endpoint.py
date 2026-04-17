"""Integration tests for the /token endpoint (client_credentials and refresh_token grants)."""
import jwt as pyjwt
import pytest

from src.keys import get_public_key


@pytest.mark.asyncio
class TestClientCredentials:
    async def test_valid_credentials_returns_tokens(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 300
        assert "access_token" in body
        assert "refresh_token" in body
        assert "scope" in body

    async def test_access_token_claims(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
            },
        )
        decoded = pyjwt.decode(
            resp.json()["access_token"],
            get_public_key(),
            algorithms=["RS256"],
            audience="memoryhub",
        )
        assert decoded["sub"] == "test-agent"
        assert decoded["identity_type"] == "user"
        assert decoded["tenant_id"] == "test-tenant"

    async def test_scope_parameter_subset(self, client, sample_client):
        """Requesting a subset of allowed scopes should succeed."""
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "scope": "memory:read",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == "memory:read"

    async def test_no_scope_defaults_to_all_client_scopes(self, client, sample_client):
        """Omitting scope returns all scopes assigned to the client."""
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
            },
        )
        assert resp.status_code == 200
        # Both scopes should be present (sorted)
        returned = set(resp.json()["scope"].split())
        assert returned == {"memory:read", "memory:write:user"}

    async def test_invalid_scope_rejected(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "scope": "memory:admin",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_scope"

    async def test_wrong_secret(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "wrong-password",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    async def test_unknown_client(self, client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "nonexistent",
                "client_secret": "anything",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    async def test_inactive_client_rejected(self, client, inactive_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "inactive-agent",
                "client_secret": "inactive-secret",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    async def test_missing_client_id(self, client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_secret": "whatever",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_missing_client_secret(self, client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"


@pytest.mark.asyncio
class TestRefreshTokenGrant:
    async def _get_initial_tokens(self, client):
        """Helper: exchange client credentials for initial token pair."""
        resp = await client.post(
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
            },
        )
        assert resp.status_code == 200, f"setup failed: {resp.text}"
        return resp.json()

    async def test_refresh_returns_new_tokens(self, client, sample_client):
        tokens = await self._get_initial_tokens(client)

        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "refresh_token": tokens["refresh_token"],
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body

    async def test_refresh_token_is_rotated(self, client, sample_client):
        """Each refresh must issue a new refresh token (token rotation)."""
        tokens = await self._get_initial_tokens(client)
        original_rt = tokens["refresh_token"]

        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "refresh_token": original_rt,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["refresh_token"] != original_rt

    async def test_reused_refresh_token_rejected(self, client, sample_client):
        """A refresh token used once must be revoked; a second use must fail."""
        tokens = await self._get_initial_tokens(client)
        original_rt = tokens["refresh_token"]

        # First use succeeds
        resp1 = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "refresh_token": original_rt,
            },
        )
        assert resp1.status_code == 200

        # Second use must fail
        resp2 = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "refresh_token": original_rt,
            },
        )
        assert resp2.status_code == 401, f"expected 401, got {resp2.status_code}: {resp2.text}"
        assert resp2.json()["error"] == "invalid_grant"

    async def test_refresh_requires_client_auth(self, client, sample_client):
        """client_id and client_secret are mandatory for the refresh_token grant."""
        tokens = await self._get_initial_tokens(client)

        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                # no client_id or client_secret
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_refresh_requires_refresh_token_field(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                # no refresh_token field
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_refresh_with_wrong_client_secret(self, client, sample_client):
        tokens = await self._get_initial_tokens(client)

        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "bad-secret",
                "refresh_token": tokens["refresh_token"],
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    async def test_bogus_refresh_token(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "test-agent",
                "client_secret": "test-secret-123",
                "refresh_token": "completely-made-up-token",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
class TestUnsupportedGrant:
    async def test_password_grant_rejected(self, client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "password",
                "username": "user",
                "password": "pass",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "unsupported_grant_type"
