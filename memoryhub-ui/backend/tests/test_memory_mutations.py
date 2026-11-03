"""Persistence regressions for dashboard editing, restore and project membership."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.schemas import MemoryNodeUpdate
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import update_memory
from sqlalchemy import select, text

from src import memory_content, routes, routes_admin, routes_dashboard, routes_workspace, teams, ui_common
from src.access import Access, Grants
from src.config import Settings
from src.ui_common import DEFAULT_TENANT_SETTINGS, Viewer


@pytest.fixture
def mutation_viewer(monkeypatch):
    viewer = Viewer("alice", "Alice", None, "account", "user")
    access = Access(viewer, Grants("alice"), ())
    embedding = MockEmbeddingService()
    for module in (routes, routes_admin, routes_dashboard, routes_workspace):
        monkeypatch.setattr(module, "access_for", AsyncMock(return_value=access))
        monkeypatch.setattr(module, "viewer_from_request", lambda *_: viewer)
    monkeypatch.setattr(routes_dashboard, "_embedding_service", lambda _: embedding)
    monkeypatch.setattr(routes_dashboard, "load_tenant_settings", AsyncMock(return_value=DEFAULT_TENANT_SETTINGS))
    for module in (routes_admin, routes_dashboard, routes_workspace, ui_common):
        monkeypatch.setattr(module, "audit", AsyncMock())
    monkeypatch.setattr(teams, "ensure_tables", AsyncMock())
    monkeypatch.setenv("MEMORYHUB_ENTITY_EXTRACTION_ENABLED", "false")
    return SimpleNamespace(
        viewer=viewer,
        access=access,
        embedding=embedding,
        settings=Settings(),
        request=Request({"type": "http", "headers": []}),
    )


def memory(content="Original content", **values):
    memory_id = uuid.uuid4()
    return MemoryNode(
        **{
            "id": memory_id,
            "logical_id": memory_id,
            "content": content,
            "stub": content[:50],
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


@pytest.mark.parametrize("status", ["quarantined", "pending"])
@pytest.mark.parametrize("action", ["edit", "bulk_weight"])
async def test_new_versions_preserve_moderation_state(mutation_db, mutation_viewer, status, action):
    db, ctx = mutation_db, mutation_viewer
    root = memory(status=status)
    branch = memory("Private rationale", parent_id=root.id, branch_type="rationale", status="quarantined")
    db.add_all([root, branch])
    await db.commit()
    if action == "edit":
        result = await routes_dashboard.new_version(
            str(root.id),
            routes_dashboard.NewVersionRequest(content="Revised content"),
            ctx.request,
            db,
            ctx.settings,
        )
        updated_id = result["id"]
    else:
        result = await routes_dashboard.bulk_action(
            routes_dashboard.BulkRequest(action="weight", ids=[str(root.id)], weight=0.9),
            ctx.request,
            db,
            ctx.settings,
        )
        assert result["errors"] == []
        updated_id = result["done"][0]
    updated = await db.get(MemoryNode, uuid.UUID(updated_id))
    assert updated.status == status
    copied = (await db.execute(select(MemoryNode).where(MemoryNode.parent_id == updated.id))).scalar_one()
    assert copied.status == "quarantined"


async def test_s3_detail_edit_and_promotion_keep_complete_content(mutation_db, mutation_viewer, monkeypatch):
    db, ctx = mutation_db, mutation_viewer
    full_text = "x" * 1000 + " Full document tail must survive editing and promotion."
    original = memory(full_text[:1000], storage_type="s3", content_ref="default/full-document")
    db.add(original)
    await db.commit()
    storage = SimpleNamespace(get_content=AsyncMock(return_value=full_text))
    monkeypatch.setattr(memory_content, "get_memory_storage", lambda: storage)
    detail = await routes_dashboard.memory_context(str(original.id), db, ctx.settings, ctx.viewer)
    assert detail["memory"]["content"] == full_text
    assert detail["versions"][0]["content"] == full_text
    storage.get_content.assert_awaited_once()
    result = await routes_dashboard.new_version(
        str(original.id),
        routes_dashboard.NewVersionRequest(content=detail["memory"]["content"] + " Edited."),
        ctx.request,
        db,
        ctx.settings,
    )
    edited = await db.get(MemoryNode, uuid.UUID(result["id"]))
    assert edited.content == full_text + " Edited."
    promoted_id = await routes_dashboard._propose_promotion(
        db, ctx.settings, ctx.viewer, original, "organizational", None
    )
    promoted = await db.get(MemoryNode, promoted_id)
    assert promoted.content == full_text


@pytest.mark.parametrize("failure", ["unconfigured", "unavailable"])
async def test_s3_failures_never_expose_prefix_as_complete_content(mutation_db, mutation_viewer, monkeypatch, failure):
    db, ctx = mutation_db, mutation_viewer
    original = memory("Incomplete prefix", storage_type="s3", content_ref="default/full-document")
    db.add(original)
    await db.commit()
    storage = (
        None if failure == "unconfigured" else SimpleNamespace(get_content=AsyncMock(side_effect=OSError("offline")))
    )
    monkeypatch.setattr(memory_content, "get_memory_storage", lambda: storage)
    with pytest.raises(HTTPException) as error:
        await routes_dashboard.memory_context(str(original.id), db, ctx.settings, ctx.viewer)
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error:
        await routes_dashboard._propose_promotion(db, ctx.settings, ctx.viewer, original, "organizational", None)
    assert error.value.status_code == 503
    assert len((await db.execute(select(MemoryNode))).scalars().all()) == 1


async def test_hidden_s3_content_does_not_require_storage_access(mutation_db, mutation_viewer, monkeypatch):
    db, ctx = mutation_db, mutation_viewer
    ctx.viewer.role = "admin"
    ctx.access.grants = None
    original = memory("Private prefix", storage_type="s3", content_ref="default/full-document")
    db.add(original)
    await db.commit()
    storage = SimpleNamespace(get_content=AsyncMock(side_effect=AssertionError("Private content must stay hidden")))
    monkeypatch.setattr(memory_content, "get_memory_storage", lambda: storage)
    detail = await routes_dashboard.memory_context(str(original.id), db, ctx.settings, ctx.viewer)
    assert detail["memory"]["redacted"]
    storage.get_content.assert_not_awaited()


async def test_restore_keeps_historical_branch_copies_superseded(mutation_db, mutation_viewer):
    db, ctx = mutation_db, mutation_viewer
    root = memory()
    branch = memory("Original rationale", parent_id=root.id, branch_type="rationale")
    db.add_all([root, branch])
    await db.commit()
    updated = await update_memory(root.id, MemoryNodeUpdate(content="Updated content"), db, ctx.embedding)
    await routes.forget_memory(str(updated.id), db, ctx.settings, ctx.viewer)
    db.expire_all()
    result = await routes_workspace.restore_memory(db, ctx.settings, ctx.viewer, str(updated.id))
    await db.commit()
    assert result["id"] == str(updated.id)
    rows = (await db.execute(select(MemoryNode))).scalars().all()
    assert all(row.deleted_at is None for row in rows)
    current = [row for row in rows if row.is_current]
    assert len(current) == 2
    assert all(row.parent_id in (None, updated.id) for row in current)


async def test_bulk_weight_reports_stale_and_deleted_items_and_continues(mutation_db, mutation_viewer):
    db, ctx = mutation_db, mutation_viewer
    first, stale, deleted, last = memory(), memory(is_current=False), memory(deleted_at=datetime.now(UTC)), memory()
    db.add_all([first, stale, deleted, last])
    await db.commit()
    result = await routes_dashboard.bulk_action(
        routes_dashboard.BulkRequest(
            action="weight", ids=[str(n.id) for n in (first, stale, deleted, last)], weight=0.9
        ),
        ctx.request,
        db,
        ctx.settings,
    )
    assert len(result["done"]) == 2
    assert {item["id"] for item in result["errors"]} == {str(stale.id), str(deleted.id)}
    for updated_id in result["done"]:
        updated = await db.get(MemoryNode, uuid.UUID(updated_id))
        assert updated.weight == 0.9 and updated.is_current


async def empty_teams(db):
    for statement in (
        "CREATE TABLE memoryhub_ui_teams (id TEXT, name TEXT, tenant_id TEXT)",
        "CREATE TABLE memoryhub_ui_team_members (team_id TEXT, user_id TEXT)",
        "CREATE TABLE memoryhub_ui_team_projects (team_id TEXT, project_id TEXT)",
    ):
        await db.execute(text(statement))


@pytest.mark.parametrize("already_promoted", [False, True])
async def test_team_unlink_preserves_explicit_project_admin(mutation_db, mutation_viewer, already_promoted):
    db, ctx = mutation_db, mutation_viewer
    await empty_teams(db)
    db.add(Project(name="team-project", tenant_id="default", created_by="alice"))
    await db.flush()
    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id="team-project",
        user_id="bob",
        role="admin" if already_promoted else "member",
        joined_by="team:engineers",
    )
    stale_member = ProjectMembership(
        id=uuid.uuid4(),
        project_id="team-project",
        user_id="carol",
        role="member",
        joined_by="team:engineers",
    )
    db.add_all([membership, stale_member])
    await db.commit()
    if not already_promoted:
        ctx.viewer.role = "admin"
        await routes_admin.set_member_role(
            "team-project",
            "bob",
            routes_admin.MemberRoleRequest(role="admin"),
            ctx.request,
            db,
            ctx.settings,
        )
        assert membership.joined_by == "alice"
    result = await teams.sync_project_access(db, "default")
    await db.commit()
    remaining = (await db.execute(select(ProjectMembership))).scalars().all()
    assert result["removed"] == 1
    assert [(m.user_id, m.role) for m in remaining] == [("bob", "admin")]
    assert not remaining[0].joined_by.startswith("team:")


@pytest.mark.parametrize(
    "role,scope,write,moderate",
    [
        ("user", "user", True, True),
        ("user", "enterprise", False, False),
        ("admin", "enterprise", False, True),
        ("admin", "user", False, False),
    ],
)
async def test_memory_context_exposes_actual_action_capabilities(
    mutation_db, mutation_viewer, role, scope, write, moderate
):
    db, ctx = mutation_db, mutation_viewer
    ctx.viewer.role = role
    ctx.access.open_scopes = ("enterprise",)
    if role == "admin":
        ctx.access.grants = None
    original = memory(scope=scope)
    db.add(original)
    await db.commit()
    detail = await routes_dashboard.memory_context(str(original.id), db, ctx.settings, ctx.viewer)
    assert detail["memory"]["capabilities"] == {"write": write, "moderate": moderate}
