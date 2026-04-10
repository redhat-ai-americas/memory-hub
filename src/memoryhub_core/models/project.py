"""SQLAlchemy ORM model for project memberships.

Maps users to projects for scope-based access control. Project-scoped
memories are only visible to users who hold a membership in the memory's
project (stored in memory_nodes.scope_id).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_core.models.base import Base


class ProjectMembership(Base):
    """Enrollment record linking a user to a project."""

    __tablename__ = "project_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'member'"),
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    joined_by: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_member"),
        Index("ix_project_memberships_project", "project_id"),
        Index("ix_project_memberships_user", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectMembership id={self.id!s:.8} "
            f"project_id={self.project_id!r} user_id={self.user_id!r}>"
        )
