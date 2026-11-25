"""Profiles of people admitted to the dashboard (docs/auth/human-role-resolution.md).

A row is written just in time, after identity and entitlement have both
been verified. It records who the person is at their identity source
``(issuer, subject)`` and gives them a durable internal ``user_id``. It never
grants a role, a membership or anything else.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import Column, DateTime, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from src.identity import VerifiedIdentity

logger = logging.getLogger(__name__)
IdentityBase = declarative_base()


class HumanIdentity(IdentityBase):
    __tablename__ = "human_identities"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String(255), nullable=False)
    issuer = Column(String(512), nullable=False)
    subject = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    disabled_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "issuer", "subject", name="uq_human_identities_subject"),
        UniqueConstraint("tenant_id", "username", name="uq_human_identities_username"),
    )


async def record_profile(db: AsyncSession, tenant_id: str, identity: VerifiedIdentity) -> HumanIdentity:
    """Create or refresh the profile of an admitted person."""
    row = (await db.execute(select(HumanIdentity).where(
        HumanIdentity.tenant_id == tenant_id,
        HumanIdentity.issuer == identity.issuer,
        HumanIdentity.subject == identity.subject,
    ))).scalar_one_or_none()
    if row is None:
        row = HumanIdentity(tenant_id=tenant_id, issuer=identity.issuer, subject=identity.subject,
                            username=identity.username, display_name=identity.display_name)
        db.add(row)
        logger.info("Dashboard profile created for %r", identity.username)
    else:
        row.username = identity.username
        row.display_name = identity.display_name
        row.last_seen_at = func.now()
    await db.commit()
    return row
