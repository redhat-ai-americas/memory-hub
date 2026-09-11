"""Tests for entity management functions: list_entities, merge_entities, rename_entity."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.utils import generate_stub
from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.entity import (
    create_mentions_relationship,
    find_or_create_entity,
    list_entities,
    merge_entities,
    rename_entity,
)


# Helper to create a memory node for relationship testing
async def create_memory_node(
    session: AsyncSession,
    *,
    content: str,
    tenant_id: str = "test-tenant",
    owner_id: str = "user-123",
) -> uuid.UUID:
    """Create a memory node and return its ID."""
    memory_id = uuid.uuid4()
    memory_node = MemoryNode(
        id=memory_id, 
		logical_id=memory_id, 
        content=content,
        stub=generate_stub(content, "user", 0.7, 0, False),
        scope="user",
        owner_id=owner_id,
        tenant_id=tenant_id,
        weight=0.7,
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(memory_node)
    await session.commit()
    return memory_id


# ============================================================================
# list_entities tests
# ============================================================================


@pytest.mark.asyncio
async def test_list_entities_empty_result(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Empty result when no entities exist."""
    result = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert result["entities"] == []
    assert result["total"] == 0
    assert result["limit"] == 50
    assert result["offset"] == 0
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_list_entities_with_mentions_count(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Returns entities with correct mentions_count."""
    # Create two entities
    alice, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    bob, _ = await find_or_create_entity(
        name="Bob",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Create memories mentioning Alice twice, Bob once
    mem1_id = await create_memory_node(async_session, content="I met Alice")
    mem2_id = await create_memory_node(async_session, content="Alice called")
    mem3_id = await create_memory_node(async_session, content="Bob emailed")

    await create_mentions_relationship(
        memory_id=mem1_id,
        entity_id=alice.id,
        session=async_session,
        tenant_id="test-tenant",
    )
    await create_mentions_relationship(
        memory_id=mem2_id,
        entity_id=alice.id,
        session=async_session,
        tenant_id="test-tenant",
    )
    await create_mentions_relationship(
        memory_id=mem3_id,
        entity_id=bob.id,
        session=async_session,
        tenant_id="test-tenant",
    )

    result = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert result["total"] == 2
    assert len(result["entities"]) == 2

    # Verify mentions counts
    entities_by_name = {e["content"]: e for e in result["entities"]}
    assert entities_by_name["Alice"]["mentions_count"] == 2
    assert entities_by_name["Bob"]["mentions_count"] == 1


@pytest.mark.asyncio
async def test_list_entities_ordered_by_mentions_desc(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Ordered by mentions_count descending."""
    # Create three entities with different mention counts
    alice, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    bob, _ = await find_or_create_entity(
        name="Bob",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    charlie, _ = await find_or_create_entity(
        name="Charlie",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Bob: 3 mentions, Alice: 2 mentions, Charlie: 1 mention
    for _ in range(3):
        mem_id = await create_memory_node(async_session, content=f"Bob msg {_}")
        await create_mentions_relationship(
            memory_id=mem_id,
            entity_id=bob.id,
            session=async_session,
            tenant_id="test-tenant",
        )

    for _ in range(2):
        mem_id = await create_memory_node(async_session, content=f"Alice msg {_}")
        await create_mentions_relationship(
            memory_id=mem_id,
            entity_id=alice.id,
            session=async_session,
            tenant_id="test-tenant",
        )

    mem_id = await create_memory_node(async_session, content="Charlie msg")
    await create_mentions_relationship(
        memory_id=mem_id,
        entity_id=charlie.id,
        session=async_session,
        tenant_id="test-tenant",
    )

    result = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Should be ordered Bob (3), Alice (2), Charlie (1)
    assert result["entities"][0]["content"] == "Bob"
    assert result["entities"][0]["mentions_count"] == 3
    assert result["entities"][1]["content"] == "Alice"
    assert result["entities"][1]["mentions_count"] == 2
    assert result["entities"][2]["content"] == "Charlie"
    assert result["entities"][2]["mentions_count"] == 1


@pytest.mark.asyncio
async def test_list_entities_filter_by_entity_type(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Filtering by entity_type works."""
    await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    await find_or_create_entity(
        name="Acme Inc",
        entity_type="organization",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Filter for person only
    result = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
        entity_type="person",
    )

    assert result["total"] == 1
    assert result["entities"][0]["content"] == "Alice"
    assert result["entities"][0]["entity_type"] == "person"


@pytest.mark.asyncio
async def test_list_entities_pagination(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Pagination (limit/offset) works, including has_more."""
    # Create 5 entities
    for i in range(5):
        await find_or_create_entity(
            name=f"Person{i}",
            entity_type="person",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )

    # First page (limit=2, offset=0)
    page1 = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
        limit=2,
        offset=0,
    )
    assert page1["total"] == 5
    assert len(page1["entities"]) == 2
    assert page1["has_more"] is True

    # Second page (limit=2, offset=2)
    page2 = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
        limit=2,
        offset=2,
    )
    assert page2["total"] == 5
    assert len(page2["entities"]) == 2
    assert page2["has_more"] is True

    # Last page (limit=2, offset=4)
    page3 = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-123",
        limit=2,
        offset=4,
    )
    assert page3["total"] == 5
    assert len(page3["entities"]) == 1
    assert page3["has_more"] is False


@pytest.mark.asyncio
async def test_list_entities_invalid_entity_type(
    async_session: AsyncSession,
) -> None:
    """Invalid entity_type raises ValueError."""
    with pytest.raises(ValueError, match="Invalid entity_type"):
        await list_entities(
            async_session,
            tenant_id="test-tenant",
            owner_id="user-123",
            entity_type="invalid_type",
        )


@pytest.mark.asyncio
async def test_list_entities_tenant_isolation(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Entities from different tenant not returned."""
    # Create entity in tenant-1
    await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant-1",
        owner_id="user-123",
    )
    # Create entity in tenant-2
    await find_or_create_entity(
        name="Bob",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant-2",
        owner_id="user-123",
    )

    # List entities for tenant-1
    result = await list_entities(
        async_session,
        tenant_id="tenant-1",
        owner_id="user-123",
    )

    assert result["total"] == 1
    assert result["entities"][0]["content"] == "Alice"


@pytest.mark.asyncio
async def test_list_entities_owner_isolation(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Entities from different owner not returned."""
    # Create entity for user-1
    await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-1",
    )
    # Create entity for user-2
    await find_or_create_entity(
        name="Bob",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-2",
    )

    # List entities for user-1
    result = await list_entities(
        async_session,
        tenant_id="test-tenant",
        owner_id="user-1",
    )

    assert result["total"] == 1
    assert result["entities"][0]["content"] == "Alice"


# ============================================================================
# merge_entities tests
# ============================================================================


@pytest.mark.asyncio
async def test_merge_entities_basic(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Basic merge: MENTIONS edges move from source to target."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Create memory mentioning source
    mem_id = await create_memory_node(async_session, content="I met Alice")
    await create_mentions_relationship(
        memory_id=mem_id,
        entity_id=source.id,
        session=async_session,
        tenant_id="test-tenant",
    )

    result = await merge_entities(
        source_id=source.id,
        target_id=target.id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert result["reassigned_mentions"] == 1
    assert result["skipped_duplicates"] == 0
    assert result["source_deleted"] == str(source.id)


@pytest.mark.asyncio
async def test_merge_entities_source_name_in_aliases(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Source's canonical name added to target's aliases."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    result = await merge_entities(
        source_id=source.id,
        target_id=target.id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert "Alice" in result["surviving_entity"]["aliases"]


@pytest.mark.asyncio
async def test_merge_entities_source_soft_deleted(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Source entity is soft-deleted after merge."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    await merge_entities(
        source_id=source.id,
        target_id=target.id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Verify source is deleted
    await async_session.refresh(
        await async_session.get(MemoryNode, source.id)
    )
    source_node = await async_session.get(MemoryNode, source.id)
    assert source_node.deleted_at is not None


@pytest.mark.asyncio
async def test_merge_entities_duplicate_edge_handling(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Duplicate edge handling: if memory already mentions target, source edge invalidated."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Create memory mentioning both source and target
    mem_id = await create_memory_node(async_session, content="Alice and Alice Smith")
    await create_mentions_relationship(
        memory_id=mem_id,
        entity_id=source.id,
        session=async_session,
        tenant_id="test-tenant",
    )
    await create_mentions_relationship(
        memory_id=mem_id,
        entity_id=target.id,
        session=async_session,
        tenant_id="test-tenant",
    )

    result = await merge_entities(
        source_id=source.id,
        target_id=target.id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Source edge should be skipped (duplicate)
    assert result["reassigned_mentions"] == 0
    assert result["skipped_duplicates"] == 1


@pytest.mark.asyncio
async def test_merge_entities_cannot_merge_into_self(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Cannot merge entity into itself."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="Cannot merge an entity into itself"):
        await merge_entities(
            source_id=entity.id,
            target_id=entity.id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_merge_entities_source_not_found(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Source entity not found raises ValueError."""
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match=f"Source entity {fake_id} not found"):
        await merge_entities(
            source_id=fake_id,
            target_id=target.id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_merge_entities_target_not_found(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Target entity not found raises ValueError."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match=f"Target entity {fake_id} not found"):
        await merge_entities(
            source_id=source.id,
            target_id=fake_id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_merge_entities_source_not_entity_node(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Source is not an entity node raises ValueError."""
    # Create a regular memory node
    mem_id = await create_memory_node(async_session, content="Not an entity")

    target, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="Source .* is not an entity node"):
        await merge_entities(
            source_id=mem_id,
            target_id=target.id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_merge_entities_different_tenant(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Different tenant raises ValueError."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant-1",
        owner_id="user-123",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant-2",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="different tenant"):
        await merge_entities(
            source_id=source.id,
            target_id=target.id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="tenant-1",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_merge_entities_different_owner(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Different owner raises ValueError."""
    source, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-1",
    )
    target, _ = await find_or_create_entity(
        name="Alice Smith",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-2",
    )

    with pytest.raises(ValueError, match="different owner"):
        await merge_entities(
            source_id=source.id,
            target_id=target.id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-1",
        )


# ============================================================================
# rename_entity tests
# ============================================================================


@pytest.mark.asyncio
async def test_rename_entity_basic(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Basic rename: content updated, old name in aliases."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    result = await rename_entity(
        entity_id=entity.id,
        new_name="Alice Smith",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert result["entity"]["content"] == "Alice Smith"
    assert "Alice" in result["entity"]["aliases"]
    assert result["old_name"] == "Alice"


@pytest.mark.asyncio
async def test_rename_entity_content_hash_recalculated(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Content hash recalculated."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    old_hash = entity.content_hash

    result = await rename_entity(
        entity_id=entity.id,
        new_name="Alice Smith",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    assert result["entity"]["content_hash"] != old_hash


@pytest.mark.asyncio
async def test_rename_entity_empty_name_error(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Empty name raises ValueError."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        await rename_entity(
            entity_id=entity.id,
            new_name="   ",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_same_name_error(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Same name (case-insensitive) raises ValueError."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="same as the current name"):
        await rename_entity(
            entity_id=entity.id,
            new_name="alice",  # Same name, different case
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_not_found(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Entity not found raises ValueError."""
    fake_id = uuid.uuid4()

    with pytest.raises(ValueError, match=f"Entity {fake_id} not found"):
        await rename_entity(
            entity_id=fake_id,
            new_name="New Name",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_already_deleted(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Entity already deleted raises ValueError."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Soft-delete the entity
    node = await async_session.get(MemoryNode, entity.id)
    node.deleted_at = datetime.now(UTC)
    await async_session.commit()

    with pytest.raises(ValueError, match="already deleted"):
        await rename_entity(
            entity_id=entity.id,
            new_name="Alice Smith",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_name_collision(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Name collision with existing entity raises ValueError."""
    await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )
    bob, _ = await find_or_create_entity(
        name="Bob",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-123",
    )

    # Try to rename Bob to Alice
    with pytest.raises(ValueError, match="already exists"):
        await rename_entity(
            entity_id=bob.id,
            new_name="Alice",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_different_tenant(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Different tenant raises ValueError."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant-1",
        owner_id="user-123",
    )

    with pytest.raises(ValueError, match="different tenant"):
        await rename_entity(
            entity_id=entity.id,
            new_name="Alice Smith",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="tenant-2",
            owner_id="user-123",
        )


@pytest.mark.asyncio
async def test_rename_entity_different_owner(
    async_session: AsyncSession,
    embedding_service: EmbeddingService,
) -> None:
    """Different owner raises ValueError."""
    entity, _ = await find_or_create_entity(
        name="Alice",
        entity_type="person",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        owner_id="user-1",
    )

    with pytest.raises(ValueError, match="different owner"):
        await rename_entity(
            entity_id=entity.id,
            new_name="Alice Smith",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
            owner_id="user-2",
        )
