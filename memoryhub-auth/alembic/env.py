"""Alembic environment configuration for memoryhub-auth.

Loads the database URL from AUTH_DB_* environment variables at runtime,
overriding the placeholder in alembic.ini.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Add the memoryhub-auth root to sys.path so `src.models` is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Alembic Config object (provides access to alembic.ini values)
config = context.config

# Set up loggers from the config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Build the database URL from AUTH_DB_* env vars (same as AuthSettings).
_db_url = "postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}".format(
    user=os.environ.get("AUTH_DB_USER", "memoryhub"),
    password=os.environ.get("AUTH_DB_PASSWORD", ""),
    host=os.environ.get("AUTH_DB_HOST", "localhost"),
    port=os.environ.get("AUTH_DB_PORT", "5432"),
    name=os.environ.get("AUTH_DB_NAME", "memoryhub"),
)
config.set_main_option("sqlalchemy.url", _db_url)

# Import models' MetaData for autogenerate support.
from src.models import Base  # noqa: E402

target_metadata = Base.metadata

# Tables owned by the core MCP server that live in the same database.
# Without this hook, autogenerate would propose dropping them.
_EXTERNAL_TABLES = {
    "memory_nodes",
    "memory_relationships",
    "curation_rules",
    "contradiction_reports",
    "campaigns",
    "campaign_enrollments",
    "alembic_version",  # core server's migration tracking
}


def include_object(object, name, type_, reflected, compare_to):  # noqa: A002
    """Skip external tables so autogenerate does not propose dropping them."""
    return not (type_ == "table" and name in _EXTERNAL_TABLES)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        version_table="auth_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            version_table="auth_alembic_version",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
