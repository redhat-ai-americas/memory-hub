"""SQLAlchemy ORM model for role assignments.

Maps users to named roles for scope-based access control. Role-scoped
memories are only visible to users who hold the role stored in
memory_nodes.scope_id.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_core.models.base import Base


class RoleAssignment(Base):
    """Assignment record linking a user to a named role within a tenant."""

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
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
