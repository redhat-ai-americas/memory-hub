"""SQLAlchemy ORM models for memory nodes and graph relationships.

Represents the core memory tree structure using an adjacency list pattern
with parent_id for tree relationships and previous_version_id for version chains.
Graph-level relationships (derived_from, supersedes, etc.) are stored in
MemoryRelationship as directed edges between nodes.
"""

import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub_core.models.base import Base, TimestampMixin


class MemoryNode(TimestampMixin, Base):
    """A single node in the memory tree.

    Each node holds a memory (preference, fact, policy, etc.) and can have
    child branches (rationale, provenance, description, etc.). Versioning
    is tracked via is_current and previous_version_id.
    """

    __tablename__ = "memory_nodes"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )

    # Tree structure (adjacency list)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    stub: Mapped[str] = mapped_column(Text, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(10), nullable=False, default="inline")
    content_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Classification
    weight: Mapped[float] = mapped_column(nullable=False, default=0.7)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    branch_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )
    # Scope group identifier for project and role isolation.
    # Holds the project_id for project-scoped memories, role_name for
    # role-scoped memories, NULL for other scopes.
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Crosscutting knowledge domains (e.g., "React", "Spring Boot", "CORS")
    domains: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text),
        nullable=True,
        server_default=text("'{}'::text[]"),
    )

    # Versioning
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # TTL for superseded versions (current versions never expire)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    # Embedding (384 dims for sentence-transformers/all-MiniLM-L6-v2)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

    # Soft-delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    # Extensible metadata
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

    # -- Table-level indexes --

    __table_args__ = (
        Index("ix_memory_nodes_owner_scope_current", "owner_id", "scope", "is_current"),
        Index("ix_memory_nodes_tenant_scope", "tenant_id", "scope"),
        # These indexes are created by migrations 007 and 002 respectively.
        # Declaring them here keeps autogenerate clean — without them, alembic
        # sees the migration-created indexes in the DB but not in the metadata
        # and proposes to drop them on every autogenerate run.
        Index("ix_memory_nodes_deleted_at", "deleted_at"),
        Index("ix_memory_nodes_scope_id", "scope_id"),
        Index("ix_memory_nodes_domains", "domains", postgresql_using="gin"),
        Index(
            "ix_memory_nodes_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryNode id={self.id!s:.8} scope={self.scope} "
            f"weight={self.weight} v{self.version} current={self.is_current}>"
        )


class MemoryRelationship(Base):
    """A directed edge between two memory nodes.

    Relationships are immutable — create or delete, never update. The type
    vocabulary is intentionally constrained (see RelationshipType in schemas).
    Self-referential edges are rejected at the DB level via a CHECK constraint.
    """

    __tablename__ = "memory_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata_",
        JSON,
        server_default=text("'{}'::jsonb"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
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
        UniqueConstraint("source_id", "target_id", "relationship_type", name="uq_memory_relationships_edge"),
        CheckConstraint("source_id != target_id", name="ck_memory_relationships_no_self_ref"),
        Index("ix_memory_relationships_source_type", "source_id", "relationship_type"),
        Index("ix_memory_relationships_target_type", "target_id", "relationship_type"),
        Index("ix_memory_relationships_type", "relationship_type"),
        Index("ix_memory_relationships_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryRelationship id={self.id!s:.8} "
            f"{self.source_id!s:.8} --[{self.relationship_type}]--> {self.target_id!s:.8}>"
        )
