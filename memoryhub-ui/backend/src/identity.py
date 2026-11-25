"""Who the dashboard caller is, and whether they may use MemoryHub.

Three separate decisions are made for every human request
(docs/auth/human-role-resolution.md):

1. Identity: an ``IdentityProvider`` turns the request into a
   ``VerifiedIdentity``.
2. Entitlement: an ``EntitlementResolver`` decides whether that identity
   may use the dashboard, as ``user`` or ``admin``.
3. Data access: ``authorization.Access`` decides per object. It is not
   touched by this module.

A failure in one source is never answered by another: the configured
providers are the only ones consulted.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import HTTPException, Request

from src.config import Settings

logger = logging.getLogger(__name__)

ROLES = ("user", "admin")


@dataclass(frozen=True)
class VerifiedIdentity:
    """A caller whose identity has been established by a trusted source.

    ``username`` is a display name. ``(issuer, subject)`` is the durable key
    of the person at that source.
    """

    username: str
    issuer: str
    subject: str
    display_name: str | None = None


@dataclass(frozen=True)
class Authentication:
    """A verified identity plus the credential that proved it.

    The credential (an OpenShift access token) is needed only for the
    entitlement check. It is excluded from ``repr`` and comparisons so it
    cannot leak into logs or error messages by accident.
    """

    identity: VerifiedIdentity
    credential: str | None = field(default=None, repr=False, compare=False)

    @property
    def credential_digest(self) -> str | None:
        if self.credential is None:
            return None
        return hashlib.sha256(self.credential.encode()).hexdigest()


class IdentityProvider(Protocol):
    async def authenticate(self, request: Request) -> Authentication: ...


class EntitlementResolver(Protocol):
    async def resolve(self, authn: Authentication) -> str:
        """Return ``"admin"`` or ``"user"``; raise 403 or 503 otherwise."""
        ...


def unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="Authenticated user required")


def forbidden() -> HTTPException:
    return HTTPException(status_code=403, detail="Tenant access forbidden")


def single_header(request: Request, name: str, *, max_len: int = 255) -> str:
    """Exactly one, well-formed value of a proxy-set header, or 401."""
    values = request.headers.getlist(name)
    if len(values) != 1:
        raise unauthenticated()
    value = values[0].strip()
    if not value or len(value) > max_len or any(c in value for c in "\r\n\x00"):
        raise unauthenticated()
    return value


def require_loopback_peer(request: Request) -> None:
    """Only the OAuth proxy sidecar, on loopback, may assert identity."""
    peer = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(status_code=401, detail="OAuth proxy required")


class ProxyHeaderIdentity:
    """The username the OpenShift OAuth proxy authenticated (lists mode).

    Trusts ``X-Forwarded-User`` from the loopback sidecar. There is no
    durable subject in this mode, so the username stands in for it.
    """

    issuer = "openshift-oauth-proxy"

    async def authenticate(self, request: Request) -> Authentication:
        require_loopback_peer(request)
        username = single_header(request, "x-forwarded-user")
        return Authentication(VerifiedIdentity(username=username, issuer=self.issuer, subject=username))


class LocalIdentity:
    """Static single-user development identity; request headers are ignored."""

    issuer = "local"

    def __init__(self, username: str):
        self.username = username.strip()

    async def authenticate(self, request: Request) -> Authentication:
        return Authentication(VerifiedIdentity(username=self.username, issuer=self.issuer, subject=self.username))


class ListEntitlements:
    """Transitional role source (#667): two username lists from a Secret."""

    def __init__(self, admins: set[str], users: set[str]):
        self.admins = admins
        self.users = users

    async def resolve(self, authn: Authentication) -> str:
        username = authn.identity.username
        if username in self.admins:
            return "admin"
        if username in self.users:
            return "user"
        logger.warning("Dashboard access denied: %r is not in the human access lists", username)
        raise forbidden()


def identity_provider_for(settings: Settings) -> IdentityProvider:
    if settings.ui_auth_mode == "local":
        return LocalIdentity(settings.ui_local_user)
    return ProxyHeaderIdentity()


def entitlement_resolver_for(settings: Settings) -> EntitlementResolver:
    admins, users = settings.human_access()
    return ListEntitlements(admins, users)
