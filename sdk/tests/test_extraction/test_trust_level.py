"""Tests for upstream trust level inference and propagation (#559)."""

from __future__ import annotations

import pytest

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent, TraceEventType
from memoryhub.extraction.pipeline import ExtractionPipeline, infer_trust_level


class MockExtractor(Extractor):
    def __init__(self, name: str, candidates: list[CandidateMemory] | None = None):
        self._name = name
        self._candidates = candidates or []

    @property
    def name(self) -> str:
        return self._name

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        return self._candidates


# ── infer_trust_level unit tests ────────────────────────────────────────────


class TestInferTrustLevel:
    def test_user_message_is_trusted(self):
        event = TraceEvent(event_type=TraceEventType.USER_MESSAGE, content="hello")
        assert infer_trust_level(event) == "trusted"

    def test_assistant_message_is_trusted(self):
        event = TraceEvent(event_type=TraceEventType.ASSISTANT_MESSAGE, content="hi")
        assert infer_trust_level(event) == "trusted"

    def test_tool_result_is_untrusted(self):
        event = TraceEvent(event_type=TraceEventType.TOOL_RESULT, content="web data")
        assert infer_trust_level(event) == "untrusted"

    def test_tool_call_is_trusted(self):
        event = TraceEvent(event_type=TraceEventType.TOOL_CALL, content="calling tool")
        assert infer_trust_level(event) == "trusted"

    def test_explicit_metadata_overrides_event_type(self):
        event = TraceEvent(
            event_type=TraceEventType.TOOL_RESULT,
            content="verified data",
            metadata={"upstream_trust_level": "trusted"},
        )
        assert infer_trust_level(event) == "trusted"

    def test_explicit_trust_level_key(self):
        event = TraceEvent(
            event_type=TraceEventType.USER_MESSAGE,
            content="forwarded untrusted",
            metadata={"trust_level": "untrusted"},
        )
        assert infer_trust_level(event) == "untrusted"

    def test_explicit_mixed(self):
        event = TraceEvent(
            event_type=TraceEventType.ASSISTANT_MESSAGE,
            content="mixed content",
            metadata={"upstream_trust_level": "mixed"},
        )
        assert infer_trust_level(event) == "mixed"

    def test_invalid_metadata_value_falls_through(self):
        event = TraceEvent(
            event_type=TraceEventType.USER_MESSAGE,
            content="bad value",
            metadata={"upstream_trust_level": "invalid_value"},
        )
        assert infer_trust_level(event) == "trusted"

    def test_no_metadata(self):
        event = TraceEvent(event_type=TraceEventType.USER_MESSAGE, content="plain")
        assert infer_trust_level(event) == "trusted"

    def test_empty_metadata(self):
        event = TraceEvent(
            event_type=TraceEventType.TOOL_RESULT,
            content="data",
            metadata={},
        )
        assert infer_trust_level(event) == "untrusted"


# ── Pipeline trust propagation tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_infers_trust_from_tool_result(mock_client, sample_events):
    """Candidates extracted from tool results get untrusted trust level."""
    tool_event = sample_events["tool_call"]
    candidate = CandidateMemory(
        content="From tool result",
        source_event=TraceEvent(
            event_type=TraceEventType.TOOL_RESULT,
            content="scraped web content",
        ),
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(tool_event)

    assert len(result.written) == 1
    call_kwargs = mock_client.write.call_args[1]
    assert call_kwargs["upstream_trust_level"] == "untrusted"


@pytest.mark.asyncio
async def test_pipeline_preserves_explicit_trust(mock_client, sample_events):
    """Candidates with explicit trust level are not overridden."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="Explicitly untrusted",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
        upstream_trust_level="untrusted",
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(event)

    assert len(result.written) == 1
    call_kwargs = mock_client.write.call_args[1]
    assert call_kwargs["upstream_trust_level"] == "untrusted"


@pytest.mark.asyncio
async def test_pipeline_user_message_stays_trusted(mock_client, sample_events):
    """Candidates from user messages keep trusted trust level."""
    event = sample_events["preference"]
    candidate = CandidateMemory(
        content="User preference",
        source_event=event,
        extractor_name="test",
        confidence=0.9,
    )
    extractor = MockExtractor("test", [candidate])
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(event)

    assert len(result.written) == 1
    call_kwargs = mock_client.write.call_args[1]
    assert call_kwargs["upstream_trust_level"] == "trusted"


@pytest.mark.asyncio
async def test_mixed_trust_candidates_in_same_batch(mock_client):
    """Multiple candidates with different trust levels in the same batch."""
    trusted_event = TraceEvent.user_message("I prefer FastAPI")
    untrusted_event = TraceEvent(
        event_type=TraceEventType.TOOL_RESULT,
        content="web scrape data",
    )

    candidates = [
        CandidateMemory(
            content="Trusted pref",
            source_event=trusted_event,
            extractor_name="test",
            confidence=0.9,
        ),
        CandidateMemory(
            content="Untrusted data",
            source_event=untrusted_event,
            extractor_name="test",
            confidence=0.9,
        ),
    ]
    extractor = MockExtractor("test", candidates)
    pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

    result = await pipeline.observe(trusted_event)

    assert len(result.written) == 2
    trust_levels = [
        mock_client.write.call_args_list[i][1]["upstream_trust_level"]
        for i in range(2)
    ]
    assert "trusted" in trust_levels
    assert "untrusted" in trust_levels
