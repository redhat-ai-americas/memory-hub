"""Integration tests for push broadcast against real Valkey + pgvector.

These tests verify the broadcast pipeline end-to-end: session registration,
focus vector storage, cosine-filtered delivery, and queue roundtrip. They
exercise the mock-vs-real boundary that unit tests with fakeredis cannot cover.

Run with the compose stack active:
    podman-compose -f tests/integration/compose.yaml up -d
    pytest tests/integration/test_push_broadcast.py
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryScope
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import create_memory as _svc_create_memory
from memoryhub_core.services.push_broadcast import (
    broadcast_to_sessions,
    build_uri_only_notification,
)
from memoryhub_core.services.valkey_client import ValkeyClient

pytestmark = pytest.mark.integration

_TEST_TENANT_ID = "default"


async def create_memory(data, session, embedding_service, skip_curation=False, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around the service create_memory with a default tenant."""
    return await _svc_create_memory(
        data, session, embedding_service, tenant_id=tenant_id, skip_curation=skip_curation,
    )


def _make(content, *, owner_id="test-user", scope=MemoryScope.USER, weight=0.9, domains=None):
    return MemoryNodeCreate(content=content, scope=scope, weight=weight, owner_id=owner_id, domains=domains)


# ---------------------------------------------------------------------------
# 1. Valkey queue roundtrip (LPUSH / BRPOP)
# ---------------------------------------------------------------------------


async def test_push_pop_roundtrip(valkey_client: ValkeyClient) -> None:
    """Push a JSON message to a broadcast queue, pop it, verify payload is identical."""
    session_id = "roundtrip-session"
    payload = json.dumps({"type": "test", "data": "hello"})

    await valkey_client.push_broadcast_message(session_id, payload)
    result = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=2)

    assert result is not None, "Expected a message but got None"
    assert result == payload, f"Payload mismatch: expected {payload!r}, got {result!r}"
    parsed = json.loads(result)
    assert parsed["type"] == "test"
    assert parsed["data"] == "hello"


async def test_push_pop_fifo_order(valkey_client: ValkeyClient) -> None:
    """Push 3 messages, pop them in order, verify FIFO."""
    session_id = "fifo-session"
    messages = [
        json.dumps({"seq": i, "content": f"message-{i}"})
        for i in range(3)
    ]

    for msg in messages:
        await valkey_client.push_broadcast_message(session_id, msg)

    for i, expected in enumerate(messages):
        result = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=2)
        assert result is not None, f"Pop {i} returned None, expected message"
        assert result == expected, (
            f"FIFO violation at position {i}: expected {expected!r}, got {result!r}"
        )


async def test_pop_timeout_returns_none(valkey_client: ValkeyClient) -> None:
    """Pop from an empty queue with a short timeout returns None, not blocking forever."""
    session_id = "empty-queue-session"

    result = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=1)

    assert result is None, f"Expected None from empty queue, got {result!r}"


# ---------------------------------------------------------------------------
# 2. Focus filter with real Valkey session state
# ---------------------------------------------------------------------------


async def test_broadcast_delivers_to_on_topic_sessions(
    valkey_client: ValkeyClient,
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """On-topic session receives the broadcast; off-topic session is filtered out."""
    session_a = "session-python"
    session_b = "session-k8s"

    await valkey_client.register_active_session(session_a)
    await valkey_client.register_active_session(session_b)

    # Session A focuses on Python testing.
    focus_a = "python testing pytest"
    vector_a = await embedding_service.embed(focus_a)
    await valkey_client.write_session_focus(
        session_a, focus_a, vector_a, user_id="user-a", project="test-project",
    )

    # Session B focuses on Kubernetes.
    focus_b = "kubernetes deployment orchestration"
    vector_b = await embedding_service.embed(focus_b)
    await valkey_client.write_session_focus(
        session_b, focus_b, vector_b, user_id="user-b", project="test-project",
    )

    # Create a memory about Python testing to get a real embedding.
    memory = await create_memory(
        _make("python unit testing with pytest fixtures"),
        async_session, embedding_service, skip_curation=True,
    )

    # Read the embedding back from pgvector.
    row = await async_session.execute(
        select(MemoryNode.embedding).where(MemoryNode.id == memory.id)
    )
    memory_embedding = list(row.scalar_one())

    notification = build_uri_only_notification(str(memory.id))
    stats = await broadcast_to_sessions(
        notification, memory_embedding,
        valkey_client=valkey_client,
        push_filter_weight=0.5,
    )

    assert stats["delivered"] >= 1, f"Expected at least 1 delivery, got stats={stats}"
    assert stats["filtered"] >= 1, f"Expected at least 1 filtered, got stats={stats}"

    # Session A (Python-focused) should have received the message.
    msg_a = await valkey_client.pop_broadcast_message(session_a, timeout_seconds=2)
    assert msg_a is not None, "On-topic session A did not receive the broadcast"
    parsed = json.loads(msg_a)
    assert "notification" in parsed
    assert parsed["notification"]["method"] == "notifications/resources/updated"

    # Session B (K8s-focused) should NOT have received the message.
    msg_b = await valkey_client.pop_broadcast_message(session_b, timeout_seconds=1)
    assert msg_b is None, f"Off-topic session B should not have received: {msg_b!r}"


async def test_broadcast_delivers_to_sessions_without_focus(
    valkey_client: ValkeyClient,
    embedding_service: MockEmbeddingService,
) -> None:
    """A session with no focus vector always receives broadcasts (no-focus = deliver all)."""
    session_id = "no-focus-session"
    await valkey_client.register_active_session(session_id)
    # Deliberately NOT setting a focus vector.

    # Generate an arbitrary embedding to pass as the memory's vector.
    memory_embedding = await embedding_service.embed("anything at all")

    notification = {"method": "notifications/resources/updated", "params": {"uri": "memoryhub://memory/fake-id"}}
    stats = await broadcast_to_sessions(
        notification, memory_embedding,
        valkey_client=valkey_client,
        push_filter_weight=0.6,
    )

    assert stats["targeted"] == 1
    assert stats["delivered"] == 1
    assert stats["filtered"] == 0

    msg = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=2)
    assert msg is not None, "Session without focus should have received the broadcast"


async def test_broadcast_excludes_writer_session(
    valkey_client: ValkeyClient,
    embedding_service: MockEmbeddingService,
) -> None:
    """The exclude_session_id parameter prevents the writing session from receiving its own broadcast."""
    session_id = "writer-session"
    await valkey_client.register_active_session(session_id)

    # Set a focus that would match the broadcast content.
    focus = "python development"
    vector = await embedding_service.embed(focus)
    await valkey_client.write_session_focus(
        session_id, focus, vector, user_id="writer", project="test-project",
    )

    memory_embedding = await embedding_service.embed("python development best practices")
    notification = {"method": "notifications/resources/updated", "params": {"uri": "memoryhub://memory/fake"}}

    stats = await broadcast_to_sessions(
        notification, memory_embedding,
        valkey_client=valkey_client,
        push_filter_weight=0.5,
        exclude_session_id=session_id,
    )

    # The session was excluded before targeting, so targeted should be 0.
    assert stats["targeted"] == 0, f"Writer session should have been excluded, got stats={stats}"
    assert stats["delivered"] == 0

    msg = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=1)
    assert msg is None, f"Excluded writer session should not have received: {msg!r}"


# ---------------------------------------------------------------------------
# 3. End-to-end: write_memory -> broadcast -> pop
# ---------------------------------------------------------------------------


async def test_end_to_end_write_and_broadcast(
    valkey_client: ValkeyClient,
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Full flow: create memory in pgvector, broadcast notification, pop and verify.

    Exercises the complete write -> broadcast -> consume pipeline against real
    infrastructure, verifying that the notification structure matches the MCP
    spec and carries the correct memory ID.
    """
    session_id = "e2e-consumer"
    await valkey_client.register_active_session(session_id)

    # Set the consumer's focus to "python development".
    focus = "python development"
    focus_vector = await embedding_service.embed(focus)
    await valkey_client.write_session_focus(
        session_id, focus, focus_vector, user_id="consumer", project="test-project",
    )

    # Create a memory about a related topic.
    memory = await create_memory(
        _make("python type hints best practices for large codebases"),
        async_session, embedding_service, skip_curation=True,
    )

    # Read the embedding back from pgvector.
    row = await async_session.execute(
        select(MemoryNode.embedding).where(MemoryNode.id == memory.id)
    )
    memory_embedding = list(row.scalar_one())

    # Build the spec-compliant notification and broadcast.
    notification = build_uri_only_notification(str(memory.id))
    stats = await broadcast_to_sessions(
        notification, memory_embedding,
        valkey_client=valkey_client,
        push_filter_weight=0.5,
    )

    assert stats["delivered"] >= 1, f"Expected delivery but got stats={stats}"
    assert stats["errors"] == 0, f"Unexpected errors: stats={stats}"

    # Pop the message from the consumer's queue.
    raw = await valkey_client.pop_broadcast_message(session_id, timeout_seconds=2)
    assert raw is not None, "Consumer session did not receive the broadcast"

    envelope = json.loads(raw)
    assert "notification" in envelope, f"Missing 'notification' key in envelope: {envelope}"

    inner = envelope["notification"]
    assert inner["method"] == "notifications/resources/updated", (
        f"Expected MCP spec method, got {inner['method']!r}"
    )
    assert "params" in inner
    assert str(memory.id) in inner["params"]["uri"], (
        f"Memory ID {memory.id} not found in notification URI: {inner['params']['uri']!r}"
    )
    assert inner["params"]["uri"] == f"memoryhub://memory/{memory.id}"
