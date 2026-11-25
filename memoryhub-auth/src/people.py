"""Does a username still belong to the same person? (docs/auth/human-role-resolution.md)

Used on every path that issues a token for a person or for their agent:
broker sign-in, refresh of a person's session, and every token of a
personal agent. Entitlement (``src.entitlements``) answers *may* they use
MemoryHub; this module answers *who* they are.

The person is identified by the OpenShift User ``uid`` (read with the auth
service account) and the shared ``human_identities`` registry, the same one
the dashboard writes. A deleted User, a different uid, a username recorded
for another account, a renamed account or a disabled profile all raise
``IdentityChanged``: the caller revokes the affected sessions.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.entitlements import openshift_user
from src.models import HumanIdentity

log = logging.getLogger("memoryhub-auth.people")


class IdentityChanged(Exception):  # noqa: N818 - an outcome, not a failure of the check
    """The username no longer denotes the person the session was issued to."""

    def __init__(self, username: str, reason: str):
        super().__init__(f"{username}: {reason}")
        self.username = username
        self.reason = reason


async def current_uid(username: str) -> str:
    """The OpenShift uid of ``username`` now; IdentityChanged if the User is gone."""
    user = await openshift_user(username)
    uid = ((user or {}).get("metadata") or {}).get("uid")
    if not uid:
        raise IdentityChanged(username, "OpenShift user no longer exists")
    return uid


async def verify_person(session: AsyncSession, tenant_id: str, username: str, *,
                        expected_uid: str | None, require_profile: bool, create_profile: bool) -> str:
    """Return the person's uid after checking it is still the same person.

    ``expected_uid``: the uid recorded when the session began (None when the
    caller has none). ``require_profile``: a missing registry row is a
    failure (owners of personal agents must have signed in to MemoryHub).
    ``create_profile``: create the row just in time (broker sign-in).
    Raises IdentityChanged; EntitlementUnavailableError propagates.
    """
    uid = await current_uid(username)
    if expected_uid is not None and uid != expected_uid:
        raise IdentityChanged(username, "OpenShift user was recreated (different uid)")
    issuer = settings.verified_issuer()
    rows = (await session.execute(select(HumanIdentity).where(
        HumanIdentity.tenant_id == tenant_id,
        or_(HumanIdentity.username == username,
            and_(HumanIdentity.issuer == issuer, HumanIdentity.subject == uid)),
    ))).scalars().all()
    mine = next((r for r in rows if r.issuer == issuer and r.subject == uid), None)
    other = next((r for r in rows if r is not mine and r.username == username), None)
    if other is not None:
        raise IdentityChanged(username, f"username is recorded for another account (profile {other.id})")
    if mine is not None and mine.username != username:
        raise IdentityChanged(username, f"account was renamed from {mine.username!r}")
    if mine is not None and mine.disabled_at is not None:
        raise IdentityChanged(username, "profile is disabled")
    if mine is None:
        if create_profile:
            session.add(HumanIdentity(id=str(uuid.uuid4()), tenant_id=tenant_id, issuer=issuer,
                                      subject=uid, username=username))
            log.info("Profile created for %r at broker sign-in", username)
        elif require_profile:
            raise IdentityChanged(username, "no verified MemoryHub identity")
    return uid
