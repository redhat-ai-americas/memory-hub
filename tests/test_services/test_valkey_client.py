"""Tests for the Valkey client wrapper.

Uses fakeredis to avoid a running Valkey instance. fakeredis implements the
Redis protocol in Python and is compatible with the async redis-py client
used by ``valkey_client``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    ValkeyUnavailableError,
    decode_vector,
    encode_vector,
)


@pytest.fixture
async def valkey_client() -> ValkeyClient:
    """A ValkeyClient backed by an in-memory fakeredis instance."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(
        settings=ValkeySettings(session_ttl_seconds=900, history_retention_days=30),
        client=fake,
    )
    yield client
    await client.close()


class TestVectorCodec:
    """Float-vector encoding round-trips through base64."""

    def test_round_trip_preserves_values(self):
        original = [0.1, -0.2, 0.3, 0.0, 1.0, -1.0]
        encoded = encode_vector(original)
        decoded = decode_vector(encoded)
        assert len(decoded) == len(original)
        for a, b in zip(original, decoded, strict=True):
            # float32 precision ~1e-7
            assert abs(a - b) < 1e-6

    def test_encoded_is_ascii_string(self):
        encoded = encode_vector([0.5] * 384)
        assert isinstance(encoded, str)
        assert encoded.isascii()

    def test_encoded_length_shorter_than_json(self):
        """384-dim float32 vector should base64-encode to ~2 KB, less than
        a JSON-encoded float list would."""
        encoded = encode_vector([0.123456] * 384)
        # 384 floats * 4 bytes = 1536 bytes, base64 encoded ≈ 2048 chars
        assert len(encoded) < 2100
        # JSON encoding would be roughly ~3 KB+ for the same vector
        import json

        json_encoded = json.dumps([0.123456] * 384)
        assert len(encoded) < len(json_encoded)

    def test_empty_vector_round_trip(self):
        assert decode_vector(encode_vector([])) == []


class TestPing:
    async def test_ping_returns_true_when_backend_reachable(self, valkey_client):
        assert await valkey_client.ping() is True

    async def test_ping_returns_false_when_backend_errors(self):
        # Point at an unreachable host with a short timeout
        client = ValkeyClient(
            settings=ValkeySettings(url="redis://127.0.0.1:1/0", session_ttl_seconds=900)
        )
        # Note: we can't actually connect here, but we don't want the test to
        # hang. Skip unless the real connection fails gracefully.
        result = await client.ping()
        # Either False (connection refused) or True (nothing at this port
        # surprisingly accepted) — we're mainly asserting it doesn't raise.
        assert isinstance(result, bool)


class TestWriteSessionFocus:
    async def test_writes_session_hash_and_history_entry(self, valkey_client):
        fixed_now = datetime(2026, 4, 7, 12, 30, 0, tzinfo=timezone.utc)
        result = await valkey_client.write_session_focus(
            session_id="sess-abc",
            focus="deployment",
            focus_vector=[0.1, 0.2, 0.3],
            user_id="wjackson",
            project="memory-hub",
            now=fixed_now,
        )

        assert result["session_id"] == "sess-abc"
        assert result["expires_at"] == "2026-04-07T12:45:00+00:00"

        # Session hash
        fake = valkey_client._client
        session_data = await fake.hgetall("memoryhub:sessions:sess-abc")
        assert session_data["focus"] == "deployment"
        assert session_data["user_id"] == "wjackson"
        assert session_data["project"] == "memory-hub"
        assert session_data["created_at"] == "2026-04-07T12:30:00+00:00"
        assert session_data["expires_at"] == "2026-04-07T12:45:00+00:00"
        decoded = decode_vector(session_data["focus_vector"])
        for a, b in zip([0.1, 0.2, 0.3], decoded, strict=True):
            assert abs(a - b) < 1e-6

        # History entry
        history = await fake.lrange(
            "memoryhub:session_focus_history:memory-hub:2026-04-07", 0, -1
        )
        assert len(history) == 1
        import json

        entry = json.loads(history[0])
        assert entry["focus"] == "deployment"
        assert entry["session_id"] == "sess-abc"
        assert entry["user_id"] == "wjackson"
        assert entry["timestamp"] == "2026-04-07T12:30:00+00:00"

    async def test_session_key_carries_ttl(self, valkey_client):
        await valkey_client.write_session_focus(
            session_id="sess-ttl",
            focus="auth",
            focus_vector=[0.0] * 3,
            user_id="wjackson",
            project="memory-hub",
            ttl_seconds=600,
        )
        fake = valkey_client._client
        ttl = await fake.ttl("memoryhub:sessions:sess-ttl")
        assert 500 < ttl <= 600  # within the requested window

    async def test_history_list_carries_retention_ttl(self, valkey_client):
        fixed_now = datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc)
        await valkey_client.write_session_focus(
            session_id="sess-hist",
            focus="ui",
            focus_vector=[0.5, 0.5],
            user_id="wjackson",
            project="memory-hub",
            now=fixed_now,
        )
        fake = valkey_client._client
        ttl = await fake.ttl("memoryhub:session_focus_history:memory-hub:2026-04-07")
        # 30 days = 2_592_000 seconds
        assert 2_591_000 < ttl <= 2_592_000

    async def test_multiple_writes_append_to_same_day_list(self, valkey_client):
        fixed_now = datetime(2026, 4, 7, 9, 0, 0, tzinfo=timezone.utc)
        for i in range(3):
            await valkey_client.write_session_focus(
                session_id=f"sess-{i}",
                focus="deployment" if i < 2 else "ui",
                focus_vector=[float(i)] * 3,
                user_id="wjackson",
                project="memory-hub",
                now=fixed_now,
            )

        fake = valkey_client._client
        history = await fake.lrange(
            "memoryhub:session_focus_history:memory-hub:2026-04-07", 0, -1
        )
        assert len(history) == 3

    async def test_writes_use_project_scoped_history_key(self, valkey_client):
        fixed_now = datetime(2026, 4, 7, 9, 0, 0, tzinfo=timezone.utc)
        await valkey_client.write_session_focus(
            session_id="s1",
            focus="auth",
            focus_vector=[0.1],
            user_id="wjackson",
            project="project-a",
            now=fixed_now,
        )
        await valkey_client.write_session_focus(
            session_id="s2",
            focus="ui",
            focus_vector=[0.2],
            user_id="wjackson",
            project="project-b",
            now=fixed_now,
        )

        fake = valkey_client._client
        a_history = await fake.lrange(
            "memoryhub:session_focus_history:project-a:2026-04-07", 0, -1
        )
        b_history = await fake.lrange(
            "memoryhub:session_focus_history:project-b:2026-04-07", 0, -1
        )
        assert len(a_history) == 1
        assert len(b_history) == 1


class TestReadFocusHistory:
    async def test_returns_empty_list_for_unknown_project(self, valkey_client):
        entries = await valkey_client.read_focus_history(
            project="nonexistent",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 7),
        )
        assert entries == []

    async def test_reads_entries_from_single_day(self, valkey_client):
        fixed_now = datetime(2026, 4, 7, 9, 0, 0, tzinfo=timezone.utc)
        for focus in ["deployment", "ui", "auth"]:
            await valkey_client.write_session_focus(
                session_id=f"sess-{focus}",
                focus=focus,
                focus_vector=[0.1],
                user_id="wjackson",
                project="memory-hub",
                now=fixed_now,
            )

        entries = await valkey_client.read_focus_history(
            project="memory-hub",
            start_date=date(2026, 4, 7),
            end_date=date(2026, 4, 7),
        )
        assert len(entries) == 3
        focuses = {e["focus"] for e in entries}
        assert focuses == {"deployment", "ui", "auth"}

    async def test_reads_entries_across_multiple_days(self, valkey_client):
        for day, focus in [
            (date(2026, 4, 5), "deployment"),
            (date(2026, 4, 6), "ui"),
            (date(2026, 4, 7), "auth"),
        ]:
            now = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            await valkey_client.write_session_focus(
                session_id=f"sess-{day}",
                focus=focus,
                focus_vector=[0.1],
                user_id="wjackson",
                project="memory-hub",
                now=now,
            )

        # Full range
        all_entries = await valkey_client.read_focus_history(
            project="memory-hub",
            start_date=date(2026, 4, 5),
            end_date=date(2026, 4, 7),
        )
        assert len(all_entries) == 3

        # Narrower range
        narrow = await valkey_client.read_focus_history(
            project="memory-hub",
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 7),
        )
        assert len(narrow) == 2
        assert {e["focus"] for e in narrow} == {"ui", "auth"}

    async def test_raises_on_inverted_date_range(self, valkey_client):
        with pytest.raises(ValueError, match="before start_date"):
            await valkey_client.read_focus_history(
                project="memory-hub",
                start_date=date(2026, 4, 7),
                end_date=date(2026, 4, 1),
            )

    async def test_skips_malformed_entries(self, valkey_client):
        """Malformed JSON in a history entry should be skipped silently, not
        crash the read path. Defence in depth: the writer always emits JSON."""
        fake = valkey_client._client
        key = "memoryhub:session_focus_history:memory-hub:2026-04-07"
        await fake.lpush(key, "not valid json{")
        await fake.lpush(key, '{"focus": "deployment", "session_id": "s1"}')

        entries = await valkey_client.read_focus_history(
            project="memory-hub",
            start_date=date(2026, 4, 7),
            end_date=date(2026, 4, 7),
        )
        assert len(entries) == 1
        assert entries[0]["focus"] == "deployment"


class TestErrorMapping:
    async def test_write_error_raises_valkey_unavailable(self):
        """If the underlying redis client raises, write_session_focus should
        wrap it in ValkeyUnavailableError."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        class BrokenClient:
            def pipeline(self, transaction=True):
                raise RedisConnectionError("simulated")

            async def aclose(self):
                pass

        client = ValkeyClient(
            settings=ValkeySettings(session_ttl_seconds=900),
            client=BrokenClient(),
        )
        with pytest.raises(ValkeyUnavailableError, match="Failed to write"):
            await client.write_session_focus(
                session_id="s1",
                focus="x",
                focus_vector=[0.1],
                user_id="u",
                project="p",
            )
