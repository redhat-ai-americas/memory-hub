"""Concurrency coverage for API-key identity bound to MCP transport sessions."""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import AsyncExitStack

import pytest
from src.core.authz import get_claims_from_context
from src.tools import auth


class _FakeMcpContext:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.session = type("Session", (), {"_exit_stack": AsyncExitStack()})()


@pytest.fixture(autouse=True)
def _clear_auth_state(monkeypatch):
    active_context: contextvars.ContextVar[_FakeMcpContext | None] = (
        contextvars.ContextVar("active_mcp_context", default=None)
    )
    monkeypatch.setattr(auth, "_get_active_context", active_context.get)
    auth.clear_session()
    yield active_context
    auth.clear_session()


def _register(
    ctx: _FakeMcpContext,
    *,
    user_id: str,
    scopes: list[str],
    memberships: list[str],
    session_id: str,
    default_driver_id: str,
    tenant_id: str = "default",
) -> None:
    auth.set_session(
        {
            "user_id": user_id,
            "name": user_id.title(),
            "scopes": scopes,
            "project_memberships": memberships,
            "tenant_id": tenant_id,
        },
        ttl_seconds=600,
        ctx=ctx,
        session_id=session_id,
        default_driver_id=default_driver_id,
    )


@pytest.mark.asyncio
async def test_interleaved_clients_resolve_their_own_identity_and_session(
    _clear_auth_state,
):
    active_context = _clear_auth_state
    context_a = _FakeMcpContext("mcp-client-a")
    context_b = _FakeMcpContext("mcp-client-b")
    _register(
        context_a,
        user_id="user-a",
        scopes=["user", "project"],
        memberships=["project-a"],
        tenant_id="tenant-a",
        session_id="memoryhub-session-a",
        default_driver_id="driver-a",
    )
    _register(
        context_b,
        user_id="user-b",
        scopes=["user"],
        memberships=["project-b"],
        tenant_id="tenant-b",
        session_id="memoryhub-session-b",
        default_driver_id="driver-b",
    )

    both_ready = asyncio.Event()
    ready_count = 0

    async def observe(context: _FakeMcpContext) -> dict:
        nonlocal ready_count
        token = active_context.set(context)
        try:
            ready_count += 1
            if ready_count == 2:
                both_ready.set()
            await both_ready.wait()
            claims = get_claims_from_context()
            return {
                "claims": claims,
                "session_id": auth.get_session_id(),
                "driver_id": auth.get_default_driver_id(),
            }
        finally:
            active_context.reset(token)

    result_a, result_b = await asyncio.gather(observe(context_a), observe(context_b))

    assert result_a["claims"]["sub"] == "user-a"
    assert result_a["claims"]["tenant_id"] == "tenant-a"
    assert result_a["claims"]["project_memberships"] == ["project-a"]
    assert "memory:write:project" in result_a["claims"]["scopes"]
    assert result_a["session_id"] == "memoryhub-session-a"
    assert result_a["driver_id"] == "driver-a"
    assert result_b["claims"]["sub"] == "user-b"
    assert result_b["claims"]["tenant_id"] == "tenant-b"
    assert result_b["claims"]["project_memberships"] == ["project-b"]
    assert "memory:write:project" not in result_b["claims"]["scopes"]
    assert result_b["session_id"] == "memoryhub-session-b"
    assert result_b["driver_id"] == "driver-b"


def test_same_user_gets_independent_per_mcp_session_state(_clear_auth_state):
    context_a = _FakeMcpContext("same-user-client-a")
    context_b = _FakeMcpContext("same-user-client-b")
    shared_user = {
        "user_id": "shared-user",
        "name": "Shared User",
        "scopes": ["user"],
        "project_memberships": ["project-shared"],
    }
    _register(
        context_a,
        user_id=shared_user["user_id"],
        scopes=shared_user["scopes"],
        memberships=shared_user["project_memberships"],
        session_id="shared-user-session-a",
        default_driver_id="driver-a",
    )
    _register(
        context_b,
        user_id=shared_user["user_id"],
        scopes=shared_user["scopes"],
        memberships=shared_user["project_memberships"],
        session_id="shared-user-session-b",
        default_driver_id="driver-b",
    )

    assert auth.get_current_user(context_a)["user_id"] == "shared-user"
    assert auth.get_current_user(context_b)["user_id"] == "shared-user"
    assert auth.get_session_id(context_a) == "shared-user-session-a"
    assert auth.get_session_id(context_b) == "shared-user-session-b"
    assert auth.get_default_driver_id(context_a) == "driver-a"
    assert auth.get_default_driver_id(context_b) == "driver-b"


@pytest.mark.asyncio
async def test_disconnect_cleanup_removes_only_the_disconnected_binding(
    _clear_auth_state,
):
    context_a = _FakeMcpContext("disconnect-client-a")
    context_b = _FakeMcpContext("disconnect-client-b")
    _register(
        context_a,
        user_id="user-a",
        scopes=["user"],
        memberships=[],
        session_id="memoryhub-session-a",
        default_driver_id="driver-a",
    )
    _register(
        context_b,
        user_id="user-b",
        scopes=["user"],
        memberships=[],
        session_id="memoryhub-session-b",
        default_driver_id="driver-b",
    )

    await context_a.session._exit_stack.aclose()

    assert auth.get_current_user(context_a) is None
    assert auth.get_current_user(context_b)["user_id"] == "user-b"
    assert auth.get_session_id(context_a) is None
    assert auth.get_session_id(context_b) == "memoryhub-session-b"


def test_expired_client_cannot_use_another_clients_registration(_clear_auth_state):
    from datetime import UTC, datetime, timedelta

    context_a = _FakeMcpContext("expired-client-a")
    context_b = _FakeMcpContext("valid-client-b")
    _register(
        context_a,
        user_id="user-a",
        scopes=["user"],
        memberships=[],
        session_id="memoryhub-session-a",
        default_driver_id="driver-a",
    )
    _register(
        context_b,
        user_id="user-b",
        scopes=["user"],
        memberships=[],
        session_id="memoryhub-session-b",
        default_driver_id="driver-b",
    )
    auth._sessions_by_mcp_session[context_a.session_id].expires_at = (
        datetime.now(UTC) - timedelta(seconds=1)
    )

    assert auth.get_current_user(context_a) is None
    with pytest.raises(RuntimeError, match="Session expired"):
        auth.require_auth(context_a)
    assert auth.get_current_user(context_b)["user_id"] == "user-b"
    assert context_a.session_id not in auth._sessions_by_mcp_session
