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


class ValkeySettings(BaseSettings):
    """Valkey (Redis-compatible) connection settings. Env prefix: MEMORYHUB_VALKEY_

    Used for session focus state (#61) and, when it lands, Pattern E push-side
    broadcast filtering (#62). Any Redis client library works unchanged since
    Valkey is protocol-compatible.
    """

    model_config = {"env_prefix": "MEMORYHUB_VALKEY_"}

    url: str = "redis://localhost:6379/0"
    session_ttl_seconds: int = 900  # 15 minutes, matches default JWT lifetime
    history_retention_days: int = 30  # per-day list keys auto-expire after this
    broadcast_ttl_seconds: int = 300  # 5 min TTL on per-session broadcast queue (#62)
    broadcast_pop_timeout_seconds: int = 30  # BRPOP timeout = subscriber heartbeat
    compilation_ttl_seconds: int = 604800  # 7-day TTL on compilation epochs (#175)


class AppSettings(BaseSettings):
    """Application-level settings. Env prefix: MEMORYHUB_"""

    model_config = {"env_prefix": "MEMORYHUB_"}

    log_level: str = "INFO"
    version_retention_days: int = 90
    s3_threshold_bytes: int = 102400  # Content above this goes to S3 (if configured)
    s3_prefix_chars: int = 1000       # Chars stored in DB when content is in S3
    embedding_max_tokens: int = 8192  # Embedding model context window (granite-embedding-small-english-r2)
    session_ttl_seconds: int = 3600   # API-key session lifetime; auto-extends on activity

    # Conversation thread persistence (#168)
    conv_inline_max_bytes: int = 8192  # Messages above this go to S3

    # Dreaming pipeline (#168 Phase 3)
    conv_extraction_model: str = ""
    conv_extraction_model_url: str = ""
    conv_extraction_window_size: int = 4
    conv_extraction_timeout: int = 60

    # Phase 2 entity extraction (#170)
    entity_extraction_enabled: bool = False
    entity_extraction_concurrency: int = 10

    # GLiNER Stage 2 (#248)
    gliner_model: str = "urchade/gliner_medium-v2.1"
    gliner_confidence_threshold: float = 0.5
    # Deprecated since #267: GLiNER now runs unconditionally alongside spaCy.
    # No longer used by the extraction pipeline; retained to avoid breaking
    # existing environment configs.
    gliner_stage2_trigger_count: int = 2
    gliner_stage2_trigger_confidence: float = 0.8

    # LLM Stage 3 (#249)
    llm_extraction_url: str = ""
    llm_extraction_model: str = ""
    llm_extraction_timeout: int = 60
    llm_stage3_trigger_count: int = 2
    llm_stage3_trigger_confidence: float = 0.7
