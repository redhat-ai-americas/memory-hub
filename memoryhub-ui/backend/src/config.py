"""Settings for the MemoryHub UI backend.

Uses env_prefix="MEMORYHUB_" which matches the memoryhub-db-credentials Secret
naming: MEMORYHUB_DB_HOST, MEMORYHUB_DB_PORT, etc.
"""

from functools import lru_cache

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

    # --- Dashboard redesign (component health, search playground, login) ---
    # Optional cross-encoder reranker (TEI-compatible POST {"query","texts"}).
    # Empty disables the rerank stage in the search playground and marks the
    # component as "Not configured" on the overview.
    reranker_url: str = ""
    # Same variables the MCP server reads; used only for health probes and the
    # session-focus histogram. Empty = component not deployed.
    valkey_url: str = ""
    s3_endpoint: str = ""
    # Extra trusted token issuers shown on the Clients screen, as a JSON list
    # of {"name", "kind", "description", "status"} objects. The local cluster
    # issuer is derived from the auth service metadata automatically.
    trusted_issuers: str = ""
    # Development-only API-key login (screen 13). When set, every /api route
    # except auth, health and public config requires a session cookie created
    # by POST /api/auth/login. Leave empty behind the OpenShift OAuth proxy.
    ui_dev_api_key: str = ""
    # Label shown in the masthead, e.g. "for OpenShift AI" cluster suffix.
    cluster_domain: str = ""

    # --- Accounts, roles and confidentiality ---
    # Local dashboard accounts (email + password) with self-service sign-up and
    # a first-run admin setup. When true, every /api route except auth, health
    # and public config needs a session, exactly like the dev API-key login.
    # Behind the OpenShift OAuth proxy leave it false: identities come from
    # X-Forwarded-* headers and the admin role from ui_admin_group.
    ui_local_accounts: bool = False
    # HMAC key for session cookies. Set it in production (a Secret). When empty
    # the BFF falls back to the dev API key, then to a key derived from the DB
    # credentials, so sessions survive restarts but rotate with the password.
    ui_session_secret: str = ""
    # Optional one-time token required to create the first platform admin
    # (POST /api/auth/setup). Strongly recommended on shared clusters.
    ui_setup_token: str = ""
    # OpenShift group whose members get the platform-admin role.
    ui_admin_group: str = "memoryhub-admins"
    # Comma-separated OpenShift usernames that are platform admins. Use this
    # when the OAuth proxy does not forward X-Forwarded-Groups.
    ui_admin_users: str = ""
    # #667 tier 3: super-users may open user-scope memories, but only through
    # a time-limited incident grant (break-glass). Granted by deployment
    # config only, never self-service: an OpenShift group and/or usernames.
    # A super-user is also a platform admin.
    ui_superuser_group: str = "memoryhub-superusers"
    ui_superuser_users: str = ""
    # Where "Log out" sends the browser behind the OAuth proxy. Empty = derive
    # https://oauth-openshift.apps.<cluster>/logout from the route host.
    ui_oauth_logout_url: str = ""
    # TEST DEPLOYMENTS ONLY. Adds an account switcher to the user menu that lets
    # whoever is signed in view the dashboard as another identity and role
    # (admin / user), without logging out. Never enable in production.
    ui_test_mode: bool = False
    # Background scheduler inside the BFF: runs due dreams (nightly / weekly)
    # and rebuilds stale knowledge pages. One replica works per tick
    # (Postgres advisory lock).
    # Run the UI's Alembic migrations (backend/migrations) when the app starts.
    # Turn off when a deploy step runs `alembic upgrade head` instead.
    ui_migrate_on_start: bool = True
    # MemoryHub Labs: dashboard features beyond the Release 1 scope (knowledge
    # pages, documents, context packs, retrieval checks, memory hygiene,
    # entity merge). Off by default; their API answers 404 while off.
    ui_labs: bool = False
    ui_scheduler_enabled: bool = True
    ui_scheduler_interval_s: int = 300

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
