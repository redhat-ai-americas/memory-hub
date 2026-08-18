"""Audit service for persistent event logging.

Replaces the stub implementation (logger-only) with PostgreSQL persistence.
Audit events are written to the audit_log table with RLS-enforced immutability.

Every MCP tool invocation that touches authorization or data mutation calls
record_event() to emit an audit event. The service is fire-and-forget: audit
failures are logged but never propagate to the caller, ensuring that audit
infrastructure issues never block memory operations.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.audit import AuditLog

logger = logging.getLogger(__name__)


async def record_event(
    session: AsyncSession,
    event_type: str,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: uuid.UUID | str | None,
    decision: str,
    tenant_id: str,
    metadata: dict | None = None,
) -> None:
    """Insert an audit event into the audit_log table.

    Fire-and-forget: exceptions are logged but never propagate to caller.
    The audit event participates in the caller's transaction — if the
    caller's transaction rolls back, the audit event rolls back too.

    Args:
        session: SQLAlchemy async session (shared with the operation being audited)
        event_type: Dot-separated event kind (e.g., "memory.write")
        actor_id: Authenticated principal performing the operation
        driver_id: Upstream human/system on whose behalf the action was taken
        scope: Memory scope (user, project, campaign, ...) or "session"
        owner_id: Owner of the target memory or resource
        memory_id: UUID of the target memory, or None for non-memory ops
        decision: "allowed" or "denied"
        tenant_id: Tenant this event belongs to
        metadata: Optional dict with additional context (query terms, etc.)

    Example:
        await record_event(
            session=session,
            event_type="memory.write",
            actor_id="user-alice",
            driver_id="human-bob",
            scope="project",
            owner_id="project-1",
            memory_id=None,
            decision="allowed",
            tenant_id="default",
            metadata={"project_id": "project-1"},
        )
    """
    try:
        # Normalize memory_id to UUID if it's a string
        if isinstance(memory_id, str):
            memory_id = uuid.UUID(memory_id)

        stmt = insert(AuditLog).values(
            event_type=event_type,
            actor_id=actor_id,
            driver_id=driver_id,
            scope=scope,
            owner_id=owner_id,
            memory_id=memory_id,
            decision=decision,
            event_metadata=metadata,
            tenant_id=tenant_id,
        )
        await session.execute(stmt)
        # NOTE: We do not commit here — the caller manages the transaction.
        # This ensures the audit event participates in the same transaction
        # as the operation being audited. If the operation rolls back, the
        # audit event rolls back too (which is correct — we don't want to
        # record "allowed" if the write ultimately failed).

    except Exception as exc:
        # Fire-and-forget: log the failure but never propagate to caller
        logger.error(
            "Audit insert failed for event_type=%s actor_id=%s: %s",
            event_type,
            actor_id,
            exc,
            exc_info=True,
        )
        # Swallow the exception — audit failures never block operations


def record_event_sync(
    event_type: str,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: uuid.UUID | str | None,
    decision: str,
    metadata: dict | None = None,
) -> None:
    """Synchronous fallback for the stub logger path (deprecated).

    This function is a no-op shim for backward compatibility with the
    stub implementation. New code should use the async record_event()
    with a database session.

    The stub logger path (logger.info(json.dumps(...))) is still available
    for environments where the database is not accessible (e.g., local
    development without PostgreSQL running). This function emits a warning
    and does nothing.

    DEPRECATED: Use async record_event() with a database session instead.
    """
    logger.warning(
        "record_event_sync called for event_type=%s — stub path is deprecated, "
        "use async record_event() with database session",
        event_type,
    )
