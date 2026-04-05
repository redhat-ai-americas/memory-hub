"""Tests for the /.well-known/* and /healthz endpoints."""
import pytest


@pytest.mark.asyncio
class TestOAuthServerMetadata:
    async def test_status_ok(self, client):
        resp = await client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200

    async def test_issuer(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert body["issuer"] == "https://test-auth.example.com"

    async def test_token_endpoint(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert body["token_endpoint"] == "https://test-auth.example.com/token"

    async def test_jwks_uri(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert body["jwks_uri"] == "https://test-auth.example.com/.well-known/jwks.json"

    async def test_grant_types(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert "client_credentials" in body["grant_types_supported"]
        assert "refresh_token" in body["grant_types_supported"]

    async def test_auth_methods(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert "client_secret_post" in body["token_endpoint_auth_methods_supported"]

    async def test_scopes_supported(self, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        scopes = body["scopes_supported"]
        assert "memory:read" in scopes
        assert "memory:write:user" in scopes
        assert "memory:admin" in scopes


@pytest.mark.asyncio
class TestJWKS:
    async def test_status_ok(self, client):
        resp = await client.get("/.well-known/jwks.json")
        assert resp.status_code == 200

    async def test_keys_present(self, client):
        body = (await client.get("/.well-known/jwks.json")).json()
        assert "keys" in body
        assert len(body["keys"]) == 1

    async def test_key_fields(self, client):
        key = (await client.get("/.well-known/jwks.json")).json()["keys"][0]
        assert key["kty"] == "RSA"
        assert key["alg"] == "RS256"
        assert key["use"] == "sig"
        assert "kid" in key
        assert "n" in key
        assert "e" in key


@pytest.mark.asyncio
class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
