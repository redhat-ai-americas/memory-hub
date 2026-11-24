"""Authorization and contract checks for the Stage 2.1 human adapters."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.curation import CuratorRule
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, Principal, get_access
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import (
    _human_can_see_content,
    _human_content_clause,
    _record_human_audit,
    get_embedding_service,
)
from src.main import app


def result(value=None, *, items=None, row=None, rows=None):
    answer = MagicMock()
    answer.scalar_one_or_none.return_value = value
    answer.scalar_one.return_value = value
    answer.scalars.return_value.all.return_value = items if items is not None else []
    answer.one.return_value = row
    answer.all.return_value = rows if rows is not None else []
    return answer


def node(**changes):
    values = {
        "id": uuid.uuid4(), "tenant_id": "tenant-a", "scope": "user", "scope_id": None,
        "owner_id": "alice", "actor_id": "alice", "status": "active", "deleted_at": None,
        "is_current": True, "parent_id": None, "weight": 0.7,
        "content": "Entity", "stub": "Memory stub", "branch_type": None,
        "metadata_": None, "version": 1,
        "driver_id": None, "domains": [], "content_type": "experiential",
        "relevant_until": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def access(role="user", **changes):
    data = {"principal": Principal("alice", role, "tenant-a"), "projects": {"p"},
            "project_admins": {"p"}, "human_projects": {"p"},
            "human_project_admins": {"p"},
            "moderation_scopes": {"project", "organizational"}}
    data.update(changes)
    return Access(**data)


@pytest.fixture
def client():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.execute.return_value = result(None)
    current = access()
    settings = Settings(
        ui_tenant_id="tenant-a", ui_allowed_users="alice,bob", ui_admin_users="admin",
        embedding_url="http://embed.test/embed",
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_access] = lambda: current
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_embedding_service] = lambda: MagicMock()
    with TestClient(app) as test_client:
        yield test_client, session, lambda value: app.dependency_overrides.__setitem__(get_access, lambda: value)
    app.dependency_overrides.clear()


def test_independent_human_write_policy():
    personal = node()
    project = node(scope="project", scope_id="p")
    foreign = node(owner_id="bob")
    other_tenant = node(tenant_id="tenant-b", scope="project", scope_id="p")
    assert access().can_write(personal)
    assert access().can_write(project)
    assert not access().can_write(foreign)
    assert not access("admin").can_write(personal)
    assert access("admin").can_write(project)
    assert not access("admin").can_write(other_tenant)
    assert not access("admin").can_write(node(scope="organizational"))
    assert access("admin", admin_write_scopes={"organizational"}).can_write(node(scope="organizational"))


def test_bound_agent_personal_memory_does_not_grant_project_membership():
    viewer = access(agents={"agent-owned"}, projects={"agent-project"}, human_projects=set())
    assert _human_can_see_content(viewer, node(owner_id="agent-owned"))
    assert not _human_can_see_content(viewer, node(scope="project", scope_id="agent-project"))
    sql = str(_human_content_clause(viewer).compile(compile_kwargs={"literal_binds": True}))
    assert "agent-owned" in sql
    assert "agent-project" not in sql


def test_human_audit_stages_verified_actor_in_existing_transaction():
    session = MagicMock(spec=AsyncSession)
    memory_id = uuid.uuid4()
    _record_human_audit(session, access(), "memory.update", "project", "bob", memory_id,
                        {"project_id": "p"})
    staged = session.add.call_args.args[0]
    assert isinstance(staged, AuditLog)
    assert (staged.actor_id, staged.driver_id, staged.tenant_id) == ("alice", "alice", "tenant-a")
    assert (staged.scope, staged.owner_id, staged.memory_id) == ("project", "bob", memory_id)
    assert staged.decision == "allowed"
    session.commit.assert_not_called()


def test_new_routes_require_unambiguous_proxy_principal(client):
    http, _db, _set_access = client
    app.dependency_overrides.pop(get_access)
    assert http.get("/api/projects").status_code == 401
    assert http.post("/api/memories", json={"content": "x", "scope": "user"}).status_code == 401
    duplicate = [("x-forwarded-user", "alice"), ("x-forwarded-user", "admin")]
    assert http.get("/api/entities", headers=duplicate).status_code == 401


def test_project_create_admin_only_and_server_owned(client):
    http, db, set_access = client
    with patch("src.human_adapters.core_create_project", new_callable=AsyncMock) as create, patch(
        "src.human_adapters.add_project_member", new_callable=AsyncMock, return_value=True,
    ):
        assert http.post("/api/projects", json={"name": "p"}).status_code == 403
        set_access(access("admin"))
        response = http.post("/api/projects", json={"name": "new", "members": [{"user_id": "bob", "role": "member"}]})
        assert response.status_code == 201
        assert response.json() == {"name": "new"}
        create.assert_awaited_once()
        assert create.await_args.args[2:4] == ("tenant-a", "alice")
        db.commit.assert_awaited_once()
        assert http.post("/api/projects", json={"name": "x", "tenant_id": "tenant-b"}).status_code == 422
        assert http.post("/api/projects", json={"name": "x", "members": [
            {"user_id": "unknown", "role": "admin"},
        ]}).status_code == 422


def test_project_list_filters_user_visibility_and_admin_tenant(client):
    http, db, set_access = client
    project = SimpleNamespace(name="p", tenant_id="tenant-a")
    db.execute.side_effect = [result(items=[project])]
    with patch("src.human_adapters._project_row", new_callable=AsyncMock,
               return_value={"name": "p", "campaigns": [], "members": 1}):
        response = http.get("/api/projects?mine=false")
        assert response.status_code == 200 and response.json()["total"] == 1
        assert response.json()["can_create"] is False
        sql = str(db.execute.await_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
        assert "tenant-a" in sql and "invite_only" in sql
        db.execute.side_effect = [result(items=[project])]
        set_access(access("admin"))
        response = http.get("/api/projects?mine=false")
        assert response.status_code == 200 and response.json()["can_create"] is True
        sql = str(db.execute.await_args_list[-1].args[0].compile(compile_kwargs={"literal_binds": True}))
        assert "tenant-a" in sql and "invite_only = false" not in sql.lower()


def test_project_detail_requires_membership_for_invite_only(client):
    http, db, _ = client
    project = SimpleNamespace(name="p", tenant_id="tenant-a", invite_only=True)
    db.execute.side_effect = [result(project), result(items=[])]
    assert http.get("/api/projects/p").status_code == 404
    db.execute.side_effect = [result(project), result(items=[SimpleNamespace(role="member")])]
    with patch("src.human_adapters._project_row", new_callable=AsyncMock,
               return_value={"name": "p"}), patch(
        "src.human_adapters.get_project_members", new_callable=AsyncMock,
        return_value=[{"user_id": "alice", "role": "member"}],
    ):
        response = http.get("/api/projects/p")
        assert response.status_code == 200
        assert response.json()["members_list"][0]["user_id"] == "alice"
        assert response.json()["focus_available"] is False


@pytest.mark.parametrize("role,member,project_scope,invite_only,status,visible", [
    ("user", True, False, True, 200, True),
    ("admin", True, True, True, 200, True),
    ("admin", True, False, True, 200, False),
    ("user", False, False, False, 200, False),
    ("user", False, False, True, 404, False),
    ("admin", False, True, False, 200, False),
    ("admin", False, True, True, 200, False),
])
def test_project_focus_history_uses_project_content_grants(client, role, member, project_scope,
                                                        invite_only, status, visible):
    http, db, set_access = client
    set_access(access(
        role, projects={"p"}, agents={"alice-agent"},
        human_projects={"p"} if member else set(),
        moderation_scopes={"project"} if project_scope else set(),
    ))
    app.dependency_overrides[get_settings] = lambda: Settings(
        ui_tenant_id="tenant-a", valkey_url="redis://focus.test/0",
    )
    project = SimpleNamespace(name="p", tenant_id="tenant-a", invite_only=invite_only)
    db.execute.side_effect = [
        result(project), result(items=[SimpleNamespace(role="member")] if member else []),
        result(items=[]),
    ]
    focus = MagicMock()
    focus.read_focus_history = AsyncMock(return_value=[{"focus": "search"}, {"focus": "search"}, {"focus": "write"}])
    with patch("src.human_adapters._project_row", new_callable=AsyncMock,
               return_value={"name": "p"}), patch(
        "src.human_adapters.get_project_members", new_callable=AsyncMock, return_value=[],
    ), patch("src.human_adapters._cached_valkey_client", return_value=focus) as valkey:
        response = http.get("/api/projects/p")
    assert response.status_code == status, response.text
    if visible:
        assert response.json()["focus_available"] is True
        assert response.json()["focus_history"] == [
            {"focus": "search", "count": 2}, {"focus": "write", "count": 1},
        ]
        assert focus.read_focus_history.await_args.args[0] == "p"
    else:
        valkey.assert_not_called()
        focus.read_focus_history.assert_not_awaited()
        if status == 200:
            assert response.json()["focus_available"] is False
            assert response.json()["focus_history"] is None


def test_admin_reads_tenant_project_members_without_management_grant(client):
    http, db, set_access = client
    set_access(access("admin", projects=set(), project_admins=set()))
    project = SimpleNamespace(name="p", tenant_id="tenant-a", invite_only=True)
    db.execute.side_effect = [result(project), result(items=[]), result(items=[])]
    with patch("src.human_adapters._project_row", new_callable=AsyncMock,
               return_value={"name": "p"}), patch(
        "src.human_adapters.get_project_members", new_callable=AsyncMock,
        return_value=[{"user_id": "bob", "role": "member"}],
    ) as members:
        response = http.get("/api/projects/p")
        assert response.status_code == 200
        assert response.json()["members_list"] == [{"user_id": "bob", "role": "member"}]
        assert response.json()["can_manage"] is False
        members.assert_awaited_once()


def test_me_write_capabilities_use_human_memberships_only(client):
    http, _db, set_access = client
    set_access(access("user", projects={"p"}, human_projects=set()))
    response = http.get("/api/me")
    assert response.json()["write"] == {
        "scopes": ["user"], "project_ids": [], "campaign_ids": [], "owner_id": "alice",
    }
    set_access(access("admin", project_admins={"p"}, human_project_admins=set()))
    assert http.get("/api/me").json()["write"]["scopes"] == []
    set_access(access("admin", human_project_admins={"p"}, admin_write_scopes={"organizational"}))
    assert http.get("/api/me").json()["write"]["scopes"] == ["project", "organizational"]


def test_project_membership_needs_human_project_admin(client):
    http, db, set_access = client
    project = SimpleNamespace(name="p", tenant_id="tenant-a")
    membership = SimpleNamespace(role="admin")
    db.execute.side_effect = [result(project), result(items=[membership])]
    with patch("src.human_adapters.add_project_member", new_callable=AsyncMock, return_value=True) as add:
        assert http.post("/api/projects/p/members", json={"user_id": "bob"}).status_code == 403
        set_access(access("admin"))
        response = http.post("/api/projects/p/members", json={"user_id": "bob", "role": "member"})
        assert response.status_code == 200
        assert add.await_args.args[2] == "bob"
        invalid = {"user_id": "bob", "role": "admin", "tenant_id": "tenant-b"}
        assert http.post("/api/projects/p/members", json=invalid).status_code == 422
    assert "tenant-a" in str(db.execute.await_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))


def test_project_self_leave_and_foreign_remove_split(client):
    http, db, set_access = client
    project = SimpleNamespace(name="p", tenant_id="tenant-a")
    membership = SimpleNamespace(role="admin")
    db.execute.side_effect = [
        result(project), result(project), result(items=[membership]),
        result(project), result(items=[membership]), result(project),
    ]
    with patch("src.human_adapters.remove_project_member", new_callable=AsyncMock) as remove:
        assert http.delete("/api/projects/p/members/bob").status_code == 403
        assert http.delete("/api/projects/p/members/alice").status_code == 204
        set_access(access("admin"))
        assert http.delete("/api/projects/p/members/bob").status_code == 204
        assert http.delete("/api/projects/p/members/alice").status_code == 403
        assert [call.args[2] for call in remove.await_args_list] == ["alice", "bob"]


def test_memory_create_rejects_spoofing_and_role_inheritance(client):
    http, db, set_access = client
    created = SimpleNamespace(id=uuid.uuid4())
    with patch("src.human_adapters.core_create_memory", new_callable=AsyncMock, return_value=(created, {})) as write:
        assert http.post("/api/memories", json={"content": "hello", "scope": "user"}).status_code == 201
        assert write.await_args.args[0].owner_id == "alice"
        assert write.await_args.kwargs["tenant_id"] == "tenant-a"
        foreign_body = {"content": "hello", "scope": "user", "owner_id": "bob"}
        assert http.post("/api/memories", json=foreign_body).status_code == 403
        spoofed = {"content": "hello", "scope": "user", "role": "admin"}
        assert http.post("/api/memories", json=spoofed).status_code == 422
        set_access(access("admin"))
        assert http.post("/api/memories", json={"content": "hello", "scope": "user"}).status_code == 403
        assert http.post("/api/memories", json={"content": "hello", "scope": "organizational"}).status_code == 403
        set_access(access("admin", admin_write_scopes={"organizational"}))
        assert http.post("/api/memories", json={"content": "hello", "scope": "organizational"}).status_code == 201
        assert write.await_count == 2


def test_memory_project_create_requires_live_membership(client):
    http, db, set_access = client
    project = SimpleNamespace(name="p", tenant_id="tenant-a")
    db.execute.side_effect = [
        result(project), result(items=[]), result(project), result(items=[SimpleNamespace(role="admin")]),
    ]
    with patch("src.human_adapters.core_create_memory", new_callable=AsyncMock,
               return_value=(SimpleNamespace(id=uuid.uuid4()), {})) as write:
        body = {"content": "hello", "scope": "project", "scope_id": "p"}
        assert http.post("/api/memories", json=body).status_code == 403
        set_access(access("admin"))
        assert http.post("/api/memories", json=body).status_code == 201
        assert write.await_args.args[0].scope_id == "p"
        assert write.await_args.args[0].owner_id == "alice"


def test_version_preflights_all_affected_nodes(client):
    http, db, _ = client
    own = node()
    foreign = node(owner_id="bob")
    db.execute.side_effect = [result(own), result(items=[foreign]), result(items=[])]
    with patch("src.human_adapters.core_update_memory", new_callable=AsyncMock) as update:
        assert http.post(f"/api/memory/{own.id}/versions", json={"content": "new"}).status_code == 404
        update.assert_not_awaited()
    db.execute.side_effect = [result(own), result(items=[]), result(items=[])]
    with patch("src.human_adapters.core_update_memory", new_callable=AsyncMock,
               return_value=SimpleNamespace(id=uuid.uuid4(), version=2)) as update, patch(
        "src.human_adapters.run_curation_pipeline", new_callable=AsyncMock, return_value={"blocked": False},
    ):
        response = http.post(f"/api/memory/{own.id}/versions", json={"content": "new"})
        assert response.status_code == 201
        assert response.json()["version"] == 2
        assert update.await_args.kwargs["actor_id"] == "alice"


def test_version_preserves_authorized_entity_mention(client):
    http, db, _ = client
    own = node()
    entity = node(scope="entity", owner_id="bob")
    mention = SimpleNamespace(
        source_id=own.id, target_id=entity.id,
        tenant_id="tenant-a", relationship_type="mentions",
    )
    db.execute.side_effect = [
        result(own), result(items=[]), result(items=[mention]), result(items=[entity]),
    ]
    with patch("src.human_adapters.core_update_memory", new_callable=AsyncMock,
               return_value=SimpleNamespace(id=uuid.uuid4(), version=2)) as update, patch(
        "src.human_adapters.run_curation_pipeline", new_callable=AsyncMock, return_value={"blocked": False},
    ):
        response = http.post(f"/api/memory/{own.id}/versions", json={"content": "new"})
        assert response.status_code == 201
        update.assert_awaited_once()


@pytest.mark.parametrize("action", ["block", "quarantine", "reject_with_pointer"])
def test_version_applies_content_rules_for_the_memory_owner(client, action):
    http, db, set_access = client
    own = node(owner_id="alice-agent")
    set_access(access(agents={"alice-agent"}))
    policy = CuratorRule(
        name="personal-policy", tier="regex", config={"pattern": "FORBIDDEN_CONTENT"}, action=action,
    )
    db.execute.side_effect = [result(own), result(items=[]), result(items=[])]
    with patch("memoryhub_core.services.curation.pipeline.seed_default_rules", new_callable=AsyncMock), patch(
        "memoryhub_core.services.curation.pipeline.load_rules", new_callable=AsyncMock, return_value=[policy],
    ) as load, patch("src.human_adapters.core_update_memory", new_callable=AsyncMock) as update:
        response = http.post(f"/api/memory/{own.id}/versions", json={"content": "FORBIDDEN_CONTENT"})
    assert response.status_code == 409, response.text
    update.assert_not_awaited()
    db.commit.assert_not_awaited()
    assert load.await_args.kwargs["owner_id"] == "alice-agent"
    assert load.await_args.kwargs["tenant_id"] == "tenant-a"


def test_version_allows_clean_content_without_a_duplicate_gate(client):
    http, db, _ = client
    own = node()
    db.execute.side_effect = [result(own), result(items=[]), result(items=[])]
    with patch("memoryhub_core.services.curation.pipeline.seed_default_rules", new_callable=AsyncMock), patch(
        "memoryhub_core.services.curation.pipeline.load_rules", new_callable=AsyncMock, return_value=[],
    ), patch("memoryhub_core.services.curation.pipeline.check_similarity", new_callable=AsyncMock) as similarity, patch(
        "src.human_adapters.core_update_memory", new_callable=AsyncMock,
        return_value=SimpleNamespace(id=uuid.uuid4(), version=2),
    ) as update:
        response = http.post(f"/api/memory/{own.id}/versions", json={"content": "Clean revised content"})
    assert response.status_code == 201, response.text
    update.assert_awaited_once()
    similarity.assert_not_awaited()


def test_branch_inherits_parent_boundary(client):
    http, db, _ = client
    own = node(scope="project", scope_id="p")
    db.execute.side_effect = [result(own), result(items=[SimpleNamespace(role="member")])]
    with patch("src.human_adapters.core_create_memory", new_callable=AsyncMock,
               return_value=(SimpleNamespace(id=uuid.uuid4()), {})) as write:
        response = http.post(f"/api/memory/{own.id}/branches", json={"branch_type": "rationale", "content": "why"})
        assert response.status_code == 201
        created = write.await_args.args[0]
        assert created.parent_id == own.id
        assert created.owner_id == own.owner_id
        assert created.scope_id == "p"
        assert write.await_args.kwargs["tenant_id"] == "tenant-a"
        invalid = {"branch_type": "invalid", "content": "why"}
        assert http.post(f"/api/memory/{own.id}/branches", json=invalid).status_code == 422


def test_relationship_checks_both_objects_and_scope(client):
    http, db, _ = client
    a = node()
    b = node(owner_id="bob")
    db.execute.side_effect = [result(a), result(b)]
    with patch("src.human_adapters.create_relationship", new_callable=AsyncMock) as create:
        body = {"source_id": str(a.id), "target_id": str(b.id), "relationship_type": "related_to"}
        assert http.post("/api/relationships", json=body).status_code == 404
        create.assert_not_awaited()
    b.owner_id = "alice"
    db.execute.side_effect = [result(a), result(b)]
    with patch("src.human_adapters.create_relationship", new_callable=AsyncMock,
               return_value=SimpleNamespace(id=uuid.uuid4())) as create:
        assert http.post("/api/relationships", json=body).status_code == 201
        assert create.await_args.args[0].created_by == "alice"


def test_report_uses_human_reporter_and_authorized_object(client):
    http, db, _ = client
    foreign = node(owner_id="bob")
    db.execute.side_effect = [result(foreign)]
    body = {"observed_behavior": "different", "confidence": 0.8}
    with patch("src.human_adapters.core_report_contradiction", new_callable=AsyncMock) as report:
        assert http.post(f"/api/memory/{foreign.id}/contradictions", json=body).status_code == 404
        report.assert_not_awaited()
    own = node()
    db.execute.side_effect = [result(own)]
    with patch("src.human_adapters.core_report_contradiction", new_callable=AsyncMock, return_value=2) as report:
        response = http.post(f"/api/memory/{own.id}/contradictions", json=body)
        assert response.status_code == 201 and response.json() == {"unresolved": 2}
        assert report.await_args.args[3] == "alice"


def test_moderation_bulk_preflights_every_object(client):
    http, db, set_access = client
    set_access(access("admin"))
    allowed = node(scope="organizational")
    foreign = node(scope="organizational", tenant_id="tenant-b")
    db.execute.side_effect = [result(allowed), result(foreign)]
    with patch("src.human_adapters.quarantine_memory", new_callable=AsyncMock) as quarantine:
        body = {"action": "quarantine", "ids": sorted([str(allowed.id), str(foreign.id)])}
        assert http.post("/api/memories/bulk", json=body).status_code == 404
        quarantine.assert_not_awaited()
        db.commit.assert_not_awaited()
    second = node(scope="organizational")
    ordered = sorted([allowed, second], key=lambda n: n.id)
    db.execute.side_effect = [result(item) for item in ordered]
    with patch("src.human_adapters.quarantine_memory", new_callable=AsyncMock) as quarantine:
        body = {"action": "quarantine", "ids": [str(allowed.id), str(second.id)], "reason": "policy"}
        response = http.post("/api/memories/bulk", json=body)
        assert response.status_code == 200
        assert set(response.json()["done"]) == {str(allowed.id), str(second.id)}
        assert quarantine.await_count == 2
        assert all(call.kwargs["commit"] is False for call in quarantine.await_args_list)
        db.commit.assert_awaited_once()


def test_moderation_rejects_user_and_personal_admin(client):
    http, db, set_access = client
    personal = node()
    assert http.post("/api/memories/bulk", json={"action": "quarantine", "ids": [str(personal.id)]}).status_code == 403
    set_access(access("admin"))
    db.execute.side_effect = [result(personal)]
    assert http.post("/api/memories/bulk", json={"action": "quarantine", "ids": [str(personal.id)]}).status_code == 404
    db.commit.assert_not_awaited()


def test_bulk_restore_commits_before_human_audit(client):
    http, db, set_access = client
    set_access(access("admin"))
    quarantined = node(scope="organizational", status="quarantined")
    db.execute.side_effect = [result(quarantined)]
    order = []

    async def commit():
        order.append("commit")

    db.commit.side_effect = commit
    with patch("src.human_adapters.restore_memory", new_callable=AsyncMock) as restore, patch(
        "src.human_adapters.record_moderation_audit", side_effect=lambda *a, **k: order.append("audit"),
    ) as audit:
        response = http.post("/api/memories/bulk", json={"action": "restore", "ids": [str(quarantined.id)]})
        assert response.status_code == 200
        assert order == ["commit", "audit"]
        assert restore.await_args.kwargs["commit"] is False
        assert audit.call_args.kwargs["actor_type"] == "user"


def test_entities_list_is_user_only_and_filters_at_sql_level(client):
    http, db, set_access = client
    entity = node(scope="entity", branch_type="entity:person", metadata_={"aliases": ["A"]})
    db.execute.side_effect = [
        result(rows=[("entity:person", 1)]), result(1),
        result(rows=[(entity, 1, entity.updated_at)]), result(rows=[]),
    ]
    response = http.get("/api/entities?q=Entity&page=1&per_page=20")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Entity"
    assert response.json()["counts"]["person"] == 1
    for call in db.execute.await_args_list:
        sql = str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        assert "tenant-a" in sql and "memory_nodes" in sql
        assert "owner_id IN" in sql and "scope_id IN" in sql
        assert "mentions" in sql
    set_access(access("admin"))
    assert http.get("/api/entities").status_code == 403


def test_entity_detail_hides_foreign_mentions(client):
    http, db, _ = client
    entity = node(scope="entity", branch_type="entity:person")
    own = node()
    foreign = node(owner_id="bob")
    rels = [
        SimpleNamespace(source_id=own.id, tenant_id="tenant-a"),
        SimpleNamespace(source_id=foreign.id, tenant_id="tenant-a"),
    ]
    db.execute.side_effect = [result(entity), result(items=rels), result(items=[own, foreign]), result(rows=[])]
    response = http.get(f"/api/entities/{entity.id}")
    assert response.status_code == 200
    assert response.json()["memory_count"] == 1
    assert response.json()["hidden_mentions"] == 0
    assert [item["id"] for item in response.json()["memories"]] == [str(own.id)]
    sql = str(db.execute.await_args_list[2].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tenant-a" in sql and "owner_id IN" in sql and "scope_id IN" in sql


@pytest.mark.parametrize("inaccessible", [
    {"owner_id": "bob"},
    {"scope": "project", "scope_id": "other-project"},
    {"tenant_id": "tenant-b"},
])
def test_entity_detail_aggregate_unchanged_by_inaccessible_source(client, inaccessible):
    http, db, _ = client
    entity = node(scope="entity", branch_type="entity:person")
    own = node()
    foreign = node(**inaccessible)

    db.execute.side_effect = [result(entity), result(items=[
        SimpleNamespace(source_id=own.id, tenant_id="tenant-a"),
    ]), result(items=[own]), result(rows=[])]
    baseline = http.get(f"/api/entities/{entity.id}")
    assert baseline.status_code == 200

    db.execute.side_effect = [result(entity), result(items=[
        SimpleNamespace(source_id=own.id, tenant_id="tenant-a"),
        SimpleNamespace(source_id=foreign.id, tenant_id=foreign.tenant_id),
    ]), result(items=[own, foreign]), result(rows=[])]
    with_hidden = http.get(f"/api/entities/{entity.id}")
    assert with_hidden.status_code == 200
    assert with_hidden.json() == baseline.json()
    assert with_hidden.json()["hidden_mentions"] == 0


def test_entity_detail_only_accessible_sources(client):
    http, db, _ = client
    entity = node(scope="entity", branch_type="entity:person")
    own = node()
    project = node(scope="project", scope_id="p", owner_id="bob")
    db.execute.side_effect = [result(entity), result(items=[
        SimpleNamespace(source_id=own.id, tenant_id="tenant-a"),
        SimpleNamespace(source_id=project.id, tenant_id="tenant-a"),
    ]), result(items=[own, project]), result(rows=[])]
    response = http.get(f"/api/entities/{entity.id}")
    assert response.status_code == 200
    assert response.json()["memory_count"] == 2
    assert response.json()["hidden_mentions"] == 0
    assert {item["id"] for item in response.json()["memories"]} == {str(own.id), str(project.id)}


def test_entity_detail_never_reports_hidden_only_sources(client):
    http, db, _ = client
    entity = node(scope="entity", branch_type="entity:person")
    foreign = node(owner_id="bob")
    rel = SimpleNamespace(source_id=foreign.id, tenant_id="tenant-a")
    db.execute.side_effect = [result(entity), result(items=[rel]), result(items=[foreign])]
    owned_detail = http.get(f"/api/entities/{entity.id}")
    assert owned_detail.status_code == 200
    assert owned_detail.json()["memory_count"] == owned_detail.json()["hidden_mentions"] == 0
    assert owned_detail.json()["memories"] == []

    entity.owner_id = "bob"
    db.execute.side_effect = [result(entity), result(items=[rel]), result(items=[foreign])]
    assert http.get(f"/api/entities/{entity.id}").status_code == 404


def test_entity_rename_rechecks_linked_memories_and_rejects_unsupported_changes(client):
    http, db, _ = client
    entity = node(scope="entity", branch_type="entity:person", metadata_={"aliases": ["Old"]})
    foreign = node(owner_id="bob")
    rel = SimpleNamespace(source_id=foreign.id, tenant_id="tenant-a")
    db.execute.side_effect = [result(entity), result(items=[rel]), result(items=[foreign])]
    with patch("src.human_adapters.rename_entity", new_callable=AsyncMock) as rename:
        assert http.patch(f"/api/entities/{entity.id}", json={"name": "New", "aliases": ["Old"]}).status_code == 404
        rename.assert_not_awaited()
    db.execute.side_effect = [result(entity), result(items=[])]
    with patch("src.human_adapters.rename_entity", new_callable=AsyncMock,
               return_value={"entity": {"id": str(entity.id), "content": "New",
                                        "entity_type": "person", "aliases": ["Entity", "Old"]}}) as rename:
        assert http.patch(f"/api/entities/{entity.id}", json={"name": "New", "aliases": ["changed"]}).status_code == 422
        rename.assert_not_awaited()
    db.execute.side_effect = [result(entity), result(items=[])]
    with patch("src.human_adapters.rename_entity", new_callable=AsyncMock,
               return_value={"entity": {"id": str(entity.id), "content": "New",
                                        "entity_type": "person", "aliases": ["Entity", "Old"]}}) as rename:
        response = http.patch(f"/api/entities/{entity.id}", json={"name": "New", "aliases": ["Old"]})
        assert response.status_code == 200
        assert response.json()["name"] == "New"
        assert rename.await_args.kwargs["owner_id"] == "alice"


def test_entity_merge_previews_then_uses_existing_core_operation(client):
    http, db, _ = client
    source = node(scope="entity", branch_type="entity:person")
    target = node(scope="entity", branch_type="entity:person", content="Target")
    ordered = sorted([source, target], key=lambda item: item.id)
    db.execute.side_effect = [result(item) for item in ordered] + [result(items=[]), result(items=[])]
    with patch("src.human_adapters.merge_entities", new_callable=AsyncMock) as merge:
        response = http.post(f"/api/entities/{source.id}/merge", json={"into": str(target.id), "dry_run": True})
        assert response.status_code == 200 and response.json()["dry_run"] is True
        merge.assert_not_awaited()
    db.execute.side_effect = [result(item) for item in ordered] + [result(items=[]), result(items=[])]
    with patch("src.human_adapters.merge_entities", new_callable=AsyncMock, return_value={}) as merge:
        response = http.post(f"/api/entities/{source.id}/merge", json={"into": str(target.id), "dry_run": False})
        assert response.status_code == 200 and response.json()["source_removed"] is True
        merge.assert_awaited_once()
        assert merge.await_args.kwargs["tenant_id"] == "tenant-a"


@pytest.mark.parametrize("inaccessible", [
    {"owner_id": "bob"},
    {"scope": "project", "scope_id": "other-project"},
    {"tenant_id": "tenant-b"},
])
def test_entity_merge_rejects_inaccessible_linked_source(client, inaccessible):
    http, db, _ = client
    source = node(scope="entity", branch_type="entity:person")
    target = node(scope="entity", branch_type="entity:person", content="Target")
    foreign = node(**inaccessible)
    rel = SimpleNamespace(source_id=foreign.id, tenant_id=foreign.tenant_id)
    ordered = sorted([source, target], key=lambda item: item.id)
    db.execute.side_effect = [result(item) for item in ordered] + [
        result(items=[rel]), result(items=[foreign]),
    ]
    with patch("src.human_adapters.merge_entities", new_callable=AsyncMock) as merge:
        response = http.post(
            f"/api/entities/{source.id}/merge", json={"into": str(target.id), "dry_run": False},
        )
        assert response.status_code in (404, 409)
        merge.assert_not_awaited()


def test_browse_admin_excludes_personal_and_redacts_unmoderated_shared_rows(client):
    http, db, set_access = client
    set_access(access("admin"))
    personal = node(owner_id="bob", content="private text", stub="private stub")
    foreign_project = node(scope="project", scope_id="other", owner_id="bob",
                           content="project text", stub="project stub")
    db.execute.side_effect = [
        result(2), result(items=[personal, foreign_project]), result(rows=[]), result(rows=[]),
        result(1), result(1), result(0), result(0),
        # No "writers" facet query for an admin: per-person counts are individual activity.
        result(rows=[("project", 1)]), result(rows=[]),
        result(rows=[]), result(0), result(0),
    ]
    response = http.get("/api/memories/browse?q=bob&mode=semantic")
    assert response.status_code == 200
    body = response.json()
    assert body["search_mode"] == "text"
    # A personal row is not an admin's even as metadata (#667); it is dropped.
    assert [item["id"] for item in body["items"]] == [str(foreign_project.id)]
    assert "private" not in response.text
    item = body["items"][0]
    assert item["redacted"] is True and item["content_preview"] == "" and item["stub"] == "Content hidden"
    assert item["capabilities"] == {"write": False, "moderate": False}
    assert body["facets"]["flags"] == {"contradicted": 0, "has_branches": 0,
                                      "near_duplicate": None}
    sql = str(db.execute.await_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tenant-a" in sql and "bob" in sql and "memory_nodes.scope IN" in sql
    assert "'entity'" not in sql and "'user'" not in sql


def test_browse_user_cannot_request_quarantine_or_see_foreign_row(client):
    http, db, _ = client
    assert http.get("/api/memories/browse?tab=quarantined").status_code == 403
    foreign = node(owner_id="bob")
    db.execute.side_effect = [
        result(1), result(items=[foreign]), result(1), result(1),
        result(rows=[]), result(rows=[]), result(rows=[]),
        result(rows=[]), result(0), result(0),
    ]
    response = http.get("/api/memories/browse")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["tab_counts"]["quarantined"] == 0
    assert response.json()["tab_counts"]["deleted"] == 0


def test_browse_rejects_unsupported_flag_and_role_spoof_is_inert(client):
    http, db, _ = client
    assert http.get("/api/memories/browse?flag=near_duplicate").status_code == 422
    db.execute.side_effect = [
        result(0), result(items=[]), result(0), result(0),
        result(rows=[]), result(rows=[]), result(rows=[]),
        result(rows=[]), result(0), result(0),
    ]
    response = http.get("/api/memories/browse?role=admin&tenant_id=tenant-b")
    assert response.status_code == 200
    assert response.json()["metadata_only"] is False
    sql = str(db.execute.await_args_list[0].args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "tenant-a" in sql and "tenant-b" not in sql
