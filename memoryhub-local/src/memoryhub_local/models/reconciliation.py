"""SQLAlchemy ORM model for reconciliation decision audit trail.

Dialect-portable version: uses PortableUUID instead of PostgreSQL UUID.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_local.models.base import Base
from memoryhub_local.models.dialect import PortableUUID


class ReconciliationDecision(Base):
    """Records each create/update/skip decision during extraction reconciliation.

    Every candidate produced by the dreaming extraction pipeline gets a row
    here, regardless of outcome. This enables threshold tuning from data
    and provides the surface for extraction-run rollback.
    """

    __tablename__ = "reconciliation_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    extraction_run_id: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_content: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_stub: Mapped[str] = mapped_column(Text, nullable=False)

    nearest_match_id: Mapped[uuid.UUID | None] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    similarity_score: Mapped[float | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    tiebreaker_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content_type_match: Mapped[bool | None] = mapped_column(nullable=True)
    domain_match: Mapped[bool | None] = mapped_column(nullable=True)

    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        PortableUUID(),
        ForeignKey("memory_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_recon_decisions_run", "extraction_run_id"),
        Index("ix_recon_decisions_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ReconciliationDecision id={self.id!s:.8}"
            f" action={self.action} score={self.similarity_score}>"
        )
