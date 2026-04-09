"""SQLAlchemy ORM models for campaigns and campaign memberships.

Campaigns group projects under a shared governance policy, including a
default TTL that controls how long memories live within participating
projects. CampaignMembership records which projects are enrolled in a
campaign and tracks who enrolled them.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Index, Interval, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from memoryhub_core.models.base import Base, TimestampMixin


class Campaign(TimestampMixin, Base):
    """A named governance campaign that spans one or more projects.

    Campaigns define a shared policy context — most importantly a default TTL
    applied to memories written by projects that are enrolled as members.
    Status flows: active → completed or active → archived.
    """

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'active'"),
    )
    default_ttl: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

    # -- Relationships --

    memberships: Mapped[list["CampaignMembership"]] = relationship(
        "CampaignMembership",
        back_populates="campaign",
    )

    # -- Table-level constraints and indexes --

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),
        Index("ix_campaigns_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<Campaign id={self.id!s:.8} name={self.name!r} status={self.status}>"


class CampaignMembership(Base):
    """Enrollment record linking a project to a campaign.

    A project may belong to at most one enrollment per campaign. The
    enrolled_by field records which agent or user performed the enrollment
    action for auditability.
    """

    __tablename__ = "campaign_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    enrolled_by: Mapped[str] = mapped_column(String(255), nullable=False)

    # -- Relationships --

    campaign: Mapped["Campaign"] = relationship(
        "Campaign",
        back_populates="memberships",
    )

    # -- Table-level constraints and indexes --

    __table_args__ = (
        UniqueConstraint("campaign_id", "project_id", name="uq_campaign_memberships_enrollment"),
        Index("ix_campaign_memberships_campaign", "campaign_id"),
        Index("ix_campaign_memberships_project", "project_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CampaignMembership id={self.id!s:.8} "
            f"campaign_id={self.campaign_id!s:.8} project_id={self.project_id!r}>"
        )
