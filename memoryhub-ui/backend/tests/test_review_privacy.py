"""Regression coverage for the eight reported access and search findings."""

import json
import re
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request, Response
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from sqlalchemy import event, func, select, text

from src import documents, retrieval, routes_admin, routes_dashboard, teams, ui_common
from src.access import Access, Grants
from src.config import Settings
from src.ui_common import DEFAULT_TENANT_SETTINGS, VIEW_AS_COOKIE, Viewer, make_view_as_cookie, viewer_from_request


def memory(content="Shared needle", **values):
    memory_id = uuid.uuid4()
    return MemoryNode(
        **{
            "id": memory_id,
            "logical_id": memory_id,
            "content": content,
            "stub": content,
            "scope": "user",
            "owner_id": "alice",
            "tenant_id": "default",
            "is_current": True,
            "version": 1,
            "status": "active",
            "storage_type": "inline",
            **values,
        }
    )


@pytest.fixture
async def privacy_context(mutation_db, monkeypatch):
    db = mutation_db
    viewer = Viewer("alice", "Alice", None, "account", "user")
    acc = Access(viewer, Grants("alice", projects={"shared-project"}, agents={"alice-agent"}), ())
    for module in (documents, retrieval, routes_admin):
        monkeypatch.setattr(module, "access_for", AsyncMock(return_value=acc))
    for module in (routes_admin, teams):
        monkeypatch.setattr(module, "viewer_from_request", lambda *_: viewer)
        monkeypatch.setattr(module, "audit", AsyncMock())
    for module in (retrieval, routes_admin):
        monkeypatch.setattr(module, "load_tenant_settings", AsyncMock(return_value=DEFAULT_TENANT_SETTINGS))
    monkeypatch.setattr(documents, "ensure_tables", AsyncMock())
    monkeypatch.setattr(teams, "ensure_tables", AsyncMock())
    monkeypatch.setattr(retrieval, "_record", AsyncMock())
    monkeypatch.setattr(retrieval, "embed", AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setitem(sqlite3.adapters, (uuid.UUID, sqlite3.PrepareProtocol), lambda value: value.hex)

    # Translate only PostgreSQL ranking primitives. Authorization, ordering,
    # limits, joins and persisted rows are exercised by the real SQL engine.
    comparator = type(MemoryNode.embedding.expression.comparator)
    monkeypatch.setattr(
        comparator,
        "cosine_distance",
        lambda self, vector: func.test_distance(self.expr, json.dumps(list(vector))),
        raising=False,
    )
    connection = await db.connection()

    def functions(sync):
        sqlite = sync.connection.dbapi_connection
        sqlite.create_function(
            "test_distance", 2, lambda raw, query: 1 - ui_common.cosine(json.loads(raw), json.loads(query))
        )
        sqlite.create_function("plainto_tsquery", 2, lambda language, query: f"%{query}%")
        sqlite.create_function("ts_rank", 2, lambda vector, query: len(vector or ""))

    await connection.run_sync(functions)

    @event.listens_for(db.bind.sync_engine, "before_cursor_execute", retval=True)
    def full_text_operator(connection, cursor, statement, parameters, context, many):
        return statement.replace(" @@ ", " LIKE "), parameters

    return SimpleNamespace(
        db=db,
        viewer=viewer,
        acc=acc,
        settings=Settings(),
        request=Request({"type": "http", "headers": []}),
    )


def proxy_request(user="alice", *, admin=False, cookie=None):
    headers = [(b"x-forwarded-user", user.encode())]
    if admin:
        headers.append((b"x-forwarded-groups", b"memoryhub-admins"))
    if cookie:
        headers.append((b"cookie", f"{VIEW_AS_COOKIE}={cookie}".encode()))
    return Request({"type": "http", "headers": headers})


def test_production_manifest_disables_account_switching():
    manifest = (Path(__file__).resolve().parents[2] / "openshift.yaml").read_text()
    assert re.search(r'name: MEMORYHUB_UI_TEST_MODE\s+value: "false"', manifest)


@pytest.mark.parametrize("enabled,admin,status", [(False, True, 404), (True, False, 403)])
async def test_switcher_cannot_elevate_regular_users(enabled, admin, status):
    settings = Settings(ui_trust_proxy_headers=True, ui_test_mode=enabled)
    with pytest.raises(HTTPException) as error:
        await routes_admin.switch_account(
            routes_admin.SwitchRequest(username="someone-else", role="operator"),
            proxy_request(admin=admin),
            Response(),
            settings,
        )
    assert error.value.status_code == status


async def test_development_admin_can_switch_but_user_cannot_reuse_cookie():
    settings = Settings(ui_trust_proxy_headers=True, ui_test_mode=True, ui_session_secret="test")
    result = await routes_admin.switch_account(
        routes_admin.SwitchRequest(username="test-user", role="user"),
        proxy_request(admin=True),
        Response(),
        settings,
    )
    assert result["username"] == "test-user"
    old_cookie = make_view_as_cookie("someone-else", "operator", settings)
    viewer = viewer_from_request(proxy_request(cookie=old_cookie), settings)
    assert (viewer.username, viewer.role) == ("alice", "user")


@pytest.mark.parametrize("admin", [False, True])
async def test_switcher_is_advertised_only_to_real_admins(privacy_context, monkeypatch, admin):
    c = privacy_context
    monkeypatch.setattr(routes_dashboard, "access_for", AsyncMock(return_value=c.acc))
    result = await routes_dashboard.me(
        proxy_request(admin=admin), c.db, Settings(ui_trust_proxy_headers=True, ui_test_mode=True),
    )
    assert result["test_mode"] is admin


@pytest.mark.parametrize("decision", ["approve", "reject", "request_changes", "restore"])
async def test_regular_user_cannot_review_enterprise_memory(privacy_context, decision):
    c = privacy_context
    proposal = memory(scope="enterprise", owner_id="default", actor_id="bob", status="pending")
    c.db.add(proposal)
    await c.db.commit()
    with pytest.raises(HTTPException) as error:
        await routes_admin.review_decision(
            str(proposal.id),
            routes_admin.ReviewDecision(decision=decision),
            c.request,
            c.db,
            c.settings,
        )
    assert error.value.status_code == 403
    assert proposal.status == "pending" and proposal.deleted_at is None


async def source_document(c, *, owner="bob", project=None, tenant="default", exists=True):
    await c.db.execute(
        text(
            "CREATE TABLE memoryhub_ui_documents (id TEXT, tenant_id TEXT, owner TEXT, title TEXT, mime TEXT, "
            "body TEXT, version INTEGER, project TEXT, created_at TEXT, updated_at TEXT)"
        )
    )
    await c.db.execute(
        text(
            "CREATE TABLE memoryhub_ui_document_links (memory_id TEXT, document_id TEXT, start_at INTEGER, "
            "end_at INTEGER, status TEXT, snippet TEXT, doc_version INTEGER)"
        )
    )
    doc_id = uuid.uuid4()
    node = memory(scope="enterprise", owner_id="default")
    c.db.add(node)
    if exists:
        await c.db.execute(
            text(
                "INSERT INTO memoryhub_ui_documents VALUES (:id, :tenant, :owner, 'Secret title', 'text/plain', "
                "'Secret before. Secret passage. Secret after.', 1, :project, NULL, NULL)"
            ),
            {"id": doc_id, "tenant": tenant, "owner": owner, "project": project},
        )
    await c.db.execute(
        text("INSERT INTO memoryhub_ui_document_links VALUES (:memory, :doc, 15, 30, 'current', 'Secret passage.', 1)"),
        {"memory": node.id, "doc": doc_id},
    )
    await c.db.commit()
    return node


@pytest.mark.parametrize("values", [{}, {"project": "private-project"}, {"tenant": "other"}, {"exists": False}])
async def test_shared_memory_never_exposes_inaccessible_document(privacy_context, values):
    c = privacy_context
    node = await source_document(c, **values)
    result = await documents.memory_source(str(node.id), c.db, c.settings, c.viewer)
    assert result == {"linked": True, "redacted": True, "status": "current"}
    assert "Secret" not in json.dumps(result)


@pytest.mark.parametrize("values", [{"owner": "alice"}, {"project": "shared-project"}])
async def test_document_context_remains_available_to_owner_or_project_member(privacy_context, values):
    c = privacy_context
    node = await source_document(c, **values)
    result = await documents.memory_source(str(node.id), c.db, c.settings, c.viewer)
    assert result["before"] + result["passage"] + result["after"] == "Secret before. Secret passage. Secret after."
    assert result["document_id"]


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_review_related_memories_are_filtered_before_similarity_limit(privacy_context, role):
    c = privacy_context
    if role == "admin":
        c.viewer.role = "admin"
        c.acc.grants = None
        c.acc.open_scopes = ("enterprise",)
    proposal = memory(scope="enterprise", status="pending", embedding=[1.0, 0.0])
    private = memory("Private content", owner_id="bob", embedding=[1.0, 0.0])
    private_source = memory("Private provenance", owner_id="bob", embedding=[1.0, 0.0])
    allowed = memory("Public candidate", scope="enterprise", embedding=[0.9, 0.1])
    c.db.add_all([proposal, private, private_source, allowed])
    await c.db.flush()
    c.db.add(
        MemoryRelationship(
            id=uuid.uuid4(),
            source_id=proposal.id,
            target_id=private_source.id,
            relationship_type="derived_from",
            tenant_id="default",
            created_by="bob",
        )
    )
    await c.db.commit()
    result = await routes_admin.review_item(str(proposal.id), c.request, c.db, c.settings, kind="approval")
    assert result["checks"]["similar"]["id"] == str(allowed.id)
    assert result["sources"] == []
    output = json.dumps(result, default=str)
    assert "Private" not in output and str(private.id) not in output and str(private_source.id) not in output


async def test_review_history_filters_private_rows_before_limit(privacy_context):
    c = privacy_context
    mine, private = memory("My memory"), memory("Private history", owner_id="bob")
    c.db.add_all([mine, private])
    await c.db.flush()
    for node in [mine, *([private] * 110)]:
        c.db.add(
            AuditLog(
                event_type="review.reject",
                actor_id="moderator",
                driver_id="moderator",
                scope=node.scope,
                owner_id=node.owner_id,
                memory_id=node.id,
                decision="allowed",
                tenant_id="default",
            )
        )
    await c.db.commit()
    result = await routes_admin.review_queue(c.request, c.db, c.settings, tab="history")
    assert [item["memory_id"] for item in result["items"]] == [str(mine.id)]
    assert str(private.id) not in json.dumps(result, default=str)


@pytest.mark.parametrize("mode", ["vector", "text", "fallback"])
async def test_search_applies_access_before_top_k(privacy_context, monkeypatch, mode):
    c = privacy_context
    if mode != "vector":
        monkeypatch.setattr(retrieval, "embed", AsyncMock(return_value=None))
    private = [
        memory(
            "Private needle",
            owner_id="bob",
            embedding=[1.0, 0.0],
            search_vector="needle needle" if mode == "text" else None,
        )
        for _ in range(55)
    ]
    allowed = memory("My needle", embedding=[0.9, 0.1], search_vector="needle" if mode == "text" else None)
    c.db.add_all([*private, allowed])
    await c.db.commit()
    result = await retrieval.run_search(c.db, c.settings, c.viewer, routes_dashboard.SearchRequest(query="needle"))
    assert [item["id"] for item in result["results"]] == [str(allowed.id)]
    assert "Private" not in json.dumps(result, default=str)


async def test_search_uses_owned_agent_identity_without_modifying_request(privacy_context):
    c = privacy_context
    own, agent = (
        memory("Human needle", embedding=[1.0, 0.0]),
        memory("Agent needle", owner_id="alice-agent", embedding=[1.0, 0.0]),
    )
    c.db.add_all([own, agent])
    await c.db.commit()
    body = routes_dashboard.SearchRequest(query="needle", identity="alice-agent")
    result = await retrieval.run_search(c.db, c.settings, c.viewer, body)
    assert result["run_as"] == body.identity == "alice-agent"
    assert [item["id"] for item in result["results"]] == [str(agent.id)]


async def test_search_rejects_unowned_identity(privacy_context):
    c = privacy_context
    with pytest.raises(HTTPException) as error:
        await retrieval.run_search(
            c.db, c.settings, c.viewer, routes_dashboard.SearchRequest(query="needle", identity="bob")
        )
    assert error.value.status_code == 403


async def test_search_project_context_does_not_grant_central_membership(privacy_context):
    c = privacy_context
    c.db.add(Project(name="shared-project", tenant_id="default", created_by="alice", invite_only=False))
    c.db.add(memory("Project needle", scope="project", scope_id="shared-project", embedding=[1.0, 0.0]))
    await c.db.commit()
    body = routes_dashboard.SearchRequest(query="needle", project="shared-project", identity="alice-agent")
    result = await retrieval.run_search(c.db, c.settings, c.viewer, body)
    assert result["results"] == []
    c.db.add(ProjectMembership(id=uuid.uuid4(), project_id="shared-project", user_id="alice-agent", joined_by="alice"))
    await c.db.commit()
    result = await retrieval.run_search(c.db, c.settings, c.viewer, body)
    assert len(result["results"]) == 1


async def test_team_rename_is_tenant_scoped(privacy_context):
    c = privacy_context
    c.viewer.role = "admin"
    await c.db.execute(text("CREATE TABLE memoryhub_ui_teams (id TEXT, tenant_id TEXT, name TEXT)"))
    team_ids = [uuid.uuid4(), uuid.uuid4()]
    for team_id, tenant, project in zip(team_ids, ["default", "other"], ["project-a", "project-b"], strict=True):
        await c.db.execute(
            text("INSERT INTO memoryhub_ui_teams VALUES (:id, :tenant, 'engineers')"), {"id": team_id, "tenant": tenant}
        )
        c.db.add(Project(name=project, tenant_id=tenant, created_by="alice"))
        await c.db.flush()
        c.db.add(ProjectMembership(id=uuid.uuid4(), project_id=project, user_id="bob", joined_by="team:engineers"))
    await c.db.commit()
    await teams.update_team(str(team_ids[0]), teams.TeamUpdate(name="platform"), c.request, c.db, c.settings)
    memberships = {row.project_id: row.joined_by for row in (await c.db.execute(select(ProjectMembership))).scalars()}
    assert memberships == {"project-a": "team:platform", "project-b": "team:engineers"}
