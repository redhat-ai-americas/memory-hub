"""Tests for remote API key validation fallback (authenticate_remote)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import auth as auth_module
from src.tools.auth import AuthServiceUnavailableError, authenticate, authenticate_remote


@pytest.fixture(autouse=True)
def _clear_remote_cache():
    """Clear the remote key cache between tests."""
    auth_module._remote_key_cache.clear()
    yield
    auth_module._remote_key_cache.clear()


@pytest.fixture(autouse=True)
def _clear_users_loaded():
    """Reset user loading state so authenticate() re-reads from env."""
    auth_module._users_loaded = False
    auth_module._users_by_key.clear()
    yield
    auth_module._users_loaded = False
    auth_module._users_by_key.clear()


# -- Local authenticate still works ------------------------------------------


def test_authenticate_local_still_works(monkeypatch):
    """authenticate() returns ConfigMap users as before."""
    users_json = '{"users": [{"api_key": "mh-dev-abc123", "user_id": "alice", "name": "Alice", "scopes": ["user"]}]}'
    monkeypatch.setenv("MEMORYHUB_USERS_JSON", users_json)
    user = authenticate("mh-dev-abc123")
    assert user is not None
    assert user["user_id"] == "alice"


def test_authenticate_local_rejects_unknown_key(monkeypatch):
    """authenticate() returns None for unknown keys."""
    monkeypatch.setenv("MEMORYHUB_USERS_JSON", '{"users": []}')
    assert authenticate("mh-dev-unknown") is None


# -- Remote fallback ---------------------------------------------------------

_VALID_RESPONSE = {
    "user_id": "bob",
    "name": "Bob Remote",
    "identity_type": "user",
    "tenant_id": "acme",
    "scopes": ["memory:read", "memory:write:user"],
}


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or _VALID_RESPONSE
    return resp


@pytest.mark.asyncio
async def test_remote_fallback_success(monkeypatch):
    """Auth service returns a valid user; authenticate_remote returns it."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response())

    with patch("httpx.AsyncClient", return_value=mock_client):
        user = await authenticate_remote("mh-dev-remote-key")

    assert user is not None
    assert user["user_id"] == "bob"
    assert user["name"] == "Bob Remote"
    assert user["tenant_id"] == "acme"
    assert "memory:read" in user["scopes"]

    # Verify the POST was called with the right payload
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["json"] == {"api_key": "mh-dev-remote-key"}
    assert call_kwargs.kwargs["headers"]["X-Service-Key"] == "svc-secret"


@pytest.mark.asyncio
async def test_remote_fallback_derives_url_from_issuer(monkeypatch):
    """When AUTH_API_KEY_VALIDATE_URL is unset, derive from AUTH_ISSUER."""
    monkeypatch.delenv("AUTH_API_KEY_VALIDATE_URL", raising=False)
    monkeypatch.setenv("AUTH_ISSUER", "http://auth:8080/")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response())

    with patch("httpx.AsyncClient", return_value=mock_client):
        user = await authenticate_remote("mh-dev-key")

    assert user is not None
    # Verify URL was derived correctly (trailing slash stripped)
    call_args = mock_client.post.call_args
    assert call_args.args[0] == "http://auth:8080/internal/validate-api-key"


@pytest.mark.asyncio
async def test_remote_cache_hit(monkeypatch):
    """Second call within TTL returns cached result without HTTP request."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response())

    with patch("httpx.AsyncClient", return_value=mock_client):
        first = await authenticate_remote("mh-dev-cached")
        second = await authenticate_remote("mh-dev-cached")

    assert first == second
    # Only one HTTP call should have been made
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_remote_cache_expiry(monkeypatch):
    """After TTL expires, a fresh HTTP request is made."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response())

    with patch("httpx.AsyncClient", return_value=mock_client):
        await authenticate_remote("mh-dev-ttl")

    # Manually expire the cache entry
    for key in list(auth_module._remote_key_cache):
        user_dict, _expiry = auth_module._remote_key_cache[key]
        auth_module._remote_key_cache[key] = (user_dict, time.time() - 1)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await authenticate_remote("mh-dev-ttl")

    assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_remote_connection_error_raises(monkeypatch):
    """Connection errors raise AuthServiceUnavailableError."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("httpx.AsyncClient", return_value=mock_client), \
         pytest.raises(AuthServiceUnavailableError):
        await authenticate_remote("mh-dev-fail")


@pytest.mark.asyncio
async def test_remote_401_returns_none(monkeypatch):
    """401 (invalid key) returns None -- not an error, just rejected."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(status_code=401))

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await authenticate_remote("mh-dev-bad")

    assert result is None


@pytest.mark.asyncio
async def test_remote_500_raises(monkeypatch):
    """Non-401 error responses raise AuthServiceUnavailableError."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc-secret")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=_mock_response(status_code=500))

    with patch("httpx.AsyncClient", return_value=mock_client), \
         pytest.raises(AuthServiceUnavailableError):
        await authenticate_remote("mh-dev-server-err")


@pytest.mark.asyncio
async def test_remote_no_env_vars(monkeypatch):
    """Returns None when neither AUTH_API_KEY_VALIDATE_URL nor AUTH_ISSUER is set."""
    monkeypatch.delenv("AUTH_API_KEY_VALIDATE_URL", raising=False)
    monkeypatch.delenv("AUTH_ISSUER", raising=False)

    result = await authenticate_remote("mh-dev-noenv")
    assert result is None


@pytest.mark.asyncio
async def test_remote_no_service_key(monkeypatch):
    """Returns None when AUTH_INTERNAL_SERVICE_KEY is not set."""
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth:8080/internal/validate-api-key")
    monkeypatch.delenv("AUTH_INTERNAL_SERVICE_KEY", raising=False)

    result = await authenticate_remote("mh-dev-nokey")
    assert result is None
