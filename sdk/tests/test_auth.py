"""Tests for memoryhub.auth.MemoryHubAuth."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt as pyjwt
import pytest

from memoryhub.auth import MemoryHubAuth, _TokenState
from memoryhub.exceptions import AuthenticationError

AUTH_URL = "https://auth.example.com"
CLIENT_ID = "test-client"
CLIENT_SECRET = "test-secret"


_JWT_TEST_KEY = "test-key-32-bytes-long-for-hmac!!"  # meets RFC 7518 minimum


def _make_token(exp_offset: int = 300) -> str:
    return pyjwt.encode(
        {"sub": "test", "exp": time.time() + exp_offset},
        _JWT_TEST_KEY,
        algorithm="HS256",
    )


def _mock_post_response(status_code: int, body: dict) -> AsyncMock:
    """Return an AsyncMock that stands in for httpx.AsyncClient.post."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.text = str(body)

    mock_post = AsyncMock(return_value=mock_resp)
    return mock_post


def _make_auth() -> MemoryHubAuth:
    return MemoryHubAuth(AUTH_URL, CLIENT_ID, CLIENT_SECRET)


# ---------------------------------------------------------------------------
# _ensure_token tests
# ---------------------------------------------------------------------------


async def test_initial_token_fetch(monkeypatch):
    """First call to _ensure_token fetches via client_credentials."""
    token = _make_token()
    mock_post = _mock_post_response(200, {"access_token": token, "refresh_token": "rt-1"})

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        auth = _make_auth()
        result = await auth._ensure_token()

    assert result == token
    assert auth._state.access_token == token
    assert auth._state.refresh_token == "rt-1"
    mock_post.assert_awaited_once()
    call_data = mock_post.call_args.kwargs.get("data") or mock_post.call_args.args[1]
    assert call_data["grant_type"] == "client_credentials"


async def test_token_cached_when_valid(monkeypatch):
    """Second call to _ensure_token returns cached token without HTTP."""
    token = _make_token(exp_offset=600)
    mock_post = _mock_post_response(200, {"access_token": token})

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        auth = _make_auth()
        first = await auth._ensure_token()
        second = await auth._ensure_token()

    assert first == second == token
    # HTTP should only have been called once
    mock_post.assert_awaited_once()


async def test_token_refreshed_when_expired():
    """When the cached token is expired, _ensure_token uses refresh_token grant."""
    expired_token = _make_token(exp_offset=-100)
    fresh_token = _make_token(exp_offset=600)

    # Sequence: first call → expired token; second call → fresh token via refresh
    refresh_resp = MagicMock(spec=httpx.Response)
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {"access_token": fresh_token}
    refresh_resp.headers = {"content-type": "application/json"}
    mock_post = AsyncMock(return_value=refresh_resp)

    auth = _make_auth()
    # Seed state with an expired token and a refresh token
    auth._state = _TokenState(
        access_token=expired_token,
        refresh_token="rt-old",
        expires_at=time.time() - 200,
    )

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await auth._ensure_token()

    assert result == fresh_token
    call_data = mock_post.call_args.kwargs.get("data") or mock_post.call_args.args[1]
    assert call_data["grant_type"] == "refresh_token"
    assert call_data["refresh_token"] == "rt-old"


async def test_refresh_fallback_to_client_credentials():
    """When refresh returns non-200, falls back to client_credentials."""
    fail_resp = MagicMock(spec=httpx.Response)
    fail_resp.status_code = 400
    fail_resp.json.return_value = {"error": "invalid_grant"}
    fail_resp.headers = {"content-type": "application/json"}
    fail_resp.text = '{"error": "invalid_grant"}'

    fresh_token = _make_token(exp_offset=600)
    ok_resp = MagicMock(spec=httpx.Response)
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"access_token": fresh_token}
    ok_resp.headers = {"content-type": "application/json"}

    # First post (refresh) fails; second post (client_credentials) succeeds
    mock_post = AsyncMock(side_effect=[fail_resp, ok_resp])

    auth = _make_auth()
    auth._state = _TokenState(
        access_token=_make_token(exp_offset=-100),
        refresh_token="rt-stale",
        expires_at=time.time() - 200,
    )

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await auth._ensure_token()

    assert result == fresh_token
    assert mock_post.await_count == 2
    # The second call must be client_credentials
    second_call = mock_post.call_args_list[1]
    second_call_data = second_call.kwargs.get("data") or second_call.args[1]
    assert second_call_data["grant_type"] == "client_credentials"


async def test_auth_error_on_failed_credentials():
    """When client_credentials returns non-200, raises AuthenticationError."""
    fail_resp = MagicMock(spec=httpx.Response)
    fail_resp.status_code = 401
    fail_resp.json.return_value = {"error": "invalid_client", "error_description": "Bad secret"}
    fail_resp.headers = {"content-type": "application/json"}
    fail_resp.text = "unauthorized"

    mock_post = AsyncMock(return_value=fail_resp)

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        auth = _make_auth()
        with pytest.raises(AuthenticationError, match="Bad secret"):
            await auth._ensure_token()


# ---------------------------------------------------------------------------
# _parse_token_response tests
# ---------------------------------------------------------------------------


def test_parse_token_from_jwt_exp():
    """Extracts expiry from JWT exp claim."""
    future_exp = int(time.time()) + 1800
    token = pyjwt.encode({"sub": "x", "exp": future_exp}, _JWT_TEST_KEY, algorithm="HS256")

    auth = _make_auth()
    state = auth._parse_token_response({"access_token": token, "refresh_token": "rt"})

    assert state.access_token == token
    assert state.expires_at == float(future_exp)
    assert state.refresh_token == "rt"


def test_parse_token_from_expires_in_fallback():
    """Falls back to expires_in when JWT decode fails (opaque token)."""
    opaque_token = "not.a.jwt"

    auth = _make_auth()
    before = time.time()
    state = auth._parse_token_response({"access_token": opaque_token, "expires_in": 600})
    after = time.time()

    assert state.access_token == opaque_token
    # expires_at should be approximately now + 600
    assert before + 600 <= state.expires_at <= after + 600


# ---------------------------------------------------------------------------
# async_auth_flow tests
# ---------------------------------------------------------------------------


async def test_auth_flow_injects_bearer_header():
    """async_auth_flow sets Authorization: Bearer <token> on the request."""
    token = _make_token()
    ok_resp = MagicMock(spec=httpx.Response)
    ok_resp.status_code = 200
    mock_post = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"access_token": token}),
            headers={"content-type": "application/json"},
        )
    )

    request = httpx.Request("GET", "https://memoryhub.example.com/memories")

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        auth = _make_auth()
        flow = auth.async_auth_flow(request)

        # First yield produces the request with the header injected
        sent_request = await flow.__anext__()

    assert sent_request.headers["Authorization"] == f"Bearer {token}"


async def test_auth_flow_retries_on_401():
    """async_auth_flow refreshes token and yields a second request on 401."""
    first_token = _make_token(exp_offset=600)
    second_token = _make_token(exp_offset=1200)

    # Two sequential token responses: first for initial fetch, second for refresh
    first_token_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"access_token": first_token, "refresh_token": "rt"}),
        headers={"content-type": "application/json"},
    )
    second_token_resp = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"access_token": second_token}),
        headers={"content-type": "application/json"},
    )
    mock_post = AsyncMock(side_effect=[first_token_resp, second_token_resp])

    request = httpx.Request("GET", "https://memoryhub.example.com/memories")
    unauthorized = MagicMock(spec=httpx.Response)
    unauthorized.status_code = 401

    with patch("memoryhub.auth.httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        auth = _make_auth()
        flow = auth.async_auth_flow(request)

        # Step 1: get request with first token
        first_request = await flow.__anext__()
        assert first_request.headers["Authorization"] == f"Bearer {first_token}"

        # Step 2: simulate a 401 response — flow should refresh and yield again
        try:
            second_request = await flow.asend(unauthorized)
        except StopAsyncIteration:
            pytest.fail("Flow should have yielded a second request after 401")

    assert second_request.headers["Authorization"] == f"Bearer {second_token}"
