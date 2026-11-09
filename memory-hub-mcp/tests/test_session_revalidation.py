"""QA 2026-11-09 RT-CL-04/08: revoked, rotated or narrowed API keys must not survive in MCP sessions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from src.tools import auth


@pytest.fixture
def session(monkeypatch):
    ctx = SimpleNamespace(session_id="mcp-session-1", session=None)
    user = {
        "user_id": "agent-1",
        "name": "a",
        "identity_type": "user",
        "tenant_id": "t1",
        "scopes": ["memory:read", "memory:write:user"],
        "project_memberships": ["p1"],
    }
    auth.set_session(dict(user), ttl_seconds=600, ctx=ctx, session_id="s1")
    auth.bind_session_credential("mh-dev-key", ctx)
    monkeypatch.setattr(auth, "SESSION_REVALIDATE_SECONDS", 0)
    yield ctx
    auth._sessions_by_mcp_session.pop("mcp-session-1", None)
    auth._remote_key_cache.clear()


async def test_revoked_key_ends_the_session(session, monkeypatch):
    monkeypatch.setattr(auth, "authenticate_remote", AsyncMock(return_value=None))
    with pytest.raises(auth.SessionRevokedError):
        await auth.revalidate_session(session)
    assert auth.get_current_user(session) is None
    with pytest.raises(RuntimeError):
        auth.require_auth(session)


async def test_narrowed_scopes_replace_cached_scopes(session, monkeypatch):
    fresh = {"user_id": "agent-1", "name": "a", "identity_type": "user", "tenant_id": "t1", "scopes": ["memory:read"]}
    remote = AsyncMock(return_value=fresh)
    monkeypatch.setattr(auth, "authenticate_remote", remote)
    await auth.revalidate_session(session)
    user = auth.require_auth(session)
    assert user["scopes"] == ["memory:read"]
    assert user["project_memberships"] == ["p1"]
    assert remote.await_args.kwargs == {"use_cache": False}


async def test_revalidation_is_throttled(session, monkeypatch):
    monkeypatch.setattr(auth, "SESSION_REVALIDATE_SECONDS", 3600)
    remote = AsyncMock(return_value=None)
    monkeypatch.setattr(auth, "authenticate_remote", remote)
    await auth.revalidate_session(session)
    remote.assert_not_awaited()


async def test_auth_outage_fails_closed(session, monkeypatch):
    monkeypatch.setattr(auth, "authenticate_remote", AsyncMock(side_effect=auth.AuthServiceUnavailableError("down")))
    with pytest.raises(auth.AuthServiceUnavailableError):
        await auth.revalidate_session(session)


async def test_rejected_key_is_evicted_from_cache(monkeypatch):
    import hashlib

    auth._remote_key_cache[hashlib.sha256(b"k").hexdigest()] = ({"user_id": "x"}, 9e18)
    monkeypatch.setenv("AUTH_API_KEY_VALIDATE_URL", "http://auth/internal/validate-api-key")
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "svc")

    class _Resp:
        status_code = 401

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _Client)
    assert await auth.authenticate_remote("k", use_cache=False) is None
    assert hashlib.sha256(b"k").hexdigest() not in auth._remote_key_cache


def test_cache_ttl_default_is_short():
    assert auth._CACHE_TTL <= 60
