"""Role boundary and direct-HTTP regression tests for the existing BFF API."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.authorization import Access, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.main import app


def node(*, scope="user", owner="alice", tenant="tenant-a", scope_id=None, parent_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant, owner_id=owner, scope=scope,
        scope_id=scope_id, status="active", content="private text", stub="private stub",
        weight=0.8, branch_type=None, version=1, is_current=True,
        parent_id=parent_id, previous_version_id=None, metadata_={"secret": "value"},
        created_at=datetime(2026, 1, 1, tzinfo=UTC), updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        expires_at=None, deleted_at=None, storage_type="inline", content_ref=None,
    )


def result(*, scalar=None, items=None):
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar_one.return_value = scalar
    r.scalars.return_value.all.return_value = items or []
    r.all.return_value = items or []
    r.fetchall.return_value = []
    return r


def access(role="user", username="alice", tenant="tenant-a", **kwargs):
    return Access(
        Principal(username, role, tenant),
        moderation_scopes={"project", "campaign", "role", "organizational"},
        **kwargs,
    )


@pytest.fixture(autouse=True)
def clear_dependencies():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id="tenant-a")
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_direct_http_requires_local_oauth_proxy_and_verified_username():
    settings = Settings(ui_tenant_id="tenant-a", ui_admin_users="alice", ui_allowed_users="bob")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result(items=[]))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app, client=("203.0.113.1", 5000)),
                           base_url="http://test") as client:
        forged = await client.get("/api/graph", headers={"x-forwarded-user": "alice", "x-role": "admin"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        anonymous = await client.get("/api/graph")
        unassigned = await client.get("/api/graph", headers={"x-forwarded-user": "charlie"})
        admin = await client.get("/api/graph", headers={"x-forwarded-user": "alice"})

    assert forged.status_code == 401
    assert anonymous.status_code == 401
    assert unassigned.status_code == 403
    assert admin.status_code == 200


@pytest.mark.asyncio
async def test_empty_access_lists_say_so_instead_of_refusing_everyone():
    """A clean deploy with no bootstrap admin answers 503 with the fix, not a bare 403 (#667 review)."""
    # Explicit empty lists: Settings would otherwise read them from the environment.
    app.dependency_overrides[get_settings] = lambda: Settings(
        ui_tenant_id="tenant-a", ui_admin_users="", ui_allowed_users="",
    )
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph", headers={"x-forwarded-user": "alice"})
    assert response.status_code == 503
    assert "MEMORYHUB_UI_ADMIN_USERS" in response.json()["detail"]


@pytest.mark.asyncio
async def test_local_mode_uses_the_configured_user_and_ignores_identity_headers(monkeypatch):
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    settings = Settings(ui_tenant_id="tenant-a", ui_auth_mode="local", ui_local_user="dev",
                        ui_admin_users="dev", ui_allowed_users="bob")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result(items=[]))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db
    # A non-loopback peer (Compose port mapping) is fine in local mode ...
    async with AsyncClient(transport=ASGITransport(app=app, client=("172.18.0.1", 5000)),
                           base_url="http://test") as client:
        me = await client.get("/api/me", headers={"x-forwarded-user": "bob"})
    assert me.status_code == 200
    # ... and a forged header never changes who you are.
    assert me.json()["username"] == "dev" and me.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_local_mode_is_refused_in_a_cluster_and_without_a_user(monkeypatch):
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")
    app.dependency_overrides[get_settings] = lambda: Settings(
        ui_tenant_id="tenant-a", ui_auth_mode="local", ui_local_user="dev", ui_admin_users="dev")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get("/api/me")
    assert refused.status_code == 503 and "inside a cluster" in refused.json()["detail"]
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST")
    app.dependency_overrides[get_settings] = lambda: Settings(
        ui_tenant_id="tenant-a", ui_auth_mode="local", ui_admin_users="dev")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/api/me")
    assert missing.status_code == 503 and "MEMORYHUB_UI_LOCAL_USER" in missing.json()["detail"]


@pytest.mark.asyncio
async def test_role_cannot_be_supplied_by_request_header():
    settings = Settings(ui_tenant_id="tenant-a", ui_admin_users="alice", ui_allowed_users="bob")
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result(items=[]))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/contradictions/{uuid.uuid4()}",
            headers={"x-forwarded-user": "bob", "x-role": "admin", "x-forwarded-groups": "admins"},
            json={"resolved": True},
        )
    assert response.status_code == 403


def test_independent_memory_capabilities_and_tenant_boundary():
    own = node()
    other = node(owner="bob")
    shared = node(scope="project", owner="bob", scope_id="p1")
    foreign = node(tenant="tenant-b")
    user = access(projects={"p1"}, human_projects={"p1"})
    admin = access(role="admin", projects={"p1"}, project_admins={"p1"},
                   human_projects={"p1"}, human_project_admins={"p1"})

    assert user.can_read(own) and user.can_delete(own)
    assert not user.can_read(other) and not user.can_delete(other)
    assert user.can_read(shared) and not user.can_delete(shared)
    assert not user.can_read(foreign) and not admin.can_read(foreign)
    # Admins never read personal memories, not even their metadata (#667).
    assert not admin.can_read(other)
    assert not admin.can_delete(other)  # Admin does not inherit User's personal writes
    assert admin.can_delete(shared)
    assert not user.can_delete(node(scope="organizational"))
    quarantined = node()
    quarantined.status = "quarantined"
    assert not user.can_delete(quarantined)
    assert user.can_read(node(scope="organizational", owner="bob"))
    assert not admin.can_delete(node(scope="user", owner="admin"))


def test_enterprise_is_unavailable_to_admin_but_remains_readable_to_users():
    enterprise = node(scope="enterprise", owner="alice")
    admin = access(role="admin", username="alice")
    assert not admin.can_read(enterprise)
    assert admin.hides_content(enterprise)
    assert not admin.can_write(enterprise)
    assert not admin.can_delete(enterprise)
    assert not admin.can_moderate(enterprise)
    for clause in (admin.clause(), admin.content_clause()):
        sql = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "enterprise" not in sql
    assert access().can_read(enterprise)


def test_agent_membership_is_not_human_project_or_role_authority():
    project = node(scope="project", owner="agent-a", scope_id="p1")
    role_memory = node(scope="role", owner="agent-a", scope_id="reviewer")
    user = access(agents={"agent-a"}, projects={"p1"}, project_admins={"p1"}, roles={"reviewer"})
    admin = access(role="admin", agents={"agent-a"}, projects={"p1"}, project_admins={"p1"},
                   roles={"reviewer"})
    assert not user.can_read(project)
    assert not user.can_write(project)
    assert not user.can_delete(project)
    assert not user.can_read(role_memory)
    assert not admin.can_write(project)
    assert not admin.can_delete(project)
    assert not admin.can_review(project)
    assert not admin.can_moderate(project)
    assert admin.hides_content(project)
    assert "p1" not in str(user.clause().compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_agent_only_project_grant_cannot_use_existing_human_memory_routes():
    project = node(scope="project", owner="agent-a", scope_id="p1")
    db = AsyncMock()
    db.execute.return_value = result(scalar=project)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access(
        agents={"agent-a"}, projects={"p1"}, project_admins={"p1"},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        detail = await client.get(f"/api/memory/{project.id}")
        deleted = await client.delete(f"/api/memory/{project.id}")
    assert detail.status_code == 404
    assert deleted.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_grants_are_loaded_from_tenant_bound_owner_and_membership_rows():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        result(items=["agent-a"]), result(items=[("project-a", "admin", "alice")]),
        result(items=[("reviewer", "alice")]),
        result(items=[(uuid.UUID(int=1), "project-a")]),
    ])
    grants = await get_access(
        Principal("alice", "user", "tenant-a"), db, Settings(ui_tenant_id="tenant-a"),
    )
    assert grants.identities == {"alice", "agent-a"}
    assert grants.projects == {"project-a"}
    assert grants.project_admins == {"project-a"}
    assert grants.human_project_admins == {"project-a"}
    assert grants.roles == {"reviewer"}
    assert grants.human_roles == {"reviewer"}
    assert grants.campaigns == {str(uuid.UUID(int=1))}
    assert grants.human_campaigns == {str(uuid.UUID(int=1))}
    assert grants.can_read(node(owner="agent-a"))
    assert grants.can_read(node(scope="project", scope_id="project-a"))
    assert grants.can_read(node(scope="role", scope_id="reviewer"))
    assert grants.can_read(node(scope="campaign", owner=str(uuid.UUID(int=1))))
    for call in db.execute.await_args_list:
        sql = str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        assert "tenant-a" in sql


@pytest.mark.asyncio
async def test_admin_search_excludes_personal_content_in_sql():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result(items=[]))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access(role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/graph/search", params={"q": "private"})
    assert response.status_code == 200
    sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "memory_nodes.scope = 'project'" in sql
    assert "memory_nodes.scope = 'organizational'" in sql
    assert "memory_nodes.scope = 'enterprise'" not in sql


@pytest.mark.asyncio
async def test_admin_and_foreign_user_get_no_personal_detail():
    personal = node(owner="bob")
    db = AsyncMock()
    # Even if a row slipped past the SQL predicate, the object check refuses it.
    db.execute = AsyncMock(side_effect=[result(scalar=personal), result(scalar=0), result(items=[])])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access(role="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/memory/{personal.id}")
    assert response.status_code == 404
    assert "bob" not in response.text

    db.execute = AsyncMock(return_value=result(scalar=personal))
    app.dependency_overrides[get_access] = lambda: access(role="user")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get(f"/api/memory/{personal.id}")
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_user_can_read_own_personal_memory_through_http():
    personal = node(owner="alice")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result(scalar=personal), result(scalar=0), result(items=[])])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/memory/{personal.id}")
    assert response.status_code == 200
    assert response.json()["content"] == "private text"


@pytest.mark.asyncio
async def test_user_client_list_is_owner_and_tenant_filtered():
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access(agents={"mine"})
    base = {
        "client_name": "Agent", "identity_type": "user", "default_scopes": ["memory:read:user"],
        "active": True, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }
    payload = [
        {**base, "client_id": "mine", "tenant_id": "tenant-a"},
        {**base, "client_id": "other", "tenant_id": "tenant-a"},
        {**base, "client_id": "mine", "tenant_id": "tenant-b"},
    ]
    upstream_response = MagicMock()
    upstream_response.json.return_value = payload
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/clients")
    assert response.status_code == 200
    assert [(c["client_id"], c["tenant_id"]) for c in response.json()] == [("mine", "tenant-a")]


@pytest.mark.asyncio
async def test_user_client_creation_records_proven_owner():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = result(scalar=False)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    created = {
        "client_id": "new-agent", "client_name": "New agent", "identity_type": "user",
        "tenant_id": "tenant-a", "default_scopes": ["memory:read:user"], "active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "client_secret": "once", "api_key": "once",
    }
    upstream_response = MagicMock()
    upstream_response.json.return_value = created
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/clients", json={
                "client_id": "new-agent", "client_name": "New agent", "tenant_id": "tenant-a",
                "default_scopes": ["memory:read:user"],
            })
    assert response.status_code == 201
    assert upstream.await_args.kwargs["json_body"]["owner"] == "alice"
    assert upstream.await_args.kwargs["json_body"]["tenant_id"] == "tenant-a"
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_cannot_review_or_reach_unowned_client_credentials():
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    with patch("src.routes._admin_request", new_callable=AsyncMock) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            review = await client.patch(f"/api/contradictions/{uuid.uuid4()}", json={"resolved": True})
            rotate = await client.post("/api/clients/other-agent/rotate-api-key")
        upstream.assert_not_awaited()
    assert review.status_code == 403
    assert rotate.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_client_creation_and_scope_escalation_denied():
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access(agents={"mine"})
    with patch("src.routes._admin_request", new_callable=AsyncMock) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.post("/api/clients", json={
                "client_id": "x", "client_name": "X", "tenant_id": "tenant-b",
            })
            privileged = await client.post("/api/clients", json={
                "client_id": "x", "client_name": "X", "tenant_id": "tenant-a",
                "default_scopes": ["memory:admin"],
            })
        upstream.assert_not_awaited()
    assert foreign.status_code == 403
    assert privileged.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_rotate_privileged_mcp_client_into_dashboard_access():
    app.dependency_overrides[get_access] = lambda: access(role="admin")
    privileged = {
        "client_id": "technical", "tenant_id": "tenant-a", "identity_type": "service",
        "default_scopes": ["memory:admin"],
    }
    upstream_response = MagicMock()
    upstream_response.json.return_value = privileged
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/clients/technical/rotate-api-key")
        assert upstream.await_count == 1  # detail lookup, no credential rotation
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_checks_entire_closure_before_bulk_update():
    root = node()
    child = node(owner="bob", parent_id=root.id)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result(scalar=root), result(items=[child]), result(items=[child])])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/memory/{root.id}")
    assert response.status_code == 403
    assert db.execute.await_count == 3
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_walks_nested_branches_before_single_update():
    root = node()
    child = node(parent_id=root.id)
    grandchild = node(parent_id=child.id)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        result(scalar=root), result(items=[child, grandchild]),
        result(items=[child, grandchild]), result(), result(),
    ])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/memory/{root.id}")
    assert response.status_code == 204
    assert db.execute.await_count == 5
    update_params = db.execute.await_args.args[0].compile().params
    selected_ids = next(value for value in update_params.values() if isinstance(value, list))
    assert set(selected_ids) == {root.id, child.id, grandchild.id}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_rule_owner_and_layer_cannot_be_forged():
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: access()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        layer = await client.post("/api/rules", json={"name": "x", "tier": "regex", "action": "block",
                                                      "layer": "organizational"})
        owner = await client.post("/api/rules", json={"name": "x", "tier": "regex", "action": "block",
                                                      "layer": "user", "owner_id": "bob"})
    assert layer.status_code == 403
    assert owner.status_code == 403
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_rule_history_hides_another_users_personal_rule_from_admin():
    app.dependency_overrides[get_access] = lambda: access(role="admin")
    db = AsyncMock()
    db.execute.return_value = result(scalar=SimpleNamespace(tenant_id="tenant-a", layer="user", owner_id="bob"))
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/rules/{uuid.uuid4()}/history")
    assert response.status_code == 404
    db.execute.assert_awaited_once()
