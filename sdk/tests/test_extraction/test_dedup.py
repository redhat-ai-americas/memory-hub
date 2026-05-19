"""Tests for deduplication filter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from memoryhub.extraction.dedup import DedupFilter
from memoryhub.extraction.models import CandidateMemory
from memoryhub.models import Memory, SearchResult

# ── Duplicate detection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_marks_duplicate_when_high_relevance_match(mock_client, sample_events):
    """Marks candidate as duplicate when search returns high-relevance match."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Use Podman not Docker", source_event=event, extractor_name="test"
    )

    # Mock search to return a high-similarity match
    async def mock_search(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-existing",
                    content="Use Podman not Docker",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.95,
                )
            ],
            total_matching=1,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    assert result.is_duplicate is True
    assert result.duplicate_of == "mem-existing"


@pytest.mark.asyncio
async def test_passes_through_when_no_similar_memories(mock_client, sample_events):
    """Passes through when no similar memories exist."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Unique content", source_event=event, extractor_name="test"
    )

    # Mock search to return no results
    async def mock_search(*args, **kwargs):
        return SearchResult(results=[], total_matching=0, has_more=False)

    mock_client.search = AsyncMock(side_effect=mock_search)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    assert result.is_duplicate is False
    assert result.duplicate_of is None


@pytest.mark.asyncio
async def test_passes_through_when_relevance_below_threshold(mock_client, sample_events):
    """Passes through when relevance_score is below threshold."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Similar but different", source_event=event, extractor_name="test"
    )

    # Mock search to return a low-similarity match
    async def mock_search(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-existing",
                    content="Somewhat similar content",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.75,
                )
            ],
            total_matching=1,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    assert result.is_duplicate is False
    assert result.duplicate_of is None


# ── Threshold parameter ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_threshold_parameter_works(mock_client, sample_events):
    """Threshold parameter controls what counts as duplicate."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Threshold test", source_event=event, extractor_name="test"
    )

    # Mock search to return a match with 0.85 relevance
    async def mock_search(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-existing",
                    content="Threshold test",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.85,
                )
            ],
            total_matching=1,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search)

    # With threshold=0.90, should not be duplicate
    dedup_high = DedupFilter(threshold=0.90)
    result_high = await dedup_high.check(candidate, mock_client)
    assert result_high.is_duplicate is False

    # With threshold=0.80, should be duplicate
    dedup_low = DedupFilter(threshold=0.80)
    result_low = await dedup_low.check(candidate, mock_client)
    assert result_low.is_duplicate is True


# ── Search failure handling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_failure_passes_through(mock_client, sample_events):
    """Search failure: candidate passes through un-deduped (fail-open)."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Search fail test", source_event=event, extractor_name="test"
    )

    # Mock search to raise exception
    async def mock_search_fail(*args, **kwargs):
        raise RuntimeError("Search service unavailable")

    mock_client.search = AsyncMock(side_effect=mock_search_fail)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    # Should fail-open: not marked as duplicate
    assert result.is_duplicate is False
    assert result.duplicate_of is None


# ── Highest-scoring match ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uses_highest_scoring_match(mock_client, sample_events):
    """Uses highest-scoring match for duplicate_of."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Multiple matches test", source_event=event, extractor_name="test"
    )

    # Mock search to return multiple high-relevance matches
    async def mock_search(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-001",
                    content="Match 1",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.92,
                ),
                Memory(
                    id="mem-002",
                    content="Match 2",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.96,
                ),
                Memory(
                    id="mem-003",
                    content="Match 3",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.91,
                ),
            ],
            total_matching=3,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    assert result.is_duplicate is True
    assert result.duplicate_of == "mem-002"  # Highest score (0.96)


# ── Edge cases ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_without_relevance_score_ignored(mock_client, sample_events):
    """Memory without relevance_score is ignored."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="No score test", source_event=event, extractor_name="test"
    )

    # Mock search to return a match without relevance_score
    async def mock_search(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-existing",
                    content="No score memory",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=None,
                )
            ],
            total_matching=1,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search)

    dedup = DedupFilter(threshold=0.90)
    result = await dedup.check(candidate, mock_client)

    assert result.is_duplicate is False
    assert result.duplicate_of is None
