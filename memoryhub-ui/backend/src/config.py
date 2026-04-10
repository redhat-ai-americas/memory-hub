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

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
