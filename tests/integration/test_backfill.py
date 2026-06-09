"""Integration tests for the entity extraction backfill script (#250).

These tests use PostgreSQL-specific JSON path operators and must run
against the real PostgreSQL instance from compose.yaml.

Run via: ./scripts/run-integration-tests.sh
"""

import importlib.util
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from memoryhub_core.models.memory import MemoryNode


def _load_backfill():
    """Load the backfill script as a module despite hyphen in filename."""
    spec = importlib.util.spec_from_file_location(
        "backfill_entities",
        "scripts/backfill-entities.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backfill = _load_backfill()


@pytest.mark.asyncio
async def test_count_candidates_finds_unextracted(async_session):
    """Memories without extraction_status are counted as candidates."""
    now = datetime.now(UTC)

    # Create memory with no metadata
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="No metadata memory",
        stub="No metadata...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))

    # Create memory with extraction_status="complete"
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="Completed extraction memory",
        stub="Completed...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        metadata_={"extraction_status": "complete"},
        created_at=now,
        updated_at=now,
    ))

    # Create memory with extraction_status="failed"
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="Failed extraction memory",
        stub="Failed...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        metadata_={"extraction_status": "failed"},
        created_at=now,
        updated_at=now,
    ))

    await async_session.commit()

    # Without include_failed: only the unextracted memory
    count = await backfill.count_candidates(async_session, include_failed=False)
    assert count == 1

    # With include_failed: unextracted + failed
    count = await backfill.count_candidates(async_session, include_failed=True)
    assert count == 2


@pytest.mark.asyncio
async def test_count_candidates_excludes_entities_and_deleted(async_session):
    """Entity-scoped and soft-deleted memories are excluded from candidates."""
    now = datetime.now(UTC)

    # Create entity-scoped memory
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="Entity memory",
        stub="Entity...",
        scope="entity",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        branch_type="entity:person",
        created_at=now,
        updated_at=now,
    ))

    # Create soft-deleted memory
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="Deleted memory",
        stub="Deleted...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        deleted_at=now,
        created_at=now,
        updated_at=now,
    ))

    # Create valid candidate
    async_session.add(MemoryNode(
        id=uuid.uuid4(),
        content="Valid memory",
        stub="Valid...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))

    await async_session.commit()

    count = await backfill.count_candidates(async_session, include_failed=False)
    assert count == 1


@pytest.mark.asyncio
async def test_scan_returns_oldest_first(async_session):
    """Scan returns memories ordered by created_at ascending."""
    base_time = datetime.now(UTC)

    # Create memories with different timestamps
    ids = []
    for i in range(3):
        memory_id = uuid.uuid4()
        ids.append(memory_id)
        async_session.add(MemoryNode(
            id=memory_id,
            content=f"Memory {i}",
            stub=f"Memory {i}...",
            scope="user",
            weight=0.9,
            owner_id="test-user",
            tenant_id="test-tenant",
            is_current=True,
            version=1,
            storage_type="inline",
            created_at=base_time.replace(microsecond=i * 1000),
            updated_at=base_time,
        ))

    await async_session.commit()

    rows = await backfill.scan(async_session, include_failed=False)

    # Should return all 3 in chronological order
    assert len(rows) == 3
    assert rows[0]["id"] == ids[0]
    assert rows[1]["id"] == ids[1]
    assert rows[2]["id"] == ids[2]


@pytest.mark.asyncio
async def test_scan_respects_limit(async_session):
    """Scan respects the limit parameter."""
    now = datetime.now(UTC)

    # Create 5 candidate memories
    for i in range(5):
        async_session.add(MemoryNode(
            id=uuid.uuid4(),
            content=f"Memory {i}",
            stub=f"Memory {i}...",
            scope="user",
            weight=0.9,
            owner_id="test-user",
            tenant_id="test-tenant",
            is_current=True,
            version=1,
            storage_type="inline",
            created_at=now,
            updated_at=now,
        ))

    await async_session.commit()

    # Request only 2 memories
    rows = await backfill.scan(async_session, include_failed=False, limit=2)

    assert len(rows) == 2


@pytest.mark.asyncio
async def test_update_extraction_status_sets_metadata(async_session):
    """update_extraction_status correctly updates metadata."""
    now = datetime.now(UTC)
    memory_id = uuid.uuid4()

    async_session.add(MemoryNode(
        id=memory_id,
        content="Test memory",
        stub="Test...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Update extraction status
    entities = [{"name": "Alice", "type": "person", "confidence": 0.9}]
    await backfill.update_extraction_status(
        async_session,
        memory_id,
        "complete",
        entities,
    )

    # Verify metadata was updated
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await async_session.execute(stmt)
    node = result.scalar_one()

    assert node.metadata_["extraction_status"] == "complete"
    assert node.metadata_["extracted_entities"] == entities


@pytest.mark.asyncio
async def test_update_extraction_status_preserves_existing_metadata(async_session):
    """update_extraction_status preserves other metadata fields."""
    now = datetime.now(UTC)
    memory_id = uuid.uuid4()

    async_session.add(MemoryNode(
        id=memory_id,
        content="Test memory",
        stub="Test...",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id="test-tenant",
        is_current=True,
        version=1,
        storage_type="inline",
        metadata_={"existing_field": "existing_value"},
        created_at=now,
        updated_at=now,
    ))
    await async_session.commit()

    # Update extraction status
    await backfill.update_extraction_status(
        async_session,
        memory_id,
        "complete",
        None,
    )

    # Verify existing metadata was preserved
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await async_session.execute(stmt)
    node = result.scalar_one()

    assert node.metadata_["extraction_status"] == "complete"
    assert node.metadata_["existing_field"] == "existing_value"
