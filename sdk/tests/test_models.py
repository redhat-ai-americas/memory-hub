"""Tests for memoryhub.models."""

from __future__ import annotations

import pytest

from memoryhub.models import (
    ContradictionResult,
    CurationInfo,
    CurationRule,
    CurationRuleResult,
    HistoryResult,
    Memory,
    SearchResult,
    WriteResult,
)

# ---------------------------------------------------------------------------
# Fixtures / shared test data
# ---------------------------------------------------------------------------

MEMORY_FULL = {
    "id": "mem-abc123",
    "content": "The user prefers Podman over Docker for all container operations.",
    "stub": "User prefers Podman over Docker.",
    "weight": 0.9,
    "scope": "user",
    "branch_type": None,
    "owner_id": "user-wjackson",
    "is_current": True,
    "version": 2,
    "parent_id": None,
    "previous_version_id": "mem-abc122",
    "storage_type": "inline",
    "content_ref": None,
    "metadata": {"source": "conversation", "project": "memory-hub"},
    "created_at": "2026-01-15T10:00:00Z",
    "updated_at": "2026-03-01T08:30:00Z",
    "expires_at": None,
    "has_children": False,
    "has_rationale": True,
    "branches": None,
    "relationships": None,
    "relevance_score": 0.94,
    "result_type": "full",
}

MEMORY_MINIMAL = {
    "id": "mem-min001",
    "content": "Use FastAPI for new Python web services.",
    "scope": "organizational",
    "owner_id": "user-wjackson",
}


# ---------------------------------------------------------------------------
# Memory tests
# ---------------------------------------------------------------------------


def test_memory_from_search_result():
    """Parse a realistic search result dict into Memory."""
    mem = Memory(**MEMORY_FULL)

    assert mem.id == "mem-abc123"
    assert mem.weight == 0.9
    assert mem.scope == "user"
    assert mem.owner_id == "user-wjackson"
    assert mem.version == 2
    assert mem.previous_version_id == "mem-abc122"
    assert mem.relevance_score == 0.94
    assert mem.result_type == "full"
    assert mem.metadata == {"source": "conversation", "project": "memory-hub"}
    assert mem.created_at is not None
    assert mem.updated_at is not None


def test_memory_minimal_fields():
    """Memory can be created with only required fields."""
    mem = Memory(**MEMORY_MINIMAL)

    assert mem.id == "mem-min001"
    assert mem.content == "Use FastAPI for new Python web services."
    assert mem.scope == "organizational"
    assert mem.owner_id == "user-wjackson"
    # Defaults
    assert mem.weight == 0.7
    assert mem.is_current is True
    assert mem.version == 1
    assert mem.storage_type == "inline"
    assert mem.has_children is False
    assert mem.has_rationale is False
    assert mem.stub is None
    assert mem.branches is None


def test_memory_extra_fields_allowed():
    """Extra fields in a memory dict do not cause validation errors."""
    data = dict(MEMORY_MINIMAL, unknown_future_field="some value", another_extra=42)
    mem = Memory(**data)

    assert mem.id == MEMORY_MINIMAL["id"]
    # Pydantic stores extras — confirm they are accessible
    assert mem.model_extra["unknown_future_field"] == "some value"
    assert mem.model_extra["another_extra"] == 42


# ---------------------------------------------------------------------------
# SearchResult tests
# ---------------------------------------------------------------------------


def test_search_result_parse():
    """Parse a full search response into SearchResult."""
    payload = {
        "results": [
            MEMORY_FULL,
            {**MEMORY_MINIMAL, "relevance_score": 0.75, "result_type": "stub"},
        ],
        "total_accessible": 42,
    }
    result = SearchResult(**payload)

    assert len(result.results) == 2
    assert result.total_accessible == 42
    assert result.results[0].id == "mem-abc123"
    assert result.results[1].relevance_score == 0.75
    assert result.results[1].result_type == "stub"


def test_search_result_empty():
    """SearchResult handles an empty results list."""
    result = SearchResult(results=[], total_accessible=0)
    assert result.results == []
    assert result.total_accessible == 0


# ---------------------------------------------------------------------------
# WriteResult tests
# ---------------------------------------------------------------------------


def test_write_result_parse():
    """Parse a write response with curation info."""
    payload = {
        "memory": MEMORY_FULL,
        "curation": {
            "blocked": False,
            "similar_count": 1,
            "nearest_id": "mem-xyz999",
            "nearest_score": 0.88,
            "flags": ["near_duplicate"],
        },
    }
    result = WriteResult(**payload)

    assert result.memory.id == "mem-abc123"
    assert result.curation.blocked is False
    assert result.curation.similar_count == 1
    assert result.curation.nearest_id == "mem-xyz999"
    assert result.curation.nearest_score == 0.88
    assert "near_duplicate" in result.curation.flags


@pytest.mark.parametrize("blocked,similar_count,flags", [
    (False, 0, []),
    (True, 3, ["near_duplicate", "high_overlap"]),
    (False, 1, ["near_duplicate"]),
])
def test_curation_info_variants(blocked, similar_count, flags):
    """CurationInfo handles various blocked/similar_count/flags combinations."""
    info = CurationInfo(blocked=blocked, similar_count=similar_count, flags=flags)
    assert info.blocked == blocked
    assert info.similar_count == similar_count
    assert info.flags == flags


# ---------------------------------------------------------------------------
# HistoryResult tests
# ---------------------------------------------------------------------------


def test_history_result_parse():
    """Parse version history for a memory."""
    payload = {
        "memory_id": "mem-abc123",
        "versions": [
            {
                "id": "mem-abc123",
                "version": 2,
                "content": "The user prefers Podman over Docker for all container operations.",
                "stub": "User prefers Podman over Docker.",
                "is_current": True,
                "created_at": "2026-03-01T08:30:00Z",
            },
            {
                "id": "mem-abc122",
                "version": 1,
                "content": "The user prefers Podman.",
                "stub": None,
                "is_current": False,
                "created_at": "2026-01-15T10:00:00Z",
            },
        ],
        "total_versions": 2,
        "has_more": False,
        "offset": 0,
    }
    result = HistoryResult(**payload)

    assert result.memory_id == "mem-abc123"
    assert result.total_versions == 2
    assert result.has_more is False
    assert len(result.versions) == 2

    current = result.versions[0]
    assert current.is_current is True
    assert current.version == 2

    old = result.versions[1]
    assert old.is_current is False
    assert old.version == 1
    assert old.created_at is not None


# ---------------------------------------------------------------------------
# ContradictionResult tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contradiction_count,revision_triggered,message", [
    (1, False, "Contradiction recorded."),
    (5, True, "Threshold reached — revision queued."),
    (0, False, ""),
])
def test_contradiction_result_parse(contradiction_count, revision_triggered, message):
    """Parse contradiction report with various trigger states."""
    payload = {
        "memory_id": "mem-abc123",
        "contradiction_count": contradiction_count,
        "threshold": 5,
        "revision_triggered": revision_triggered,
        "message": message,
    }
    result = ContradictionResult(**payload)

    assert result.memory_id == "mem-abc123"
    assert result.contradiction_count == contradiction_count
    assert result.threshold == 5
    assert result.revision_triggered == revision_triggered
    assert result.message == message


# ---------------------------------------------------------------------------
# CurationRuleResult tests
# ---------------------------------------------------------------------------


def test_curation_rule_result():
    """Parse curation rule creation/update response."""
    payload = {
        "created": True,
        "updated": False,
        "rule": {
            "name": "semantic-dedup",
            "tier": "embedding",
            "action": "flag",
            "config": {"threshold": 0.92},
            "scope_filter": "user",
            "enabled": True,
            "priority": 5,
        },
    }
    result = CurationRuleResult(**payload)

    assert result.created is True
    assert result.updated is False
    assert isinstance(result.rule, CurationRule)
    assert result.rule.name == "semantic-dedup"
    assert result.rule.tier == "embedding"
    assert result.rule.config == {"threshold": 0.92}
    assert result.rule.scope_filter == "user"
    assert result.rule.priority == 5


def test_curation_rule_result_as_dict():
    """CurationRuleResult.rule may be a raw dict (forward-compat with new rule types)."""
    payload = {
        "created": False,
        "updated": True,
        "rule": {"name": "custom-rule", "some_new_field": "value"},
    }
    result = CurationRuleResult(**payload)
    # rule may parse as CurationRule (with extras) or remain a dict depending on data
    assert result.updated is True
    if isinstance(result.rule, dict):
        assert result.rule["name"] == "custom-rule"
    else:
        assert result.rule.name == "custom-rule"
