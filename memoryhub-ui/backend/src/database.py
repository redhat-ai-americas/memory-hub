"""Async SQLAlchemy engine and session factory for the MemoryHub UI backend."""

from collections.abc import AsyncGenerator

from memoryhub_core.services.database import create_session_factory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings, get_settings

_session_factory = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _engine, _session_factory = create_session_factory(settings.database_url, pool_size=5, max_overflow=10)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    settings = get_settings()
    factory = _get_session_factory(settings)
    async with factory() as session:
        yield session
