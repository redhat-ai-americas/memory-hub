"""Alembic environment for the MemoryHub UI's own tables.

Uses the UI's database settings (MEMORYHUB_DB_*) and a separate version table,
``alembic_version_memoryhub_ui``, so it coexists with memoryhub_core's
migrations in the same database. Run with ``alembic upgrade head`` from
``backend/``, or let the app do it on startup (``src.schema``).
"""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

VERSION_TABLE = "alembic_version_memoryhub_ui"
config = context.config


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=None, version_table=VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()


def run_offline() -> None:
    from src.config import get_settings

    context.configure(url=get_settings().database_url, literal_binds=True, version_table=VERSION_TABLE)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    from src.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await engine.dispose()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # called from src.schema with an open connection
        _run(connection)
    else:
        asyncio.run(_run_async())


if context.is_offline_mode():
    run_offline()
else:
    run_online()
