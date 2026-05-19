"""Tests for memory promotion service."""

import uuid

import pytest

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.promotion import promote_memory


@pytest.mark.asyncio
async def test_promote_user_to_project(async_session, embedding_service):
    """Happy path: promote user-scope memory to project scope."""
    # Create source memory at user scope
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="Use React hooks for state management",
        stub="Use React hooks",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.9,
        domains=["React", "JavaScript"],
        content_type="knowledge",
        embedding=[0.1] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Promote to project scope
    promoted = await promote_memory(
        memory_id=source_id,
        target_scope="project",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        promoted_by="bob",
        target_scope_id="frontend-team",
        project_id="frontend-team",
    )

    # Verify promoted memory
    assert promoted.scope == "project"
    assert promoted.scope_id == "frontend-team"
    assert promoted.content == source.content
    assert promoted.weight == source.weight
    assert promoted.domains == source.domains
    assert promoted.content_type == source.content_type
    assert promoted.owner_id == "bob"
    assert promoted.id != source_id

    # Verify metadata tracks promotion
    assert promoted.metadata is not None
    assert "promoted_from" in promoted.metadata
    assert promoted.metadata["promoted_from"]["source_id"] == str(source_id)
    assert promoted.metadata["promoted_from"]["promoted_by"] == "bob"

    # Verify derived_from relationship exists
    from sqlalchemy import select
    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.source_id == promoted.id,
        MemoryRelationship.target_id == source_id,
    )
    result = await async_session.execute(rel_stmt)
    rel = result.scalar_one_or_none()
    assert rel is not None
    assert rel.relationship_type == "derived_from"


@pytest.mark.asyncio
async def test_promote_invalid_direction(async_session, embedding_service):
    """Promotion from project to user scope raises ValueError."""
    # Create source memory at project scope
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="Project-level guideline",
        stub="Project guideline",
        scope="project",
        scope_id="frontend-team",
        owner_id="bob",
        tenant_id="default",
        weight=0.9,
        embedding=[0.1] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Attempt to promote to narrower user scope
    with pytest.raises(ValueError, match="Cannot promote from 'project' to 'user'"):
        await promote_memory(
            memory_id=source_id,
            target_scope="user",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            promoted_by="alice",
        )


@pytest.mark.asyncio
async def test_promote_nonexistent_memory(async_session, embedding_service):
    """Promoting nonexistent memory raises MemoryNotFoundError."""
    fake_id = uuid.uuid4()

    with pytest.raises(MemoryNotFoundError):
        await promote_memory(
            memory_id=fake_id,
            target_scope="project",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            promoted_by="alice",
        )


@pytest.mark.asyncio
async def test_promote_preserves_content(async_session, embedding_service):
    """Promoted memory has identical content, weight, and domains."""
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="Detailed multi-line content\nwith formatting\nand structure",
        stub="Detailed content",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.85,
        domains=["Python", "Testing", "Best Practices"],
        embedding=[0.2] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    promoted = await promote_memory(
        memory_id=source_id,
        target_scope="organizational",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        promoted_by="charlie",
    )

    assert promoted.content == source.content
    assert promoted.weight == source.weight
    assert promoted.domains == source.domains
    assert promoted.scope == "organizational"


@pytest.mark.asyncio
async def test_promote_sets_metadata(async_session, embedding_service):
    """promoted_from metadata is populated with source details."""
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="Source memory",
        stub="Source",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.7,
        embedding=[0.3] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    promoted = await promote_memory(
        memory_id=source_id,
        target_scope="enterprise",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        promoted_by="dave",
    )

    assert promoted.metadata is not None
    promoted_from = promoted.metadata.get("promoted_from")
    assert promoted_from is not None
    assert promoted_from["source_id"] == str(source_id)
    assert promoted_from["promoted_by"] == "dave"
    assert "promoted_at" in promoted_from


@pytest.mark.asyncio
async def test_promote_user_to_organizational(async_session, embedding_service):
    """Promotion can skip intermediate scopes (user -> organizational)."""
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="Best practice",
        stub="Best practice",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.9,
        embedding=[0.4] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    promoted = await promote_memory(
        memory_id=source_id,
        target_scope="organizational",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        promoted_by="eve",
    )

    assert promoted.scope == "organizational"
    assert promoted.content == source.content


@pytest.mark.asyncio
async def test_promote_same_scope_raises(async_session, embedding_service):
    """Promoting to the same scope raises ValueError."""
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        content="User memory",
        stub="User memory",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.7,
        embedding=[0.5] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    with pytest.raises(ValueError, match="Cannot promote from 'user' to 'user'"):
        await promote_memory(
            memory_id=source_id,
            target_scope="user",
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            promoted_by="alice",
        )
