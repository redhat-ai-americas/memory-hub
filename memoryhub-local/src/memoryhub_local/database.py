"""SQLite database engine and session management for personal edition."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

_DEFAULT_SUBDIR = "memoryhub"
_DEFAULT_FILENAME = "memoryhub.db"


def get_default_db_path() -> Path:
    """Return the default database path following XDG conventions.

    Uses $XDG_DATA_HOME/memoryhub/memoryhub.db, falling back to
    ~/.local/share/memoryhub/memoryhub.db.
    """
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        base = Path(xdg_data)
    else:
        base = Path.home() / ".local" / "share"
    return base / _DEFAULT_SUBDIR / _DEFAULT_FILENAME


async def create_local_engine(db_path: Path | None = None) -> AsyncEngine:
    """Create an async SQLite engine with WAL mode.

    Creates parent directories if they don't exist. Sets WAL journal
    mode for concurrent read/write safety.
    """
    if db_path is None:
        db_path = get_default_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


async def auto_migrate(engine: AsyncEngine) -> None:
    """Run Alembic migrations to latest version, then ensure FTS tables.

    On a pre-existing database (created before Alembic was added), the
    initial migration detects existing tables and stamps the version
    without recreating them.
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    from memoryhub_local.storage.sqlite import ensure_fts_table

    alembic_dir = Path(__file__).parent / "alembic"
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(alembic_dir))

    def _run_upgrade(sync_conn):
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_run_upgrade)

    # FTS5 virtual tables are outside Alembic (can't manage virtual tables)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await ensure_fts_table(session)
        await session.commit()


def make_session_factory(engine: AsyncEngine) -> sessionmaker:
    """Create an async session factory bound to the given engine."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
