"""Tests for ``memoryhub_core.services.push_subscriber`` (#62 reader side).

Exercises the subscriber loop + lifecycle management against a fakeredis
ValkeyClient and a minimal stand-in for FastMCP 3's ``ServerSession``.
The stand-in records calls to ``send_notification`` so tests can assert on
delivery without bringing up the full FastMCP transport stack.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import fakeredis.aioredis
import mcp.types as mt
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.push_broadcast import (
    build_full_content_notification,
    build_uri_only_notification,
)
from memoryhub_core.services.push_subscriber import (
    _reconstruct_notification,
    _reset_subscriber_registry_for_tests,
    ensure_memoryhub_subscriber_running,
    get_active_subscriber_count,
    memoryhub_subscriber_loop,
    stop_memoryhub_subscriber,
)
from memoryhub_core.services.valkey_client import ValkeyClient


class FakeServerSession:
    """Minimal stand-in for ``mcp.server.session.ServerSession``.

    Records every call to ``send_notification`` for later assertion. The
    ``fail_first_n`` constructor arg lets tests simulate a session that
    rejects notifications a few times before succeeding, so the retry path
    in the subscriber loop gets exercised.
    """

    def __init__(self, fail_first_n: int = 0):
        self.sent: list[Any] = []
        self._fail_count = 0
        self._fail_first_n = fail_first_n

    async def send_notification(self, notification: Any) -> None:
        if self._fail_count < self._fail_first_n:
            self._fail_count += 1
            raise RuntimeError(f"simulated send failure {self._fail_count}")
        self.sent.append(notification)


@pytest.fixture
async def valkey_client() -> ValkeyClient:
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
    yield client
    await client.close()


@pytest.fixture(autouse=True)
def reset_subscriber_registry():
    """Clear the module-level subscriber registry between tests.

    The registry is process-global by design (it tracks one subscriber
    per live session), so tests must clean up after themselves to avoid
    leaking tasks into neighbors."""
    _reset_subscriber_registry_for_tests()
    yield
    _reset_subscriber_registry_for_tests()


async def _drain_until(
    condition,
    *,
    timeout: float = 2.0,
    interval: float = 0.02,
) -> bool:
    """Poll ``condition`` until True or timeout expires.

    Used for async assertions where the subscriber loop needs a few scheduler
    turns before the observable state matches what the test expects. Keeps
    tests deterministic without sprinkling fixed sleeps throughout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return False


class TestReconstructNotification:
    """Subscriber round-trip: dict -> Pydantic notification type."""

    def test_spec_compliant_uri_only_wraps_in_server_notification(self):
        dict_form = build_uri_only_notification("mem-42")
        notif = _reconstruct_notification(dict_form)
        assert isinstance(notif, mt.ServerNotification)
        # The root of the RootModel union should be a ResourceUpdatedNotification.
        assert isinstance(notif.root, mt.ResourceUpdatedNotification)
        # params.uri is a Pydantic AnyUrl, not a plain str — str() coerces for
        # equality comparison without losing the URL type in the runtime value.
        assert str(notif.root.params.uri) == "memoryhub://memory/mem-42"

    def test_custom_full_content_returns_plain_notification(self):
        dict_form = build_full_content_notification(
            {"id": "mem-42", "content": "hello"}
        )
        notif = _reconstruct_notification(dict_form)
        # Not in the closed ServerNotification union — stays as a plain
        # Notification instance which ServerSession.send_notification can
        # still serialize via model_dump.
        assert not isinstance(notif, mt.ServerNotification)
        assert isinstance(notif, mt.Notification)
        dumped = notif.model_dump(by_alias=True, mode="json", exclude_none=True)
        assert dumped["method"] == "notifications/memoryhub/memory_written"
        assert dumped["params"]["uri"] == "memoryhub://memory/mem-42"
        assert dumped["params"]["memory"]["id"] == "mem-42"


class TestSubscriberLifecycle:
    """ensure_memoryhub_subscriber_running / stop_memoryhub_subscriber."""

    async def test_ensure_starts_a_task(self, valkey_client):
        session = FakeServerSession()
        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        assert get_active_subscriber_count() == 1
        await stop_memoryhub_subscriber("sess-1")

    async def test_ensure_is_idempotent_on_live_task(self, valkey_client):
        """Calling ensure twice for the same session is a no-op the second time."""
        session = FakeServerSession()
        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        assert get_active_subscriber_count() == 1
        await stop_memoryhub_subscriber("sess-1")

    async def test_stop_cancels_the_task(self, valkey_client):
        session = FakeServerSession()
        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        await stop_memoryhub_subscriber("sess-1")
        assert get_active_subscriber_count() == 0

    async def test_stop_is_noop_for_unknown_session(self, valkey_client):
        # Should not raise or otherwise misbehave.
        await stop_memoryhub_subscriber("never-started")
        assert get_active_subscriber_count() == 0

    async def test_multiple_sessions_tracked_independently(self, valkey_client):
        sessions = [FakeServerSession() for _ in range(3)]
        for i, session in enumerate(sessions):
            await ensure_memoryhub_subscriber_running(
                f"sess-{i}", session, valkey_client
            )
        assert get_active_subscriber_count() == 3

        await stop_memoryhub_subscriber("sess-1")
        assert get_active_subscriber_count() == 2

        await stop_memoryhub_subscriber("sess-0")
        await stop_memoryhub_subscriber("sess-2")
        assert get_active_subscriber_count() == 0


class TestSubscriberLoop:
    """End-to-end: LPUSH -> subscriber loop -> FakeServerSession.send_notification."""

    async def test_happy_path_delivers_one_message(self, valkey_client):
        session = FakeServerSession()

        # Pre-load a message into the queue so BRPOP returns immediately.
        envelope = {
            "notification": build_uri_only_notification("mem-1"),
            "attempt": 0,
        }
        await valkey_client.push_broadcast_message("sess-1", json.dumps(envelope))

        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        delivered = await _drain_until(lambda: len(session.sent) == 1)
        await stop_memoryhub_subscriber("sess-1")

        assert delivered, "subscriber did not deliver the message within timeout"
        assert isinstance(session.sent[0], mt.ServerNotification)
        assert isinstance(session.sent[0].root, mt.ResourceUpdatedNotification)
        assert str(session.sent[0].root.params.uri) == "memoryhub://memory/mem-1"

    async def test_happy_path_delivers_multiple_in_fifo_order(self, valkey_client):
        session = FakeServerSession()

        for i in range(3):
            envelope = {
                "notification": build_uri_only_notification(f"mem-{i}"),
                "attempt": 0,
            }
            await valkey_client.push_broadcast_message("sess-1", json.dumps(envelope))

        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        delivered = await _drain_until(lambda: len(session.sent) == 3)
        await stop_memoryhub_subscriber("sess-1")

        assert delivered
        uris = [str(n.root.params.uri) for n in session.sent]
        assert uris == [
            "memoryhub://memory/mem-0",
            "memoryhub://memory/mem-1",
            "memoryhub://memory/mem-2",
        ]

    async def test_malformed_json_is_dropped_loop_continues(self, valkey_client):
        """A bad envelope shouldn't terminate the subscriber. Push garbage,
        then a good message, and verify the good one is still delivered."""
        session = FakeServerSession()

        await valkey_client.push_broadcast_message("sess-1", "not valid json{")
        good = {
            "notification": build_uri_only_notification("mem-1"),
            "attempt": 0,
        }
        await valkey_client.push_broadcast_message("sess-1", json.dumps(good))

        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        delivered = await _drain_until(lambda: len(session.sent) == 1)
        await stop_memoryhub_subscriber("sess-1")

        assert delivered
        assert str(session.sent[0].root.params.uri) == "memoryhub://memory/mem-1"

    async def test_delivery_failure_triggers_retry(self, valkey_client):
        """If send_notification raises, the subscriber re-queues the message
        with attempt+1 until MAX_DELIVERY_ATTEMPTS is reached. FakeServerSession
        configured to fail once then succeed should result in exactly one
        delivered notification."""
        session = FakeServerSession(fail_first_n=1)
        envelope = {
            "notification": build_uri_only_notification("mem-1"),
            "attempt": 0,
        }
        await valkey_client.push_broadcast_message("sess-1", json.dumps(envelope))

        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)
        delivered = await _drain_until(lambda: len(session.sent) == 1, timeout=3.0)
        await stop_memoryhub_subscriber("sess-1")

        assert delivered, "retry path did not eventually deliver"
        assert len(session.sent) == 1

    async def test_delivery_discarded_after_max_attempts(self, valkey_client):
        """A session that always fails exhausts the retry budget and discards
        the message; the queue should be empty after the subscriber gives up."""
        session = FakeServerSession(fail_first_n=999)  # never succeeds
        envelope = {
            "notification": build_uri_only_notification("mem-1"),
            "attempt": 0,
        }
        await valkey_client.push_broadcast_message("sess-1", json.dumps(envelope))

        await ensure_memoryhub_subscriber_running("sess-1", session, valkey_client)

        fake = valkey_client._client

        async def queue_empty() -> bool:
            # Use EXISTS rather than LLEN because Redis auto-deletes empty
            # lists and fakeredis's LLEN on a deleted key returns None, not 0.
            return await fake.exists("memoryhub:broadcast:sess-1") == 0

        # Give the subscriber enough turns to run through MAX_DELIVERY_ATTEMPTS.
        # The loop requeues with attempt+1, processes again, requeues, etc.
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            if await queue_empty():
                break
            await asyncio.sleep(0.05)

        await stop_memoryhub_subscriber("sess-1")

        # Nothing was delivered (all three attempts failed) and nothing
        # remains in the queue (discarded after MAX_DELIVERY_ATTEMPTS).
        # Note: fakeredis's EXISTS on a drained-auto-deleted key can return
        # None rather than 0 (real Redis returns 0). `not result` covers both.
        assert session.sent == []
        assert not await fake.exists("memoryhub:broadcast:sess-1"), (
            "queue should be empty after MAX_DELIVERY_ATTEMPTS discard"
        )

    async def test_cancellation_exits_cleanly(self, valkey_client):
        """stop_memoryhub_subscriber cancels the task. The loop catches
        CancelledError and re-raises so asyncio can mark the task done."""
        session = FakeServerSession()
        task = asyncio.create_task(
            memoryhub_subscriber_loop("sess-1", session, valkey_client)
        )
        await asyncio.sleep(0.05)  # let it enter BRPOP
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()
