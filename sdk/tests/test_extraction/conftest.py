"""Shared fixtures for extraction pipeline tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from memoryhub.client import MemoryHubClient
from memoryhub.extraction.models import TraceEvent
from memoryhub.models import CurationInfo, Memory, SearchResult, WriteResult


@pytest.fixture
def mock_client():
    """Return a MemoryHubClient with mocked write/search/create_relationship methods."""
    client = MemoryHubClient(url="https://fake.example.com/mcp/", api_key="mh-dev-test")

    # Mock the write method to return a WriteResult with a Memory
    async def mock_write(*args, **kwargs):
        memory = Memory(
            id="mem-test-001",
            content=kwargs.get("content", "test content"),
            scope=kwargs.get("scope", "user"),
            owner_id="test-user",
            weight=kwargs.get("weight", 0.7),
            is_current=True,
            version=1,
            storage_type="inline",
        )
        curation = CurationInfo(blocked=False, gated=False, similar_count=0, flags=[])
        return WriteResult(memory=memory, curation=curation)

    client.write = AsyncMock(side_effect=mock_write)

    # Mock the search method to return a SearchResult with configurable results
    async def mock_search(*args, **kwargs):
        return SearchResult(results=[], total_matching=0, has_more=False)

    client.search = AsyncMock(side_effect=mock_search)

    # Mock the create_relationship method
    async def mock_create_relationship(*args, **kwargs):
        return None

    client.create_relationship = AsyncMock(side_effect=mock_create_relationship)

    return client


@pytest.fixture
def sample_events():
    """Return a dict of common test TraceEvents."""
    return {
        "preference": TraceEvent.user_message(
            content="I always use Podman, not Docker",
            metadata={"category": "preference"},
        ),
        "entity_rich": TraceEvent.assistant_message(
            content="Created project 'memory-hub' with FastAPI and PostgreSQL",
            metadata={"entities": ["memory-hub", "FastAPI", "PostgreSQL"]},
        ),
        "decision": TraceEvent.assistant_message(
            content="Decided to use pgvector for semantic search instead of a separate vector DB",
            metadata={"category": "architectural_decision"},
        ),
        "tool_call": TraceEvent.tool_call(
            name="create_file",
            args={"path": "/tmp/test.py", "content": "print('hello')"},
            result="File created successfully",
        ),
        "bland": TraceEvent.assistant_message(
            content="Let me read that file for you.",
        ),
    }
