"""Basic route tests for the MemoryHub UI BFF API.

Uses httpx's AsyncClient with the ASGI transport so no real database or
embedding service is needed. Database sessions are overridden with a mock
that returns empty/predictable results.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.config import Settings, get_settings
from src.database import get_db
from src.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_node(**kwargs) -> MagicMock:
    """Build a minimal MemoryNode-like mock."""
    node_id = kwargs.get("id", uuid.uuid4())
    defaults = {
        "id": node_id,
        "content": "Test memory content",
        "stub": "Test stub",
        "scope": "user",
        "weight": 0.8,
        "branch_type": None,
        "owner_id": "test-user",
        "version": 1,
        "is_current": True,
        "parent_id": None,
        "previous_version_id": None,
        "metadata_": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
        "expires_at": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _scalar_result(value):
    """Mock that returns value from scalar_one() or scalar_one_or_none()."""
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    r.scalars.return_value.all.return_value = []
    r.fetchall.return_value = []
    return r


def _scalars_result(items):
    """Mock that returns items from scalars().all()."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    r.scalar_one.return_value = len(items)
    r.fetchall.return_value = []
    return r


def _make_db_session(execute_side_effects: list):
    """Build an async DB session mock with a queue of execute() return values."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=execute_side_effects)
    return session


@pytest.fixture
def test_settings():
    return Settings(
        db_host="localhost",
        db_port=5432,
        db_name="memoryhub",
        db_user="memoryhub",
        db_password="",
        embedding_url="",
        mcp_server_url="http://mcp-server:8080/mcp/",
    )


# ---------------------------------------------------------------------------
# Sync TestClient tests (simpler for basic checks)
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=True)


class TestHealthz:
    def test_healthz_returns_200(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Async client tests using mocked DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGraphEndpoint:
    async def test_returns_graph_structure(self, test_settings):
        node = _make_node()

        # execute() is called twice: once for nodes, once for relationships
        db_session = _make_db_session(
            [
                _scalars_result([node]),  # MemoryNode query
                _scalars_result([]),  # MemoryRelationship query
            ]
        )

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/graph")

            assert response.status_code == 200
            body = response.json()
            assert "nodes" in body
            assert "edges" in body
            assert isinstance(body["nodes"], list)
            assert isinstance(body["edges"], list)
            assert len(body["nodes"]) == 1
            assert body["nodes"][0]["id"] == str(node.id)
        finally:
            app.dependency_overrides.clear()

    async def test_empty_graph_returns_empty_lists(self, test_settings):
        db_session = _make_db_session(
            [
                _scalars_result([]),  # no nodes
            ]
        )

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/graph")

            assert response.status_code == 200
            body = response.json()
            assert body["nodes"] == []
            assert body["edges"] == []
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestStatsEndpoint:
    async def test_returns_stats_structure(self, test_settings):
        node = _make_node()

        # total count, scope breakdown, recent nodes
        total_result = _scalar_result(5)
        scope_result = MagicMock()
        scope_result.fetchall.return_value = [("user", 3), ("project", 2)]
        recent_result = _scalars_result([node])

        db_session = _make_db_session([total_result, scope_result, recent_result])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        # Patch the MCP health check so we don't make a real HTTP call
        with patch("src.routes.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=None)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_http

            try:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                    response = await ac.get("/api/stats")

                assert response.status_code == 200
                body = response.json()
                assert "total_memories" in body
                assert "scope_counts" in body
                assert "recent_activity" in body
                assert "mcp_health" in body
                assert body["total_memories"] == 5
                assert len(body["scope_counts"]) == 2
            finally:
                app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestMemoryDetailEndpoint:
    async def test_returns_404_for_nonexistent_id(self, test_settings):
        missing_id = str(uuid.uuid4())

        # node lookup returns None, no further queries needed
        db_session = _make_db_session([_scalar_result(None)])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(f"/api/memory/{missing_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    async def test_returns_detail_for_existing_node(self, test_settings):
        node = _make_node()

        node_result = _scalar_result(node)
        count_result = _scalar_result(0)  # no children
        rel_result = _scalars_result([])  # no relationships

        db_session = _make_db_session([node_result, count_result, rel_result])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(f"/api/memory/{node.id}")

            assert response.status_code == 200
            body = response.json()
            assert body["id"] == str(node.id)
            assert body["children_count"] == 0
            assert body["relationships"] == []
        finally:
            app.dependency_overrides.clear()

    async def test_returns_422_for_invalid_uuid(self, test_settings):
        # DB is never reached (UUID parse fails first), but we still override it
        # to avoid SQLAlchemy trying to create a real connection during teardown.
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/memory/not-a-uuid")

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
class TestMemoryHistoryEndpoint:
    """Regression tests for the /api/memory/{id}/history walker fix (#63).

    The BFF endpoint previously hand-rolled a backward-only walker that was
    a parallel copy of the bug fixed by #49 at the service layer. The fix
    delegates to ``memoryhub.services.memory.get_memory_history`` so that
    middle-version IDs resolve the full chain. These tests pin the route's
    contract with the service function so a future refactor can't silently
    reintroduce the backward-only walk.
    """

    async def test_returns_full_chain_from_service(self, test_settings):
        memory_id = uuid.uuid4()
        v1_id = uuid.uuid4()
        v2_id = uuid.uuid4()
        v3_id = memory_id  # caller passed the current version

        # Service returns a dict with newest-first "versions" list; this
        # mirrors the real get_memory_history shape so the test catches
        # mock/real drift the way #52 taught us to.
        v1 = MagicMock(
            id=v1_id,
            version=1,
            is_current=False,
            stub="v1 stub",
            content="v1 content",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        v2 = MagicMock(
            id=v2_id,
            version=2,
            is_current=False,
            stub="v2 stub",
            content="v2 content",
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        v3 = MagicMock(
            id=v3_id,
            version=3,
            is_current=True,
            stub="v3 stub",
            content="v3 content",
            created_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
        service_result = {
            "versions": [v3, v2, v1],  # newest-first
            "total_versions": 3,
            "has_more": False,
            "offset": 0,
        }

        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        with patch(
            "src.routes.get_memory_history_service",
            new=AsyncMock(return_value=service_result),
        ) as mock_service:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.get(f"/api/memory/{memory_id}/history")

                assert response.status_code == 200
                body = response.json()
                assert len(body) == 3
                # Newest first — the whole point of the #63 fix is that the
                # BFF now gets a sorted chain regardless of which version ID
                # the caller passed, not a truncated backward walk.
                assert [v["version"] for v in body] == [3, 2, 1]
                assert body[0]["id"] == str(v3_id)
                assert body[0]["is_current"] is True
                assert body[2]["id"] == str(v1_id)
                assert body[2]["is_current"] is False

                # Verify the BFF delegates to the service function (not a
                # hand-rolled walker) and passes a large max_versions to
                # preserve the unpaginated BFF contract.
                mock_service.assert_awaited_once()
                call_kwargs = mock_service.await_args.kwargs
                assert call_kwargs["memory_id"] == memory_id
                assert call_kwargs["max_versions"] >= 1000
            finally:
                app.dependency_overrides.clear()

    async def test_returns_404_when_service_raises_not_found(self, test_settings):
        from memoryhub.services.exceptions import MemoryNotFoundError

        missing_id = uuid.uuid4()

        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        with patch(
            "src.routes.get_memory_history_service",
            new=AsyncMock(side_effect=MemoryNotFoundError(missing_id)),
        ):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.get(f"/api/memory/{missing_id}/history")

                assert response.status_code == 404
                assert "not found" in response.json()["detail"].lower()
            finally:
                app.dependency_overrides.clear()

    async def test_returns_422_for_invalid_uuid(self, test_settings):
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                response = await ac.get("/api/memory/not-a-uuid/history")

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
