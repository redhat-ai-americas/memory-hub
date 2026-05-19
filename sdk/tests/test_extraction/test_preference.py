"""Tests for memoryhub.extraction.extractors.preference.PreferenceExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from memoryhub.extraction.extractors.preference import PreferenceExtractor
from memoryhub.extraction.models import TraceEvent


@pytest.mark.asyncio
class TestPreferenceExtractor:
    """Test PreferenceExtractor functionality."""

    async def test_use_x_instead_of_y_detected(self) -> None:
        """'Use X instead of Y' pattern provides better matching for comparisons."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Use PostgreSQL instead of MySQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert "PostgreSQL" in candidate.content
        assert "MySQL" in candidate.content
        metadata = candidate.metadata
        assert metadata is not None
        assert metadata["subject"] == "PostgreSQL"
        assert metadata["alternative"] == "MySQL"
        assert metadata["polarity"] == "positive"

    async def test_always_use_detected(self) -> None:
        """'Always use X' pattern detected with subject."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Always use Podman")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert metadata["subject"] == "Podman"
        assert metadata["polarity"] == "positive"
        assert metadata["alternative"] is None

    async def test_dont_use_negative_polarity(self) -> None:
        """'Don't use X' pattern detected with negative polarity."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Don't use Docker")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert "Avoid" in candidate.content
        metadata = candidate.metadata
        assert metadata is not None
        assert metadata["subject"] == "Docker"
        assert metadata["polarity"] == "negative"


    async def test_bland_message_returns_empty(self) -> None:
        """Bland messages with no preferences return empty list."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Hello, how are you?")

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_tool_call_events_return_empty(self) -> None:
        """Tool call events return empty (only user messages processed)."""
        extractor = PreferenceExtractor()
        event = TraceEvent.tool_call(
            name="search_memory",
            args={"query": "FastAPI"},
            content="Tool call: search_memory"
        )

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_weight_defaults_to_0_85(self) -> None:
        """Weight defaults to 0.85 for preference candidates."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("I prefer FastAPI")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].weight == 0.85

    async def test_confidence_0_7_for_regex_matches(self) -> None:
        """Confidence is approximately 0.7 for regex pattern matches."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("I prefer FastAPI")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].confidence == pytest.approx(0.7, abs=0.01)

    async def test_llm_path_called_for_ambiguous(self) -> None:
        """LLM path is called for ambiguous text when configured."""
        # Mock LLM that returns structured preference JSON
        mock_llm = AsyncMock(return_value=json.dumps([
            {
                "subject": "FastAPI",
                "polarity": "positive",
                "alternative": None
            }
        ]))

        extractor = PreferenceExtractor(llm=mock_llm)
        event = TraceEvent.user_message("FastAPI is better")

        candidates = await extractor.extract(event)

        # LLM should be called since pattern matching doesn't find anything
        mock_llm.assert_called_once()
        assert len(candidates) == 1
        assert candidates[0].confidence == 0.85  # Higher confidence for LLM

    async def test_llm_not_configured_falls_back_to_pattern(self) -> None:
        """When LLM not configured, falls back to pattern-only."""
        extractor = PreferenceExtractor(llm=None)
        event = TraceEvent.user_message("I prefer FastAPI")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert metadata["detection_method"] == "pattern"

    async def test_name_property_returns_preference(self) -> None:
        """Name property returns 'preference'."""
        extractor = PreferenceExtractor()
        assert extractor.name == "preference"

    async def test_never_use_pattern(self) -> None:
        """'Never use X' pattern detected with negative polarity."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Never use global state")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert metadata["polarity"] == "negative"
        assert "Avoid" in candidates[0].content

    async def test_avoid_pattern(self) -> None:
        """'Avoid X' pattern detected with negative polarity."""
        extractor = PreferenceExtractor()
        event = TraceEvent.user_message("Avoid using mocks in tests")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert metadata["polarity"] == "negative"
