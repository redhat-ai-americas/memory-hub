"""Tests for graph edge re-pointing and logical_id propagation (#472)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from memoryhub_local.embeddings.base import MockEmbeddingService
from memoryhub_local.models.memory import MemoryRelationship
from memoryhub_local.services.memory import create_memory, update_memory


@pytest.fixture
def embedding_service():
    return MockEmbeddingService()


async def test_update_repoints_outgoing_edges(async_session, embedding_service):
    """After update, outgoing edges from the updated memory point to the new version."""
    a = await create_memory(async_session, "memory A", embedding_service, scope="user")
    b = await create_memory(async_session, "memory B", embedding_service, scope="user")

    edge = MemoryRelationship(
        source_id=a.id, target_id=b.id,
        relationship_type="related_to",
        created_by="test-user", tenant_id="local",
    )
    async_session.add(edge)
    await async_session.commit()

    updated_a = await update_memory(async_session, str(a.id), embedding_service, content="memory A v2")

    result = await async_session.execute(
        select(MemoryRelationship).where(MemoryRelationship.id == edge.id)
    )
    repointed = result.scalar_one()
    assert repointed.source_id == updated_a.id, f"outgoing edge should point from new version, got {repointed.source_id}"
    assert repointed.target_id == b.id


async def test_update_repoints_incoming_edges(async_session, embedding_service):
    """After update, incoming edges to the updated memory point to the new version."""
    a = await create_memory(async_session, "memory A", embedding_service, scope="user")
    b = await create_memory(async_session, "memory B", embedding_service, scope="user")

    edge = MemoryRelationship(
        source_id=b.id, target_id=a.id,
        relationship_type="related_to",
        created_by="test-user", tenant_id="local",
    )
    async_session.add(edge)
    await async_session.commit()

    updated_a = await update_memory(async_session, str(a.id), embedding_service, content="memory A v2")

    result = await async_session.execute(
        select(MemoryRelationship).where(MemoryRelationship.id == edge.id)
    )
    repointed = result.scalar_one()
    assert repointed.source_id == b.id
    assert repointed.target_id == updated_a.id, f"incoming edge should point to new version, got {repointed.target_id}"


async def test_update_preserves_invalidated_edges(async_session, embedding_service):
    """Invalidated edges (valid_until set) should not be re-pointed."""
    a = await create_memory(async_session, "memory A", embedding_service, scope="user")
    b = await create_memory(async_session, "memory B", embedding_service, scope="user")
    old_a_id = a.id

    edge = MemoryRelationship(
        source_id=a.id, target_id=b.id,
        relationship_type="related_to",
        created_by="test-user", tenant_id="local",
        valid_until=datetime.now(timezone.utc),
    )
    async_session.add(edge)
    await async_session.commit()

    await update_memory(async_session, str(a.id), embedding_service, content="memory A v2")

    result = await async_session.execute(
        select(MemoryRelationship).where(MemoryRelationship.id == edge.id)
    )
    unchanged = result.scalar_one()
    assert unchanged.source_id == old_a_id, "invalidated edge should not be re-pointed"


# -- logical_id propagation --


async def test_create_sets_logical_id(async_session, embedding_service):
    """New v1 memories have logical_id == id."""
    node = await create_memory(async_session, "test memory", embedding_service, scope="user")
    assert node.logical_id is not None
    assert node.logical_id == node.id


async def test_update_propagates_logical_id(async_session, embedding_service):
    """Updated memory inherits logical_id from the previous version."""
    v1 = await create_memory(async_session, "v1", embedding_service, scope="user")
    v2 = await update_memory(async_session, str(v1.id), embedding_service, content="v2")

    assert v2.logical_id == v1.logical_id
    assert v2.id != v1.id


async def test_update_chain_shares_logical_id(async_session, embedding_service):
    """All versions in a chain share the same logical_id."""
    v1 = await create_memory(async_session, "v1", embedding_service, scope="user")
    v2 = await update_memory(async_session, str(v1.id), embedding_service, content="v2")
    v3 = await update_memory(async_session, str(v2.id), embedding_service, content="v3")

    assert v1.logical_id == v2.logical_id == v3.logical_id
    assert len({v1.id, v2.id, v3.id}) == 3
