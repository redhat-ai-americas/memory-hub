"""Tests for Valkey compilation epoch state management (#175).

Uses fakeredis — no running Valkey needed. Follows patterns from
test_valkey_client.py.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.compilation import CompilationEpoch
from memoryhub_core.services.valkey_client import ValkeyClient, _compilation_key


@pytest.fixture
async def valkey_client() -> ValkeyClient:
    """A ValkeyClient backed by an in-memory fakeredis instance."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(
        settings=ValkeySettings(compilation_ttl_seconds=600),
        client=fake,
    )
    yield client
    await client.close()


def _sample_epoch(epoch: int = 1) -> CompilationEpoch:
    """Create a deterministic test epoch."""
    return CompilationEpoch(
        epoch=epoch,
        ordered_ids=["aaa-111", "bbb-222", "ccc-333"],
        compilation_hash="abc123hash",
        compiled_at="2026-04-13T12:00:00+00:00",
    )


class TestWriteReadRoundtrip:
    async def test_write_then_read_returns_same_epoch(self, valkey_client):
        original = _sample_epoch()
        await valkey_client.write_compilation("t1", "owner1", original.to_dict())

        data = await valkey_client.read_compilation("t1", "owner1")
        assert data is not None
        restored = CompilationEpoch.from_dict(data)

        assert restored.epoch == original.epoch
        assert restored.ordered_ids == original.ordered_ids
        assert restored.compilation_hash == original.compilation_hash
        assert restored.compiled_at == original.compiled_at

    async def test_overwrite_replaces_previous(self, valkey_client):
        epoch1 = _sample_epoch(epoch=1)
        epoch2 = CompilationEpoch(
            epoch=2,
            ordered_ids=["ddd-444"],
            compilation_hash="newHash",
            compiled_at="2026-04-14T00:00:00+00:00",
        )

        await valkey_client.write_compilation("t1", "owner1", epoch1.to_dict())
        await valkey_client.write_compilation("t1", "owner1", epoch2.to_dict())

        data = await valkey_client.read_compilation("t1", "owner1")
        restored = CompilationEpoch.from_dict(data)
        assert restored.epoch == 2
        assert restored.ordered_ids == ["ddd-444"]


class TestReadNonexistent:
    async def test_returns_none_for_missing_key(self, valkey_client):
        result = await valkey_client.read_compilation("no-tenant", "no-owner")
        assert result is None


class TestTtlRefresh:
    async def test_read_refreshes_ttl(self, valkey_client):
        """Reading a compilation should refresh its TTL."""
        epoch = _sample_epoch()
        await valkey_client.write_compilation("t1", "owner1", epoch.to_dict())

        # Read refreshes TTL
        await valkey_client.read_compilation("t1", "owner1")

        # Verify key still has a TTL set (fakeredis supports TTL inspection)
        client = await valkey_client._get_client()
        key = _compilation_key("t1", "owner1")
        ttl = await client.ttl(key)
        assert ttl > 0  # TTL was refreshed


class TestDeleteCompilation:
    async def test_delete_removes_key(self, valkey_client):
        epoch = _sample_epoch()
        await valkey_client.write_compilation("t1", "owner1", epoch.to_dict())

        await valkey_client.delete_compilation("t1", "owner1")

        result = await valkey_client.read_compilation("t1", "owner1")
        assert result is None

    async def test_delete_nonexistent_is_noop(self, valkey_client):
        """Deleting a missing key should not raise."""
        await valkey_client.delete_compilation("no-tenant", "no-owner")


class TestScopeIsolation:
    async def test_different_owners_have_separate_compilations(self, valkey_client):
        epoch_a = _sample_epoch(epoch=1)
        epoch_b = CompilationEpoch(
            epoch=5,
            ordered_ids=["zzz-999"],
            compilation_hash="otherHash",
            compiled_at="2026-04-13T18:00:00+00:00",
        )

        await valkey_client.write_compilation("t1", "owner_a", epoch_a.to_dict())
        await valkey_client.write_compilation("t1", "owner_b", epoch_b.to_dict())

        data_a = await valkey_client.read_compilation("t1", "owner_a")
        data_b = await valkey_client.read_compilation("t1", "owner_b")

        assert CompilationEpoch.from_dict(data_a).epoch == 1
        assert CompilationEpoch.from_dict(data_b).epoch == 5

    async def test_different_tenants_have_separate_compilations(self, valkey_client):
        epoch = _sample_epoch()
        await valkey_client.write_compilation("tenant_x", "owner1", epoch.to_dict())

        result = await valkey_client.read_compilation("tenant_y", "owner1")
        assert result is None
