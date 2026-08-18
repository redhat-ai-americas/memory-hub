"""SQLAlchemy ORM model for the audit_log table.

Audit events capture every memory operation with actor_id (authenticated
principal) and driver_id (upstream human/system on whose behalf the
operation was taken). Supports compliance recordkeeping and the "who did
what on whose behalf" query pattern.

The table has RLS policies that enforce append-only semantics: events can
be inserted but never updated or deleted (except by DB superuser).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_core.models.base import Base


class AuditLog(Base):
    """Persistent audit event for memory operations.

    Every MCP tool invocation that touches authorization or data mutation
    emits an audit event. Events are append-only: they can be inserted but
    never modified or deleted (enforced via PostgreSQL RLS policies).

    Fields:
        id: Auto-incrementing primary key for sequential ordering
        timestamp: When the event occurred (server-side UTC)
        event_type: Dot-separated event kind (e.g., "memory.write")
        actor_id: Authenticated principal performing the operation
        driver_id: Upstream human/system on whose behalf the action was taken
        scope: Memory scope (user, project, campaign, ...) or "session"
        owner_id: Owner of the target memory or resource
        memory_id: UUID of the target memory, or None for non-memory ops
        decision: "allowed" or "denied"
        metadata: Optional dict with additional context (query terms, etc.)
        tenant_id: Tenant this event belongs to (for multi-tenancy filtering)
    """

    __tablename__ = "audit_log"

    # Primary key: auto-incrementing for chronological ordering
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Timestamp: server-side default ensures consistency
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )

    # Event identification
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Identity fields (actor = authenticated principal, driver = on behalf of)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    driver_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Target resource
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Authorization result
    decision: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )

    # Optional structured metadata (query params, error details, etc.)
    # Note: 'metadata' is reserved in SQLAlchemy, so we use event_metadata as the
    # Python attribute name and map it to the metadata column in the database
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    # Multi-tenancy
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Table-level constraints
    __table_args__ = (
        CheckConstraint(
            "decision IN ('allowed', 'denied')",
            name="ck_audit_decision",
        ),
        # Composite indexes for common query patterns
        Index("ix_audit_log_actor_time", "actor_id", text("timestamp DESC")),
        Index("ix_audit_log_event_type_time", "event_type", text("timestamp DESC")),
        Index("ix_audit_log_decision_time", "decision", text("timestamp DESC")),
        Index("ix_audit_log_tenant_time", "tenant_id", text("timestamp DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, timestamp={self.timestamp}, "
            f"event_type={self.event_type!r}, actor={self.actor_id!r}, "
            f"decision={self.decision!r})>"
        )
