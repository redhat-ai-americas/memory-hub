"""Tests for PTC taint metadata reporting (#563).

Covers:
- _taint_entry helper: trusted -> None, untrusted -> taint dict, mixed -> taint dict
- _inject_taint: modifies entry dict in place
- Propagation: upstream_trust_level flows through node_to_read and MemoryNodeStub
- SDK Memory model accepts taint field
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub
from memoryhub_core.services.memory import node_to_read

from src.tools.search_memory import _inject_taint, _taint_entry


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
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
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
        now = datetime.now(tz=timezone.utc)
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
            generating_model="gemini-2.5-flash",
            created_at=now,
            updated_at=now,
        )
        read = node_to_read(node, has_children=False, has_rationale=False)
        assert read.upstream_trust_level == "untrusted"
        assert read.generating_model == "gemini-2.5-flash"
        assert read.source == "dreaming"

    def test_node_to_read_defaults_trusted(self):
        now = datetime.now(tz=timezone.utc)
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
        assert read.generating_model is None


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
