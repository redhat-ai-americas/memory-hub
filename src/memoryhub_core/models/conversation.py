"""SQLAlchemy ORM models for conversation threads, messages, and extraction provenance."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub_core.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from memoryhub_core.models.memory import MemoryNode


class ConversationThread(TimestampMixin, Base):
    """A conversation thread with scope-based access control.

    Represents a logical conversation thread with messages, participants,
    and lifecycle management (active, archived, deleted). Threads can be
    scoped to user, project, organizational, or enterprise contexts.
    """

    __tablename__ = "conversation_threads"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Metadata
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    a2a_context_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scope and ownership
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    driver_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

    # Participants
    participant_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    participant_access: Mapped[dict | None] = mapped_column(
        "participant_access",
        JSON,
        nullable=True,
    )

    # Lifecycle
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Extraction cursor
    last_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Extensible metadata
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # -- Relationships --
    messages: Mapped[list[ConversationMessage]] = relationship(
        "ConversationMessage",
        back_populates="thread",
    )
    extractions: Mapped[list[ConversationExtraction]] = relationship(
        "ConversationExtraction",
        back_populates="thread",
    )
    failures: Mapped[list[ConversationExtractionFailure]] = relationship(
        "ConversationExtractionFailure",
        back_populates="thread",
    )

    # -- Table-level indexes and constraints --
    __table_args__ = (
        Index("ix_conv_threads_owner_scope", "owner_id", "scope"),
        Index("ix_conv_threads_tenant_scope", "tenant_id", "scope"),
        Index("ix_conv_threads_scope_id", "scope_id", postgresql_where=text("scope_id IS NOT NULL")),
        Index("ix_conv_threads_a2a_context_id", "a2a_context_id", postgresql_where=text("a2a_context_id IS NOT NULL")),
        Index("ix_conv_threads_status", "status"),
        Index("ix_conv_threads_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
        Index("ix_conv_threads_expires_at", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
        CheckConstraint(
            "participant_access IS NULL OR jsonb_typeof(participant_access) = 'object'",
            name="ck_participant_access_object",
        ),
    )

    def __repr__(self) -> str:
        return f"<ConversationThread id={self.id!s:.8} scope={self.scope} status={self.status}>"


class ConversationMessage(Base):
    """A single message in a conversation thread.

    Messages are append-only and immutable after creation. Large message
    content can be offloaded to S3 via storage_type='s3'.
    """

    __tablename__ = "conversation_messages"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Thread reference
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Ordering and attribution
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Content storage
    storage_type: Mapped[str] = mapped_column(String(10), nullable=False, default="inline")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Tool call tracking
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Handoff metadata
    handoff_from_agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handoff_authorized_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handoff_redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Tenant
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

    # Extensible metadata
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # Timestamp (append-only, no updated_at)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -- Relationships --
    thread: Mapped[ConversationThread] = relationship(
        "ConversationThread",
        back_populates="messages",
    )

    # -- Table-level indexes and constraints --
    __table_args__ = (
        Index("uq_conv_messages_thread_seq", "thread_id", "sequence_number", unique=True),
        Index("ix_conv_messages_thread_id", "thread_id"),
        Index("ix_conv_messages_tenant_id", "tenant_id"),
        Index("ix_conv_messages_actor_id", "actor_id", postgresql_where=text("actor_id IS NOT NULL")),
        Index("ix_conv_messages_tool_call_id", "tool_call_id", postgresql_where=text("tool_call_id IS NOT NULL")),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationMessage id={self.id!s:.8} thread={self.thread_id!s:.8}"
            f" seq={self.sequence_number} role={self.role}>"
        )


class ConversationExtraction(Base):
    """Links a memory node to the conversation messages it was extracted from.

    Provides provenance and reproducibility for entity extraction. The
    thread FK is RESTRICT to preserve audit trail even after conversation
    deletion.
    """

    __tablename__ = "conversation_extractions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Foreign keys
    memory_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_threads.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Provenance
    source_messages: Mapped[list[int]] = mapped_column(
        ARRAY(sa.Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    )
    extracted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    extraction_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extraction_prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Tenant
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -- Relationships --
    thread: Mapped[ConversationThread] = relationship(
        "ConversationThread",
        back_populates="extractions",
    )
    memory_node: Mapped[MemoryNode] = relationship("MemoryNode")

    # -- Table-level indexes --
    __table_args__ = (
        Index("ix_conv_extractions_memory_node", "memory_node_id"),
        Index("ix_conv_extractions_thread_id", "thread_id"),
        Index("ix_conv_extractions_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationExtraction id={self.id!s:.8}"
            f" thread={self.thread_id!s:.8} memory={self.memory_node_id!s:.8}>"
        )


class ConversationExtractionFailure(Base):
    """Records extraction failures for conversation windows.

    When extraction fails for a window of messages, the failure is recorded
    here for retry and monitoring. After successful retry, the failure is
    marked as resolved.
    """

    __tablename__ = "conversation_extraction_failures"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Thread reference
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_threads.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Failed window (sequence_numbers)
    window_start: Mapped[int] = mapped_column(Integer, nullable=False)
    window_end: Mapped[int] = mapped_column(Integer, nullable=False)

    # Retry metadata
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_error: Mapped[str] = mapped_column(Text, nullable=False)
    last_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Tenant
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # -- Relationships --
    thread: Mapped[ConversationThread] = relationship(
        "ConversationThread",
        back_populates="failures",
    )

    # -- Table-level indexes --
    __table_args__ = (
        Index("ix_conv_extraction_failures_thread_id", "thread_id"),
        Index("ix_conv_extraction_failures_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationExtractionFailure id={self.id!s:.8}"
            f" thread={self.thread_id!s:.8} window={self.window_start}-{self.window_end}"
            f" attempts={self.attempt_count} resolved={self.resolved}>"
        )


class PurgeLog(Base):
    """Audit log for purged conversations and messages.

    Records metadata about deleted resources for compliance and debugging.
    The resource_id is not a FK to allow logging after the resource is deleted.
    """

    __tablename__ = "purge_log"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Resource identification
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Purge metadata
    purged_by: Mapped[str] = mapped_column(String(255), nullable=False)
    purged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    incident_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PurgeLog id={self.id!s:.8} type={self.resource_type}"
            f" resource={self.resource_id!s:.8} reason={self.reason}>"
        )
