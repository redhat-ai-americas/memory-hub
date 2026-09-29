"""Tests for deterministic dreaming gates (#562)."""

from __future__ import annotations

import pytest

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.gates import DreamingGate, GateThresholds
from memoryhub.extraction.models import CandidateMemory, TraceEvent, TraceEventType
from memoryhub.extraction.pipeline import ExtractionPipeline


class MockExtractor(Extractor):
    def __init__(self, name: str, candidates: list[CandidateMemory] | None = None):
        self._name = name
        self._candidates = candidates or []

    @property
    def name(self) -> str:
        return self._name

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        return self._candidates


def _make_candidate(**kwargs) -> CandidateMemory:
    defaults = {
        "content": "test memory",
        "source_event": TraceEvent(
            event_type=TraceEventType.USER_MESSAGE, content="test"
        ),
        "extractor_name": "test",
        "confidence": 0.7,
    }
    defaults.update(kwargs)
    return CandidateMemory(**defaults)


# ── GateThresholds defaults ─────────────────────────────────────────────────


class TestGateThresholds:
    def test_defaults_are_zero(self):
        t = GateThresholds()
        assert t.min_recall_count == 0
        assert t.min_unique_queries == 0
        assert t.min_score == 0.0

    def test_custom_thresholds(self):
        t = GateThresholds(min_recall_count=3, min_unique_queries=2, min_score=0.75)
        assert t.min_recall_count == 3
        assert t.min_unique_queries == 2
        assert t.min_score == 0.75

    def test_frozen(self):
        t = GateThresholds()
        with pytest.raises(AttributeError):
            t.min_score = 0.5  # type: ignore[misc]


# ── DreamingGate unit tests ─────────────────────────────────────────────────


class TestDreamingGate:
    def test_no_thresholds_all_pass(self):
        gate = DreamingGate(GateThresholds())
        candidates = [_make_candidate(confidence=0.1), _make_candidate(confidence=0.9)]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 2
        assert len(result.deferred) == 0

    def test_min_score_filters(self):
        gate = DreamingGate(GateThresholds(min_score=0.7))
        candidates = [
            _make_candidate(content="low", confidence=0.5),
            _make_candidate(content="high", confidence=0.8),
            _make_candidate(content="exact", confidence=0.7),
        ]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 2
        passed_contents = {c.content for c in result.passed}
        assert passed_contents == {"high", "exact"}
        assert len(result.deferred) == 1
        assert result.deferred[0].content == "low"

    def test_min_recall_count_filters(self):
        gate = DreamingGate(GateThresholds(min_recall_count=3))
        candidates = [
            _make_candidate(content="few", recall_count=1),
            _make_candidate(content="enough", recall_count=3),
            _make_candidate(content="plenty", recall_count=10),
        ]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 2
        assert len(result.deferred) == 1
        assert result.deferred[0].content == "few"

    def test_min_unique_queries_filters(self):
        gate = DreamingGate(GateThresholds(min_unique_queries=2))
        candidates = [
            _make_candidate(content="one_query", unique_query_count=1),
            _make_candidate(content="two_queries", unique_query_count=2),
        ]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 1
        assert result.passed[0].content == "two_queries"

    def test_combined_thresholds_all_must_pass(self):
        gate = DreamingGate(GateThresholds(
            min_score=0.6,
            min_recall_count=2,
            min_unique_queries=2,
        ))
        candidates = [
            _make_candidate(
                content="all_pass",
                confidence=0.8,
                recall_count=5,
                unique_query_count=3,
            ),
            _make_candidate(
                content="score_fail",
                confidence=0.4,
                recall_count=5,
                unique_query_count=3,
            ),
            _make_candidate(
                content="recall_fail",
                confidence=0.8,
                recall_count=1,
                unique_query_count=3,
            ),
            _make_candidate(
                content="query_fail",
                confidence=0.8,
                recall_count=5,
                unique_query_count=1,
            ),
        ]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 1
        assert result.passed[0].content == "all_pass"
        assert len(result.deferred) == 3

    def test_empty_candidates(self):
        gate = DreamingGate(GateThresholds(min_score=0.5))
        result = gate.evaluate([])
        assert result.passed == []
        assert result.deferred == []

    def test_deferred_not_discarded(self):
        """Deferred candidates retain all their data for the next cycle."""
        gate = DreamingGate(GateThresholds(min_score=0.9))
        candidate = _make_candidate(
            content="important but young",
            confidence=0.5,
            recall_count=1,
            metadata={"origin": "conversation-123"},
        )
        result = gate.evaluate([candidate])
        assert len(result.deferred) == 1
        deferred = result.deferred[0]
        assert deferred.content == "important but young"
        assert deferred.metadata == {"origin": "conversation-123"}
        assert deferred.recall_count == 1

    def test_default_gate_no_thresholds(self):
        gate = DreamingGate()
        candidates = [_make_candidate(confidence=0.01)]
        result = gate.evaluate(candidates)
        assert len(result.passed) == 1


# ── Pipeline integration with gates ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_with_gates_defers_low_score(mock_client):
    event = TraceEvent.user_message("test")
    candidates = [
        CandidateMemory(
            content="high confidence",
            source_event=event,
            extractor_name="test",
            confidence=0.9,
        ),
        CandidateMemory(
            content="low confidence",
            source_event=event,
            extractor_name="test",
            confidence=0.3,
        ),
    ]
    extractor = MockExtractor("test", candidates)
    pipeline = ExtractionPipeline(
        mock_client,
        extractors=[extractor],
        gate_thresholds=GateThresholds(min_score=0.5),
    )

    result = await pipeline.observe(event)

    assert len(result.deferred) == 1
    assert result.deferred[0].content == "low confidence"
    assert len(result.written) == 1


@pytest.mark.asyncio
async def test_pipeline_without_gates_writes_all(mock_client):
    event = TraceEvent.user_message("test")
    candidates = [
        CandidateMemory(
            content="any confidence",
            source_event=event,
            extractor_name="test",
            confidence=0.9,
        ),
    ]
    extractor = MockExtractor("test", candidates)
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(event)

    assert len(result.deferred) == 0
    assert len(result.written) == 1


@pytest.mark.asyncio
async def test_pipeline_gates_run_after_dedup(mock_client):
    """Gates should not see duplicates -- dedup runs first."""
    event = TraceEvent.user_message("test")
    candidate = CandidateMemory(
        content="Duplicate",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
        is_duplicate=True,
        duplicate_of="existing-id",
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(
        mock_client,
        extractors=[extractor],
        gate_thresholds=GateThresholds(min_score=0.5),
    )

    result = await pipeline.observe(event)

    assert len(result.filtered) == 1
    assert len(result.deferred) == 0
    assert len(result.written) == 0


@pytest.mark.asyncio
async def test_pipeline_deferred_not_written(mock_client):
    """Deferred candidates must not be written."""
    event = TraceEvent.user_message("test")
    candidate = CandidateMemory(
        content="Below threshold",
        source_event=event,
        extractor_name="test",
        confidence=0.2,
    )
    extractor = MockExtractor("test", [candidate])

    pipeline = ExtractionPipeline(
        mock_client,
        extractors=[extractor],
        gate_thresholds=GateThresholds(min_score=0.5),
        confidence_threshold=0.1,
    )

    result = await pipeline.observe(event)

    assert len(result.deferred) == 1
    assert len(result.written) == 0
    mock_client.write.assert_not_called()
