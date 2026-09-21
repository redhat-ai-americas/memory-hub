"""Integration tests for procedural content_type (#552) against real PostgreSQL.

SQLite unit tests mirror the CHECK on the ORM. This file proves Alembic 028
actually recreated the constraint on Postgres: inserts with 'procedural'
succeed, unknown values fail, and pg_constraint lists the fourth value.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import ContentType, MemoryNodeCreate, MemoryScope
from memoryhub_core.services.memory import create_memory as _svc_create_memory

pytestmark = pytest.mark.integration

_TEST_TENANT_ID = "default"


@pytest.mark.asyncio
async def test_alembic_check_constraint_lists_procedural(async_session: AsyncSession):
    """Migration 028 must have recreated ck_memory_nodes_content_type with procedural."""
    result = await async_session.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_memory_nodes_content_type'"
        )
    )
    definition = result.scalar_one()
    assert "procedural" in definition
    assert "experiential" in definition
    assert "knowledge" in definition
    assert "behavioral" in definition


@pytest.mark.asyncio
async def test_postgres_accepts_procedural_insert(async_session, embedding_service):
    node, _ = await _svc_create_memory(
        MemoryNodeCreate(
            content="[test] Deploy to staging runbook",
            scope=MemoryScope.USER,
            owner_id="test-user",
            content_type=ContentType.PROCEDURAL,
        ),
        async_session,
        embedding_service,
        tenant_id=_TEST_TENANT_ID,
        skip_curation=True,
    )
    assert node.content_type == "procedural"


@pytest.mark.asyncio
async def test_postgres_check_rejects_unknown_content_type(async_session: AsyncSession):
    now = datetime.now(UTC)
    node_id = uuid.uuid4()
    async_session.add(
        MemoryNode(
            id=node_id,
            logical_id=node_id,
            content="[test] invalid type",
            stub="[test] invalid type",
            scope="user",
            weight=0.7,
            owner_id="test-user",
            tenant_id=_TEST_TENANT_ID,
            is_current=True,
            version=1,
            storage_type="inline",
            content_type="not_a_type",
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        await async_session.commit()
    await async_session.rollback()
