"""Tests for memoryhub.extraction.extractors.entity.EntityExtractor."""

from __future__ import annotations

import pytest

from memoryhub.extraction.extractors.entity import EntityExtractor
from memoryhub.extraction.models import TraceEvent


@pytest.mark.asyncio
class TestEntityExtractor:
    """Test EntityExtractor functionality."""

    async def test_detects_technology_names(self) -> None:
        """Technology names like PostgreSQL and FastAPI are detected."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("We use PostgreSQL and FastAPI")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert "PostgreSQL" in candidate.content
        assert "FastAPI" in candidate.content
        assert candidate.metadata is not None
        assert len(candidate.metadata["entities"]) == 2
        entity_names = {e["name"] for e in candidate.metadata["entities"]}
        assert "PostgreSQL" in entity_names
        assert "FastAPI" in entity_names

    async def test_returns_empty_for_bland_messages(self) -> None:
        """Bland messages with no entities return empty list."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("Hello, how are you?")

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_returns_empty_for_tool_call_events(self) -> None:
        """Tool call events are skipped (only message events processed)."""
        extractor = EntityExtractor()
        event = TraceEvent.tool_call(
            name="search_memory",
            args={"query": "PostgreSQL"},
            content="Tool call: search_memory"
        )

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_returns_empty_for_reasoning_events(self) -> None:
        """Reasoning events are skipped (only message events processed)."""
        extractor = EntityExtractor()
        event = TraceEvent.reasoning("I need to search for PostgreSQL information")

        candidates = await extractor.extract(event)

        assert len(candidates) == 0

    async def test_confidence_pattern_only(self) -> None:
        """Confidence is approximately 0.55 for pattern-only detection."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("We use PostgreSQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].confidence == pytest.approx(0.55, abs=0.01)

    async def test_weight_defaults_to_0_7(self) -> None:
        """Weight defaults to 0.7 for entity candidates."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("We use PostgreSQL")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        assert candidates[0].weight == 0.7

    async def test_min_entity_count_parameter(self) -> None:
        """min_entity_count parameter filters low-entity content."""
        extractor = EntityExtractor(min_entity_count=2)
        event_single = TraceEvent.user_message("We use PostgreSQL")
        event_multiple = TraceEvent.user_message("We use PostgreSQL and FastAPI")

        # Single entity should be skipped
        candidates_single = await extractor.extract(event_single)
        assert len(candidates_single) == 0

        # Multiple entities should be extracted
        candidates_multiple = await extractor.extract(event_multiple)
        assert len(candidates_multiple) == 1

    async def test_metadata_includes_entity_names(self) -> None:
        """Metadata includes detected entity names and types."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("We use PostgreSQL and Kubernetes")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        assert "entities" in metadata
        assert len(metadata["entities"]) == 2

        entity_dict = {e["name"]: e["type"] for e in metadata["entities"]}
        assert "PostgreSQL" in entity_dict
        assert "Kubernetes" in entity_dict
        assert entity_dict["PostgreSQL"] == "TECHNOLOGY"
        assert entity_dict["Kubernetes"] == "TECHNOLOGY"

    async def test_name_property_returns_entity(self) -> None:
        """Name property returns 'entity'."""
        extractor = EntityExtractor()
        assert extractor.name == "entity"

    async def test_works_with_assistant_messages(self) -> None:
        """Entity extraction works on assistant messages too."""
        extractor = EntityExtractor()
        event = TraceEvent.assistant_message("I recommend using PostgreSQL with FastAPI")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        candidate = candidates[0]
        assert "PostgreSQL" in candidate.content
        assert "FastAPI" in candidate.content

    async def test_capitalized_multi_word_names(self) -> None:
        """Detects capitalized multi-word names like 'Memory Hub'."""
        extractor = EntityExtractor()
        event = TraceEvent.user_message("We deployed Memory Hub successfully")

        candidates = await extractor.extract(event)

        assert len(candidates) == 1
        metadata = candidates[0].metadata
        assert metadata is not None
        entity_names = {e["name"] for e in metadata["entities"]}
        assert "Memory Hub" in entity_names
