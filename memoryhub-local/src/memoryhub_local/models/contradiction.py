"""SQLAlchemy ORM model for contradiction reports.

Dialect-portable version: uses PortableUUID instead of PostgreSQL UUID.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub_local.models.base import Base
from memoryhub_local.models.dialect import PortableUUID

if TYPE_CHECKING:
    from memoryhub_local.models.memory import MemoryNode  # noqa: F401


class ContradictionReport(Base):
    """A report that observed behavior contradicts a stored memory.

    Agents file these when they notice the user doing something that conflicts
    with a stored preference. The curation engine aggregates them and may
    trigger a revision prompt after enough accumulate.
    """

    __tablename__ = "contradiction_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reporter: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    resolution_action: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="default",
    )

    # Relationship to the contradicted memory
    memory: Mapped[MemoryNode] = relationship(
        "MemoryNode",
        foreign_keys=[memory_id],
    )

    __table_args__ = (
        Index("ix_contradiction_reports_memory_resolved", "memory_id", "resolved"),
        Index("ix_contradiction_reports_resolved_created", "resolved", "created_at"),
        Index("ix_contradiction_reports_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ContradictionReport id={self.id!s:.8} "
            f"memory={self.memory_id!s:.8} resolved={self.resolved}>"
        )
