"""Tests for extraction pipeline orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, ExtractionResult, TraceEvent
from memoryhub.extraction.pipeline import ExtractionPipeline
from memoryhub.models import CurationInfo, Memory, SearchResult, WriteResult

# ── Mock Extractor ───────────────────────────────────────────────────────────


class MockExtractor(Extractor):
    """Simple mock extractor that returns configurable candidates."""

    def __init__(self, name: str, candidates: list[CandidateMemory] | None = None):
        self._name = name
        self._candidates = candidates or []

    @property
    def name(self) -> str:
        return self._name

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        return self._candidates


class FailingExtractor(Extractor):
    """Extractor that always raises an exception."""

    @property
    def name(self) -> str:
        return "failing"

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        raise RuntimeError("Extractor failed")


# ── Pipeline with no extractors ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_no_extractors(mock_client, sample_events):
    pipeline = ExtractionPipeline(mock_client, extractors=None)
    result = await pipeline.observe(sample_events["preference"])

    assert isinstance(result, ExtractionResult)
    assert result.candidates == []
    assert result.written == []
    assert result.reviewed == []
    assert result.filtered == []


@pytest.mark.asyncio
async def test_pipeline_empty_extractors_list(mock_client, sample_events):
    pipeline = ExtractionPipeline(mock_client, extractors=[])
    result = await pipeline.observe(sample_events["preference"])

    assert result.candidates == []
    assert result.written == []


# ── High-confidence auto-write ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_confidence_auto_write(mock_client, sample_events):
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Auto-write test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], confidence_threshold=0.7
    )

    result = await pipeline.observe(event)

    assert len(result.written) == 1
    assert len(result.reviewed) == 0
    mock_client.write.assert_called_once()


@pytest.mark.asyncio
async def test_threshold_boundary_auto_write(mock_client, sample_events):
    """Candidate with confidence exactly at threshold should auto-write."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Threshold test",
        source_event=event,
        extractor_name="test",
        confidence=0.7,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], confidence_threshold=0.7
    )

    result = await pipeline.observe(event)

    assert len(result.written) == 1
    assert len(result.reviewed) == 0


# ── Low-confidence callback routing ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_confidence_goes_to_callback(mock_client, sample_events):
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Low confidence test",
        source_event=event,
        extractor_name="test",
        confidence=0.4,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], confidence_threshold=0.7
    )

    callback_called = False
    received_candidate = None

    @pipeline.on_candidate
    async def review(c: CandidateMemory) -> bool:
        nonlocal callback_called, received_candidate
        callback_called = True
        received_candidate = c
        return True

    result = await pipeline.observe(event)

    assert callback_called
    assert received_candidate == candidate
    assert len(result.written) == 1


@pytest.mark.asyncio
async def test_callback_returns_true_writes(mock_client, sample_events):
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Callback approve test",
        source_event=event,
        extractor_name="test",
        confidence=0.5,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    @pipeline.on_candidate
    async def review(c: CandidateMemory) -> bool:
        return True

    result = await pipeline.observe(event)

    assert len(result.written) == 1
    assert len(result.reviewed) == 0


@pytest.mark.asyncio
async def test_callback_returns_false_skips(mock_client, sample_events):
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Callback reject test",
        source_event=event,
        extractor_name="test",
        confidence=0.5,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    @pipeline.on_candidate
    async def review(c: CandidateMemory) -> bool:
        return False

    result = await pipeline.observe(event)

    assert len(result.written) == 0
    assert len(result.reviewed) == 1
    assert result.reviewed[0] == candidate


@pytest.mark.asyncio
async def test_no_callback_low_confidence_goes_to_reviewed(mock_client, sample_events):
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="No callback test",
        source_event=event,
        extractor_name="test",
        confidence=0.5,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(event)

    assert len(result.written) == 0
    assert len(result.reviewed) == 1


# ── Dedup filter routing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_candidates_filtered(mock_client, sample_events):
    """Dedup-marked candidates go to filtered list, not written."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Duplicate test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    # Mock search to return a high-similarity match
    async def mock_search_with_match(*args, **kwargs):
        return SearchResult(
            results=[
                Memory(
                    id="mem-existing",
                    content="Duplicate test",
                    scope="user",
                    owner_id="test-user",
                    relevance_score=0.95,
                )
            ],
            total_matching=1,
            has_more=False,
        )

    mock_client.search = AsyncMock(side_effect=mock_search_with_match)

    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], dedup_threshold=0.90
    )
    result = await pipeline.observe(event)

    assert len(result.filtered) == 1
    assert len(result.written) == 0
    assert result.filtered[0].is_duplicate is True
    assert result.filtered[0].duplicate_of == "mem-existing"


# ── Extractor exception handling ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extractor_exception_logged_continues(mock_client, sample_events):
    """Extractor exception is caught, other extractors still run."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Good candidate", source_event=event, extractor_name="good", confidence=0.9
    )

    failing = FailingExtractor()
    good = MockExtractor("good", [candidate])

    pipeline = ExtractionPipeline(mock_client, extractors=[failing, good])
    result = await pipeline.observe(event)

    # Good extractor should have run despite failing extractor
    assert len(result.candidates) == 1
    assert len(result.written) == 1


# ── Write failure handling ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_failure_logged_continues(mock_client, sample_events):
    """Write failure is logged but pipeline continues."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Write fail test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    # Mock write to raise exception
    async def mock_write_fail(*args, **kwargs):
        raise RuntimeError("Write failed")

    mock_client.write = AsyncMock(side_effect=mock_write_fail)

    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])
    result = await pipeline.observe(event)

    # Pipeline should complete without raising
    assert len(result.candidates) == 1
    assert len(result.written) == 0


@pytest.mark.asyncio
async def test_gated_write_returns_none(mock_client, sample_events):
    """Write that returns None (gated) doesn't add to written list."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Gated test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    # Mock write to return gated result (memory=None)
    async def mock_gated_write(*args, **kwargs):
        return WriteResult(
            memory=None,
            curation=CurationInfo(
                blocked=False, gated=True, reason="Similar memory exists"
            ),
        )

    mock_client.write = AsyncMock(side_effect=mock_gated_write)

    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])
    result = await pipeline.observe(event)

    assert len(result.written) == 0


# ── Relationship creation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relate_to_creates_relationships(mock_client, sample_events):
    """Candidates with relate_to trigger create_relationship calls."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Related test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
        relate_to=["mem-001", "mem-002"],
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])
    result = await pipeline.observe(event)

    assert len(result.written) == 1
    assert mock_client.create_relationship.call_count == 2


@pytest.mark.asyncio
async def test_relationship_creation_failure_logged(mock_client, sample_events):
    """Relationship creation failure is logged but doesn't block write."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Relation fail test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
        relate_to=["mem-001"],
    )
    extractor = MockExtractor("test", [candidate])

    # Mock create_relationship to raise
    async def mock_create_rel_fail(*args, **kwargs):
        raise RuntimeError("Relationship creation failed")

    mock_client.create_relationship = AsyncMock(side_effect=mock_create_rel_fail)

    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])
    result = await pipeline.observe(event)

    # Write should still succeed
    assert len(result.written) == 1


# ── Auto-write disabled ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_write_disabled_routes_to_callback(mock_client, sample_events):
    """With auto_write=False, even high-confidence candidates go to callback."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Auto-write disabled test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], auto_write=False
    )

    callback_called = False

    @pipeline.on_candidate
    async def review(c: CandidateMemory) -> bool:
        nonlocal callback_called
        callback_called = True
        return False

    result = await pipeline.observe(event)

    assert callback_called
    assert len(result.written) == 0
    assert len(result.reviewed) == 1


# ── Pipeline scope and domains ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_uses_configured_scope(mock_client, sample_events):
    """Pipeline uses configured scope as default."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Scope test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], scope="project", project_id="test-project"
    )
    await pipeline.observe(event)

    # Check that write was called with project scope
    call_kwargs = mock_client.write.call_args[1]
    assert call_kwargs["scope"] == "user"  # Candidate scope takes precedence


@pytest.mark.asyncio
async def test_pipeline_uses_configured_domains(mock_client, sample_events):
    """Pipeline uses configured domains as default."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Domains test",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(
        mock_client, extractors=[extractor], domains=["architecture"]
    )
    await pipeline.observe(event)

    # Check that write was called with configured domains
    call_kwargs = mock_client.write.call_args[1]
    assert call_kwargs["domains"] == ["architecture"]


# ── Callback exception handling ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_exception_logged_continues(mock_client, sample_events):
    """Callback exception is logged, candidate goes to reviewed."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Callback exception test",
        source_event=event,
        extractor_name="test",
        confidence=0.5,
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    @pipeline.on_candidate
    async def failing_callback(c: CandidateMemory) -> bool:
        raise RuntimeError("Callback failed")

    result = await pipeline.observe(event)

    # Candidate should be in reviewed despite callback exception
    assert len(result.reviewed) == 1
    assert len(result.written) == 0


# ── Flush method ─────────────────────────────────────────────────────────────


def test_flush_is_noop(mock_client):
    """Flush is currently a no-op placeholder."""
    pipeline = ExtractionPipeline(mock_client)
    pipeline.flush()  # Should not raise
