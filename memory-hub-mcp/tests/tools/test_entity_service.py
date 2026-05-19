"""Tests for entity service layer."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.schemas import MemoryNodeRead, RelationshipRead
from memoryhub_core.services.entity import (
    create_mentions_relationship,
    find_entities_by_names,
    find_or_create_entity,
)


@pytest.mark.asyncio
async def test_find_or_create_entity_creates_new():
    """When no existing entity matches, find_or_create_entity creates a new
    MemoryNode with scope='entity', branch_type='entity:<type>', and weight=0.6."""
    session = MagicMock()

    # Mock both exact match and vector similarity queries to return None
    mock_execute_exact = AsyncMock()
    mock_execute_exact.scalar_one_or_none = MagicMock(return_value=None)

    mock_execute_vec = AsyncMock()
    mock_execute_vec.first = MagicMock(return_value=None)

    call_count = 0
    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_execute_exact
        return mock_execute_vec

    session.execute = fake_execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    embedding_service = AsyncMock()
    embedding_service.embed = AsyncMock(return_value=[0.1] * 384)

    # Patch node_to_read since the function calls it at the end
    with patch("memoryhub_core.services.entity.node_to_read") as mock_node_to_read:
        mock_node_to_read.return_value = MagicMock(spec=MemoryNodeRead)

        entity_read, was_created = await find_or_create_entity(
            name="PostgreSQL",
            entity_type="organization",
            session=session,
            embedding_service=embedding_service,
            tenant_id="default",
            owner_id="wjackson",
        )

    assert was_created is True
    assert session.add.called
    added_node = session.add.call_args[0][0]
    assert isinstance(added_node, MemoryNode)
    assert added_node.scope == "entity"
    assert added_node.branch_type == "entity:organization"
    assert added_node.content == "PostgreSQL"
    assert added_node.weight == 0.6
    assert added_node.tenant_id == "default"
    assert added_node.owner_id == "wjackson"


@pytest.mark.asyncio
async def test_find_or_create_entity_rejects_invalid_type():
    """Calling with entity_type not in VALID_ENTITY_TYPES raises ValueError."""
    session = MagicMock()
    embedding_service = AsyncMock()

    with pytest.raises(ValueError, match="Invalid entity_type"):
        await find_or_create_entity(
            name="Test",
            entity_type="invalid",
            session=session,
            embedding_service=embedding_service,
            tenant_id="default",
            owner_id="wjackson",
        )


@pytest.mark.asyncio
async def test_find_or_create_entity_rejects_empty_name():
    """Calling with empty or whitespace-only name raises ValueError."""
    session = MagicMock()
    embedding_service = AsyncMock()

    with pytest.raises(ValueError, match="cannot be empty"):
        await find_or_create_entity(
            name="   ",
            entity_type="person",
            session=session,
            embedding_service=embedding_service,
            tenant_id="default",
            owner_id="wjackson",
        )


@pytest.mark.asyncio
async def test_create_mentions_relationship_idempotent():
    """When an active MENTIONS edge already exists, create_mentions_relationship
    returns it without calling create_relationship."""
    memory_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    # Mock existing relationship
    existing_rel = MagicMock(spec=MemoryRelationship)
    existing_rel.id = uuid.uuid4()
    existing_rel.source_id = memory_id
    existing_rel.target_id = entity_id
    existing_rel.relationship_type = "mentions"
    existing_rel.metadata_ = None
    existing_rel.created_at = datetime.now(UTC)
    existing_rel.created_by = "system"
    existing_rel.tenant_id = "default"
    existing_rel.valid_from = datetime.now(UTC)
    existing_rel.valid_until = None

    session = MagicMock()
    mock_execute_rel = AsyncMock()
    mock_execute_rel.scalar_one_or_none = MagicMock(return_value=existing_rel)

    # Mock stub retrieval
    mock_execute_stub = AsyncMock()
    mock_execute_stub.scalar_one_or_none = MagicMock(return_value="memory stub")

    async def fake_execute(stmt):
        # Return existing relationship for first call, stubs for subsequent calls
        if not hasattr(fake_execute, "call_count"):
            fake_execute.call_count = 0
        fake_execute.call_count += 1
        if fake_execute.call_count == 1:
            return mock_execute_rel
        return mock_execute_stub

    session.execute = fake_execute

    with patch(
        "memoryhub_core.services.entity.create_relationship"
    ) as mock_create:
        result = await create_mentions_relationship(
            memory_id=memory_id,
            entity_id=entity_id,
            session=session,
            tenant_id="default",
        )

    # Should return existing relationship without calling create_relationship
    assert mock_create.call_count == 0
    assert isinstance(result, RelationshipRead)
    assert result.source_id == memory_id
    assert result.target_id == entity_id


@pytest.mark.asyncio
async def test_find_entities_by_names_empty_list():
    """When names is an empty list, find_entities_by_names returns empty
    list without executing any query."""
    session = MagicMock()
    session.execute = AsyncMock()

    result = await find_entities_by_names(
        names=[],
        session=session,
        tenant_id="default",
        owner_id="wjackson",
    )

    assert result == []
    assert session.execute.call_count == 0


@pytest.mark.asyncio
async def test_find_entities_by_names_returns_ids():
    """When matching entities exist, find_entities_by_names returns their IDs."""
    id1 = uuid.uuid4()
    id2 = uuid.uuid4()

    session = MagicMock()
    mock_execute = AsyncMock()
    # Mock result rows as tuples
    mock_execute.all = MagicMock(return_value=[(id1,), (id2,)])
    session.execute = AsyncMock(return_value=mock_execute)

    result = await find_entities_by_names(
        names=["PostgreSQL", "Redis"],
        session=session,
        tenant_id="default",
        owner_id="wjackson",
    )

    assert len(result) == 2
    assert id1 in result
    assert id2 in result
