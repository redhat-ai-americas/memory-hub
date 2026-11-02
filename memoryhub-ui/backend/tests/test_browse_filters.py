"""All memory representations must execute the same authorized filter predicate."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from src import routes_dashboard, routes_workspace
from src.access import Access, Grants
from src.config import Settings, get_settings
from src.database import get_db
from src.main import app
from src.ui_common import Viewer


@pytest.mark.parametrize("tab", ["current", "all", "quarantined", "deleted"])
@pytest.mark.parametrize("mode", ["text", "semantic"])
async def test_table_graph_timeline_and_export_share_filters(monkeypatch, tab, mode):
    viewer = Viewer("alice", "Alice", None, "account", "user")
    access = Access(viewer, Grants("alice", projects={"p1"}), ())
    monkeypatch.setattr("src.access.viewer_from_request", lambda *a: viewer)
    for module in [routes_dashboard, routes_workspace]:
        monkeypatch.setattr(module, "access_for", AsyncMock(return_value=access))
    monkeypatch.setattr(routes_dashboard, "embed", AsyncMock(return_value=[0.1] * 1024))
    result = MagicMock()
    result.scalar_one.return_value = 0
    result.scalar.return_value = None
    result.all.return_value = []
    result.scalars.return_value.all.return_value = []
    ranked = MagicMock()
    match_id = uuid.uuid4()
    ranked.all.return_value = [(match_id, 0.9)]
    db = MagicMock()

    async def execute(statement):
        return ranked if " AS score" in str(statement) else result

    db.execute = AsyncMock(side_effect=execute)
    db.rollback = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings()
    entity = str(uuid.uuid4())
    params = {
        "tab": tab,
        "q": "needle",
        "mode": mode,
        "actor": "alice-agent",
        "scope": "project",
        "project": "p1",
        "domain": "security",
        "flag": ["contradicted", "has_branches", "near_duplicate"],
        "min_weight": 0.75,
        "entity": entity,
    }
    predicates = []
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for path in ["/api/memories/browse", "/api/graph/all", "/api/memories/timeline", "/api/memories/export"]:
                db.execute.reset_mock()
                response = await client.get(path, params=params)
                assert response.status_code == 200, response.text
                statement = db.execute.call_args_list[1 if mode == "semantic" else 0].args[0]
                compiled = statement.whereclause.compile(dialect=postgresql.dialect())
                predicates.append((str(compiled), compiled.params))
                if path.endswith("timeline"):
                    assert response.json()["days"] == 0
        assert all(p == predicates[0] for p in predicates)
        sql, values = predicates[0]
        assert "memory_nodes.tenant_id =" in sql
        assert "memory_nodes.actor_id IN" in sql
        assert "memory_nodes.domains &&" in sql
        assert "memory_nodes.weight >=" in sql
        assert "memory_relationships.target_id =" in sql
        assert "contradiction_reports" in sql
        assert "%needle%" in values.values() if mode == "text" else [match_id] in values.values()
        assert (
            "memory_nodes.deleted_at IS NOT NULL" in sql
            if tab == "deleted"
            else "memory_nodes.deleted_at IS NULL" in sql
        )
    finally:
        app.dependency_overrides.clear()
