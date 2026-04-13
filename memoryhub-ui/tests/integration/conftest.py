"""Fixtures for deployed-stack integration tests.

These tests run against the live OpenShift cluster, not a local compose stack.
Three ``oc port-forward`` tunnels are opened per session:

    - PostgreSQL (memoryhub-db)       → localhost:25432
    - Embedding service (TEI)         → localhost:28080
    - BFF (memoryhub-ui, app port)    → localhost:28081

Every test that writes rows into the DB cleans up via the ``seed_cleanup``
fixture, which truncates seeded IDs after each test.

Requires:
    - ``oc`` logged in to the target cluster
    - pgvector extension enabled on the DB
    - Embedding service running in ``embedding-model`` namespace
    - memoryhub-ui pod running in ``memory-hub-mcp`` namespace
"""

import os
import socket
import subprocess
import time

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Mark every test in this package as a deployed-stack integration test.
pytestmark = [pytest.mark.integration, pytest.mark.deployed]

# Port-forward local ports (high to avoid conflicts with local compose stack).
DB_LOCAL_PORT = int(os.environ.get("TEST_DB_PORT", "25432"))
EMBED_LOCAL_PORT = int(os.environ.get("TEST_EMBED_PORT", "28080"))
BFF_LOCAL_PORT = int(os.environ.get("TEST_BFF_PORT", "28081"))

# Cluster coordinates — override via env for non-default clusters.
DB_NAMESPACE = os.environ.get("TEST_DB_NAMESPACE", "memoryhub-db")
DB_SERVICE = os.environ.get("TEST_DB_SERVICE", "memoryhub-pg")
EMBED_NAMESPACE = os.environ.get("TEST_EMBED_NAMESPACE", "embedding-model")
EMBED_SERVICE = os.environ.get("TEST_EMBED_SERVICE", "all-minilm-l6-v2")
BFF_NAMESPACE = os.environ.get("TEST_BFF_NAMESPACE", "memory-hub-mcp")
BFF_SERVICE = os.environ.get("TEST_BFF_SERVICE", "memoryhub-ui")

DB_USER = os.environ.get("TEST_DB_USER", "memoryhub")
DB_PASSWORD = os.environ.get("TEST_DB_PASSWORD", "memoryhub-dev-password")
DB_NAME = os.environ.get("TEST_DB_NAME", "memoryhub")
TENANT_ID = os.environ.get("TEST_TENANT_ID", "default")


def _start_port_forward(namespace: str, service: str, local_port: int, remote_port: int) -> subprocess.Popen:
    """Start an ``oc port-forward`` process and wait for it to be ready."""
    proc = subprocess.Popen(
        [
            "oc", "port-forward",
            f"svc/{service}", f"{local_port}:{remote_port}",
            "-n", namespace,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Wait for the port-forward to be listening (up to 10 s).
    for _ in range(20):
        if proc.poll() is not None:
            output = proc.stdout.read().decode() if proc.stdout else ""
            raise RuntimeError(
                f"oc port-forward to {namespace}/{service} exited early "
                f"(rc={proc.returncode}): {output}"
            )
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.3):
                return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"Timed out waiting for port-forward {namespace}/{service}:{remote_port} → :{local_port}")


@pytest.fixture(scope="session")
def _port_forwards():
    """Session-scoped: open port-forwards to DB, embedding service, and BFF."""
    procs: list[subprocess.Popen] = []
    try:
        procs.append(_start_port_forward(DB_NAMESPACE, DB_SERVICE, DB_LOCAL_PORT, 5432))
        procs.append(_start_port_forward(EMBED_NAMESPACE, EMBED_SERVICE, EMBED_LOCAL_PORT, 80))
        procs.append(_start_port_forward(BFF_NAMESPACE, BFF_SERVICE, BFF_LOCAL_PORT, 8080))
        yield
    finally:
        for p in procs:
            p.kill()
            p.wait()


@pytest.fixture(scope="session")
def db_url(_port_forwards) -> str:
    return f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{DB_LOCAL_PORT}/{DB_NAME}"


@pytest.fixture(scope="session")
def embedding_url(_port_forwards) -> str:
    return f"http://127.0.0.1:{EMBED_LOCAL_PORT}"


@pytest.fixture(scope="session")
def bff_base_url(_port_forwards) -> str:
    return f"http://127.0.0.1:{BFF_LOCAL_PORT}"


@pytest_asyncio.fixture
async def db_session(db_url) -> AsyncSession:
    """Per-test async DB session. Does NOT truncate — use ``seed_cleanup``."""
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_cleanup(db_session):
    """Collect seeded memory IDs during a test and delete them afterward.

    Usage::

        async def test_foo(seed_cleanup, ...):
            seed_cleanup.add(memory_id)
            ...
    """

    class _Tracker:
        def __init__(self):
            self.ids: list[str] = []

        def add(self, memory_id: str) -> None:
            self.ids.append(memory_id)

    tracker = _Tracker()
    yield tracker

    if tracker.ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(tracker.ids)))
        params = {f"id_{i}": uid for i, uid in enumerate(tracker.ids)}
        await db_session.execute(
            text(f"DELETE FROM memory_nodes WHERE id::text IN ({placeholders})"),
            params,
        )
        await db_session.commit()


async def get_embedding(text_query: str, embedding_url: str) -> list[float]:
    """Call the TEI embedding service and return a 384-dim vector."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(embedding_url, json={"inputs": text_query})
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data[0], list) else data
