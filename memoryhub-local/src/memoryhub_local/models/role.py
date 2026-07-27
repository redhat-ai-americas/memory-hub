"""SQLAlchemy ORM model for role assignments.

Dialect-portable version: uses PortableUUID instead of PostgreSQL UUID,
plain string defaults instead of text()-wrapped server defaults.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_local.models.base import Base
from memoryhub_local.models.dialect import PortableUUID


class RoleAssignment(Base):
    """Assignment record linking a user to a named role within a tenant."""

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="default",
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    assigned_by: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "role_name", "tenant_id", name="uq_role_assignments_member"),
        Index("ix_role_assignments_user", "user_id"),
        Index("ix_role_assignments_role", "role_name"),
        Index("ix_role_assignments_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<RoleAssignment id={self.id!s:.8} "
            f"user_id={self.user_id!r} role_name={self.role_name!r}>"
        )
