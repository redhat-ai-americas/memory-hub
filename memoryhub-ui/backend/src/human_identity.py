"""Profiles of people admitted to the dashboard (docs/auth/human-role-resolution.md).

A row is written just in time, after identity and entitlement have both
been verified. It records who the person is at their identity source
``(issuer, subject)`` and gives them a durable internal ``user_id`` (the row
id). It never grants a role, a membership or anything else.

Usernames are display names, but ownership (``owner_id``), memberships and
the audit log still store them. So a username that arrives with a
different ``(issuer, subject)`` than the one recorded is refused: a deleted
and recreated account, or a different person given a freed name, must
never inherit the old account's personal memories. An operator resolves
it (docs/ui/human-access.md, "Username reuse").
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, String, UniqueConstraint, func, or_, select
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


def _refused(detail: str) -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


async def profile_for(db: AsyncSession, tenant_id: str, identity: VerifiedIdentity,
                      *, refresh: bool) -> HumanIdentity:
    """The profile of an admitted person; created or refreshed when ``refresh``.

    Refuses (403) a disabled profile and a username that is recorded for a
    different external identity.
    """
    rows = (await db.execute(select(HumanIdentity).where(
        HumanIdentity.tenant_id == tenant_id,
        or_(
            (HumanIdentity.issuer == identity.issuer) & (HumanIdentity.subject == identity.subject),
            HumanIdentity.username == identity.username,
        ),
    ))).scalars().all()
    mine = next((r for r in rows if r.issuer == identity.issuer and r.subject == identity.subject), None)
    other = next((r for r in rows if r is not mine and r.username == identity.username), None)
    if other is not None:
        logger.warning("Dashboard sign-in refused: username %r is recorded for a different account "
                       "(profile %s); an operator must resolve it", identity.username, other.id)
        raise _refused("This username belongs to a different account; ask an administrator")
    if mine is not None and mine.username != identity.username:
        # Ownership is still stored by username: following a rename would
        # cut the person off from their memories and free the old name for
        # someone else, who would then inherit them.
        logger.warning("Dashboard sign-in refused: profile %s changed username %r -> %r; "
                       "an operator must resolve it", mine.id, mine.username, identity.username)
        raise _refused("Your username changed; ask an administrator to update MemoryHub")
    if mine is not None and mine.disabled_at is not None:
        logger.warning("Dashboard sign-in refused: profile %s of %r is disabled", mine.id, identity.username)
        raise _refused("This account is disabled in MemoryHub")
    if mine is None:
        mine = HumanIdentity(id=str(uuid.uuid4()), tenant_id=tenant_id, issuer=identity.issuer,
                             subject=identity.subject, username=identity.username,
                             display_name=identity.display_name)
        db.add(mine)
        logger.info("Dashboard profile created for %r", identity.username)
        await db.commit()
    elif refresh:
        mine.display_name = identity.display_name
        mine.last_seen_at = func.now()
        await db.commit()
    return mine
