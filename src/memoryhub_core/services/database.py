"""Async database session management for MemoryHub."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.config import DatabaseSettings

_engine = None
_session_factory = None


def init_db(settings: DatabaseSettings | None = None) -> None:
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory
    if settings is None:
        settings = DatabaseSettings()
    _engine = create_async_engine(settings.async_url, echo=False, pool_size=10, max_overflow=20)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    if _session_factory is None:
        init_db()
    async with _session_factory() as session:
        yield session


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None
