"""May this person use MemoryHub? The same OpenShift RBAC check as the dashboard.

docs/auth/human-role-resolution.md. A person may use MemoryHub when OpenShift
RBAC allows the ``use`` verb on ``memoryhub.io/dashboard`` in the dashboard
namespace (``AUTH_ENTITLEMENT_NAMESPACE``). Two ways to ask:

* ``person_may_use(token)``: at sign-in, with the person's own OpenShift
  token (``SelfSubjectAccessReview``, scope ``user:check-access``).
* ``subject_may_use(username)``: later, without their token (refresh,
  owned agents). The auth service resolves the person's OpenShift Groups and
  asks a ``SubjectAccessReview`` for the user and those groups.

Neither ever answers "yes" when OpenShift cannot be asked:
``EntitlementUnavailableError`` is raised instead.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import httpx

from src.config import settings

log = logging.getLogger("memoryhub-auth.entitlements")

# Groups every authenticated OAuth user carries; a SubjectAccessReview does
# not add them by itself.
IMPLICIT_GROUPS = ["system:authenticated", "system:authenticated:oauth"]


class EntitlementUnavailableError(Exception):
    """OpenShift could not be asked; never treat this as an answer."""


def enabled() -> bool:
    return settings.entitlement_mode == "openshift-rbac"


def decode_group_member(entry: str) -> str:
    """Decode an OpenShift group member entry.

    OpenShift encodes usernames containing ':' with a ``b64:`` prefix in the
    Group ``.users`` list (``b64:a3ViZTphZG1pbg==`` is ``kube:admin``).
    """
    if entry.startswith("b64:"):
        try:
            return base64.b64decode(entry[4:]).decode("utf-8")
        except Exception:
            return entry
    return entry


def _verify() -> bool | str:
    ca = settings.k8s_ca_path
    return ca if ca and os.path.isfile(ca) else True


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=_verify(), timeout=10.0)


def _sa_token() -> str:
    try:
        return Path(settings.k8s_token_path).read_text().strip()
    except OSError as exc:
        raise EntitlementUnavailableError("service account token is not readable") from exc


def _attributes(verb: str = "use") -> dict:
    return {"namespace": settings.entitlement_namespace, "group": "memoryhub.io",
            "resource": "dashboard", "verb": verb}


async def _call(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"{settings.k8s_api_server.rstrip('/')}{path}"
    try:
        async with _http() as client:
            resp = await client.request(method, url, json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        log.error("Entitlement check %s %s failed: %s", method, path, type(exc).__name__)
        raise EntitlementUnavailableError(type(exc).__name__) from exc
    if resp.status_code not in (200, 201):
        log.error("Entitlement check %s %s answered %d", method, path, resp.status_code)
        raise EntitlementUnavailableError(f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise EntitlementUnavailableError("invalid JSON") from exc


async def person_may_use(opaque_token: str) -> bool:
    """SelfSubjectAccessReview with the person's own (never stored) token."""
    data = await _call("POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", opaque_token, {
        "apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
        "spec": {"resourceAttributes": _attributes()},
    })
    return bool(data.get("status", {}).get("allowed"))


async def groups_of(username: str) -> list[str]:
    data = await _call("GET", "/apis/user.openshift.io/v1/groups", _sa_token())
    return sorted(
        item["metadata"]["name"]
        for item in data.get("items") or []
        if any(decode_group_member(member) == username for member in item.get("users") or [])
    )


async def subject_may_use(username: str) -> bool:
    """SubjectAccessReview by the auth service account for the person and their groups."""
    if not username or username.startswith("system:"):
        return False
    groups = await groups_of(username) + IMPLICIT_GROUPS
    data = await _call("POST", "/apis/authorization.k8s.io/v1/subjectaccessreviews", _sa_token(), {
        "apiVersion": "authorization.k8s.io/v1", "kind": "SubjectAccessReview",
        "spec": {"user": username, "groups": groups, "resourceAttributes": _attributes()},
    })
    allowed = bool(data.get("status", {}).get("allowed"))
    if not allowed:
        log.info("Entitlement denied for %r", username)
    return allowed
