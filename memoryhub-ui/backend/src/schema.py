"""The UI's own tables are managed by Alembic (``backend/migrations``).

``upgrade()`` runs on startup (``MEMORYHUB_UI_MIGRATE_ON_START``, default on),
under a Postgres advisory lock so concurrent replicas migrate once. Modules
call ``require(db)`` before touching their tables; it is a no-op once the
schema is at head and otherwise runs the same migrations — never ad-hoc DDL.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
LOCK_KEY = 7_301_244_020
_ready = False
_lock = asyncio.Lock()


def _alembic_config(connection=None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def _upgrade_sync(connection) -> None:
    from alembic import command

    connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
    try:
        command.upgrade(_alembic_config(connection), "head")
    finally:
        connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


async def upgrade() -> None:
    """Bring the UI tables to the latest revision."""
    global _ready
    from src.config import get_settings
    from src.database import _get_engine

    async with _lock:
        if _ready:
            return
        engine = _get_engine(get_settings())
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade_sync)
            await connection.commit()
        _ready = True
        logger.info("MemoryHub UI schema is at head")


async def require(db: AsyncSession | None = None) -> None:
    if not _ready:
        await upgrade()
