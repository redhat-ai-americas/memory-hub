"""Integration test fixtures connecting to real PostgreSQL + pgvector.

All integration tests require the compose stack to be running:

    podman-compose -f tests/integration/compose.yaml up -d

Or use the helper script which handles lifecycle automatically:

    ./scripts/run-integration-tests.sh

Connection defaults match the compose file; override with env vars:
    MEMORYHUB_DB_HOST, MEMORYHUB_DB_PORT, MEMORYHUB_DB_USER,
    MEMORYHUB_DB_PASSWORD, MEMORYHUB_DB_NAME
"""

import os
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.config import DatabaseSettings
from memoryhub_core.services.embeddings import MockEmbeddingService

# Mark every test in this package as an integration test automatically.
pytestmark = pytest.mark.integration


def _build_db_url() -> str:
    """Build the asyncpg URL from env vars (with compose-file defaults)."""
    settings = DatabaseSettings()
    # Port default is 5432 in DatabaseSettings; use 15433 for integration tests
    # unless MEMORYHUB_DB_PORT is explicitly set.
    port = int(os.environ.get("MEMORYHUB_DB_PORT", 15433))
    return (
        f"postgresql+asyncpg://{settings.user}:{settings.password}"
        f"@{settings.host}:{port}/{settings.name}"
    )


def _run_alembic_upgrade() -> None:
    """Run 'alembic upgrade head' using the test database connection settings.

    Passes MEMORYHUB_DB_* env vars so alembic/env.py picks up the right URL.
    Sets MEMORYHUB_DB_PORT to 15433 if not already set.
    """
    env = os.environ.copy()
    env.setdefault("MEMORYHUB_DB_HOST", "localhost")
    env.setdefault("MEMORYHUB_DB_PORT", "15433")
    env.setdefault("MEMORYHUB_DB_USER", "memoryhub")
    env.setdefault("MEMORYHUB_DB_PASSWORD", "memoryhub-test")
    env.setdefault("MEMORYHUB_DB_NAME", "memoryhub")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# Tables to truncate between tests, in dependency order (children before parents).
_TRUNCATE_TABLES = [
    "memory_relationships",
    "curator_rules",
    "memory_nodes",
]


@pytest.fixture(scope="session")
def _db_schema():
    """Session-scoped: run migrations once before any integration test."""
    _run_alembic_upgrade()


@pytest.fixture
async def async_session(_db_schema) -> AsyncSession:
    """Async SQLAlchemy session connected to the real PostgreSQL instance.

    Creates a fresh session per test and truncates all tables after each
    test so the next test starts from a clean slate.
    """
    db_url = _build_db_url()
    engine = create_async_engine(db_url, echo=False)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        try:
            yield session
        finally:
            # Truncate all tables in a single statement to keep tests isolated.
            table_list = ", ".join(_TRUNCATE_TABLES)
            await session.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
            await session.commit()

    await engine.dispose()


@pytest.fixture
def embedding_service():
    """Deterministic MockEmbeddingService — tests pgvector storage, not the model."""
    return MockEmbeddingService()
