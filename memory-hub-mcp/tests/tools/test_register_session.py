"""Tests for register_session — Phase 1b push lifecycle wiring (#62).

Exercises the integration between the API-key authentication flow and the
new push subscriber lifecycle: SADD to ``memoryhub:active_sessions``, spawn
of the per-session subscriber task, and registration of an
``_exit_stack``-driven cleanup callback that undoes both on disconnect.
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

import fakeredis.aioredis
import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.push_subscriber import (
    _reset_subscriber_registry_for_tests,
    get_active_subscriber_count,
)
from memoryhub_core.services.valkey_client import (
    ACTIVE_SESSIONS_KEY,
    ValkeyClient,
    set_valkey_client,
)
from src.tools.register_session import register_session

# FastMCP's @mcp.tool decorator returns the original function in this codebase
# (verified by the existing set_session_focus tests), so we don't need .fn here.
register_session_fn = register_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_valkey_client():
    """Reset the module-level Valkey singleton between tests."""
    set_valkey_client(None)
    yield
    set_valkey_client(None)


@pytest.fixture
def fake_valkey(_reset_valkey_client) -> ValkeyClient:
    """Install a fakeredis-backed ValkeyClient as the process default."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(
        settings=ValkeySettings(
            session_ttl_seconds=900,
            history_retention_days=30,
            broadcast_ttl_seconds=300,
            broadcast_pop_timeout_seconds=1,  # short for fast tests
        ),
        client=fake,
    )
    set_valkey_client(client)
    return client


@pytest.fixture(autouse=True)
def reset_push_subscriber_registry():
    """Clear the module-global subscriber registry between tests.

    The registry tracks process-wide state (one task per live session), so
    tests must clean up after themselves to avoid leaking tasks into
    neighboring cases."""
    _reset_subscriber_registry_for_tests()
    yield
    _reset_subscriber_registry_for_tests()


@pytest.fixture
def mock_authenticate():
    """Replace ``authenticate`` so we can drive both success and failure paths."""
    with patch("src.tools.register_session.authenticate") as mocker:
        yield mocker


@pytest.fixture
def mock_set_session():
    """Replace ``set_session`` so the API-key path is a no-op for identity."""
    with patch("src.tools.register_session.set_session"):
        yield


# ---------------------------------------------------------------------------
# Fake MCP types — minimal stand-ins for the FastMCP context surface
# ---------------------------------------------------------------------------


class FakeServerSession:
    """Stand-in for ``mcp.server.session.ServerSession``.

    Owns a real ``contextlib.AsyncExitStack`` so the test can call
    ``aclose()`` to drive the cleanup callbacks the same way FastMCP's
    streamable-http transport does on session shutdown.
    """

    def __init__(self):
        self._exit_stack = contextlib.AsyncExitStack()
        self.sent: list = []

    async def send_notification(self, notification):
        self.sent.append(notification)


class FakeContext:
    """Stand-in for ``fastmcp.Context`` exposing only what register_session uses."""

    def __init__(self, session: FakeServerSession | None = None):
        self._session = session or FakeServerSession()
        self.info_calls: list[str] = []

    @property
    def session(self) -> FakeServerSession:
        return self._session

    async def info(self, message: str) -> None:
        self.info_calls.append(message)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInvalidApiKey:
    """An invalid key must raise ToolError and not touch the push pipeline."""

    async def test_raises_tool_error_and_no_push_wiring(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        mock_authenticate.return_value = None
        ctx = FakeContext()

        with pytest.raises(ToolError, match="Invalid API key"):
            await register_session_fn(api_key="bogus", ctx=ctx)

        # No SADD, no subscriber, no cleanup callback.
        members = await fake_valkey._client.smembers(ACTIVE_SESSIONS_KEY)
        assert members == set()
        assert get_active_subscriber_count() == 0


class TestValidApiKey:
    """Successful API-key auth wires push end-to-end."""

    async def test_registers_active_session(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": ["memory:read:user", "memory:write:user"],
        }
        ctx = FakeContext()

        result = await register_session_fn(api_key="valid", ctx=ctx)

        assert result["user_id"] == "wjackson"
        members = await fake_valkey._client.smembers(ACTIVE_SESSIONS_KEY)
        assert members == {"wjackson"}

    async def test_starts_subscriber_task(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": ["memory:read:user"],
        }
        ctx = FakeContext()

        await register_session_fn(api_key="valid", ctx=ctx)

        assert get_active_subscriber_count() == 1

    async def test_cleanup_callback_unwinds_on_session_close(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        """Closing the session's _exit_stack should cancel the subscriber
        and remove the session from the active set — same lifecycle path
        FastMCP's transport drives on real disconnect."""
        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": [],
        }
        fake_session = FakeServerSession()
        ctx = FakeContext(session=fake_session)

        await register_session_fn(api_key="valid", ctx=ctx)
        assert get_active_subscriber_count() == 1
        members = await fake_valkey._client.smembers(ACTIVE_SESSIONS_KEY)
        assert members == {"wjackson"}

        # Drive the cleanup the way FastMCP's session __aexit__ would.
        await fake_session._exit_stack.aclose()

        assert get_active_subscriber_count() == 0
        members = await fake_valkey._client.smembers(ACTIVE_SESSIONS_KEY)
        assert members == set()

    async def test_duplicate_register_does_not_register_cleanup_twice(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        """Calling register_session twice for the same session should be
        idempotent: same subscriber task, exactly one cleanup callback on
        the _exit_stack."""
        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": [],
        }
        fake_session = FakeServerSession()
        ctx = FakeContext(session=fake_session)

        await register_session_fn(api_key="valid", ctx=ctx)
        await register_session_fn(api_key="valid", ctx=ctx)

        # Idempotent subscriber registry — only one task.
        assert get_active_subscriber_count() == 1
        # The session-scoped flag should have been set on first call and
        # short-circuited the cleanup-registration on the second call.
        assert getattr(fake_session, "_memoryhub_push_cleanup_registered", False)

        # And cleanup should still work cleanly when fired.
        await fake_session._exit_stack.aclose()
        assert get_active_subscriber_count() == 0


class TestNoContextDegradesGracefully:
    """If a tool is invoked without a Context (rare — out-of-band call), the
    SADD should still happen but the subscriber loop is skipped because
    there's no session to forward notifications to."""

    async def test_sads_session_but_skips_subscriber(
        self, fake_valkey, mock_authenticate, mock_set_session
    ):
        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": [],
        }

        await register_session_fn(api_key="valid", ctx=None)

        members = await fake_valkey._client.smembers(ACTIVE_SESSIONS_KEY)
        assert members == {"wjackson"}
        assert get_active_subscriber_count() == 0


class TestValkeyUnavailable:
    """Push infra failures must not block authentication. The agent should
    still receive the user identity dict so it can use pull-based memory
    loading even when the push pipeline is broken."""

    async def test_registration_succeeds_when_valkey_down(
        self, _reset_valkey_client, mock_authenticate, mock_set_session
    ):
        from memoryhub_core.services.valkey_client import (
            ValkeyClient as RealValkeyClient,
        )
        from redis.exceptions import ConnectionError as RedisConnectionError

        class BrokenClient:
            async def sadd(self, *args, **kwargs):
                raise RedisConnectionError("simulated outage")

            async def aclose(self):
                pass

        broken = RealValkeyClient(
            settings=ValkeySettings(session_ttl_seconds=900),
            client=BrokenClient(),
        )
        set_valkey_client(broken)

        mock_authenticate.return_value = {
            "user_id": "wjackson",
            "name": "Wes Jackson",
            "scopes": [],
        }
        ctx = FakeContext()

        result = await register_session_fn(api_key="valid", ctx=ctx)

        # Authentication still succeeds; push wiring degraded silently.
        assert result.get("error") is not True
        assert result["user_id"] == "wjackson"
        assert get_active_subscriber_count() == 0
