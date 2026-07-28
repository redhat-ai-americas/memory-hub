"""Alembic environment for memoryhub-local (async SQLite with batch mode).

Supports two invocation modes:
  1. Programmatic: database.auto_migrate() passes a synchronous connection
     via config.attributes["connection"] inside run_sync(), so env.py runs
     purely synchronously -- no asyncio.run() needed.
  2. CLI: ``alembic upgrade head`` creates an async engine from alembic.ini
     and bridges via asyncio.run().

render_as_batch=True is required for SQLite, which doesn't support ALTER
TABLE ADD/DROP COLUMN directly.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import memoryhub_local.models  # noqa: F401 -- register all models
from memoryhub_local.models.base import Base

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline():
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        version_table="local_alembic_version",
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection):
    """Configure and run migrations against a synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        version_table="local_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Entry point for online (non-offline) migration execution."""
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        # Programmatic path: already inside run_sync, connection is sync
        _do_run_migrations(connectable)
        return

    # CLI path: create async engine, bridge to sync
    async def _run():
        engine = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
        await engine.dispose()

    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
