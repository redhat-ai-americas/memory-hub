"""Technical MCP authorization remains independent of dashboard roles."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError
from src.core.authz import AuthenticationError
from src.tools import backfill_entities as backfill_module
from src.tools.manage_curation import manage_curation
from src.tools.manage_project import manage_project
from src.tools.manage_session import _require_project_member
from src.tools.memory import _dispatch_list_entities, _dispatch_promote

from memoryhub_core.services.memory import resolve_contradiction


@pytest.mark.asyncio
async def test_backfill_requires_authenticated_admin_scope(monkeypatch):
    def unauthenticated():
        raise AuthenticationError("missing")

    monkeypatch.setattr(backfill_module, "get_claims_from_context", unauthenticated)
    with pytest.raises(ToolError, match="Authentication required"):
        await backfill_module.backfill_entities()

    monkeypatch.setattr(backfill_module, "get_claims_from_context", lambda: {
        "sub": "worker", "tenant_id": "tenant-a", "scopes": ["memory:read"],
    })
    with pytest.raises(ToolError, match="memory:admin scope required"):
        await backfill_module.backfill_entities()


@pytest.mark.asyncio
async def test_backfill_candidate_query_is_tenant_scoped(monkeypatch):
    monkeypatch.setattr(backfill_module, "get_claims_from_context", lambda: {
        "sub": "worker", "tenant_id": "tenant-a", "scopes": ["memory:admin"],
    })
    db = AsyncMock()
    empty = MagicMock()
    empty.scalar_one.return_value = 0
    db.execute.return_value = empty
    monkeypatch.setattr(backfill_module, "get_db_session", AsyncMock(return_value=(db, "gen")))
    monkeypatch.setattr(backfill_module, "release_db_session", AsyncMock())

    summary = await backfill_module.backfill_entities()
    sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert summary["total_candidates"] == 0
    assert "tenant-a" in sql and "tenant_id" in sql


@pytest.mark.asyncio
async def test_list_entities_rejects_foreign_owner_before_database(monkeypatch):
    monkeypatch.setattr("src.core.authz.get_claims_from_context", lambda: {
        "sub": "alice", "tenant_id": "tenant-a", "scopes": ["memory:read"],
    })
    with pytest.raises(ToolError, match="another identity"):
        await _dispatch_list_entities({"owner_id": "bob"}, None)


@pytest.mark.asyncio
async def test_direct_promotion_requires_technical_scope(monkeypatch):
    monkeypatch.setattr("src.core.authz.get_claims_from_context", lambda: {
        "sub": "agent", "tenant_id": "tenant-a", "scopes": ["memory:write:user"],
    })
    with pytest.raises(ToolError, match="technical memory:admin"):
        await _dispatch_promote(str(uuid.uuid4()), None, {"target_scope": "project"}, None)


@pytest.mark.asyncio
async def test_direct_contradiction_resolution_requires_technical_scope(monkeypatch):
    monkeypatch.setattr("src.tools.manage_curation.get_claims_from_context", lambda: {
        "sub": "agent", "tenant_id": "tenant-a", "scopes": ["memory:write:user"],
    })
    with pytest.raises(ToolError, match="memory:admin scope"):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id=str(uuid.uuid4()),
            resolution_action="keep_old",
        )


@pytest.mark.asyncio
async def test_resolution_restricts_tenant_and_forbids_self_review():
    report = SimpleNamespace(
        id=uuid.uuid4(), reporter="agent", resolved=False,
        resolved_at=None, resolution_action=None, resolved_by=None,
    )
    row = MagicMock()
    row.scalar_one_or_none.return_value = report
    db = AsyncMock()
    db.execute.return_value = row
    with pytest.raises(ValueError, match="own contradiction"):
        await resolve_contradiction(
            report.id, db, actor_id="agent", resolution_action="keep_old", tenant_id="tenant-a",
        )
    db.commit.assert_not_awaited()
    sql = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert sql.count("tenant-a") == 2

    await resolve_contradiction(
        report.id, db, actor_id="reviewer", resolution_action="keep_old", tenant_id="tenant-a",
    )
    assert report.resolved is True
    assert report.resolved_by == "reviewer"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_describe_project_requires_tenant_and_membership(monkeypatch):
    monkeypatch.setattr("src.tools.manage_project.get_claims_from_context", lambda: {
        "sub": "alice", "tenant_id": "tenant-a", "scopes": [],
    })
    db = AsyncMock()
    monkeypatch.setattr("src.tools.manage_project.get_db_session", AsyncMock(return_value=(db, "gen")))
    monkeypatch.setattr("src.tools.manage_project.release_db_session", AsyncMock())
    project = MagicMock(tenant_id="tenant-b")
    monkeypatch.setattr("src.tools.manage_project.get_project", AsyncMock(return_value=project))
    members = AsyncMock()
    monkeypatch.setattr("src.tools.manage_project.get_project_members", members)

    with pytest.raises(ToolError, match="not found"):
        await manage_project(action="describe", project_name="foreign")
    members.assert_not_awaited()

    project.tenant_id = "tenant-a"
    monkeypatch.setattr("src.tools.manage_project._get_membership", AsyncMock(return_value=None))
    with pytest.raises(ToolError, match="not a member"):
        await manage_project(action="describe", project_name="private")
    members.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_agent_cannot_administer_projects_via_mcp(monkeypatch):
    monkeypatch.setattr("src.tools.manage_project.get_claims_from_context", lambda: {
        "sub": "agent", "tenant_id": "tenant-a", "scopes": ["memory:write:project"],
    })
    db_session = AsyncMock()
    monkeypatch.setattr("src.tools.manage_project.get_db_session", db_session)
    for action, kwargs in (
        ("create", {"project_name": "new"}),
        ("add_member", {"project_name": "existing", "user_id": "other"}),
        ("remove_member", {"project_name": "existing", "user_id": "other"}),
    ):
        with pytest.raises(ToolError, match="memory:admin scope"):
            await manage_project(action=action, **kwargs)
    db_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_focus_history_requires_membership_in_callers_tenant(monkeypatch):
    db = AsyncMock()
    memberships = AsyncMock(return_value={"own-project"})
    monkeypatch.setattr("src.tools.manage_session.get_db_session", AsyncMock(return_value=(db, "gen")))
    monkeypatch.setattr("src.tools.manage_session.release_db_session", AsyncMock())
    monkeypatch.setattr("src.tools.manage_session.get_projects_for_user_in_tenant", memberships)
    claims = {"sub": "alice", "tenant_id": "tenant-a"}
    await _require_project_member(claims, "own-project")
    with pytest.raises(ToolError, match="Not a member"):
        await _require_project_member(claims, "foreign-project")
    memberships.assert_awaited_with(db, "alice", "tenant-a")
