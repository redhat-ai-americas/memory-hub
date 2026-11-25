"""Minimal Kubernetes API client for identity and access reviews.

Only the calls the dashboard needs: read the caller's own OpenShift user,
review their access (self or delegated), and list RoleBindings in the
dashboard namespace. Tokens are passed per call and never logged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DASHBOARD_GROUP = "memoryhub.io"
DASHBOARD_RESOURCE = "dashboard"


class KubeUnavailable(Exception):
    """The API could not answer: network error, timeout, 5xx, throttling or misconfiguration."""


class KubeUnauthenticated(Exception):
    """The API does not accept the presented token."""


class KubeClient:
    def __init__(self, api_url: str, ca_path: str, token_path: str, *,
                 timeout: float = 5.0, transport: httpx.AsyncBaseTransport | None = None):
        self.api_url = api_url.rstrip("/")
        self.ca_path = ca_path
        self.token_path = token_path
        self.timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _verify(self) -> bool | str:
        return self.ca_path if self.ca_path and os.path.isfile(self.ca_path) else True

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if self._transport is not None:
                self._client = httpx.AsyncClient(transport=self._transport, timeout=self.timeout)
            else:
                self._client = httpx.AsyncClient(verify=self._verify(), timeout=self.timeout)
        return self._client

    def service_account_token(self) -> str:
        """Read on every use: projected service account tokens rotate."""
        try:
            return Path(self.token_path).read_text().strip()
        except OSError as exc:
            raise KubeUnavailable("service account token is not readable") from exc

    async def _request(self, method: str, path: str, token: str, body: dict | None = None) -> dict:
        try:
            response = await self._http().request(
                method, f"{self.api_url}{path}", json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            logger.error("Kubernetes API %s %s failed: %s", method, path, type(exc).__name__)
            raise KubeUnavailable(type(exc).__name__) from exc
        if response.status_code == 401:
            raise KubeUnauthenticated()
        if response.status_code not in (200, 201):
            # 403 here means our own request was not allowed (scope or RBAC of
            # the caller); like 5xx and 429 it is not an answer about the person.
            logger.error("Kubernetes API %s %s answered %d", method, path, response.status_code)
            raise KubeUnavailable(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise KubeUnavailable("invalid JSON") from exc

    @staticmethod
    def _attributes(namespace: str, verb: str) -> dict:
        return {"namespace": namespace, "group": DASHBOARD_GROUP, "resource": DASHBOARD_RESOURCE, "verb": verb}

    async def current_user(self, token: str) -> dict:
        """The OpenShift User behind ``token`` (needs scope user:info)."""
        return await self._request("GET", "/apis/user.openshift.io/v1/users/~", token)

    async def self_access(self, token: str, namespace: str, verb: str) -> bool:
        """SelfSubjectAccessReview with the person's own token (scope user:check-access)."""
        data = await self._request("POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", token, {
            "apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
            "spec": {"resourceAttributes": self._attributes(namespace, verb)},
        })
        return bool(data.get("status", {}).get("allowed"))

    async def token_review(self, token: str) -> dict:
        """TokenReview by our service account; returns the authenticated user."""
        data = await self._request("POST", "/apis/authentication.k8s.io/v1/tokenreviews",
                                   self.service_account_token(), {
                                       "apiVersion": "authentication.k8s.io/v1", "kind": "TokenReview",
                                       "spec": {"token": token},
                                   })
        status = data.get("status", {})
        if not status.get("authenticated"):
            raise KubeUnauthenticated()
        return status.get("user") or {}

    async def access_review(self, user: str, uid: str | None, groups: list[str],
                            namespace: str, verb: str) -> bool:
        """SubjectAccessReview by our service account for an explicit user and groups.

        Token scopes are deliberately not passed: the question is what the
        person may do, not what one narrowly scoped token may do.
        """
        spec: dict = {"user": user, "groups": groups, "resourceAttributes": self._attributes(namespace, verb)}
        if uid:
            spec["uid"] = uid
        data = await self._request("POST", "/apis/authorization.k8s.io/v1/subjectaccessreviews",
                                   self.service_account_token(), {
                                       "apiVersion": "authorization.k8s.io/v1", "kind": "SubjectAccessReview",
                                       "spec": spec,
                                   })
        return bool(data.get("status", {}).get("allowed"))

    async def role_bindings(self, namespace: str) -> list[dict]:
        data = await self._request(
            "GET", f"/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings",
            self.service_account_token(),
        )
        return list(data.get("items") or [])
