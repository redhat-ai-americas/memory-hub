"""SQLAlchemy ORM models for memory nodes and graph relationships.

Dialect-portable version: uses PortableUUID, JsonEncodedVector, and
JsonEncodedList instead of PostgreSQL-specific UUID, Vector, ARRAY, and
TSVECTOR. Full-text search is handled by FTS5 virtual tables (managed
outside the ORM), not by a generated TSVECTOR column.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from memoryhub_local.models.base import Base, TimestampMixin
from memoryhub_local.models.dialect import JsonEncodedList, JsonEncodedVector, PortableUUID


class MemoryNode(TimestampMixin, Base):
    """A single node in the memory tree."""

    __tablename__ = "memory_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    stub: Mapped[str] = mapped_column(Text, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(10), nullable=False, default="inline")
    content_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    weight: Mapped[float] = mapped_column(nullable=False, default=0.7)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    branch_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    driver_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    domains: Mapped[list[str] | None] = mapped_column(
        JsonEncodedList(),
        nullable=True,
    )

    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="experiential")

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active",
    )

    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="agent")

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )
    relevant_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    # Embedding (384 dims for ibm-granite/granite-embedding-30m-english)
    embedding: Mapped[list[float] | None] = mapped_column(
        JsonEncodedVector(), nullable=True,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None,
    )

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    # -- Relationships --

    parent: Mapped[Optional["MemoryNode"]] = relationship(
        "MemoryNode",
        remote_side="MemoryNode.id",
        foreign_keys=[parent_id],
        back_populates="children",
    )
    children: Mapped[list["MemoryNode"]] = relationship(
        "MemoryNode",
        foreign_keys=[parent_id],
        back_populates="parent",
    )
    previous_version: Mapped[Optional["MemoryNode"]] = relationship(
        "MemoryNode",
        remote_side="MemoryNode.id",
        foreign_keys=[previous_version_id],
    )

    outgoing_relationships: Mapped[list["MemoryRelationship"]] = relationship(
        "MemoryRelationship",
        foreign_keys="MemoryRelationship.source_id",
        back_populates="source",
    )
    incoming_relationships: Mapped[list["MemoryRelationship"]] = relationship(
        "MemoryRelationship",
        foreign_keys="MemoryRelationship.target_id",
        back_populates="target",
    )

    __table_args__ = (
        Index("ix_memory_nodes_owner_scope_current", "owner_id", "scope", "is_current"),
        Index("ix_memory_nodes_tenant_scope", "tenant_id", "scope"),
        Index("ix_memory_nodes_deleted_at", "deleted_at"),
        Index("ix_memory_nodes_status", "status"),
        Index("ix_memory_nodes_scope_id", "scope_id"),
        Index("ix_memory_nodes_source", "source"),
        Index("ix_memory_nodes_expires_at", "expires_at"),
        Index("ix_memory_nodes_relevant_until", "relevant_until"),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryNode id={self.id!s:.8} scope={self.scope} "
            f"weight={self.weight} v{self.version} current={self.is_current}>"
        )


class MemoryRelationship(Base):
    """A directed edge between two memory nodes."""

    __tablename__ = "memory_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata_",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source: Mapped["MemoryNode"] = relationship(
        "MemoryNode",
        foreign_keys=[source_id],
        back_populates="outgoing_relationships",
    )
    target: Mapped["MemoryNode"] = relationship(
        "MemoryNode",
        foreign_keys=[target_id],
        back_populates="incoming_relationships",
    )

    __table_args__ = (
        CheckConstraint("source_id != target_id", name="ck_memory_relationships_no_self_ref"),
        Index("ix_memory_relationships_source_type", "source_id", "relationship_type"),
        Index("ix_memory_relationships_target_type", "target_id", "relationship_type"),
        Index("ix_memory_relationships_type", "relationship_type"),
        Index("ix_memory_relationships_tenant", "tenant_id"),
        Index(
            "ix_memory_relationships_source_type_validity",
            "source_id", "relationship_type", "valid_until",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryRelationship id={self.id!s:.8} "
            f"{self.source_id!s:.8} --[{self.relationship_type}]--> {self.target_id!s:.8}>"
        )
