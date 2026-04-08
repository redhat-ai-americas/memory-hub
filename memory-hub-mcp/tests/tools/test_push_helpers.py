"""Tests for ``src.tools._push_helpers.broadcast_after_write`` (#62 Phase 3).

Verifies the helper that mutating tools call after a successful DB commit:

- Fast path returns immediately when there are no relevant subscribers,
  avoiding the embedding service call entirely.
- When relevant subscribers exist, the new content is embedded once and
  the focus filter is applied to broadcast targeting.
- Delete path (``content_for_filter=None``) skips embedding and delivers
  the broadcast unconditionally to every active session.
- Backend failures are swallowed silently — a broadcast bug must never
  surface in the tool's response path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.push_broadcast import build_uri_only_notification
from memoryhub_core.services.valkey_client import (
    ACTIVE_SESSIONS_KEY,
    ValkeyClient,
    set_valkey_client,
)
from src.tools._push_helpers import broadcast_after_write


@pytest.fixture
def _reset_valkey_client():
    set_valkey_client(None)
    yield
    set_valkey_client(None)


@pytest.fixture
def fake_valkey(_reset_valkey_client) -> ValkeyClient:
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(
        settings=ValkeySettings(
            session_ttl_seconds=900,
            history_retention_days=30,
            broadcast_ttl_seconds=300,
            broadcast_pop_timeout_seconds=1,
        ),
        client=fake,
    )
    set_valkey_client(client)
    return client


def _claims(sub: str = "wjackson") -> dict:
    return {"sub": sub, "scopes": ["memory:write:user"]}


class TestFastPath:
    """No-subscriber and writer-only-subscriber cases skip the embed call."""

    async def test_no_active_sessions_skips_embed_and_broadcast(self, fake_valkey):
        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(),
            content_for_filter="some content",
            embedding_service=embedding_service,
        )

        # Embedding was never requested because no one is listening.
        embedding_service.embed.assert_not_called()

        # And nothing landed in any broadcast queue.
        fake = fake_valkey._client
        keys = await fake.keys("memoryhub:broadcast:*")
        assert keys == []

    async def test_only_writer_in_active_sessions_skips_embed(self, fake_valkey):
        await fake_valkey.register_active_session("wjackson")
        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(sub="wjackson"),
            content_for_filter="some content",
            embedding_service=embedding_service,
        )

        # Writer is excluded from the broadcast set, so the helper sees zero
        # relevant subscribers and skips the embed call entirely.
        embedding_service.embed.assert_not_called()


class TestBroadcastFires:
    """When relevant subscribers exist, embed + broadcast happen."""

    async def test_other_subscriber_triggers_embed_and_push(self, fake_valkey):
        await fake_valkey.register_active_session("wjackson")
        await fake_valkey.register_active_session("other-agent")

        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(sub="wjackson"),
            content_for_filter="memory content",
            embedding_service=embedding_service,
        )

        # Embed happened exactly once (one write = one embed, regardless of
        # subscriber count).
        embedding_service.embed.assert_called_once_with("memory content")

        # The other agent's broadcast queue got the message; the writer's
        # did not (excluded by sub claim).
        fake = fake_valkey._client
        assert await fake.llen("memoryhub:broadcast:other-agent") == 1
        assert await fake.llen("memoryhub:broadcast:wjackson") == 0


class TestDeletePath:
    """``content_for_filter=None`` bypasses the focus filter entirely."""

    async def test_delete_skips_embed_but_still_broadcasts(self, fake_valkey):
        """Deletes broadcast unconditionally (every active session learns)
        and pay no embedding cost."""
        await fake_valkey.register_active_session("wjackson")
        await fake_valkey.register_active_session("other-agent")

        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(sub="wjackson"),
            content_for_filter=None,
            embedding_service=None,
        )

        fake = fake_valkey._client
        assert await fake.llen("memoryhub:broadcast:other-agent") == 1
        assert await fake.llen("memoryhub:broadcast:wjackson") == 0


class TestFailureTolerance:
    """Backend failures must be swallowed so a broadcast bug never reaches
    the agent's response path."""

    async def test_valkey_outage_does_not_raise(self, _reset_valkey_client):
        from redis.exceptions import ConnectionError as RedisConnectionError

        class BrokenClient:
            async def smembers(self, *args, **kwargs):
                raise RedisConnectionError("simulated outage")

            async def aclose(self):
                pass

        broken = ValkeyClient(
            settings=ValkeySettings(session_ttl_seconds=900),
            client=BrokenClient(),
        )
        set_valkey_client(broken)

        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        # Should NOT raise — the helper swallows ValkeyUnavailableError.
        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(),
            content_for_filter="content",
            embedding_service=embedding_service,
        )

        # Embedding was never reached because the SMEMBERS call failed first.
        embedding_service.embed.assert_not_called()

    async def test_embed_failure_delivers_unfiltered(self, fake_valkey):
        """If the embedding service fails, the helper logs and delivers the
        broadcast unfiltered rather than dropping it. The agent still learns
        the memory was written; it just doesn't get the focus pre-filter."""
        await fake_valkey.register_active_session("wjackson")
        await fake_valkey.register_active_session("other-agent")

        embedding_service = AsyncMock()
        embedding_service.embed = AsyncMock(side_effect=RuntimeError("embed boom"))

        await broadcast_after_write(
            memory_id="mem-1",
            notification=build_uri_only_notification("mem-1"),
            claims=_claims(sub="wjackson"),
            content_for_filter="content",
            embedding_service=embedding_service,
        )

        fake = fake_valkey._client
        # other-agent receives unfiltered (embed failed → no filter applied)
        assert await fake.llen("memoryhub:broadcast:other-agent") == 1
