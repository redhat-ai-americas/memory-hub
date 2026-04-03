"""MemoryHub configuration via environment variables.

Each settings class reads independently from the environment using its own prefix.
Instantiate them directly where needed — don't nest BaseSettings inside BaseSettings
(pydantic-settings v2 doesn't compose nested BaseSettings correctly).

    db = DatabaseSettings()       # reads MEMORYHUB_DB_*
    s3 = MinIOSettings()          # reads MEMORYHUB_S3_*
    app = AppSettings()           # reads MEMORYHUB_*
"""

from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings. Env prefix: MEMORYHUB_DB_"""

    model_config = {"env_prefix": "MEMORYHUB_DB_"}

    host: str = "localhost"
    port: int = 5432
    name: str = "memoryhub"
    user: str = "memoryhub"
    password: str = ""

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class MinIOSettings(BaseSettings):
    """MinIO/S3 connection settings. Env prefix: MEMORYHUB_S3_"""

    model_config = {"env_prefix": "MEMORYHUB_S3_"}

    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "memoryhub"
    secure: bool = True


class AppSettings(BaseSettings):
    """Application-level settings. Env prefix: MEMORYHUB_"""

    model_config = {"env_prefix": "MEMORYHUB_"}

    log_level: str = "INFO"
