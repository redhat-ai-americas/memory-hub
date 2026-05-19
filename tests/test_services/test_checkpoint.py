"""Tests for checkpoint service."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.checkpoint import read_checkpoint, upsert_checkpoint


@pytest.mark.asyncio
async def test_create_checkpoint(async_session, embedding_service):
    """Creating a new checkpoint stores workflow state with branch_type=checkpoint."""
    workflow_name = "test-workflow"
    state = {"last_run": "2026-05-19", "processed_count": 42}
    tenant_id = "test-tenant"
    user_id = "test-user"

    memory, created = await upsert_checkpoint(
        workflow_name=workflow_name,
        state=state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    assert created is True
    assert memory.content == workflow_name
    assert memory.branch_type == "checkpoint"
    assert memory.metadata == state
    assert memory.weight == 0.3
    assert memory.scope == "user"
    assert memory.owner_id == user_id
    assert memory.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_read_checkpoint(async_session, embedding_service):
    """Reading a checkpoint returns the stored state dictionary."""
    workflow_name = "test-workflow"
    state = {"last_run": "2026-05-19", "processed_count": 42}
    tenant_id = "test-tenant"
    user_id = "test-user"

    await upsert_checkpoint(
        workflow_name=workflow_name,
        state=state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    retrieved = await read_checkpoint(
        workflow_name=workflow_name,
        session=async_session,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    assert retrieved == state


@pytest.mark.asyncio
async def test_read_nonexistent_checkpoint(async_session):
    """Reading a nonexistent checkpoint returns None."""
    tenant_id = "test-tenant"
    user_id = "test-user"

    retrieved = await read_checkpoint(
        workflow_name="nonexistent-workflow",
        session=async_session,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    assert retrieved is None


@pytest.mark.asyncio
async def test_update_checkpoint(async_session, embedding_service):
    """Updating an existing checkpoint modifies metadata in-place."""
    workflow_name = "test-workflow"
    initial_state = {"last_run": "2026-05-19", "processed_count": 42}
    tenant_id = "test-tenant"
    user_id = "test-user"

    memory, created = await upsert_checkpoint(
        workflow_name=workflow_name,
        state=initial_state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )
    assert created is True
    original_id = memory.id

    # Update with new state
    updated_state = {"last_run": "2026-05-20", "processed_count": 100}
    updated_memory, updated_created = await upsert_checkpoint(
        workflow_name=workflow_name,
        state=updated_state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    assert updated_created is False
    assert updated_memory.id == original_id
    assert updated_memory.metadata == updated_state
    assert updated_memory.version == 1  # No new version created


@pytest.mark.asyncio
async def test_update_checkpoint_no_version_chain(async_session, embedding_service):
    """Updating a checkpoint does not create a new version."""
    workflow_name = "test-workflow"
    initial_state = {"count": 1}
    tenant_id = "test-tenant"
    user_id = "test-user"

    memory, _ = await upsert_checkpoint(
        workflow_name=workflow_name,
        state=initial_state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    # Update multiple times
    for i in range(2, 5):
        updated_memory, created = await upsert_checkpoint(
            workflow_name=workflow_name,
            state={"count": i},
            session=async_session,
            embedding_service=embedding_service,
            tenant_id=tenant_id,
            owner_id=user_id,
        )
        assert created is False
        assert updated_memory.version == 1

    # Verify only one node exists
    stmt = select(MemoryNode).where(
        MemoryNode.owner_id == user_id,
        MemoryNode.branch_type == "checkpoint",
        MemoryNode.content == workflow_name,
        MemoryNode.tenant_id == tenant_id,
    )
    result = await async_session.execute(stmt)
    nodes = result.scalars().all()

    assert len(nodes) == 1
    assert nodes[0].metadata_ == {"count": 4}


@pytest.mark.asyncio
async def test_checkpoint_weight(async_session, embedding_service):
    """Checkpoints have weight 0.3 to avoid polluting search results."""
    workflow_name = "test-workflow"
    state = {"data": "value"}
    tenant_id = "test-tenant"
    user_id = "test-user"

    memory, _ = await upsert_checkpoint(
        workflow_name=workflow_name,
        state=state,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id=tenant_id,
        owner_id=user_id,
    )

    assert memory.weight == 0.3
