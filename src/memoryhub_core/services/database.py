"""Async database session management for MemoryHub."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.config import DatabaseSettings

_engine = None
_session_factory = None


def create_session_factory(database_url: str, *, pool_size: int = 10, max_overflow: int = 20):
    """Construct the shared Core engine/session policy for any transport.

    Transports may size their pools independently; SQLAlchemy configuration
    and the transaction/session contract live here.
    """
    engine = create_async_engine(
        database_url, echo=False, pool_pre_ping=True,
        pool_size=pool_size, max_overflow=max_overflow,
    )
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def init_db(settings: DatabaseSettings | None = None) -> None:
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory
    if settings is None:
        settings = DatabaseSettings()
    _engine, _session_factory = create_session_factory(settings.async_url)


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
