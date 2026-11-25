from pydantic_settings import BaseSettings


class AuthSettings(BaseSettings):
    """OAuth 2.1 auth service configuration."""

    model_config = {"env_prefix": "AUTH_"}

    # Database (same PostgreSQL instance as MemoryHub)
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "memoryhub"
    db_user: str = "memoryhub"
    db_password: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8081

    # Token settings
    issuer: str = "https://memoryhub-auth.apps.example.com"
    audience: str = "memoryhub"
    access_token_ttl: int = 900  # 15 minutes in seconds
    refresh_token_ttl: int = 86400  # 24 hours in seconds

    # Admin API
    admin_key: str = ""

    # RSA key paths (for OpenShift, mounted from Secret)
    rsa_private_key_path: str = ""
    rsa_public_key_path: str = ""
    # Alternative: key content directly from env (for K8s Secrets)
    rsa_private_key_pem: str = ""
    rsa_public_key_pem: str = ""
    # Local dev: auto-generate and cache keys here
    keys_dir: str = "./keys"

    # OpenShift OAuth broker settings
    openshift_oauth_authorize_url: str = ""
    openshift_oauth_token_url: str = ""
    openshift_user_info_url: str = "https://kubernetes.default.svc/apis/user.openshift.io/v1/users/~"
    openshift_oauth_client_id: str = "memoryhub-auth-broker"
    openshift_oauth_client_secret: str = ""
    openshift_allowed_group: str = ""  # empty = allow all authenticated users
    openshift_tls_verify: bool = True  # set False only for dev/debug
    openshift_ca_bundle: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

    # Entitlement (docs/auth/human-role-resolution.md): "openshift-rbac"
    # requires the "use" verb on memoryhub.io/dashboard in
    # entitlement_namespace at sign-in, at every refresh, and for every token
    # issued to an agent owned by a person. "off" keeps the legacy
    # openshift_allowed_group check (Compose, tests).
    entitlement_mode: str = "off"
    entitlement_namespace: str = "memoryhub-ui"
    # What a missing role does to a person's sessions: "refuse" (refresh
    # fails while the role is missing; restoring the role restores it) or
    # "revoke" (the sessions end; a new sign-in is required). Identity
    # changes, blocking and token reuse always revoke.
    entitlement_denial: str = "refuse"
    # Issuer of verified OpenShift identities; must equal the dashboard's
    # MEMORYHUB_UI_IDENTITY_ISSUER. Default: "openshift:<k8s_api_server>".
    identity_issuer: str = ""
    # Absolute lifetime of a refresh-token family (a sign-in), whatever the
    # rotations: after it, a new sign-in is required. 7 days.
    session_max_age: int = 604800

    # Broker defaults for human users
    default_tenant_id: str = "default"
    default_human_scopes: list[str] = ["memory:read:user", "memory:write:user"]

    # Kubernetes API (for token exchange / TokenReview)
    k8s_api_server: str = "https://kubernetes.default.svc"
    k8s_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    k8s_ca_path: str = "/etc/pki/combined-ca/ca-bundle.crt"
    token_exchange_enabled: bool = True
    tenant_cache_ttl: int = 300  # 5 minutes

    # Session TTLs
    auth_session_pending_ttl: int = 300  # 5 minutes
    auth_session_ready_ttl: int = 600  # 10 minutes

    def verified_issuer(self) -> str:
        return self.identity_issuer.strip() or f"openshift:{self.k8s_api_server.rstrip('/')}"

    @property
    def async_db_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = AuthSettings()
