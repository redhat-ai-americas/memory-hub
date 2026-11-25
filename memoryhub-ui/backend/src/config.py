"""Settings for the MemoryHub UI backend.

Uses env_prefix="MEMORYHUB_" which matches the memoryhub-db-credentials Secret
naming: MEMORYHUB_DB_HOST, MEMORYHUB_DB_PORT, etc.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORYHUB_",
        case_sensitive=False,
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "memoryhub"
    db_user: str = "memoryhub"
    db_password: str = ""
    embedding_url: str = ""
    valkey_url: str = ""
    mcp_server_url: str = "http://memory-hub-mcp:8080/mcp/"
    auth_service_url: str = "http://auth-server.memoryhub-auth.svc:8081"
    admin_key: str = ""
    cors_origins: str = ""
    # Public-facing route URLs used in the contributor welcome email.
    # These are the URLs an external agent or SDK would connect to from
    # outside the cluster. They differ from mcp_server_url and
    # auth_service_url, which are the internal SVC addresses the BFF
    # itself uses. Populated at deploy time from `oc get route` by
    # memoryhub-ui/deploy/deploy.sh (via `oc set env`). Defaults below
    # are placeholders that surface an obviously wrong URL if the env
    # vars are missing, rather than silently pointing at localhost.
    public_mcp_url: str = "https://mcp-server.example.com/mcp/"
    public_auth_url: str = "https://auth-server.example.com"
    # Tenant this UI deployment serves. All BFF queries filter by this tenant.
    # Set via MEMORYHUB_UI_TENANT_ID env var (one UI instance per tenant --
    # multi-tenant customers run one deployment per tenant). This is the
    # minimal Option A implementation of issue #46 Phase 6 BFF scoping; a
    # future enhancement could replace this with a per-request lookup from
    # the authenticated user. Default is "default" to match the Phase 1
    # server_default on memory_nodes.tenant_id.
    ui_tenant_id: str = "default"
    # Human role assignments are deployment-owned. OAuth proxy authenticates
    # the username; a request header cannot assign an admin role.
    #
    # Transitional bootstrap (#667): these lists come from the
    # `memoryhub-ui-human-access` Secret, which memoryhub-ui/deploy/deploy.sh
    # provisions and annotates (who changed it, when). The replacement role
    # resolver is tracked in #744: OpenShift RBAC grants for groups/users,
    # with an OIDC follow-up off OpenShift. Principal/Access stay unchanged.
    # See docs/ui/human-access.md.
    ui_admin_users: str = ""
    ui_allowed_users: str = ""
    # How the dashboard learns who the person is:
    # - "openshift" (default): the OAuth proxy sidecar authenticates and sets
    #   X-Forwarded-User; only loopback peers (the sidecar) are accepted.
    # - "local": local full-stack development without an OAuth proxy. Every
    #   request acts as ``ui_local_user``; identity headers are ignored. Refused
    #   inside a Kubernetes pod.
    ui_auth_mode: Literal["openshift", "local"] = "openshift"
    ui_local_user: str = ""
    # Where a person's dashboard role comes from (docs/auth/human-role-resolution.md):
    # - "lists" (transitional, #667): the two username lists above.
    # - "openshift-rbac" (#744): OpenShift RBAC on memoryhub.io/dashboard in
    #   the dashboard namespace; verb "admin" -> Admin, "use" -> User.
    # Explicit configuration only: one source never falls back to the other.
    ui_role_source: Literal["lists", "openshift-rbac"] = "lists"
    # How RBAC is checked: "self" = SelfSubjectAccessReview with the person's
    # token (no extra privileges); "delegated" = TokenReview + SubjectAccessReview
    # by the dashboard service account (needs system:auth-delegator).
    ui_rbac_check: Literal["self", "delegated"] = "self"
    # Namespace holding the dashboard Roles; defaults to the pod's namespace.
    ui_rbac_namespace: str = ""
    ui_rbac_cache_ttl: float = 30.0
    ui_rbac_deny_ttl: float = 5.0
    # Issuer recorded for verified OpenShift identities; defaults to
    # "openshift:<kube_api_url>". Set it per cluster for a durable key.
    ui_identity_issuer: str = ""
    kube_api_url: str = "https://kubernetes.default.svc"
    kube_ca_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    kube_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    kube_namespace_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
    ui_admin_moderation_scopes: str = "project,campaign,role,organizational"
    # Explicit grant for human Admin writes outside a project-admin membership.
    # An Admin role alone is not a write capability.
    ui_admin_write_scopes: str = ""

    def human_access(self) -> tuple[set[str], set[str]]:
        """(admins, users) from the deployment's bootstrap lists."""
        admins = {item.strip() for item in self.ui_admin_users.split(",") if item.strip()}
        users = {item.strip() for item in self.ui_allowed_users.split(",") if item.strip()}
        return admins, users

    def identity_problem(self) -> str | None:
        """Why no request can be authenticated with this configuration, if so."""
        if not self.ui_tenant_id.strip():
            return "Dashboard tenant is not configured"
        if self.ui_auth_mode == "local":
            if os.environ.get("KUBERNETES_SERVICE_HOST"):
                return "Local identity mode is refused inside a cluster; use the OAuth proxy"
            if not self.ui_local_user.strip():
                return "Local identity mode needs MEMORYHUB_UI_LOCAL_USER"
        if self.ui_role_source == "openshift-rbac":
            if self.ui_auth_mode == "local":
                return "OpenShift RBAC roles need the OAuth proxy; local identity mode uses the lists"
            return None
        admins, users = self.human_access()
        if not admins and not users:
            return ("No dashboard users are configured: set MEMORYHUB_UI_ADMIN_USERS "
                    "(see docs/ui/human-access.md)")
        return None

    def rbac_namespace(self) -> str:
        if self.ui_rbac_namespace.strip():
            return self.ui_rbac_namespace.strip()
        try:
            with open(self.kube_namespace_path) as handle:
                return handle.read().strip() or "memoryhub-ui"
        except OSError:
            return "memoryhub-ui"

    def identity_issuer(self) -> str:
        return self.ui_identity_issuer.strip() or f"openshift:{self.kube_api_url.rstrip('/')}"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
