"""Tests for ``memoryhub_core.services.push_broadcast`` (#62 writer side).

The broadcast helper is exercised end-to-end against a fakeredis-backed
ValkeyClient. Session focus vectors are written via the real
``write_session_focus`` path so the tests also verify that the #61 storage
schema and #62's reader of that schema agree on the wire format.
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.push_broadcast import (
    DEFAULT_PUSH_FILTER_WEIGHT,
    broadcast_to_sessions,
    build_full_content_notification,
    build_uri_only_notification,
    cosine_similarity,
    memory_uri,
)
from memoryhub_core.services.valkey_client import ValkeyClient


@pytest.fixture
async def valkey_client() -> ValkeyClient:
    """A ValkeyClient backed by an in-memory fakeredis instance."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(
        settings=ValkeySettings(
            session_ttl_seconds=900,
            history_retention_days=30,
            broadcast_ttl_seconds=300,
            broadcast_pop_timeout_seconds=1,  # keep tests fast
        ),
        client=fake,
    )
    yield client
    await client.close()


class TestCosineSimilarity:
    def test_identical_vectors_are_one(self):
        v = [0.3, 0.4, 0.5, 0.6]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors_are_zero(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0

    def test_opposite_vectors_are_negative_one(self):
        assert abs(cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9

    def test_zero_vector_returns_zero_not_nan(self):
        """Zero vectors short-circuit to 0.0 to avoid division by zero.
        Without this guard the function would return NaN, which propagates
        through the filter and produces silently-wrong results."""
        assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0
        assert cosine_similarity([1.0, 2.0, 3.0], [0.0, 0.0, 0.0]) == 0.0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="vector length mismatch"):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


class TestBuildNotifications:
    def test_memory_uri_format(self):
        assert memory_uri("abc-123") == "memoryhub://memory/abc-123"

    def test_uri_only_notification_shape(self):
        notif = build_uri_only_notification("mem-42")
        assert notif["method"] == "notifications/resources/updated"
        assert notif["params"] == {"uri": "memoryhub://memory/mem-42"}

    def test_full_content_notification_shape(self):
        memory = {
            "id": "mem-42",
            "content": "test content",
            "scope": "user",
            "weight": 0.8,
        }
        notif = build_full_content_notification(memory)
        assert notif["method"] == "notifications/memoryhub/memory_written"
        assert notif["params"]["uri"] == "memoryhub://memory/mem-42"
        assert notif["params"]["memory"] == memory


class TestBroadcastToSessions:
    """End-to-end: active_sessions + focus filter + LPUSH to broadcast queue."""

    async def _register(self, client: ValkeyClient, session_id: str) -> None:
        await client.register_active_session(session_id)

    async def _set_focus(
        self,
        client: ValkeyClient,
        session_id: str,
        focus_vector: list[float],
    ) -> None:
        await client.write_session_focus(
            session_id=session_id,
            focus="test-focus",
            focus_vector=focus_vector,
            user_id="wjackson",
            project="memory-hub",
        )

    async def test_no_active_sessions_delivers_none(self, valkey_client):
        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=[0.1, 0.2, 0.3],
            valkey_client=valkey_client,
        )
        assert result == {"targeted": 0, "delivered": 0, "filtered": 0, "errors": 0}

    async def test_delivers_to_all_sessions_without_focus(self, valkey_client):
        """Sessions that are registered but have not declared a focus bypass
        the filter — they receive every broadcast. This matches the pull-side
        convention that focus is optional."""
        for sid in ["a", "b", "c"]:
            await self._register(valkey_client, sid)

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=[0.1, 0.2, 0.3],
            valkey_client=valkey_client,
        )
        assert result["targeted"] == 3
        assert result["delivered"] == 3
        assert result["filtered"] == 0
        assert result["errors"] == 0

        # Verify each broadcast queue got exactly one message
        fake = valkey_client._client
        for sid in ["a", "b", "c"]:
            assert await fake.llen(f"memoryhub:broadcast:{sid}") == 1

    async def test_focus_filter_skips_off_topic_sessions(self, valkey_client):
        """Session 'on-topic' declares a focus vector matching the memory
        embedding; session 'off-topic' declares an orthogonal one. With the
        default push_filter_weight=0.6, on-topic receives the broadcast and
        off-topic is filtered out."""
        await self._register(valkey_client, "on-topic")
        await self._register(valkey_client, "off-topic")

        memory_embedding = [1.0, 0.0, 0.0]
        await self._set_focus(valkey_client, "on-topic", [1.0, 0.0, 0.0])
        await self._set_focus(valkey_client, "off-topic", [0.0, 1.0, 0.0])

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=memory_embedding,
            valkey_client=valkey_client,
            push_filter_weight=DEFAULT_PUSH_FILTER_WEIGHT,
        )

        assert result["targeted"] == 2
        assert result["delivered"] == 1
        assert result["filtered"] == 1
        assert result["errors"] == 0

        fake = valkey_client._client
        assert await fake.llen("memoryhub:broadcast:on-topic") == 1
        assert await fake.llen("memoryhub:broadcast:off-topic") == 0

    async def test_exclude_session_id_skips_the_writer(self, valkey_client):
        """When the writing agent is itself an active session, it should not
        receive a broadcast for its own write."""
        for sid in ["writer", "reader-1", "reader-2"]:
            await self._register(valkey_client, sid)

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=[0.1, 0.2, 0.3],
            valkey_client=valkey_client,
            exclude_session_id="writer",
        )
        assert result["targeted"] == 2
        assert result["delivered"] == 2

        fake = valkey_client._client
        assert await fake.llen("memoryhub:broadcast:writer") == 0
        assert await fake.llen("memoryhub:broadcast:reader-1") == 1
        assert await fake.llen("memoryhub:broadcast:reader-2") == 1

    async def test_none_memory_embedding_bypasses_filter(self, valkey_client):
        """Deletes don't carry an embedding — the caller passes None and
        every active session receives the broadcast regardless of focus."""
        await self._register(valkey_client, "on-topic")
        await self._register(valkey_client, "off-topic")
        await self._set_focus(valkey_client, "on-topic", [1.0, 0.0, 0.0])
        await self._set_focus(valkey_client, "off-topic", [0.0, 1.0, 0.0])

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=None,
            valkey_client=valkey_client,
        )

        assert result["targeted"] == 2
        assert result["delivered"] == 2
        assert result["filtered"] == 0

    async def test_zero_filter_weight_delivers_to_all(self, valkey_client):
        """push_filter_weight=0.0 disables the filter: all cosine similarities
        are >= 0 so nothing is filtered."""
        await self._register(valkey_client, "a")
        await self._register(valkey_client, "b")
        await self._set_focus(valkey_client, "a", [1.0, 0.0, 0.0])
        await self._set_focus(valkey_client, "b", [0.0, 1.0, 0.0])

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=[1.0, 0.0, 0.0],
            valkey_client=valkey_client,
            push_filter_weight=0.0,
        )

        assert result["delivered"] == 2
        assert result["filtered"] == 0

    async def test_length_mismatch_logs_and_delivers(self, valkey_client):
        """If a session's stored focus vector has a different dimension than
        the memory embedding (e.g., embedding model changed between writes),
        the helper logs a warning and delivers the broadcast unfiltered
        rather than erroring. Graceful degradation over hard failure."""
        await self._register(valkey_client, "mismatched")
        await self._set_focus(valkey_client, "mismatched", [0.1, 0.2])  # 2-dim

        result = await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=[0.1, 0.2, 0.3],  # 3-dim
            valkey_client=valkey_client,
        )
        assert result["delivered"] == 1
        assert result["errors"] == 0

    async def test_envelope_contains_expected_attempt_counter(self, valkey_client):
        """The subscriber loop expects envelopes shaped as
        ``{notification, attempt}`` so it can drive retry logic."""
        await self._register(valkey_client, "sess")
        await broadcast_to_sessions(
            notification=build_uri_only_notification("mem-1"),
            memory_embedding=None,
            valkey_client=valkey_client,
        )

        fake = valkey_client._client
        raw = await fake.lrange("memoryhub:broadcast:sess", 0, -1)
        assert len(raw) == 1
        envelope = json.loads(raw[0])
        assert envelope["attempt"] == 0
        assert envelope["notification"]["method"] == "notifications/resources/updated"
        assert envelope["notification"]["params"]["uri"] == "memoryhub://memory/mem-1"
