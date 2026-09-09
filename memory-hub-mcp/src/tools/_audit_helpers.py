"""Audit helpers for MCP tools with DB fallback.

Provides a dual-path audit function that tries PostgreSQL persistence first,
falls back to the stub logger if DB is unavailable.
"""

import uuid

from src.core.audit import record_event as record_event_stub
from memoryhub_core.services.audit import record_event as record_event_db


async def record_audit_event(
    event_type: str,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: uuid.UUID | str | None,
    decision: str,
    tenant_id: str,
    metadata: dict | None = None,
    session=None,
) -> None:
    """Record an audit event with PostgreSQL persistence and stub fallback.

    If a session is provided, writes to audit_log table (fire-and-forget).
    Always writes to the stub logger (memoryhub.audit) for backward compat.

    Args:
        event_type: Dot-separated event kind (e.g., "memory.write")
        actor_id: Authenticated principal
        driver_id: Upstream human/system (on behalf of)
        scope: Memory scope or "session"
        owner_id: Resource owner
        memory_id: UUID of target memory, or None
        decision: "allowed" or "denied"
        tenant_id: Tenant ID for multi-tenancy
        metadata: Optional context dict
        session: SQLAlchemy async session (optional)
    """
    # Try persistent audit if session available
    if session is not None:
        await record_event_db(
            session=session,
            event_type=event_type,
            actor_id=actor_id,
            driver_id=driver_id,
            scope=scope,
            owner_id=owner_id,
            memory_id=memory_id,
            decision=decision,
            tenant_id=tenant_id,
            metadata=metadata,
        )

    # Always call stub for logs (backward compat + local dev)
    record_event_stub(
        event_type=event_type,
        actor_id=actor_id,
        driver_id=driver_id,
        scope=scope,
        owner_id=owner_id,
        memory_id=str(memory_id) if memory_id else None,
        decision=decision,
        metadata=metadata,
    )
