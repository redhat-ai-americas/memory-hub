"""SQLAlchemy ORM model for contradiction reports."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub.models.base import Base


class ContradictionReport(Base):
    """A report that observed behavior contradicts a stored memory.

    Agents file these when they notice the user doing something that conflicts
    with a stored preference. The curation engine aggregates them and may
    trigger a revision prompt after enough accumulate.
    """

    __tablename__ = "contradiction_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
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
        server_default=text("false"),
        nullable=False,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Relationship to the contradicted memory
    memory: Mapped["MemoryNode"] = relationship(
        "MemoryNode",
        foreign_keys=[memory_id],
    )

    __table_args__ = (
        Index("ix_contradiction_reports_memory_resolved", "memory_id", "resolved"),
        Index("ix_contradiction_reports_resolved_created", "resolved", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ContradictionReport id={self.id!s:.8} "
            f"memory={self.memory_id!s:.8} resolved={self.resolved}>"
        )
