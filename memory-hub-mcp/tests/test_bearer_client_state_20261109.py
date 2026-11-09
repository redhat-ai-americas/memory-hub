"""QA 2026-11-09 RT2-CL-05: bearer tokens of revoked or re-scoped clients stop working."""

import pytest
from fastmcp.exceptions import ToolError
from src.core import bearer


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth.test/internal/validate-api-key")
    bearer._client_cache.clear()


def _status(value):
    async def fake(client_id):
        if isinstance(value, Exception):
            raise value
        return value

    return fake


def test_status_url_is_derived_from_validate_url():
    assert bearer._client_status_url("a b") == "http://auth.test/internal/clients/a%20b/status"


async def test_revoked_client_is_refused(monkeypatch):
    monkeypatch.setattr(bearer, "_client_status", _status(None))
    with pytest.raises(ToolError, match="revoked"):
        await bearer._enforce_client_state({"sub": "u", "azp": "agent", "tenant_id": "t1", "scopes": ["memory:read"]})


async def test_tenant_mismatch_is_refused(monkeypatch):
    monkeypatch.setattr(bearer, "_client_status", _status({"tenant_id": "t2", "scopes": ["memory:read"]}))
    with pytest.raises(ToolError, match="tenant"):
        await bearer._enforce_client_state({"sub": "agent", "tenant_id": "t1", "scopes": ["memory:read"]})


async def test_scopes_are_narrowed_to_current_client_scopes(monkeypatch):
    monkeypatch.setattr(bearer, "_client_status", _status({"tenant_id": "t1", "scopes": ["memory:read"]}))
    claims = {"sub": "agent", "tenant_id": "t1", "scopes": ["memory:read", "memory:admin"]}
    await bearer._enforce_client_state(claims)
    assert claims["scopes"] == ["memory:read"]


async def test_auth_service_unreachable_fails_closed(monkeypatch):
    monkeypatch.setattr(bearer, "_client_status", _status(RuntimeError("down")))
    with pytest.raises(ToolError, match="Could not confirm"):
        await bearer._enforce_client_state({"sub": "agent", "tenant_id": "t1", "scopes": []})


async def test_without_auth_service_the_check_is_skipped(monkeypatch):
    monkeypatch.delenv("AUTH_API_KEY_VALIDATE_URL")
    claims = {"sub": "agent", "tenant_id": "t1", "scopes": ["memory:read"]}
    await bearer._enforce_client_state(claims)
    assert claims["scopes"] == ["memory:read"]


class _Access:
    def __init__(self, scopes):
        self.scopes = scopes


def test_scopes_list_claim_from_memoryhub_auth_is_used():
    scopes = bearer._token_scopes({"scopes": ["memory:read", "memory:admin"]}, _Access([]))
    assert scopes == ["memory:read", "memory:admin"]


def test_scopes_string_claim_and_standard_scope_fallback():
    assert bearer._token_scopes({"scopes": "memory:read memory:write"}, _Access([])) == ["memory:read", "memory:write"]
    assert bearer._token_scopes({}, _Access(["memory:read"])) == ["memory:read"]
