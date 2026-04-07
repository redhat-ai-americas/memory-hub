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


# ---------------------------------------------------------------------------
# Helpers for the new test classes
# ---------------------------------------------------------------------------


def _mock_httpx_response(status_code: int = 200, json_body=None, text_body: str = ""):
    """Build a MagicMock that quacks like an httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body if json_body is not None else {})
    resp.text = text_body
    return resp


def _patch_admin_httpx(response):
    """Patch ``src.routes.httpx.AsyncClient`` to return ``response`` for any request.

    Mirrors the pattern in ``TestStatsEndpoint`` so the BFF's outbound calls
    to the auth service stay in-process during tests.
    """
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)
    mock_http.request = AsyncMock(return_value=response)
    mock_http.get = AsyncMock(return_value=response)
    mock_http.post = AsyncMock(return_value=response)
    mock_http.patch = AsyncMock(return_value=response)
    return patch("src.routes.httpx.AsyncClient", return_value=mock_http), mock_http


def _make_rule(**kwargs) -> MagicMock:
    """Build a CuratorRule-like mock."""
    rule_id = kwargs.get("id", uuid.uuid4())
    defaults = {
        "id": rule_id,
        "name": "Test rule",
        "description": "A rule for tests",
        "trigger": "on_write",
        "tier": "regex",
        "config": {"pattern": "foo"},
        "action": "block",
        "scope_filter": None,
        "layer": "user",
        "owner_id": "test-user",
        "override": False,
        "enabled": True,
        "priority": 100,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_contradiction(**kwargs) -> MagicMock:
    """Build a ContradictionReport-like mock."""
    report_id = kwargs.get("id", uuid.uuid4())
    defaults = {
        "id": report_id,
        "memory_id": uuid.uuid4(),
        "observed_behavior": "User did the opposite",
        "confidence": 0.9,
        "reporter": "test-agent",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "resolved": False,
        "resolved_at": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# /api/graph/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGraphSearchEndpoint:
    async def test_text_fallback_returns_matches(self, test_settings):
        # embedding_url is empty in the fixture, so the route takes the text
        # fallback branch and runs a single ORM query.
        node = _make_node()
        db_session = _make_db_session([_scalars_result([node])])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/graph/search", params={"q": "test"})

            assert response.status_code == 200
            body = response.json()
            assert isinstance(body, list)
            assert len(body) == 1
            assert body[0]["id"] == str(node.id)
            assert body[0]["score"] == 1.0
        finally:
            app.dependency_overrides.clear()

    async def test_semantic_path_uses_embedding(self, test_settings):
        # When _get_embedding returns a vector, the route hits the raw SQL
        # path that returns (id, score) tuples from fetchall().
        match_id = str(uuid.uuid4())
        sql_result = MagicMock()
        sql_result.fetchall.return_value = [(match_id, 0.87)]
        db_session = _make_db_session([sql_result])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        with patch(
            "src.routes._get_embedding", new=AsyncMock(return_value=[0.1, 0.2, 0.3])
        ):
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.get("/api/graph/search", params={"q": "hello"})

                assert response.status_code == 200
                body = response.json()
                assert len(body) == 1
                assert body[0]["id"] == match_id
                assert body[0]["score"] == pytest.approx(0.87)
            finally:
                app.dependency_overrides.clear()

    async def test_missing_query_returns_422(self, test_settings):
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                # No `q` parameter at all → FastAPI rejects with 422
                response = await ac.get("/api/graph/search")

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /api/memory/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemoryDeletionEndpoint:
    async def test_deletes_returns_204(self, test_settings):
        # Single-version, no children, no previous_version_id, not deleted.
        node = _make_node(deleted_at=None, previous_version_id=None, parent_id=None)

        # Route execute() call sequence:
        #   1) initial node lookup
        #   2) forward-walk select (no newer versions)
        #   3) child branches select
        #   4) bulk update
        db_session = _make_db_session(
            [
                _scalar_result(node),
                _scalars_result([]),  # forward walk: no children
                _scalars_result([]),  # child branches
                MagicMock(),  # update result (unused)
            ]
        )
        db_session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete(f"/api/memory/{node.id}")

            assert response.status_code == 204
            db_session.commit.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    async def test_returns_404_for_missing_memory(self, test_settings):
        missing_id = str(uuid.uuid4())
        db_session = _make_db_session([_scalar_result(None)])
        db_session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete(f"/api/memory/{missing_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    async def test_returns_409_when_already_deleted(self, test_settings):
        already = _make_node(
            deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
            previous_version_id=None,
            parent_id=None,
        )
        db_session = _make_db_session([_scalar_result(already)])
        db_session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete(f"/api/memory/{already.id}")

            assert response.status_code == 409
            assert "already deleted" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    async def test_returns_422_for_invalid_uuid(self, test_settings):
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete("/api/memory/not-a-uuid")

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Client management (proxy to auth service)
# ---------------------------------------------------------------------------


_SAMPLE_CLIENT = {
    "client_id": "test-client",
    "client_name": "Test Client",
    "identity_type": "user",
    "tenant_id": "test-tenant",
    "default_scopes": ["memory:read"],
    "active": True,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
}


@pytest.mark.asyncio
class TestClientEndpoints:
    async def test_list_clients_returns_proxied_response(self, test_settings):
        upstream = _mock_httpx_response(200, [_SAMPLE_CLIENT])
        patcher, _ = _patch_admin_httpx(upstream)

        app.dependency_overrides[get_settings] = lambda: test_settings
        with patcher:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.get("/api/clients")

                assert response.status_code == 200
                body = response.json()
                assert isinstance(body, list)
                assert body[0]["client_id"] == "test-client"
            finally:
                app.dependency_overrides.clear()

    async def test_list_clients_propagates_upstream_error(self, test_settings):
        upstream = _mock_httpx_response(503, {"detail": "auth service down"})
        patcher, _ = _patch_admin_httpx(upstream)

        app.dependency_overrides[get_settings] = lambda: test_settings
        with patcher:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.get("/api/clients")

                assert response.status_code == 503
                assert "auth service down" in response.json()["detail"]
            finally:
                app.dependency_overrides.clear()

    async def test_create_client_returns_201(self, test_settings):
        created = {**_SAMPLE_CLIENT, "client_secret": "supersecret"}
        upstream = _mock_httpx_response(201, created)
        patcher, _ = _patch_admin_httpx(upstream)

        app.dependency_overrides[get_settings] = lambda: test_settings
        with patcher:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.post(
                        "/api/clients",
                        json={
                            "client_id": "test-client",
                            "client_name": "Test Client",
                            "identity_type": "user",
                            "tenant_id": "test-tenant",
                            "default_scopes": ["memory:read"],
                        },
                    )

                assert response.status_code == 201
                body = response.json()
                assert body["client_id"] == "test-client"
                assert body["client_secret"] == "supersecret"
            finally:
                app.dependency_overrides.clear()

    async def test_update_client_returns_200(self, test_settings):
        updated = {**_SAMPLE_CLIENT, "client_name": "Renamed"}
        upstream = _mock_httpx_response(200, updated)
        patcher, _ = _patch_admin_httpx(upstream)

        app.dependency_overrides[get_settings] = lambda: test_settings
        with patcher:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.patch(
                        "/api/clients/test-client",
                        json={"client_name": "Renamed"},
                    )

                assert response.status_code == 200
                assert response.json()["client_name"] == "Renamed"
            finally:
                app.dependency_overrides.clear()

    async def test_rotate_secret_returns_new_secret(self, test_settings):
        upstream = _mock_httpx_response(
            200, {"client_id": "test-client", "client_secret": "rotated-secret"}
        )
        patcher, _ = _patch_admin_httpx(upstream)

        app.dependency_overrides[get_settings] = lambda: test_settings
        with patcher:
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as ac:
                    response = await ac.post("/api/clients/test-client/rotate-secret")

                assert response.status_code == 200
                body = response.json()
                assert body["client_secret"] == "rotated-secret"
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Curation rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCurationRulesEndpoints:
    async def test_list_rules_returns_array(self, test_settings):
        rule = _make_rule()
        db_session = _make_db_session([_scalars_result([rule])])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/rules")

            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["id"] == str(rule.id)
            assert body[0]["tier"] == "regex"
        finally:
            app.dependency_overrides.clear()

    async def test_list_rules_accepts_filter_query_params(self, test_settings):
        # Filter params just narrow the SELECT; the test asserts the route
        # accepts them and returns whatever the mocked DB hands back.
        db_session = _make_db_session([_scalars_result([])])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(
                    "/api/rules",
                    params={"tier": "regex", "enabled": "true", "layer": "user"},
                )

            assert response.status_code == 200
            assert response.json() == []
        finally:
            app.dependency_overrides.clear()

    async def test_create_rule_returns_201(self, test_settings):
        # The route does db.add + commit + refresh. We mock refresh to
        # populate id/created_at/updated_at on the in-memory CuratorRule
        # so the response model can serialize it.
        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            obj.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        db_session = AsyncMock()
        db_session.add = MagicMock()
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock(side_effect=fake_refresh)

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post(
                    "/api/rules",
                    json={
                        "name": "New rule",
                        "tier": "regex",
                        "action": "block",
                        "config": {"pattern": "secret"},
                    },
                )

            assert response.status_code == 201
            body = response.json()
            assert body["name"] == "New rule"
            assert body["tier"] == "regex"
            db_session.add.assert_called_once()
            db_session.commit.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    async def test_get_rule_returns_detail(self, test_settings):
        rule = _make_rule()
        db_session = _make_db_session([_scalar_result(rule)])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(f"/api/rules/{rule.id}")

            assert response.status_code == 200
            assert response.json()["id"] == str(rule.id)
        finally:
            app.dependency_overrides.clear()

    async def test_get_rule_returns_404_for_missing(self, test_settings):
        db_session = _make_db_session([_scalar_result(None)])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(f"/api/rules/{uuid.uuid4()}")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    async def test_get_rule_returns_422_for_invalid_uuid(self, test_settings):
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/rules/not-a-uuid")

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()

    async def test_update_rule_modifies_fields(self, test_settings):
        rule = _make_rule(enabled=True, priority=100)

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(rule))
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    f"/api/rules/{rule.id}",
                    json={"enabled": False, "priority": 5},
                )

            assert response.status_code == 200
            # The route mutates the rule in place, so we can check the mock.
            assert rule.enabled is False
            assert rule.priority == 5
            db_session.commit.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    async def test_update_rule_returns_404_for_missing(self, test_settings):
        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(None))
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    f"/api/rules/{uuid.uuid4()}", json={"enabled": False}
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    async def test_delete_rule_returns_204(self, test_settings):
        rule = _make_rule()

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(rule))
        db_session.delete = AsyncMock()
        db_session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete(f"/api/rules/{rule.id}")

            assert response.status_code == 204
            db_session.delete.assert_awaited_once_with(rule)
            db_session.commit.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    async def test_delete_rule_returns_404_for_missing(self, test_settings):
        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(None))
        db_session.delete = AsyncMock()
        db_session.commit = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.delete(f"/api/rules/{uuid.uuid4()}")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Contradictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestContradictionsEndpoints:
    async def test_list_returns_reports(self, test_settings):
        report = _make_contradiction()
        db_session = _make_db_session([_scalars_result([report])])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/contradictions")

            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["id"] == str(report.id)
            assert body[0]["resolved"] is False
        finally:
            app.dependency_overrides.clear()

    async def test_list_accepts_filter_params(self, test_settings):
        db_session = _make_db_session([_scalars_result([])])

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get(
                    "/api/contradictions",
                    params={
                        "resolved": "false",
                        "min_confidence": "0.5",
                        "max_confidence": "1.0",
                    },
                )

            assert response.status_code == 200
            assert response.json() == []
        finally:
            app.dependency_overrides.clear()

    async def test_stats_returns_aggregated_counts(self, test_settings):
        # Five sequential SELECT count() calls: total, unresolved, high, medium, low.
        db_session = _make_db_session(
            [
                _scalar_result(10),  # total
                _scalar_result(4),  # unresolved
                _scalar_result(3),  # high
                _scalar_result(5),  # medium
                _scalar_result(2),  # low
            ]
        )

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.get("/api/contradictions/stats")

            assert response.status_code == 200
            body = response.json()
            assert body == {
                "total": 10,
                "unresolved": 4,
                "high_confidence": 3,
                "medium_confidence": 5,
                "low_confidence": 2,
            }
        finally:
            app.dependency_overrides.clear()

    async def test_resolve_contradiction_sets_resolved(self, test_settings):
        report = _make_contradiction(resolved=False, resolved_at=None)

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(report))
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    f"/api/contradictions/{report.id}", json={"resolved": True}
                )

            assert response.status_code == 200
            assert report.resolved is True
            assert report.resolved_at is not None
            db_session.commit.assert_awaited()
        finally:
            app.dependency_overrides.clear()

    async def test_unresolve_contradiction_clears_resolved_at(self, test_settings):
        report = _make_contradiction(
            resolved=True, resolved_at=datetime(2026, 1, 1, tzinfo=UTC)
        )

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(report))
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    f"/api/contradictions/{report.id}", json={"resolved": False}
                )

            assert response.status_code == 200
            assert report.resolved is False
            assert report.resolved_at is None
        finally:
            app.dependency_overrides.clear()

    async def test_update_contradiction_returns_404_for_missing(self, test_settings):
        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=_scalar_result(None))
        db_session.commit = AsyncMock()
        db_session.refresh = AsyncMock()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    f"/api/contradictions/{uuid.uuid4()}", json={"resolved": True}
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    async def test_update_contradiction_returns_422_for_invalid_uuid(self, test_settings):
        db_session = _make_db_session([])
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_settings] = lambda: test_settings

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.patch(
                    "/api/contradictions/not-a-uuid", json={"resolved": True}
                )

            assert response.status_code == 422
        finally:
            app.dependency_overrides.clear()
