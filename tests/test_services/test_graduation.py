"""Tests for memory graduation service."""

import uuid

import pytest
from sqlalchemy import select

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graduation import graduate_memory


@pytest.mark.asyncio
async def test_graduate_happy_path(async_session, embedding_service):
    """Happy path: graduate experiential memory to knowledge status."""
    # Create source experiential memory
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="Users often forget to close database connections after queries",
        stub="DB connection leak",
        scope="user",
        owner_id="alice",
        tenant_id="default",
        weight=0.85,
        domains=["Python", "Database"],
        content_type="experiential",
        embedding=[0.1] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Graduate to knowledge
    graduated = await graduate_memory(
        memory_id=source_id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        graduated_by="bob",
    )

    # Verify graduated memory has correct content_type
    assert graduated.content_type == "knowledge"

    # Verify same content, weight, scope, domains as source
    assert graduated.content == source.content
    assert graduated.weight == source.weight
    assert graduated.scope == source.scope
    assert graduated.domains == source.domains

    # Verify owner_id is from source, NOT graduated_by
    assert graduated.owner_id == source.owner_id
    assert graduated.owner_id == "alice"

    # Verify metadata contains graduation info
    assert graduated.metadata is not None
    assert "graduation" in graduated.metadata
    grad_meta = graduated.metadata["graduation"]
    assert grad_meta["source_id"] == str(source_id)
    assert grad_meta["graduated_by"] == "bob"
    assert "graduated_at" in grad_meta

    # Verify original memory unchanged
    await async_session.refresh(source)
    assert source.content_type == "experiential"
    assert source.is_current is True


@pytest.mark.asyncio
async def test_graduate_with_evidence(async_session, embedding_service):
    """Graduate with evidence text creates evidence branch."""
    # Create source experiential memory
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="API calls often fail during peak hours",
        stub="API peak failures",
        scope="project",
        scope_id="backend-team",
        owner_id="charlie",
        tenant_id="default",
        weight=0.9,
        domains=["API", "Performance"],
        content_type="experiential",
        embedding=[0.2] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Graduate with evidence
    evidence_text = "Logs from 2026-05-15 show 47% failure rate during 9-11am window"
    graduated = await graduate_memory(
        memory_id=source_id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        graduated_by="dave",
        evidence=evidence_text,
    )

    # Find evidence branch
    stmt = select(MemoryNode).where(
        MemoryNode.parent_id == graduated.id,
        MemoryNode.branch_type == "evidence",
    )
    result = await async_session.execute(stmt)
    evidence_node = result.scalar_one_or_none()

    # Verify evidence branch exists
    assert evidence_node is not None
    assert evidence_node.content == evidence_text
    assert evidence_node.branch_type == "evidence"
    assert evidence_node.content_type == "knowledge"
    assert evidence_node.parent_id == graduated.id


@pytest.mark.asyncio
async def test_graduate_with_reviewer_note(async_session, embedding_service):
    """Graduate with reviewer_note includes it in metadata."""
    # Create source experiential memory
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="Memory leaks in background workers",
        stub="Memory leak",
        scope="user",
        owner_id="eve",
        tenant_id="default",
        weight=0.8,
        content_type="experiential",
        embedding=[0.3] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Graduate with reviewer note
    note = "Confirmed across multiple environments"
    graduated = await graduate_memory(
        memory_id=source_id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        graduated_by="frank",
        reviewer_note=note,
    )

    # Verify reviewer_note in metadata
    assert graduated.metadata is not None
    assert "graduation" in graduated.metadata
    assert graduated.metadata["graduation"]["reviewer_note"] == note


@pytest.mark.asyncio
async def test_graduate_creates_derived_from(async_session, embedding_service):
    """Verify derived_from relationship is created."""
    # Create source experiential memory
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="CSS specificity issues with third-party styles",
        stub="CSS specificity",
        scope="user",
        owner_id="grace",
        tenant_id="default",
        weight=0.75,
        content_type="experiential",
        embedding=[0.4] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Graduate
    graduated = await graduate_memory(
        memory_id=source_id,
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="default",
        graduated_by="henry",
    )

    # Verify derived_from relationship
    rel_stmt = select(MemoryRelationship).where(
        MemoryRelationship.source_id == graduated.id,
        MemoryRelationship.target_id == source_id,
    )
    result = await async_session.execute(rel_stmt)
    rel = result.scalar_one_or_none()

    assert rel is not None
    assert rel.relationship_type == "derived_from"
    assert rel.created_by == "henry"


@pytest.mark.asyncio
async def test_graduate_rejects_knowledge(async_session, embedding_service):
    """Trying to graduate a knowledge memory raises ValueError."""
    # Create knowledge memory (not experiential)
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="Knowledge memories cannot be graduated",
        stub="Knowledge",
        scope="user",
        owner_id="iris",
        tenant_id="default",
        weight=0.7,
        content_type="knowledge",
        embedding=[0.5] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Attempt to graduate
    with pytest.raises(
        ValueError,
        match="Cannot graduate memory with content_type 'knowledge'. Only experiential memories can be graduated",
    ):
        await graduate_memory(
            memory_id=source_id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            graduated_by="jack",
        )


@pytest.mark.asyncio
async def test_graduate_rejects_behavioral(async_session, embedding_service):
    """Trying to graduate a behavioral memory raises ValueError."""
    # Create behavioral memory (not experiential)
    source_id = uuid.uuid4()
    source = MemoryNode(
        id=source_id,
        logical_id=source_id,
        content="Behavioral memories cannot be graduated",
        stub="Behavioral",
        scope="user",
        owner_id="kate",
        tenant_id="default",
        weight=0.6,
        content_type="behavioral",
        embedding=[0.6] * 384,
        is_current=True,
        version=1,
    )
    async_session.add(source)
    await async_session.flush()

    # Attempt to graduate
    with pytest.raises(
        ValueError,
        match="Cannot graduate memory with content_type 'behavioral'. Only experiential memories can be graduated",
    ):
        await graduate_memory(
            memory_id=source_id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            graduated_by="leo",
        )


@pytest.mark.asyncio
async def test_graduate_nonexistent_memory(async_session, embedding_service):
    """Graduating nonexistent memory raises MemoryNotFoundError."""
    fake_id = uuid.uuid4()

    with pytest.raises(MemoryNotFoundError):
        await graduate_memory(
            memory_id=fake_id,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="default",
            graduated_by="mike",
        )
