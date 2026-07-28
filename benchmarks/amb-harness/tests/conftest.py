from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from memoryhub.models import ConversationMessage, ConversationThread, ExtractionResult

from memory_bench.memory.memoryhub import MemoryHubProvider
from memory_bench.models import Document


@pytest.fixture
def provider():
    """Pre-configured MemoryHubProvider that bypasses env-var prepare()."""
    p = MemoryHubProvider()
    p._url = "https://fake.example.com/mcp/"
    p._api_key = "mh-dev-test"
    p._project_id = "amb-benchmark"
    p._tenant_id = None
    p._ingestion_mode = "dreaming"
    p._extraction_model = None
    p._extraction_model_url = None
    p._db_url = "sqlite+aiosqlite://"
    return p


@pytest.fixture
def make_document():
    """Factory for Document instances with sensible defaults."""
    _counter = 0

    def _make(
        *,
        id: str | None = None,
        content: str = "test content",
        user_id: str | None = "persona-1",
        messages: list[dict] | None = None,
        timestamp: str | None = None,
    ) -> Document:
        nonlocal _counter
        _counter += 1
        return Document(
            id=id or f"doc-{_counter:03d}",
            content=content,
            user_id=user_id,
            messages=messages if messages is not None else [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
            timestamp=timestamp,
        )

    return _make


def _make_mock_client(
    *,
    thread_id: str = "thread-001",
    extract_result: ExtractionResult | None = None,
) -> MagicMock:
    """Build an AsyncMock MemoryHubClient that works as an async context manager."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    client.create_project = AsyncMock()

    client.create_thread = AsyncMock(return_value=ConversationThread(
        id=thread_id,
        scope="project",
        scope_id="amb-benchmark",
        owner_id="amb-persona-1",
    ))

    client.append_message = AsyncMock(return_value=ConversationMessage(
        id="msg-001",
        thread_id=thread_id,
        sequence_number=1,
        role="user",
        content="hello",
    ))

    client.extract_thread = AsyncMock(
        return_value=extract_result or ExtractionResult(
            extracted_count=2, cursor=5, failures=0,
        )
    )

    return client


@pytest.fixture
def mock_client():
    """A pre-configured mock MemoryHubClient."""
    return _make_mock_client()


@pytest.fixture
def mock_client_factory():
    """Factory for building mock clients with custom config."""
    return _make_mock_client
