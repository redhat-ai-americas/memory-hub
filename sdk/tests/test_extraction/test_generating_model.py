"""Tests for generating_model propagation through extraction pipeline (#566)."""

from __future__ import annotations

import pytest

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent
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


class TestCandidateMemoryField:
    def test_generating_model_defaults_to_none(self):
        c = CandidateMemory(
            content="test",
            source_event=TraceEvent.user_message("hi"),
            extractor_name="test",
        )
        assert c.generating_model is None

    def test_generating_model_set_explicitly(self):
        c = CandidateMemory(
            content="test",
            source_event=TraceEvent.user_message("hi"),
            extractor_name="test",
            generating_model="gemini-2.5-flash",
        )
        assert c.generating_model == "gemini-2.5-flash"


class TestPipelineGeneratingModel:
    @pytest.mark.asyncio
    async def test_pipeline_generating_model_flows_to_write(self, mock_client):
        """Pipeline-level generating_model propagates to client.write()."""
        event = TraceEvent.user_message("I prefer FastAPI")
        candidate = CandidateMemory(
            content="User prefers FastAPI",
            source_event=event,
            extractor_name="test",
            confidence=0.9,
        )
        extractor = MockExtractor("test", [candidate])
        pipeline = ExtractionPipeline(
            mock_client, extractors=[extractor],
            generating_model="gemini-2.5-flash",
        )

        await pipeline.observe(event)

        call_kwargs = mock_client.write.call_args[1]
        assert call_kwargs["generating_model"] == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_candidate_generating_model_overrides_pipeline(self, mock_client):
        """Candidate-level generating_model takes precedence over pipeline default."""
        event = TraceEvent.user_message("I prefer FastAPI")
        candidate = CandidateMemory(
            content="User prefers FastAPI",
            source_event=event,
            extractor_name="test",
            confidence=0.9,
            generating_model="claude-sonnet-4",
        )
        extractor = MockExtractor("test", [candidate])
        pipeline = ExtractionPipeline(
            mock_client, extractors=[extractor],
            generating_model="gemini-2.5-flash",
        )

        await pipeline.observe(event)

        call_kwargs = mock_client.write.call_args[1]
        assert call_kwargs["generating_model"] == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_no_generating_model_when_not_configured(self, mock_client):
        """Without generating_model set, None flows through (user-stated memory)."""
        event = TraceEvent.user_message("I prefer FastAPI")
        candidate = CandidateMemory(
            content="User prefers FastAPI",
            source_event=event,
            extractor_name="test",
            confidence=0.9,
        )
        extractor = MockExtractor("test", [candidate])
        pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

        await pipeline.observe(event)

        call_kwargs = mock_client.write.call_args[1]
        assert call_kwargs["generating_model"] is None

    @pytest.mark.asyncio
    async def test_mixed_generating_models_in_batch(self, mock_client):
        """Candidates with different generating_model values in the same batch."""
        event = TraceEvent.user_message("test")
        candidates = [
            CandidateMemory(
                content="From model A",
                source_event=event,
                extractor_name="test",
                confidence=0.9,
                generating_model="model-a",
            ),
            CandidateMemory(
                content="From model B",
                source_event=event,
                extractor_name="test",
                confidence=0.9,
                generating_model="model-b",
            ),
        ]
        extractor = MockExtractor("test", candidates)
        pipeline = ExtractionPipeline(mock_client, extractors=[extractor])

        await pipeline.observe(event)

        assert len(mock_client.write.call_args_list) == 2
        models = [
            mock_client.write.call_args_list[i][1]["generating_model"]
            for i in range(2)
        ]
        assert "model-a" in models
        assert "model-b" in models
