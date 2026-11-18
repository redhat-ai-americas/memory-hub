"""Positive and negative object-authorization regressions for existing MCP tools."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from src.tools._object_access import memory_object_access
from src.tools.compile_persona import compile_persona
from src.tools.delete_memory import delete_memory
from src.tools.edit_persona import edit_persona
from src.tools.get_persona import get_persona
from src.tools.manage_graph import _handle_create_relationship
from src.tools.memory import _dispatch_checkpoint, _dispatch_graduate
from src.tools.write_memory import write_memory


def _claims():
    return {
        "sub": "alice",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:read:user", "memory:write:user"],
    }


def _node(owner="alice", scope="user", scope_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope=scope,
        scope_id=scope_id,
        owner_id=owner,
        tenant_id="default",
        previous_version_id=None,
    )


@pytest.mark.asyncio
async def test_object_access_enforces_owner_tenant_and_project_membership():
    session = AsyncMock()
    claims = _claims()
    assert await memory_object_access(session, claims, _node(owner="alice")) == (True, True)
    assert await memory_object_access(session, claims, _node(owner="bob")) == (False, False)
    cross_tenant = _node(owner="alice")
    cross_tenant.tenant_id = "other"
    assert await memory_object_access(session, claims, cross_tenant) == (False, False)

    claims["scopes"].extend(["memory:read:project", "memory:write:project"])
    with patch(
        "src.tools._object_access.get_projects_for_user_in_tenant",
        new_callable=AsyncMock,
        return_value={"member-project"},
    ):
        assert await memory_object_access(session, claims, _node(scope="project", scope_id="member-project")) == (
            True,
            True,
        )
        assert await memory_object_access(session, claims, _node(scope="project", scope_id="foreign-project")) == (
            False,
            False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_owner,allowed", [("bob", False), ("alice", True)])
async def test_write_branch_checks_parent_before_create(parent_owner, allowed):
    parent = _node(owner=parent_owner)
    created = MagicMock()
    created.id = uuid.uuid4()
    created.content = "branch"
    created.upstream_trust_level = "trusted"
    created.model_dump.return_value = {"id": str(created.id), "content": "branch"}
    curation = {"blocked": False, "similar_count": 0, "nearest_id": None, "nearest_score": None, "flags": []}
    session = AsyncMock()
    locked_result = MagicMock()
    locked_result.scalar_one_or_none.return_value = parent
    session.execute.return_value = locked_result
    with (
        patch("src.tools.write_memory.get_claims_from_context", return_value=_claims()),
        patch("src.tools.write_memory.get_db_session", new_callable=AsyncMock, return_value=(session, AsyncMock())),
        patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.write_memory.read_memory_service", new_callable=AsyncMock, return_value=parent),
        patch("src.tools.write_memory.memory_object_access", new_callable=AsyncMock, return_value=(allowed, allowed)),
        patch("src.tools.write_memory.get_embedding_service", return_value=SimpleNamespace(max_tokens=8192)),
        patch(
            "src.tools.write_memory.create_memory", new_callable=AsyncMock, return_value=(created, curation)
        ) as create,
        patch("src.tools.write_memory.broadcast_after_write", new_callable=AsyncMock),
    ):
        if allowed:
            result = await write_memory(content="branch", parent_id=str(parent.id), branch_type="rationale")
            assert result["memory"]["content"] == "branch"
            create.assert_awaited_once()
        else:
            with pytest.raises(ToolError, match="parent memory"):
                await write_memory(content="branch", parent_id=str(parent.id), branch_type="rationale")
            create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("child_allowed", [False, True])
async def test_delete_authorizes_every_descendant(child_allowed):
    seed = _node()
    child = _node(owner="alice" if child_allowed else "bob")
    expected = {seed.id, child.id}
    with (
        patch("src.tools.delete_memory.get_claims_from_context", return_value=_claims()),
        patch(
            "src.tools.delete_memory.get_db_session", new_callable=AsyncMock, return_value=(AsyncMock(), AsyncMock())
        ),
        patch("src.tools.delete_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.delete_memory._read_memory", new_callable=AsyncMock, return_value=seed),
        patch(
            "src.tools.delete_memory.collect_delete_nodes",
            new_callable=AsyncMock,
            return_value={seed.id: seed, child.id: child},
        ),
        patch(
            "src.tools.delete_memory.memory_object_access",
            new_callable=AsyncMock,
            side_effect=[(True, True), (child_allowed, child_allowed)],
        ),
        patch(
            "src.tools.delete_memory.svc_delete_memory", new_callable=AsyncMock, return_value={"total_deleted": 2}
        ) as service,
        patch("src.tools.delete_memory.get_s3_adapter", return_value=None),
        patch("src.tools.delete_memory.broadcast_after_write", new_callable=AsyncMock),
    ):
        if child_allowed:
            assert (await delete_memory(memory_id=str(seed.id)))["total_deleted"] == 2
            assert service.call_args.kwargs["expected_ids"] == expected
        else:
            with pytest.raises(ToolError, match="all affected"):
                await delete_memory(memory_id=str(seed.id))
            service.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_write", [False, True])
async def test_relate_requires_write_on_both_nodes(target_write):
    source, target = _node(), _node(owner="alice" if target_write else "bob")
    relationship = MagicMock()
    relationship.model_dump.return_value = {"id": "edge"}
    with (
        patch("src.tools.manage_graph.read_memory_service", new_callable=AsyncMock, side_effect=[source, target]),
        patch(
            "src.tools.manage_graph.memory_object_access",
            new_callable=AsyncMock,
            side_effect=[(True, True), (True, target_write)],
        ),
        patch(
            "src.tools.manage_graph.create_relationship_service", new_callable=AsyncMock, return_value=relationship
        ) as create,
    ):
        call = _handle_create_relationship(
            None,
            _claims(),
            "default",
            AsyncMock(),
            str(source.id),
            str(target.id),
            "related_to",
            None,
            None,
        )
        if target_write:
            assert (await call)["id"] == "edge"
            create.assert_awaited_once()
        else:
            with pytest.raises(ToolError, match="write target_id"):
                await call
            create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("source_write", [False, True])
async def test_graduate_checks_source_and_target_scope(source_write):
    source = _node(owner="alice" if source_write else "bob")
    graduated = SimpleNamespace(
        id=uuid.uuid4(),
        scope="user",
        scope_id=None,
        content="knowledge",
        content_type="knowledge",
        weight=0.7,
        metadata={},
        created_at=datetime.now(UTC),
    )
    with (
        patch("src.core.authz.get_claims_from_context", return_value=_claims()),
        patch("src.tools._deps.get_db_session", new_callable=AsyncMock, return_value=(AsyncMock(), AsyncMock())),
        patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
        patch("memoryhub_core.services.memory.read_memory", new_callable=AsyncMock, return_value=source),
        patch(
            "src.tools._object_access.memory_object_access", new_callable=AsyncMock, return_value=(True, source_write)
        ),
        patch("src.tools._deps.get_embedding_service", return_value=MagicMock()),
        patch(
            "memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock, return_value=graduated
        ) as service,
    ):
        if source_write:
            assert (await _dispatch_graduate(str(source.id), None, {}, None))["graduated_memory"][
                "content"
            ] == "knowledge"
            service.assert_awaited_once()
        else:
            with pytest.raises(ToolError, match="Not authorized to graduate"):
                await _dispatch_graduate(str(source.id), None, {}, None)
            service.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_denies_foreign_project_and_allows_member():
    checkpoint = SimpleNamespace(id=uuid.uuid4(), metadata={"step": 1})
    claims = _claims()
    claims["scopes"].extend(["memory:read:project", "memory:write:project"])
    with (
        patch("src.core.authz.get_claims_from_context", return_value=claims),
        patch("src.tools._deps.get_db_session", new_callable=AsyncMock, return_value=(AsyncMock(), AsyncMock())),
        patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
        patch("src.tools._deps.get_embedding_service", return_value=MagicMock()),
        patch(
            "memoryhub_core.services.project.get_projects_for_user_in_tenant",
            new_callable=AsyncMock,
            side_effect=[set(), {"project-a"}],
        ),
        patch(
            "memoryhub_core.services.checkpoint.upsert_checkpoint",
            new_callable=AsyncMock,
            return_value=(checkpoint, True),
        ) as upsert,
    ):
        opts = {"workflow_name": "run", "state": {"step": 1}, "scope": "project", "scope_id": "project-a"}
        with pytest.raises(ToolError, match="Not authorized to write"):
            await _dispatch_checkpoint(opts, None)
        upsert.assert_not_awaited()
        assert (await _dispatch_checkpoint(opts, None))["created"] is True
        upsert.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "compile", "add_pin", "list_pins"])
async def test_persona_rejects_foreign_user_before_data_access(operation):
    with (
        patch("src.tools.get_persona.get_claims_from_context", return_value=_claims()),
        patch("src.tools.compile_persona.get_claims_from_context", return_value=_claims()),
        patch("src.tools.edit_persona.get_claims_from_context", return_value=_claims()),
        patch("src.tools.get_persona.get_db_session", new_callable=AsyncMock) as get_db,
        patch("src.tools.compile_persona.get_db_session", new_callable=AsyncMock) as compile_db,
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock) as edit_db,
    ):
        if operation == "get":
            call = get_persona(user_id="bob")
        elif operation == "compile":
            call = compile_persona(user_id="bob")
        else:
            call = edit_persona(action=operation, content="pin" if operation == "add_pin" else None, user_id="bob")
        with pytest.raises(ToolError, match="another user's persona"):
            await call
        get_db.assert_not_awaited()
        compile_db.assert_not_awaited()
        edit_db.assert_not_awaited()
