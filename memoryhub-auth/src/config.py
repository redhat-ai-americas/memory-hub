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

    @property
    def async_db_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = AuthSettings()
