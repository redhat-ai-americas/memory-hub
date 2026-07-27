"""SQLAlchemy ORM models for projects and project memberships.

Dialect-portable version: uses PortableUUID instead of PostgreSQL UUID,
plain string defaults instead of text()-wrapped server defaults.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_local.models.base import Base
from memoryhub_local.models.dialect import PortableUUID


class Project(Base):
    """Project definition with enrollment policy."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    invite_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="default",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        Index("ix_projects_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<Project name={self.name!r} invite_only={self.invite_only}>"


class ProjectMembership(Base):
    """Enrollment record linking a user to a project."""

    __tablename__ = "project_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("projects.name"), nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="member",
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
