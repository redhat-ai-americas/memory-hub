"""Stage 2.2 human adapter authorization and response-contract tests."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from memoryhub_core.services.memory import _build_search_filters
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import get_embedding_service
from src.main import app


def query_result(value=None, *, items=None, rows=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    result.scalars.return_value.all.return_value = items if items is not None else []
    result.all.return_value = rows if rows is not None else []
    return result


def node(**changes):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    values = {
        "id": uuid.uuid4(), "logical_id": uuid.uuid4(), "tenant_id": "tenant-a",
        "scope": "user", "scope_id": None, "owner_id": "alice", "actor_id": "alice",
        "driver_id": "alice", "status": "active", "deleted_at": None,
        "is_current": True, "parent_id": None, "weight": 0.9,
        "content": "own content", "stub": "own stub", "branch_type": None,
        "metadata_": {"source": "test"}, "version": 1, "domains": [],
        "content_type": "experiential", "source": "agent",
        "upstream_trust_level": "trusted", "relevant_until": None,
        "created_at": stamp, "updated_at": stamp, "expires_at": None,
        "embedding": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def access(role="user", **changes):
    values = {
        "principal": Principal("alice", role, "tenant-a"),
        "human_projects": {"p"}, "human_project_admins": {"p"},
        "moderation_scopes": {"project", "organizational"},
    }
    values.update(changes)
    return Access(**values)


@pytest.fixture
def client():
    session = AsyncMock()
    session.execute.return_value = query_result(None)
    settings = Settings(ui_tenant_id="tenant-a", embedding_url="http://embed.test/embed")
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_access] = lambda: access()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedding_service] = lambda: MagicMock()
    with TestClient(app) as http:
        yield http, session, lambda grant: app.dependency_overrides.__setitem__(get_access, lambda: grant)
    app.dependency_overrides.clear()


def test_context_rechecks_history_and_relationship_neighbor(client):
    http, db, _ = client
    own = node()
    foreign = node(owner_id="bob", content="foreign secret", stub="foreign title")
    edge = SimpleNamespace(id=uuid.uuid4(), source_id=own.id, target_id=foreign.id,
                           relationship_type="related_to", created_by="bob",
                           created_at=own.created_at, tenant_id="tenant-a")
    db.execute.side_effect = [
        query_result(own), query_result(items=[own, foreign]), query_result(items=[]),
        query_result(items=[edge]), query_result(items=[foreign]),
        query_result(items=[]), query_result(0),
    ]
    with patch("src.memory_context.get_memory_history", new_callable=AsyncMock,
               return_value={"versions": [SimpleNamespace(id=own.id), SimpleNamespace(id=foreign.id)]}):
        response = http.get(f"/api/memory/{own.id}/context")
    assert response.status_code == 200
    payload = response.json()
    assert payload["memory"]["content"] == "own content"
    assert [item["id"] for item in payload["versions"]] == [str(own.id)]
    assert payload["relationships"] == []
    assert "foreign secret" not in response.text and "foreign title" not in response.text
    assert "tenant-a" in str(db.execute.await_args_list[4].args[0].compile(
        compile_kwargs={"literal_binds": True}))


def test_context_admin_personal_is_metadata_only_and_cross_tenant_is_404(client):
    http, db, set_access = client
    set_access(access("admin"))
    personal = node(owner_id="bob", content="foreign secret", stub="private title")
    db.execute.side_effect = [
        query_result(personal), query_result(items=[personal]), query_result(items=[]),
        query_result(items=[]), query_result(items=[]), query_result(0),
    ]
    with patch("src.memory_context.get_memory_history", new_callable=AsyncMock,
               return_value={"versions": [SimpleNamespace(id=personal.id)]}):
        response = http.get(f"/api/memory/{personal.id}/context")
    assert response.status_code == 200
    assert response.json()["memory"]["redacted"] is True
    assert response.json()["versions"][0]["content"] == ""
    assert "foreign secret" not in response.text and "private title" not in response.text
    db.execute.side_effect = [query_result(None)]
    assert http.get(f"/api/memory/{uuid.uuid4()}/context").status_code == 404
    db.execute.side_effect = [query_result(node(deleted_at=personal.created_at))]
    assert http.get(f"/api/memory/{uuid.uuid4()}/context").status_code == 404


def test_context_filters_hidden_branches_and_similar_hits(client):
    http, db, _ = client
    seed = node(embedding=[0.1])
    foreign = node(owner_id="bob", content="foreign secret", stub="foreign title",
                   parent_id=seed.id)
    own_match = node(content="own similar")
    db.execute.side_effect = [
        query_result(seed), query_result(items=[seed]), query_result(items=[foreign]),
        query_result(items=[]), query_result(items=[]),
        query_result(items=[foreign, own_match]), query_result(0),
    ]
    with patch("src.memory_context.get_memory_history", new_callable=AsyncMock,
               return_value={"versions": [SimpleNamespace(id=seed.id)]}), patch(
        "src.memory_context.get_similar_memories", new_callable=AsyncMock,
        return_value={"results": [{"id": str(foreign.id), "score": 0.9},
                                  {"id": str(own_match.id), "score": 0.8}]},
    ):
        response = http.get(f"/api/memory/{seed.id}/context")
    assert response.status_code == 200
    assert response.json()["branches"] == []
    assert [item["id"] for item in response.json()["similar"]] == [str(own_match.id)]
    assert "foreign secret" not in response.text and "foreign title" not in response.text


def test_graph_all_omits_unreadable_nodes_edges_and_counts(client):
    http, db, _ = client
    own = node()
    foreign = node(owner_id="bob", content="foreign secret")
    edge = SimpleNamespace(id=uuid.uuid4(), source_id=own.id, target_id=foreign.id,
                           relationship_type="related_to", tenant_id="tenant-a")
    db.execute.side_effect = [query_result(1), query_result(items=[own, foreign]),
                              query_result(items=[edge])]
    response = http.get("/api/graph/all?prefer=recent&max_nodes=10")
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["nodes"]] == [str(own.id)]
    assert payload["edges"] == [] and payload["total"] == 1
    assert payload["left_out"] == 0 and payload["hidden_links"] == 0
    sql = str(db.execute.await_args_list[0].args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "tenant-a" in sql and "alice" in sql and "bob" not in sql


def test_graph_neighbourhood_checks_each_neighbor(client):
    http, db, _ = client
    own = node()
    foreign = node(owner_id="bob", content="foreign secret")
    edge = SimpleNamespace(id=uuid.uuid4(), source_id=own.id, target_id=foreign.id,
                           relationship_type="related_to", tenant_id="tenant-a")
    db.execute.side_effect = [query_result(own), query_result(items=[edge]),
                              query_result(items=[foreign]), query_result(items=[edge])]
    response = http.get(f"/api/graph/neighbourhood?focus={own.id}&depth=1&types=related_to")
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["nodes"]] == [str(own.id)]
    assert payload["edges"] == [] and payload["hidden_count"] == 0
    assert "foreign secret" not in response.text


def test_graph_neighbourhood_includes_authorized_project_neighbor(client):
    http, db, _ = client
    own = node()
    project = node(scope="project", scope_id="p", owner_id="bob", content="project fact")
    edge = SimpleNamespace(id=uuid.uuid4(), source_id=own.id, target_id=project.id,
                           relationship_type="derived_from", tenant_id="tenant-a")
    db.execute.side_effect = [query_result(own), query_result(items=[edge]),
                              query_result(items=[project]), query_result(items=[edge])]
    response = http.get(f"/api/graph/neighbourhood?focus={own.id}&depth=1&types=derived_from")
    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload["nodes"]} == {str(own.id), str(project.id)}
    assert payload["nodes"][1]["depth"] == 1
    assert payload["edges"][0]["type"] == "derived_from"
    assert payload["provenance"][0]["id"] == str(project.id)


def test_graph_neighbourhood_admin_personal_focus_is_redacted(client):
    http, db, set_access = client
    set_access(access("admin"))
    personal = node(owner_id="bob", content="foreign secret", stub="private title")
    db.execute.side_effect = [query_result(personal), query_result(items=[]),
                              query_result(items=[])]
    response = http.get(f"/api/graph/neighbourhood?focus={personal.id}&depth=1&types=related_to")
    assert response.status_code == 200
    assert response.json()["focus"]["content"] == ""
    assert response.json()["focus"]["redacted"] is True
    assert "foreign secret" not in response.text and "private title" not in response.text


def test_graph_admin_personal_is_redacted_and_cross_tenant_edge_is_hidden(client):
    http, db, set_access = client
    set_access(access("admin"))
    personal = node(owner_id="bob", content="foreign secret", stub="private title")
    shared = node(scope="organizational", content="shared content")
    other_tenant = node(tenant_id="tenant-b", content="tenant secret")
    allowed_edge = SimpleNamespace(id=uuid.uuid4(), source_id=personal.id,
                                   target_id=shared.id, relationship_type="related_to",
                                   tenant_id="tenant-a")
    forbidden_edge = SimpleNamespace(id=uuid.uuid4(), source_id=shared.id,
                                     target_id=other_tenant.id,
                                     relationship_type="related_to", tenant_id="tenant-b")
    db.execute.side_effect = [query_result(2),
                              query_result(items=[personal, shared, other_tenant]),
                              query_result(items=[allowed_edge, forbidden_edge])]
    response = http.get("/api/graph/all?prefer=recent")
    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload["nodes"]} == {str(personal.id), str(shared.id)}
    assert payload["edges"] == [{"id": str(allowed_edge.id), "source": str(personal.id),
                                 "target": str(shared.id), "type": "related_to"}]
    assert next(item for item in payload["nodes"] if item["id"] == str(personal.id))["redacted"]
    assert "foreign secret" not in response.text and "private title" not in response.text
    assert "tenant secret" not in response.text


def test_graph_connected_sort_still_uses_human_visible_subquery(client):
    http, db, _ = client
    db.execute.side_effect = [query_result(0), query_result(items=[])]
    response = http.get("/api/graph/all?prefer=connected")
    assert response.status_code == 200
    sql = str(db.execute.await_args_list[1].args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "JOIN (SELECT memory_nodes.id" in sql
    assert "tenant-a" in sql and "alice" in sql


def test_search_uses_human_grants_and_hides_foreign_hit_and_explanation(client):
    http, db, set_access = client
    set_access(access(agents={"agent-alice"}))
    own = node(owner_id="agent-alice")
    foreign = node(owner_id="bob", content="foreign secret")
    # Rows for the hits, then the rows the explanation looks up.
    db.execute.side_effect = [query_result(items=[own, foreign]), query_result(items=[foreign])]
    hits = [(SimpleNamespace(id=own.id), 0.7), (SimpleNamespace(id=foreign.id), 0.6)]
    with patch("src.search_adapter.search_memories", new_callable=AsyncMock,
               return_value=hits) as search:
        response = http.post("/api/search", json={"query": "secret", "explain": [str(foreign.id)]})
    assert response.status_code == 200
    payload = response.json()
    assert [hit["id"] for hit in payload["results"]] == [str(own.id)]
    assert payload["returned"] == 1 and payload["candidates"] == 2
    # A hit the person may not read is counted, never described.
    assert payload["hidden_dropped"] == {"rbac": 1} and payload["dropped"] == []
    assert payload["explain"] == [{"id": str(foreign.id), "found": False,
                                   "stage": "missing",
                                   "detail": "No memory you can read has this ID"}]
    assert "foreign secret" not in response.text
    assert search.await_args.kwargs["authorized_scopes"]["user"] == ["agent-alice", "alice"]
    assert http.post("/api/search", json={"query": "x", "identity": "bob"}).status_code == 404


def test_search_admin_cannot_read_personal_even_with_core_hit(client):
    http, db, set_access = client
    set_access(access("admin"))
    personal = node(owner_id="bob", content="foreign secret")
    shared = node(scope="organizational", content="shared allowed")
    db.execute.side_effect = [query_result(items=[personal, shared]), query_result(items=[personal])]
    hits = [(SimpleNamespace(id=personal.id), 0.9), (SimpleNamespace(id=shared.id), 0.8)]
    with patch("src.search_adapter.search_memories", new_callable=AsyncMock,
               return_value=hits) as search:
        response = http.post("/api/search", json={"query": "shared", "explain": [str(personal.id)]})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [str(shared.id)]
    assert "foreign secret" not in response.text
    assert search.await_args.kwargs["authorized_scopes"] == {"organizational": None,
                                                               "project": ["p"]}


def test_search_project_filter_and_explain_cannot_expand_scope(client):
    http, db, set_access = client
    set_access(access(human_projects=set()))
    with patch("src.search_adapter.search_memories", new_callable=AsyncMock) as search:
        assert http.post("/api/search", json={"query": "q", "project": "p"}).status_code == 404
        search.assert_not_awaited()
    db.execute.assert_not_awaited()
    set_access(access("admin", human_projects=set()))
    assert http.post("/api/search", json={"query": "q", "project": "p"}).status_code == 404


def test_core_owner_list_filter_for_bound_agents():
    filters = _build_search_filters(None, None, True, {"user": ["alice", "agent-alice"]},
                                    "tenant-a")
    sql = " AND ".join(str(part.compile(compile_kwargs={"literal_binds": True}))
                       for part in filters)
    assert "agent-alice" in sql and "alice" in sql and "tenant-a" in sql
    assert "owner_id IN" in sql


def test_export_user_rehydrates_each_row_admin_gets_metadata_csv(client):
    http, db, set_access = client
    own = node()
    foreign = node(owner_id="bob", content="foreign secret")
    items = [{"id": str(own.id)}, {"id": str(foreign.id)}]
    with patch("src.export_adapter.browse_memories", new_callable=AsyncMock,
               return_value={"items": items, "total": 2}):
        db.execute.side_effect = [query_result(items=[own, foreign])]
        response = http.get("/api/memories/export?mine=true")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [line["id"] for line in map(__import__("json").loads, response.text.splitlines())] == [str(own.id)]
    assert "foreign secret" not in response.text
    set_access(access("admin"))
    admin_item = {"id": str(foreign.id), "scope": "user", "scope_id": None,
                  "owner_id": "=CMD()", "status": "active", "redacted": True}
    with patch("src.export_adapter.browse_memories", new_callable=AsyncMock,
               return_value={"items": [admin_item], "total": 1}):
        response = http.get("/api/memories/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "'=CMD()" in response.text and "foreign secret" not in response.text


def test_export_rejects_forbidden_state_before_streaming(client):
    http, db, _ = client
    response = http.get("/api/memories/export?tab=deleted")
    assert response.status_code == 403
    db.execute.assert_not_awaited()


def test_new_read_routes_require_verified_human_principal(client):
    http, db, _ = client
    app.dependency_overrides.pop(get_access)
    uid = uuid.uuid4()
    for path in (f"/api/memory/{uid}/context", "/api/graph/all",
                 f"/api/graph/neighbourhood?focus={uid}", "/api/memories/export"):
        assert http.get(path).status_code == 401
    assert http.post("/api/search", json={"query": "x"}).status_code == 401
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_delete_preflights_closure_and_commits_once():
    from src.human_adapters import _bulk_delete

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=[query_result(items=[]), query_result(None)])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    first, second = node(), node()

    async def fetch(_db, _access, uid, **_kwargs):
        return {first.id: first, second.id: second}[uid]

    with patch("src.human_adapters._node", side_effect=fetch), patch(
        "src.human_adapters.collect_delete_nodes", new_callable=AsyncMock,
        side_effect=lambda current, *_args, **_kwargs: {current.id: current},
    ):
        response = await _bulk_delete([first.id, second.id], db, access())
    assert set(response["done"]) == {str(first.id), str(second.id)}
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
    assert db.add.call_count == 2  # two audit events in the same transaction


@pytest.mark.asyncio
async def test_bulk_delete_rejects_foreign_cascade_before_update():
    from src.human_adapters import _bulk_delete

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    own, foreign = node(), node(owner_id="bob")
    with patch("src.human_adapters._node", new_callable=AsyncMock, return_value=own), patch(
        "src.human_adapters.collect_delete_nodes", new_callable=AsyncMock,
        return_value={own.id: own, foreign.id: foreign},
    ):
        with pytest.raises(HTTPException) as error:
            await _bulk_delete([own.id], db, access())
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_relate_rolls_back_on_later_core_error():
    from src.human_adapters import _bulk_relate

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=query_result(items=[]))
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    target, first, second = node(), node(), node()

    async def fetch(_db, _access, uid, **_kwargs):
        return {target.id: target, first.id: first, second.id: second}[uid]

    with patch("src.human_adapters._node", side_effect=fetch), patch(
        "src.human_adapters.create_relationship", new_callable=AsyncMock,
        side_effect=[SimpleNamespace(id=uuid.uuid4()), ValueError("duplicate")],
    ) as create:
        with pytest.raises(HTTPException) as error:
            await _bulk_relate([first.id, second.id], target.id, "related_to", db, access())
    assert error.value.status_code == 409
    assert create.await_count == 2
    assert all(call.kwargs["commit"] is False for call in create.await_args_list)
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_delete_mixed_tenant_and_db_failure_never_partially_commit():
    from src.human_adapters import _bulk_delete

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    own, cross_tenant = node(), node(tenant_id="tenant-b")

    async def fetch(_db, _access, uid, **_kwargs):
        return {own.id: own, cross_tenant.id: cross_tenant}[uid]

    with patch("src.human_adapters._node", side_effect=fetch), patch(
        "src.human_adapters.collect_delete_nodes", new_callable=AsyncMock,
        side_effect=lambda current, *_args, **_kwargs: {current.id: current},
    ):
        with pytest.raises(HTTPException):
            await _bulk_delete([own.id, cross_tenant.id], db, access())
    db.commit.assert_not_awaited()
    db.execute.assert_not_awaited()

    db.execute.side_effect = [query_result(items=[]), RuntimeError("database write failed")]
    with patch("src.human_adapters._node", new_callable=AsyncMock, return_value=own), patch(
        "src.human_adapters.collect_delete_nodes", new_callable=AsyncMock,
        return_value={own.id: own},
    ):
        with pytest.raises(RuntimeError, match="database write failed"):
            await _bulk_delete([own.id], db, access())
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_relate_success_and_foreign_target_rejected():
    from src.human_adapters import _bulk_relate

    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=query_result(items=[]))
    db.commit = AsyncMock()
    target, first, second = node(), node(), node()

    async def fetch(_db, _access, uid, **_kwargs):
        return {target.id: target, first.id: first, second.id: second}[uid]

    with patch("src.human_adapters._node", side_effect=fetch), patch(
        "src.human_adapters.create_relationship", new_callable=AsyncMock,
        return_value=SimpleNamespace(id=uuid.uuid4()),
    ) as create:
        response = await _bulk_relate([first.id, second.id], target.id, "related_to", db, access())
    assert set(response["done"]) == {str(first.id), str(second.id)}
    assert create.await_count == 2
    db.commit.assert_awaited_once()
    assert db.add.call_count == 2

    db.commit.reset_mock()
    target.owner_id = "bob"
    with patch("src.human_adapters._node", side_effect=fetch), patch(
        "src.human_adapters.create_relationship", new_callable=AsyncMock,
    ) as create:
        with pytest.raises(HTTPException) as error:
            await _bulk_relate([first.id], target.id, "related_to", db, access())
    assert error.value.status_code == 404
    create.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_bulk_weight_stays_unavailable_without_atomic_core_operation(client):
    http, db, _ = client
    response = http.post("/api/memories/bulk", json={
        "action": "weight", "ids": [str(uuid.uuid4())], "weight": 0.9,
    })
    assert response.status_code == 422
    db.execute.assert_not_awaited()


def test_legacy_graph_and_detail_exclude_invalidated_edges(client):
    http, db, _ = client
    own = node()
    db.execute.side_effect = [query_result(items=[own]), query_result(items=[])]
    assert http.get("/api/graph").status_code == 200
    graph_sql = str(db.execute.await_args_list[1].args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "valid_until IS NULL" in graph_sql

    db.execute.side_effect = [query_result(own), query_result(0), query_result(items=[])]
    assert http.get(f"/api/memory/{own.id}").status_code == 200
    detail_sql = str(db.execute.await_args_list[-1].args[0].compile(
        compile_kwargs={"literal_binds": True}))
    assert "valid_until IS NULL" in detail_sql


def test_legacy_history_rechecks_deleted_versions(client):
    http, db, _ = client
    own = node()
    deleted = node(deleted_at=own.created_at)
    db.execute.side_effect = [query_result(own), query_result(items=[own, deleted])]
    versions = [SimpleNamespace(id=own.id, version=1, is_current=True, stub="own stub",
                                content="own content", created_at=own.created_at),
                SimpleNamespace(id=deleted.id, version=0, is_current=False,
                                stub="deleted secret", content="deleted secret",
                                created_at=deleted.created_at)]
    with patch("src.routes.get_memory_history_service", new_callable=AsyncMock,
               return_value={"versions": versions}):
        response = http.get(f"/api/memory/{own.id}/history")
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()] == [str(own.id)]
    assert "deleted secret" not in response.text
