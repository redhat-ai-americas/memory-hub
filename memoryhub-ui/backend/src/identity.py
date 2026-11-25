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
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import HTTPException, Request

from src.config import Settings
from src.kube import KubeClient, KubeUnauthenticated, KubeUnavailable

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
    # True when the identity was just verified against its source rather
    # than taken from a cached decision; used to refresh the profile.
    fresh: bool = field(default=False, compare=False)

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


def unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Access cannot be verified right now; try again shortly")


@dataclass
class _Decision:
    identity: VerifiedIdentity
    role: str | None  # None: verified identity, no entitlement
    expires_at: float


@dataclass
class _Review:
    uid: str | None
    groups: list[str]


class OpenShiftRbac:
    """Identity from the person's OpenShift token, role from OpenShift RBAC.

    Identity: the proxy forwards the token (``--pass-access-token``); the
    BFF reads ``users/~`` with it (``self``) or reviews it with its service
    account (``delegated``) and requires the name to match
    ``X-Forwarded-User``.

    Entitlement: ``admin`` allowed on ``memoryhub.io/dashboard`` in the
    dashboard namespace → Admin; else ``use`` allowed → User; else 403.

    Decisions are cached per token digest, tenant and namespace. An expired
    decision is never extended when the API cannot be reached.
    """

    MAX_ENTRIES = 1024

    def __init__(self, settings: Settings, kube: KubeClient | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.mode = settings.ui_rbac_check
        self.namespace = settings.rbac_namespace()
        self.tenant = settings.ui_tenant_id
        self.issuer = settings.identity_issuer()
        self.allow_ttl = settings.ui_rbac_cache_ttl
        self.deny_ttl = settings.ui_rbac_deny_ttl
        self.kube = kube or KubeClient(settings.kube_api_url, settings.kube_ca_path, settings.kube_token_path)
        self.clock = clock
        self._decisions: OrderedDict[tuple[str, str, str], _Decision] = OrderedDict()
        self._reviews: dict[str, _Review] = {}

    def _key(self, digest: str) -> tuple[str, str, str]:
        return (digest, self.tenant, self.namespace)

    def _cached(self, digest: str) -> _Decision | None:
        key = self._key(digest)
        decision = self._decisions.get(key)
        if decision is None:
            return None
        if decision.expires_at <= self.clock():
            del self._decisions[key]
            return None
        self._decisions.move_to_end(key)
        return decision

    def _remember(self, digest: str, decision: _Decision) -> None:
        key = self._key(digest)
        self._decisions[key] = decision
        self._decisions.move_to_end(key)
        while len(self._decisions) > self.MAX_ENTRIES:
            self._decisions.popitem(last=False)

    async def authenticate(self, request: Request) -> Authentication:
        require_loopback_peer(request)
        username = single_header(request, "x-forwarded-user")
        token = single_header(request, "x-forwarded-access-token", max_len=8192)
        digest = hashlib.sha256(token.encode()).hexdigest()
        cached = self._cached(digest)
        if cached is not None:
            if cached.identity.username != username:
                logger.warning("Dashboard identity mismatch: proxy user does not own the forwarded token")
                raise unauthenticated()
            return Authentication(cached.identity, credential=token)
        identity = await self._verify(token, digest, username)
        return Authentication(identity, credential=token, fresh=True)

    async def _verify(self, token: str, digest: str, username: str) -> VerifiedIdentity:
        try:
            if self.mode == "delegated":
                user = await self.kube.token_review(token)
                name, uid = user.get("username") or "", user.get("uid")
                self._reviews[digest] = _Review(uid=uid, groups=list(user.get("groups") or []))
                display = None
            else:
                user = await self.kube.current_user(token)
                meta = user.get("metadata") or {}
                name, uid = meta.get("name") or "", meta.get("uid")
                display = user.get("fullName") or None
        except KubeUnauthenticated:
            raise unauthenticated() from None
        except KubeUnavailable:
            raise unavailable() from None
        if not name or name != username:
            logger.warning("Dashboard identity mismatch: proxy user does not own the forwarded token")
            raise unauthenticated()
        if not uid:
            logger.error("OpenShift returned no uid for %r; refusing an identity without a durable key", name)
            raise unavailable()
        return VerifiedIdentity(username=name, issuer=self.issuer, subject=uid, display_name=display)

    async def _allowed(self, authn: Authentication, verb: str) -> bool:
        if self.mode == "delegated":
            review = self._reviews.get(authn.credential_digest or "")
            if review is None:
                # The cached identity expired between authenticate and resolve.
                user = await self.kube.token_review(authn.credential or "")
                if user.get("username") != authn.identity.username:
                    raise KubeUnauthenticated()
                review = _Review(uid=user.get("uid"), groups=list(user.get("groups") or []))
            return await self.kube.access_review(authn.identity.username, review.uid, review.groups,
                                                 self.namespace, verb)
        return await self.kube.self_access(authn.credential or "", self.namespace, verb)

    async def resolve(self, authn: Authentication) -> str:
        digest = authn.credential_digest
        if digest is None:
            raise unauthenticated()
        cached = self._cached(digest)
        if cached is None or authn.fresh:
            try:
                if await self._allowed(authn, "admin"):
                    role = "admin"
                elif await self._allowed(authn, "use"):
                    role = "user"
                else:
                    role = None
            except KubeUnauthenticated:
                raise unauthenticated() from None
            except KubeUnavailable:
                raise unavailable() from None
            finally:
                self._reviews.pop(digest, None)
            ttl = self.allow_ttl if role else self.deny_ttl
            cached = _Decision(authn.identity, role, self.clock() + ttl)
            self._remember(digest, cached)
            logger.info("Dashboard entitlement: %r -> %s", authn.identity.username, role or "denied")
        if cached.role is None:
            raise forbidden()
        return cached.role


_RBAC_ADAPTERS: dict[tuple, OpenShiftRbac] = {}


def rbac_adapter_for(settings: Settings) -> OpenShiftRbac:
    """One adapter per configuration, so its decision cache outlives a request."""
    key = (settings.ui_rbac_check, settings.rbac_namespace(), settings.ui_tenant_id, settings.identity_issuer(),
           settings.ui_rbac_cache_ttl, settings.ui_rbac_deny_ttl, settings.kube_api_url,
           settings.kube_ca_path, settings.kube_token_path)
    adapter = _RBAC_ADAPTERS.get(key)
    if adapter is None:
        adapter = _RBAC_ADAPTERS[key] = OpenShiftRbac(settings)
    return adapter


def identity_provider_for(settings: Settings) -> IdentityProvider:
    if settings.ui_role_source == "openshift-rbac":
        return rbac_adapter_for(settings)
    if settings.ui_auth_mode == "local":
        return LocalIdentity(settings.ui_local_user)
    return ProxyHeaderIdentity()


def entitlement_resolver_for(settings: Settings) -> EntitlementResolver:
    if settings.ui_role_source == "openshift-rbac":
        return rbac_adapter_for(settings)
    admins, users = settings.human_access()
    return ListEntitlements(admins, users)
