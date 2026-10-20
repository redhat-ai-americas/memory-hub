"""Tests for taint metadata reporting (#563).

Covers:
- _taint_entry helper: trusted -> None, untrusted -> taint dict, mixed -> taint dict
- _inject_taint: modifies entry dict in place
- Propagation: upstream_trust_level flows through node_to_read and MemoryNodeStub
- SDK Memory model accepts taint field
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from src.tools.search_memory import _inject_taint, _taint_entry

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub
from memoryhub_core.services.memory import node_to_read


def _make_read(**overrides) -> MemoryNodeRead:
    defaults = {
        "id": uuid.uuid4(),
        "parent_id": None,
        "content": "test",
        "stub": "test [scope=user]",
        "storage_type": "inline",
        "content_ref": None,
        "weight": 0.7,
        "scope": "user",
        "branch_type": None,
        "owner_id": "user-1",
        "tenant_id": "default",
        "is_current": True,
        "version": 1,
        "previous_version_id": None,
        "metadata": None,
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
        "has_children": False,
        "has_rationale": False,
        "source": "agent",
        "upstream_trust_level": "trusted",
    }
    defaults.update(overrides)
    return MemoryNodeRead(**defaults)


class TestTaintEntry:
    def test_trusted_returns_none(self):
        item = _make_read(upstream_trust_level="trusted")
        assert _taint_entry(item) is None

    def test_untrusted_returns_taint(self):
        item = _make_read(upstream_trust_level="untrusted", source="dreaming")
        taint = _taint_entry(item)
        assert taint == {"tainted": True, "sources": ["dreaming"]}

    def test_mixed_returns_taint(self):
        item = _make_read(upstream_trust_level="mixed", source="agent")
        taint = _taint_entry(item)
        assert taint == {"tainted": True, "sources": ["agent"]}

    def test_stub_untrusted(self):
        stub = MemoryNodeStub(
            id=uuid.uuid4(), stub="test", scope="user", weight=0.7,
            upstream_trust_level="untrusted", source="dreaming",
        )
        taint = _taint_entry(stub)
        assert taint is not None
        assert taint["tainted"] is True

    def test_stub_trusted_returns_none(self):
        stub = MemoryNodeStub(
            id=uuid.uuid4(), stub="test", scope="user", weight=0.7,
        )
        assert _taint_entry(stub) is None


class TestInjectTaint:
    def test_injects_when_untrusted(self):
        item = _make_read(upstream_trust_level="untrusted", source="dreaming")
        entry: dict = {"id": "abc", "content": "test"}
        _inject_taint(entry, item)
        assert "taint" in entry
        assert entry["taint"]["tainted"] is True

    def test_skips_when_trusted(self):
        item = _make_read(upstream_trust_level="trusted")
        entry: dict = {"id": "abc", "content": "test"}
        _inject_taint(entry, item)
        assert "taint" not in entry


class TestTrustLevelPropagation:
    def test_node_to_read_propagates_trust_level(self):
        now = datetime.now(tz=UTC)
        node = MemoryNode(
            id=uuid.uuid4(),
            logical_id=uuid.uuid4(),
            content="test",
            stub="test",
            scope="user",
            weight=0.7,
            owner_id="user-1",
            tenant_id="default",
            is_current=True,
            version=1,
            storage_type="inline",
            content_type="experiential",
            upstream_trust_level="untrusted",
            source="dreaming",
            created_at=now,
            updated_at=now,
        )
        read = node_to_read(node, has_children=False, has_rationale=False)
        assert read.upstream_trust_level == "untrusted"
        assert read.source == "dreaming"

    def test_node_to_read_defaults_trusted(self):
        now = datetime.now(tz=UTC)
        node = MemoryNode(
            id=uuid.uuid4(),
            logical_id=uuid.uuid4(),
            content="test",
            stub="test",
            scope="user",
            weight=0.7,
            owner_id="user-1",
            tenant_id="default",
            is_current=True,
            version=1,
            storage_type="inline",
            content_type="experiential",
            source="agent",
            created_at=now,
            updated_at=now,
        )
        read = node_to_read(node, has_children=False, has_rationale=False)
        assert read.upstream_trust_level == "trusted"


try:
    from memoryhub.models import Memory as _Memory  # noqa: F401
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False


@pytest.mark.skipif(not _HAS_SDK, reason="memoryhub SDK not installed")
class TestSDKMemoryTaintField:
    def test_memory_accepts_taint(self):
        from memoryhub.models import Memory
        m = Memory(
            id="mem-1",
            content="test",
            upstream_trust_level="untrusted",
            taint={"tainted": True, "sources": ["dreaming"]},
        )
        assert m.taint is not None
        assert m.taint["tainted"] is True

    def test_memory_taint_defaults_none(self):
        from memoryhub.models import Memory
        m = Memory(id="mem-1", content="test")
        assert m.taint is None


# ---------------------------------------------------------------------------
# The write surface can actually set the field (#574)
# ---------------------------------------------------------------------------
#
# Until #574 the column, the schema, the taint helpers and the read path all
# existed, but no tool parameter fed them. Every write landed on the column
# default, so the whole feature was inert in production while its unit tests
# stayed green. These tests pin the tool surface itself: the parameter is
# declared, it reaches MemoryNodeCreate, and the action-dispatch wrapper
# forwards it on write and refuses it on update.


class TestWriteMemoryTrustParameter:
    def test_parameter_is_declared(self):
        import inspect

        from src.tools.write_memory import write_memory

        params = inspect.signature(write_memory).parameters
        assert "upstream_trust_level" in params, (
            "write_memory has no upstream_trust_level parameter, so callers "
            "cannot mark a memory as derived from untrusted material and the "
            "whole trust-provenance feature is unreachable"
        )
        assert params["upstream_trust_level"].default is None

    @pytest.mark.asyncio
    async def test_value_reaches_memory_node_create(self):
        """The tool argument must survive into the service's input schema."""
        captured = await _capture_create(upstream_trust_level="untrusted")
        assert captured.upstream_trust_level == "untrusted"

    @pytest.mark.asyncio
    async def test_omitted_value_defaults_to_trusted(self):
        captured = await _capture_create()
        assert captured.upstream_trust_level == "trusted"


class TestDispatchForwarding:
    """``memory(action=...)`` is the surface agents actually call."""

    def test_write_forwards_trust_level(self):
        from src.tools.memory import _WRITE_OPTS

        assert "upstream_trust_level" in _WRITE_OPTS

    def test_update_does_not_accept_trust_level(self):
        """Trust is set once at write time and inherited by later versions.

        An editable field here would be a laundering path straight through
        the feature the field exists to provide.
        """
        from src.tools.memory import _UPDATE_OPTS

        assert "upstream_trust_level" not in _UPDATE_OPTS


async def _capture_create(**tool_kwargs):
    """Call write_memory with the DB stubbed out, return the MemoryNodeCreate.

    Returns the schema object rather than asserting inline so each test can
    say what it cares about; a failure then names the field, not the mock.
    """
    import uuid as _uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.tools.write_memory import write_memory

    seen: dict[str, object] = {}

    async def _fake_create(data, session, embedding_service, *, tenant_id, **kwargs):
        seen["data"] = data
        now = datetime.now(tz=UTC)
        read = _make_read(
            id=_uuid.uuid4(),
            content=data.content,
            owner_id=data.owner_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            upstream_trust_level=str(data.upstream_trust_level),
        )
        curation = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }
        return read, curation

    claims = {
        "sub": "user_a",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:read", "memory:write", "memory:read:user", "memory:write:user"],
    }

    with (
        patch("src.tools.write_memory.get_claims_from_context", return_value=claims),
        patch("src.tools.write_memory.get_db_session", return_value=(MagicMock(), AsyncMock())),
        patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.write_memory.get_embedding_service", return_value=MagicMock(max_tokens=8192)),
        patch("src.tools.write_memory.create_memory", new=AsyncMock(side_effect=_fake_create)),
        patch("src.tools.write_memory.broadcast_after_write", new_callable=AsyncMock),
    ):
        result = await write_memory(
            content="scraped from an unauthenticated wiki",
            scope="user",
            owner_id="user_a",
            **tool_kwargs,
        )

    assert result.get("error") is not True, result
    assert "data" in seen, "create_memory was never called"
    return seen["data"]
