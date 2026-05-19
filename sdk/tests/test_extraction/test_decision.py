"""Tests for memoryhub.extraction.extractors.decision.DecisionTraceExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from memoryhub.extraction.extractors.decision import DecisionTraceExtractor
from memoryhub.extraction.models import TraceEvent


@pytest.mark.asyncio
class TestDecisionTraceExtractor:
    """Test DecisionTraceExtractor functionality."""

    async def test_decided_basic_pattern_detected(self) -> None:
        """'I decided X' pattern detected (matches minimal text due to lazy quantifier)."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message(
            "I decided to proceed with the plan."
        )

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        candidate = candidates[0]
        # Due to lazy quantifier +?, this matches minimally
        assert "Decision:" in candidate.content
        metadata = candidate.metadata
        assert metadata is not None
        assert "decision_summary" in metadata

    async def test_approach_is_pattern_detected(self) -> None:
        """'The approach is to X' pattern detected."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message("The approach is to use microservices")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert "microservices" in metadata["decision_summary"]

    async def test_bland_message_returns_empty(self) -> None:
        """Bland messages with no decisions return empty list."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message("Hello, how are you?")

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_branch_type_is_rationale(self) -> None:
        """branch_type is set to 'rationale' for decision candidates."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message("I decided to use PostgreSQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].branch_type == "rationale"

    async def test_weight_defaults_to_0_8(self) -> None:
        """Weight defaults to 0.8 for decision candidates."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message("I decided to use PostgreSQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].weight == 0.8

    async def test_llm_path_structured_extraction(self) -> None:
        """LLM path extracts structured decision data."""
        # Mock LLM that returns decision JSON
        mock_llm = AsyncMock(return_value=json.dumps({
            "has_decision": True,
            "decision_summary": "Use PostgreSQL for data storage",
            "rationale": "It ships with OpenShift and has strong consistency",
            "alternatives": "MySQL, SQLite were considered"
        }))

        extractor = DecisionTraceExtractor(llm=mock_llm)
        event = TraceEvent.user_message(
            "After considering options, I'll use PostgreSQL"
        )

        candidates = await extractor.extract(event)

        mock_llm.assert_called_once()
        assert len(candidates) == 1
        candidate = candidates[0]
        assert "PostgreSQL" in candidate.content
        assert "OpenShift" in candidate.content
        assert "MySQL" in candidate.content
        metadata = candidate.metadata
        assert metadata is not None
        assert metadata["decision_summary"] == "Use PostgreSQL for data storage"
        assert "OpenShift" in metadata["rationale"]
        assert metadata.get("alternatives") == "MySQL, SQLite were considered"

    async def test_no_llm_pattern_matching_lower_confidence(self) -> None:
        """Pattern matching without LLM has lower confidence (~0.45)."""
        extractor = DecisionTraceExtractor(llm=None)
        event = TraceEvent.user_message("I decided to use PostgreSQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].confidence == pytest.approx(0.45, abs=0.01)

    async def test_name_property_returns_decision_trace(self) -> None:
        """Name property returns 'decision_trace'."""
        extractor = DecisionTraceExtractor()
        assert extractor.name == "decision_trace"

    async def test_chose_pattern(self) -> None:
        """'We chose X' pattern detected (matches minimal text)."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message("We chose this approach.")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert "decision_summary" in metadata

    async def test_opted_for_pattern(self) -> None:
        """'Opted for X' pattern detected (matches minimal text)."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.user_message(
            "We opted for this solution."
        )

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert "decision_summary" in metadata

    async def test_tool_call_events_return_empty(self) -> None:
        """Tool call events return empty (only message events processed)."""
        extractor = DecisionTraceExtractor()
        event = TraceEvent.tool_call(
            name="search_memory",
            args={"query": "decisions"},
            content="Tool call: search_memory"
        )

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_llm_no_decision_returns_empty(self) -> None:
        """LLM returning 'has_decision: false' produces empty list."""
        mock_llm = AsyncMock(return_value=json.dumps({"has_decision": False}))

        extractor = DecisionTraceExtractor(llm=mock_llm)
        event = TraceEvent.user_message("Just asking a question")

        candidates = await extractor.extract(event)

        assert len(candidates) == 0
