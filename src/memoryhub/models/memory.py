"""SQLAlchemy ORM model for memory nodes.

Represents the core memory tree structure using an adjacency list pattern
with parent_id for tree relationships and previous_version_id for version chains.
"""

import uuid
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub.models.base import Base, TimestampMixin


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

    # Versioning
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Embedding (384 dims for sentence-transformers/all-MiniLM-L6-v2)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

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

    # -- Table-level indexes --

    __table_args__ = (Index("ix_memory_nodes_owner_scope_current", "owner_id", "scope", "is_current"),)

    def __repr__(self) -> str:
        return (
            f"<MemoryNode id={self.id!s:.8} scope={self.scope} "
            f"weight={self.weight} v{self.version} current={self.is_current}>"
        )
