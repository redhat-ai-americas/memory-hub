"""Tests for the extraction pipeline."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from memoryhub_local.embeddings.base import MockEmbeddingService
from memoryhub_local.identity import TENANT_ID
from memoryhub_local.models.conversation import (
    ConversationExtraction,
    ConversationExtractionFailure,
    ConversationMessage,
    ConversationThread,
)
from memoryhub_local.models.memory import MemoryNode
from memoryhub_local.services.extraction import (
    compute_windows,
    extract_from_thread,
    format_messages,
    get_pending_threads,
)
from memoryhub_local.services.thread import append_message, create_thread

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_llm_fn(extractions: list[dict]):
    """Return a mock llm_fn that returns fixed extractions."""

    async def _fn(messages_text: str) -> list[dict]:
        return extractions

    return _fn


def _failing_llm_fn():
    """Return a mock llm_fn that always raises."""

    async def _fn(messages_text: str) -> list[dict]:
        raise RuntimeError("LLM unavailable")

    return _fn


async def _create_thread_with_messages(
    session,
    pairs: list[tuple[str, str]],
    title: str = "test",
) -> str:
    """Create a thread and append role/content pairs, return the thread id."""
    thread = await create_thread(session, "user", title=title)
    for role, content in pairs:
        await append_message(session, thread["id"], role, content)
    return thread["id"]


async def _load_messages(session, thread_id: str) -> list[ConversationMessage]:
    """Load messages for a thread ordered by sequence_number."""
    result = await session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.thread_id == uuid.UUID(thread_id))
        .order_by(ConversationMessage.sequence_number)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_messages(async_session, backend):
    thread_id = await _create_thread_with_messages(
        async_session,
        [("user", "Hello there"), ("assistant", "Hi! How can I help?")],
    )
    messages = await _load_messages(async_session, thread_id)
    formatted = format_messages(messages)

    assert "[USER] (seq=1):" in formatted
    assert "[ASSISTANT] (seq=2):" in formatted
    assert "Hello there" in formatted
    assert "Hi! How can I help?" in formatted


@pytest.mark.asyncio
async def test_compute_windows_per_turn(async_session, backend):
    """Four alternating messages should produce two windows of two each."""
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "First question"),
            ("assistant", "First answer"),
            ("user", "Second question"),
            ("assistant", "Second answer"),
        ],
    )
    messages = await _load_messages(async_session, thread_id)
    windows = compute_windows(messages)

    assert len(windows) == 2
    assert len(windows[0]) == 2
    assert len(windows[1]) == 2
    assert windows[0][0].role == "user"
    assert windows[0][1].role == "assistant"
    assert windows[1][0].role == "user"
    assert windows[1][1].role == "assistant"


@pytest.mark.asyncio
async def test_compute_windows_size_boundary(async_session, backend):
    """A window should split at window_size even without turn boundaries."""
    thread_id = await _create_thread_with_messages(
        async_session,
        [("user", f"msg {i}") for i in range(5)],
    )
    messages = await _load_messages(async_session, thread_id)
    windows = compute_windows(messages, window_size=3)

    assert len(windows) == 2
    assert len(windows[0]) == 3
    assert len(windows[1]) == 2


@pytest.mark.asyncio
async def test_extract_from_thread_creates_memories(async_session, backend):
    """Extraction with a mock LLM should create a MemoryNode."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "I prefer Python over JavaScript for backend work"),
            ("assistant", "Got it, I'll use Python for backend tasks"),
        ],
    )

    llm_fn = _mock_llm_fn([
        {
            "content": "User prefers Python over JavaScript for backend work",
            "weight": 0.8,
            "domains": ["programming", "preferences"],
        },
    ])

    result = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    assert result["extracted_count"] == 1
    assert result["failures"] == 0
    assert result["windows_processed"] == 1

    # Verify a MemoryNode was created with source="extraction"
    nodes = (
        await async_session.execute(
            select(MemoryNode).where(
                MemoryNode.source == "extraction",
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
    ).scalars().all()
    assert len(nodes) >= 1
    assert "Python" in nodes[0].content


@pytest.mark.asyncio
async def test_extraction_cursor_advances(async_session, backend):
    """After extraction, the thread cursor should match the last sequence."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "Use Podman not Docker"),
            ("assistant", "Understood"),
        ],
    )

    llm_fn = _mock_llm_fn([
        {"content": "Always use Podman, never Docker", "weight": 0.9},
    ])

    result = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    assert result["cursor"] == 2

    # Verify thread object in DB
    thread = (
        await async_session.execute(
            select(ConversationThread).where(
                ConversationThread.id == uuid.UUID(thread_id),
            )
        )
    ).scalar_one()
    assert thread.extraction_cursor == 2
    assert thread.last_extracted_at is not None


@pytest.mark.asyncio
async def test_extraction_dedup_skips_duplicate(async_session, backend):
    """Extracting the same content twice should skip on the second run."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "I like parmesan cheese"),
            ("assistant", "Noted!"),
        ],
    )

    extractions = [
        {"content": "User's favorite cheese is parmesan", "weight": 0.7},
    ]
    llm_fn = _mock_llm_fn(extractions)

    # First extraction creates the memory
    r1 = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )
    assert r1["extracted_count"] == 1

    # Add more messages so there's something past the cursor
    await append_message(async_session, thread_id, "user", "Remind me what cheese I like")
    await append_message(async_session, thread_id, "assistant", "Parmesan!")

    # Second extraction with identical content should skip (same embedding)
    r2 = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )
    assert r2["extracted_count"] == 0

    # Should still have exactly one active, current memory with this content
    nodes = (
        await async_session.execute(
            select(MemoryNode).where(
                MemoryNode.status == "active",
                MemoryNode.is_current.is_(True),
                MemoryNode.source == "extraction",
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
    ).scalars().all()
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_extraction_failure_recorded(async_session, backend):
    """A failing LLM should record a ConversationExtractionFailure."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "Tell me about AI"),
            ("assistant", "AI is a broad field"),
        ],
    )

    result = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=_failing_llm_fn(),
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    assert result["failures"] == 1
    assert result["extracted_count"] == 0

    # Verify failure record exists
    failures = (
        await async_session.execute(
            select(ConversationExtractionFailure).where(
                ConversationExtractionFailure.thread_id == uuid.UUID(thread_id),
            )
        )
    ).scalars().all()
    assert len(failures) == 1
    assert "LLM unavailable" in failures[0].last_error

    # Cursor should still advance past the failed window
    assert result["cursor"] == 2


@pytest.mark.asyncio
async def test_extraction_provenance(async_session, backend):
    """Extraction should create a ConversationExtraction provenance record."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "Deploy to OpenShift always"),
            ("assistant", "Will do"),
        ],
    )

    llm_fn = _mock_llm_fn([
        {"content": "Always deploy applications to OpenShift", "weight": 0.9},
    ])

    await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    # Query provenance records
    provenance_rows = (
        await async_session.execute(
            select(ConversationExtraction).where(
                ConversationExtraction.thread_id == uuid.UUID(thread_id),
            )
        )
    ).scalars().all()

    assert len(provenance_rows) == 1
    prov = provenance_rows[0]
    assert prov.extracted_by == "personal_extraction"
    assert prov.extraction_model == "sampling"
    assert prov.source_messages == [1, 2]
    assert prov.tenant_id == TENANT_ID

    # Verify the provenance links to a real memory node
    node = (
        await async_session.execute(
            select(MemoryNode).where(MemoryNode.id == prov.memory_node_id)
        )
    ).scalar_one()
    assert "OpenShift" in node.content


@pytest.mark.asyncio
async def test_get_pending_threads(async_session, backend):
    """Pending threads should appear before extraction and vanish after."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "Remember this fact"),
            ("assistant", "Stored"),
        ],
    )

    # Before extraction: thread is pending
    pending = await get_pending_threads(async_session)
    ids = [p["id"] for p in pending]
    assert thread_id in ids
    match = next(p for p in pending if p["id"] == thread_id)
    assert match["pending_count"] == 2

    # Extract
    llm_fn = _mock_llm_fn([
        {"content": "Remember this fact from the user", "weight": 0.6},
    ])
    await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    # After extraction: thread is no longer pending
    pending_after = await get_pending_threads(async_session)
    ids_after = [p["id"] for p in pending_after]
    assert thread_id not in ids_after


@pytest.mark.asyncio
async def test_extraction_skips_low_weight(async_session, backend):
    """Extractions with weight < 0.5 should be skipped entirely."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "The weather is nice today"),
            ("assistant", "Indeed it is!"),
        ],
    )

    llm_fn = _mock_llm_fn([
        {"content": "It was a nice day", "weight": 0.3},
    ])

    result = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    assert result["extracted_count"] == 0


@pytest.mark.asyncio
async def test_extraction_no_messages_past_cursor(async_session, backend):
    """When all messages are already processed, return early."""
    embed_svc = MockEmbeddingService()
    thread_id = await _create_thread_with_messages(
        async_session,
        [
            ("user", "Hello"),
            ("assistant", "Hi"),
        ],
    )

    llm_fn = _mock_llm_fn([
        {"content": "User greeted the assistant", "weight": 0.6},
    ])

    # First extraction processes everything
    await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    # Second extraction with no new messages
    result = await extract_from_thread(
        async_session,
        thread_id,
        llm_fn=llm_fn,
        embedding_service=embed_svc,
        recall_backend=backend,
    )

    assert result["extracted_count"] == 0
    assert result["message"] == "no new messages"
