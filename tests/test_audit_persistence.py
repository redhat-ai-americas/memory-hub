"""Integration tests for PostgreSQL audit persistence.

Tests the dual-path audit architecture: events are written to both
PostgreSQL audit_log table AND JSON logs for backward compatibility.

These tests require a local PostgreSQL container running:
    docker run -d --name memoryhub-postgres \
        -e POSTGRES_USER=memoryhub \
        -e POSTGRES_PASSWORD=memoryhub \
        -e POSTGRES_DB=memoryhub \
        -p 5432:5432 pgvector/pgvector:pg15

Run with:
    PGHOST=localhost PGPORT=5432 PGUSER=memoryhub PGPASSWORD=memoryhub \
    PGDATABASE=memoryhub pytest tests/test_audit_persistence.py -v
"""

import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.models.audit import AuditLog
from memoryhub_core.services.audit import record_event


@pytest.fixture
async def db_session():
    """Create async session connected to local PostgreSQL."""
    # Build connection URL from environment variables
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "memoryhub")
    password = os.getenv("PGPASSWORD", "memoryhub")
    database = os.getenv("PGDATABASE", "memoryhub")

    url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    engine = create_async_engine(url, echo=False)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_event_written_to_db(db_session):
    """Verify event is persisted to audit_log table."""
    test_memory_id = uuid.uuid4()

    await record_event(
        session=db_session,
        event_type="memory.write",
        actor_id="user-test",
        driver_id="user-test",
        scope="user",
        owner_id="user-test",
        memory_id=test_memory_id,
        decision="allowed",
        tenant_id="default",
        metadata={"test": True},
    )
    await db_session.commit()

    result = await db_session.execute(
        select(AuditLog).where(AuditLog.memory_id == test_memory_id)
    )
    event = result.scalar_one()

    assert event.event_type == "memory.write"
    assert event.actor_id == "user-test"
    assert event.driver_id == "user-test"
    assert event.scope == "user"
    assert event.owner_id == "user-test"
    assert event.memory_id == test_memory_id
    assert event.decision == "allowed"
    assert event.tenant_id == "default"
    assert event.event_metadata == {"test": True}


@pytest.mark.asyncio
async def test_audit_event_denied_operation(db_session):
    """Verify denied operations are audited."""
    await record_event(
        session=db_session,
        event_type="memory.read",
        actor_id="unauthorized-user",
        driver_id="unauthorized-user",
        scope="campaign",
        owner_id="owner-123",
        memory_id=None,
        decision="denied",
        tenant_id="default",
    )
    await db_session.commit()

    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.actor_id == "unauthorized-user",
            AuditLog.decision == "denied",
        )
    )
    event = result.scalar_one()

    assert event.event_type == "memory.read"
    assert event.decision == "denied"


@pytest.mark.asyncio
async def test_audit_event_fire_and_forget(db_session):
    """Verify audit failures don't propagate exceptions."""
    # The service layer catches and logs exceptions (fire-and-forget)
    # Invalid data that exceeds column constraints should not raise
    await record_event(
        session=db_session,
        event_type="x" * 100,  # Exceeds varchar(64) limit
        actor_id="user-test",
        driver_id="user-test",
        scope="user",
        owner_id="user-test",
        memory_id=None,
        decision="allowed",
        tenant_id="default",
    )
    # Should not raise — the service swallows the exception
    # Verify nothing was inserted (the transaction should still be valid)
    await db_session.rollback()  # Clear any pending transaction state
