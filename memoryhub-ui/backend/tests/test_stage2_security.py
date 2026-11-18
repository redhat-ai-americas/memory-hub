"""Human session and role-policy checks for the existing BFF operations."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.authorization import Access, Principal, get_access, get_principal
from src.config import Settings, get_settings
from src.database import get_db
from src.main import app
from src.routes import _can_change_rule, _can_read_rule, _reject_existing_identity_claim


def _access(role="user", *, projects=(), project_admins=(), agents=()):
    return Access(
        principal=Principal("alice", role, "tenant-a"),
        projects=set(projects),
        project_admins=set(project_admins),
        human_projects=set(projects),
        human_project_admins=set(project_admins),
        agents=set(agents),
        moderation_scopes={"project", "campaign", "role", "organizational"},
    )


def _db_result(*, scalar=None, items=(), row=None):
    result = MagicMock()
    result.scalar_one.return_value = scalar
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = list(items)
    result.all.return_value = list(items)
    result.one_or_none.return_value = row
    return result


@pytest.fixture(autouse=True)
def _reset():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        ui_tenant_id="tenant-a", ui_admin_users="admin", ui_allowed_users="alice"
    )
    db = AsyncMock()
    db.execute.return_value = _db_result(scalar=False)
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_me_uses_verified_proxy_identity_and_server_role_tenant():
    db = AsyncMock()
    db.execute.return_value = _db_result()
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user = await client.get(
            "/api/me?role=admin&tenant_id=evil&owner_id=bob",
            headers={"x-forwarded-user": "alice", "x-role": "admin", "x-tenant-id": "evil"},
        )
        admin = await client.get("/api/me", headers={"x-forwarded-user": "admin"})
    assert user.status_code == admin.status_code == 200
    assert user.headers["cache-control"] == admin.headers["cache-control"] == "no-store"
    assert (user.json()["username"], user.json()["role"], user.json()["tenant_id"]) == (
        "alice", "user", "tenant-a"
    )
    assert (admin.json()["role"], admin.json()["tenant_id"]) == ("admin", "tenant-a")
    assert admin.json()["access"]["hidden_scopes"] == ["enterprise", "user"]
    for body in (user.json(), admin.json()):
        assert body["source"] == "oauth-proxy"
        assert not {"api_key", "access_token", "refresh_token", "scopes"} & body.keys()


@pytest.mark.asyncio
async def test_session_rejects_missing_invalid_unknown_and_duplicate_identity():
    db = AsyncMock()
    db.execute.return_value = _db_result()
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/api/me")
        malformed = await client.get("/api/me", headers={"x-forwarded-user": "  "})
        unknown = await client.get("/api/me", headers={"x-forwarded-user": "unknown"})
        duplicate = await client.get("/api/me", headers=[
            ("x-forwarded-user", "alice"), ("x-forwarded-user", "admin")
        ])
        remote = await client.get("/api/me", headers={"x-forwarded-user": "admin"})
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.1", 4123)), base_url="http://test"
    ) as client:
        forged_remote = await client.get("/api/me", headers={"x-forwarded-user": "admin"})
    assert (missing.status_code, malformed.status_code, unknown.status_code, duplicate.status_code) == (
        401, 401, 403, 401
    )
    assert remote.status_code == 200
    assert forged_remote.status_code == 401
    assert db.execute.await_count == 3  # only authenticated, allowlisted principals reach DB


@pytest.mark.asyncio
async def test_unknown_role_and_incomplete_tenant_fail_closed():
    with pytest.raises(HTTPException) as exc:
        await get_access(Principal("alice", "operator", "tenant-a"), AsyncMock(), Settings())
    assert exc.value.status_code == 403
    app.dependency_overrides[get_settings] = lambda: Settings(ui_tenant_id="", ui_allowed_users="alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/auth/status", headers={"x-forwarded-user": "alice"})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_bootstrap_endpoints_use_existing_oauth_proxy_contract_and_real_counts():
    access = _access("admin", projects={"p1"}, project_admins={"p1"})
    app.dependency_overrides[get_access] = lambda: access
    app.dependency_overrides[get_principal] = lambda: access.principal
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_db_result(scalar=4), _db_result(scalar=2)])
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/auth/status")
        counts = await client.get("/api/nav-counts")
        features = await client.get("/api/nav-features")
        logout = await client.post("/api/auth/logout")
        unsupported_login = await client.post("/api/auth/login", json={"role": "admin"})
    assert status.json()["mode"] == "oauth-proxy"
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["role"] == "admin"
    assert counts.json() == {"memories": 4, "review_queue": 2}
    assert features.json() == {}
    assert logout.json() == {"ok": True, "redirect": "/oauth/sign_out", "method": "GET"}
    assert unsupported_login.status_code == 405
    review_sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tenant-a" in review_sql and "p1" in review_sql
    assert "driver_id IS NULL" in review_sql and "actor_id IS NULL" in review_sql


def test_delete_requires_concrete_project_grant_for_both_roles():
    memory = SimpleNamespace(
        tenant_id="tenant-a", status="active", scope="project", scope_id="p1",
        owner_id="bob", actor_id="bob",
    )
    assert not _access("user", projects={"p1"}).can_delete(memory)
    assert not _access("admin").can_delete(memory)
    assert not _access("admin", projects={"p1"}).can_delete(memory)
    assert _access("admin", projects={"p1"}, project_admins={"p1"}).can_delete(memory)
    memory.tenant_id = "tenant-b"
    assert not _access("admin", projects={"p1"}, project_admins={"p1"}).can_delete(memory)


def test_admin_content_requires_configured_scope_and_object_membership():
    admin = _access("admin")
    enterprise = SimpleNamespace(scope="enterprise", scope_id=None, owner_id="bob")
    organization = SimpleNamespace(scope="organizational", scope_id=None, owner_id="bob")
    project = SimpleNamespace(scope="project", scope_id="p1", owner_id="bob")
    assert admin.hides_content(enterprise)
    assert not admin.hides_content(organization)
    assert admin.hides_content(project)
    assert not _access("admin", projects={"p1"}).hides_content(project)
    admin.moderation_scopes.clear()
    assert admin.hides_content(organization)


@pytest.mark.asyncio
async def test_new_client_cannot_claim_existing_memory_or_membership_identity():
    db = AsyncMock()
    db.execute.return_value = _db_result(scalar=True)
    settings = Settings(ui_tenant_id="tenant-a", ui_allowed_users="alice", ui_admin_users="admin")
    with pytest.raises(HTTPException) as occupied:
        await _reject_existing_identity_claim(db, settings, "orphan-owner", "tenant-a")
    assert occupied.value.status_code == 409
    sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert all(name in sql for name in (
        "memory_nodes", "project_memberships", "role_assignments", "curator_rules", "conversation_threads",
    ))
    assert "tenant-a" in sql and "orphan-owner" in sql
    with pytest.raises(HTTPException) as human:
        await _reject_existing_identity_claim(db, settings, "admin", "tenant-a")
    assert human.value.status_code == 409
    assert db.execute.await_count == 1

    app.dependency_overrides[get_access] = lambda: _access("user")
    app.dependency_overrides[get_db] = lambda: db
    with patch("src.routes._admin_request", new_callable=AsyncMock) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/clients", json={
                "client_id": "orphan-owner", "client_name": "Claim", "tenant_id": "tenant-a",
                "default_scopes": ["memory:read:user"],
            })
    assert response.status_code == 409
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_filters_each_version_and_redacts_unjoined_admin_project():
    seed_id, foreign_id = uuid.uuid4(), uuid.uuid4()
    seed = SimpleNamespace(
        id=seed_id, tenant_id="tenant-a", status="active", scope="user",
        scope_id=None, owner_id="alice",
    )
    foreign = SimpleNamespace(
        id=foreign_id, tenant_id="tenant-a", status="active", scope="user",
        scope_id=None, owner_id="bob",
    )
    versions = [
        SimpleNamespace(id=seed_id, version=2, is_current=True, stub="own", content="own text",
                        created_at=datetime(2026, 1, 2, tzinfo=UTC)),
        SimpleNamespace(id=foreign_id, version=1, is_current=False, stub="foreign", content="foreign text",
                        created_at=datetime(2026, 1, 1, tzinfo=UTC)),
    ]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_db_result(scalar=seed), _db_result(items=[seed, foreign])])
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: _access("user")
    with patch("src.routes.get_memory_history_service", new=AsyncMock(return_value={"versions": versions})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/memory/{seed_id}/history")
    assert response.status_code == 200
    assert [(item["id"], item["content"]) for item in response.json()] == [(str(seed_id), "own text")]

    project = SimpleNamespace(
        id=seed_id, tenant_id="tenant-a", status="active", scope="project",
        scope_id="foreign-project", owner_id="bob",
    )
    db.execute = AsyncMock(side_effect=[_db_result(scalar=project), _db_result(items=[project])])
    app.dependency_overrides[get_access] = lambda: _access("admin")
    with patch("src.routes.get_memory_history_service", new=AsyncMock(return_value={"versions": versions[:1]})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/memory/{seed_id}/history")
    assert response.status_code == 200
    assert response.json()[0]["content"] == ""
    assert response.json()[0]["stub"] == "Content hidden"


@pytest.mark.asyncio
async def test_admin_delete_outside_project_grant_never_mutates():
    memory = SimpleNamespace(
        id=uuid.uuid4(), tenant_id="tenant-a", status="active", scope="project",
        scope_id="p2", owner_id="bob", actor_id="bob", deleted_at=None,
    )
    db = AsyncMock()
    db.execute.return_value = _db_result(scalar=memory)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: _access("admin", projects={"p1"}, project_admins={"p1"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(f"/api/memory/{memory.id}")
    assert response.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_cannot_assign_arbitrary_privileged_or_unscoped_project_write():
    app.dependency_overrides[get_access] = lambda: _access("admin")
    with patch("src.routes._admin_request", new_callable=AsyncMock) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            statuses = []
            for scopes in (
                ["memory:admin"], ["memory:write:project"], ["memory:approve:enterprise"],
                ["memory:read"], ["memory:read:user"], ["memory:read:enterprise"], ["arbitrary"],
            ):
                response = await client.post("/api/clients", json={
                    "client_id": "client-a", "client_name": "Agent", "tenant_id": "tenant-a",
                    "identity_type": "service", "default_scopes": scopes,
                })
                statuses.append(response.status_code)
            forged_owner = await client.post("/api/clients", json={
                "client_id": "client-a", "client_name": "Agent", "tenant_id": "tenant-a",
                "default_scopes": ["memory:read:user"], "owner": "bob",
            })
        upstream.assert_not_awaited()
    assert statuses == [403] * 7
    assert forged_owner.status_code == 422


@pytest.mark.asyncio
async def test_admin_cannot_escalate_existing_client_scopes():
    app.dependency_overrides[get_access] = lambda: _access("admin")
    upstream_response = MagicMock()
    upstream_response.json.return_value = {
        "client_id": "client-a", "tenant_id": "tenant-a", "identity_type": "user",
        "default_scopes": ["memory:read:user"],
    }
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                "/api/clients/client-a", json={"default_scopes": ["memory:admin"]}
            )
    assert response.status_code == 403
    assert upstream.await_count == 1  # lookup only; no PATCH to Auth


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_type,scopes", [
    ("user", ["memory:read:user"]),
    ("service", ["memory:read:project"]),
])
async def test_admin_cannot_extract_foreign_agent_credentials(identity_type, scopes):
    app.dependency_overrides[get_access] = lambda: _access("admin")
    upstream_response = MagicMock()
    upstream_response.json.return_value = {
        "client_id": "bob-agent", "tenant_id": "tenant-a", "identity_type": identity_type,
        "default_scopes": scopes,
    }
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            secret = await client.post("/api/clients/bob-agent/rotate-secret")
            key = await client.post("/api/clients/bob-agent/rotate-api-key")
            scope = await client.patch(
                "/api/clients/bob-agent", json={
                    "default_scopes": (["memory:read:project", "memory:read:organizational"]
                                       if identity_type == "service" else ["memory:read"]),
                },
            )
    assert (secret.status_code, key.status_code, scope.status_code) == (403, 403, 403)
    assert all(call.args[1] == "GET" for call in upstream.await_args_list)


@pytest.mark.asyncio
async def test_admin_created_service_client_is_bound_and_user_client_denied():
    app.dependency_overrides[get_access] = lambda: _access("admin")
    upstream_response = MagicMock()
    upstream_response.json.return_value = {
        "client_id": "admin-agent", "client_name": "Admin Agent", "identity_type": "service",
        "tenant_id": "tenant-a", "default_scopes": ["memory:read:project"],
        "redirect_uris": None, "public": False, "active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "client_secret": "once", "api_key": "once",
    }
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/clients", json={
                "client_id": "admin-agent", "client_name": "Admin Agent", "tenant_id": "tenant-a",
                "identity_type": "service", "default_scopes": ["memory:read:project"],
            })
            denied = await client.post("/api/clients", json={
                "client_id": "foreign-user-agent", "client_name": "Agent", "tenant_id": "tenant-a",
                "identity_type": "user", "default_scopes": ["memory:read:user"],
            })
    assert response.status_code == 201, response.text
    assert denied.status_code == 403
    assert upstream.await_count == 1
    assert upstream.await_args.kwargs["json_body"]["owner"] == "alice"


@pytest.mark.asyncio
async def test_user_client_mutation_forwards_verified_owner_to_auth():
    app.dependency_overrides[get_access] = lambda: _access("user", agents={"alice-agent"})
    upstream_response = MagicMock()
    upstream_response.json.return_value = {
        "client_id": "alice-agent", "client_name": "Alice Agent", "identity_type": "user",
        "tenant_id": "tenant-a", "default_scopes": ["memory:read"],
        "redirect_uris": None, "public": False, "active": True,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }
    with patch("src.routes._admin_request", new=AsyncMock(return_value=upstream_response)) as upstream:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch("/api/clients/alice-agent", json={"client_name": "Alice Agent"})
    assert response.status_code == 200, response.text
    assert [call.kwargs["owner"] for call in upstream.await_args_list] == ["alice", "alice"]
    assert [call.args[1] for call in upstream.await_args_list] == ["GET", "PATCH"]


def test_personal_rule_read_and_write_are_independent():
    own = SimpleNamespace(tenant_id="tenant-a", layer="user", owner_id="alice")
    foreign = SimpleNamespace(tenant_id="tenant-a", layer="user", owner_id="bob")
    assert _can_read_rule(_access("user"), own)
    assert not _can_read_rule(_access("user"), foreign)
    assert _can_read_rule(_access("admin"), foreign)
    assert not _can_change_rule(_access("admin"), foreign)
    assert _can_change_rule(_access("admin"), own)


@pytest.mark.asyncio
@pytest.mark.parametrize("self_field", ["reporter", "owner_id", "actor_id", "driver_id"])
async def test_review_rejects_self_and_linked_agent_aliases(self_field):
    memory = SimpleNamespace(
        id=uuid.uuid4(), tenant_id="tenant-a", scope="project", scope_id="p1",
        owner_id="bob", actor_id="bob", driver_id="bob", deleted_at=None,
    )
    report = SimpleNamespace(
        id=uuid.uuid4(), memory_id=memory.id, reporter="bob", resolved=False,
        observed_behavior="conflict", confidence=0.9,
        created_at=datetime(2026, 1, 1, tzinfo=UTC), resolved_at=None,
    )
    if self_field == "reporter":
        report.reporter = "alice"
    else:
        setattr(memory, self_field, "agent-a")
    db = AsyncMock()
    db.execute.return_value = _db_result(row=(report, memory))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: _access(
        "admin", projects={"p1"}, project_admins={"p1"}, agents={"agent-a"}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/api/contradictions/{report.id}", json={"resolved": True})
    assert response.status_code == 403
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_without_project_admin_grant_is_hidden():
    memory = SimpleNamespace(
        tenant_id="tenant-a", scope="project", scope_id="p2", owner_id="bob",
        actor_id="bob", driver_id="bob",
    )
    report = SimpleNamespace(id=uuid.uuid4(), reporter="bob")
    db = AsyncMock()
    db.execute.return_value = _db_result(row=(report, memory))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_access] = lambda: _access("admin", projects={"p1"}, project_admins={"p1"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/api/contradictions/{report.id}", json={"resolved": True})
    assert response.status_code == 404
    db.commit.assert_not_awaited()
