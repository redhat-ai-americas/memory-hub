"""Tests for the unified memory() tool dispatcher (#201).

Tests the dispatcher routing, parameter validation, and forwarding logic.
Underlying tool functions are patched to isolate the dispatcher.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.tools.memory import (
    _VALID_ACTIONS,
    _forward,
    _opt_require,
    _require,
    memory,
)

# ── Helper tests ───────────────────────────────────────────────────────────

class TestHelpers:
    def test_require_passes_valid_string(self):
        assert _require("search", "query", "hello") == "hello"

    def test_require_raises_on_none(self):
        with pytest.raises(ToolError, match="action='search' requires 'query'"):
            _require("search", "query", None)

    def test_require_raises_on_empty_string(self):
        with pytest.raises(ToolError, match="action='write' requires 'content'"):
            _require("write", "content", "   ")

    def test_opt_require_passes_valid(self):
        assert _opt_require("relate", "source_id", {"source_id": "abc"}) == "abc"

    def test_opt_require_raises_missing_key(self):
        with pytest.raises(ToolError, match="requires 'source_id' in options"):
            _opt_require("relate", "source_id", {})

    def test_opt_require_raises_empty_value(self):
        with pytest.raises(ToolError, match="requires 'focus' in options"):
            _opt_require("set_focus", "focus", {"focus": ""})

    def test_forward_filters_keys(self):
        opts = {"max_results": 5, "focus": "test", "bogus": "ignored"}
        result = _forward(opts, frozenset({"max_results", "focus"}))
        assert result == {"max_results": 5, "focus": "test"}
        assert "bogus" not in result

    def test_forward_empty_opts(self):
        assert _forward({}, frozenset({"a", "b"})) == {}


# ── Action validation ──────────────────────────────────────────────────────

class TestActionValidation:
    @pytest.mark.asyncio
    async def test_invalid_action_raises(self):
        with pytest.raises(ToolError, match="Invalid action 'bogus'"):
            await memory(action="bogus")

    @pytest.mark.asyncio
    async def test_invalid_action_lists_valid(self):
        with pytest.raises(ToolError) as exc_info:
            await memory(action="not_real")
        msg = str(exc_info.value)
        # Should list at least a few valid actions
        assert "search" in msg
        assert "write" in msg

    def test_valid_actions_count(self):
        assert "guidance" in _VALID_ACTIONS
        assert len(_VALID_ACTIONS) == 29


# ── Required param validation ──────────────────────────────────────────────

class TestRequiredParams:
    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        with pytest.raises(ToolError, match="action='search' requires 'query'"):
            await memory(action="search")

    @pytest.mark.asyncio
    async def test_read_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='read' requires 'memory_id'"):
            await memory(action="read")

    @pytest.mark.asyncio
    async def test_write_requires_content(self):
        with pytest.raises(ToolError, match="action='write' requires 'content'"):
            await memory(action="write", scope="user")

    @pytest.mark.asyncio
    async def test_write_scope_defaults_to_user(self):
        """scope defaults to 'user' when omitted -- passes validation."""
        # Should pass scope validation and fail downstream (auth/DB).
        # The key assertion is that it does NOT raise "requires 'scope'".
        try:
            await memory(action="write", content="test")
        except ToolError as exc:
            assert "requires 'scope'" not in str(exc)

    @pytest.mark.asyncio
    async def test_delete_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='delete' requires 'memory_id'"):
            await memory(action="delete")

    @pytest.mark.asyncio
    async def test_update_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='update' requires 'memory_id'"):
            await memory(action="update")

    @pytest.mark.asyncio
    async def test_similar_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='similar' requires 'memory_id'"):
            await memory(action="similar")

    @pytest.mark.asyncio
    async def test_relationships_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='relationships' requires 'memory_id'"):
            await memory(action="relationships")

    @pytest.mark.asyncio
    async def test_focus_history_requires_project_id(self):
        with pytest.raises(ToolError, match="action='focus_history' requires 'project_id'"):
            await memory(action="focus_history")

    @pytest.mark.asyncio
    async def test_describe_project_requires_project_id(self):
        with pytest.raises(ToolError, match="action='describe_project' requires 'project_id'"):
            await memory(action="describe_project")

    @pytest.mark.asyncio
    async def test_set_focus_requires_project_id(self):
        with pytest.raises(ToolError, match="action='set_focus' requires 'project_id'"):
            await memory(action="set_focus", options={"focus": "test"})

    @pytest.mark.asyncio
    async def test_set_focus_requires_focus_option(self):
        with pytest.raises(ToolError, match="requires 'focus' in options"):
            await memory(action="set_focus", project_id="proj")

    @pytest.mark.asyncio
    async def test_relate_requires_source_id(self):
        with pytest.raises(ToolError, match="requires 'source_id' in options"):
            await memory(action="relate", options={
                "target_id": "b", "relationship_type": "related_to",
            })

    @pytest.mark.asyncio
    async def test_report_requires_observed_behavior(self):
        with pytest.raises(ToolError, match="requires 'observed_behavior' in options"):
            await memory(action="report", memory_id="abc")

    @pytest.mark.asyncio
    async def test_resolve_requires_contradiction_id(self):
        with pytest.raises(ToolError, match="requires 'contradiction_id' in options"):
            await memory(action="resolve", options={
                "resolution_action": "keep_old",
            })

    @pytest.mark.asyncio
    async def test_set_rule_requires_name(self):
        with pytest.raises(ToolError, match="requires 'name' in options"):
            await memory(action="set_rule")

    @pytest.mark.asyncio
    async def test_create_project_requires_project_id_or_project_name(self):
        with pytest.raises(ToolError, match="requires project_id or options.project_name"):
            await memory(action="create_project")

    @pytest.mark.asyncio
    async def test_add_member_requires_project_id(self):
        with pytest.raises(ToolError, match="action='add_member' requires 'project_id'"):
            await memory(action="add_member", options={"user_id": "u"})

    @pytest.mark.asyncio
    async def test_add_member_requires_user_id(self):
        with pytest.raises(ToolError, match="requires 'user_id' in options"):
            await memory(action="add_member", project_id="p")

    @pytest.mark.asyncio
    async def test_remove_member_requires_project_id(self):
        with pytest.raises(ToolError, match="action='remove_member' requires 'project_id'"):
            await memory(action="remove_member", options={"user_id": "u"})

    @pytest.mark.asyncio
    async def test_remove_member_requires_user_id(self):
        with pytest.raises(ToolError, match="requires 'user_id' in options"):
            await memory(action="remove_member", project_id="p")

    @pytest.mark.asyncio
    async def test_merge_entities_requires_source_id(self):
        with pytest.raises(ToolError, match="requires 'source_id' in options"):
            await memory(action="merge_entities", options={"target_id": "abc"})

    @pytest.mark.asyncio
    async def test_merge_entities_requires_target_id(self):
        with pytest.raises(ToolError, match="requires 'target_id' in options"):
            await memory(action="merge_entities", options={"source_id": "abc"})

    @pytest.mark.asyncio
    async def test_rename_entity_requires_memory_id(self):
        with pytest.raises(ToolError, match="action='rename_entity' requires 'memory_id'"):
            await memory(action="rename_entity", options={"new_name": "test"})

    @pytest.mark.asyncio
    async def test_rename_entity_requires_new_name(self):
        with pytest.raises(ToolError, match="requires 'new_name' in options"):
            await memory(action="rename_entity", memory_id="abc")


# ── Dispatch routing ───────────────────────────────────────────────────────

class TestDispatchRouting:
    """Verify each action routes to the correct underlying tool."""

    @pytest.mark.asyncio
    @patch("src.tools.search_memory.search_memory", new_callable=AsyncMock)
    async def test_search_dispatches(self, mock_search):
        mock_search.return_value = {"results": []}
        await memory(
            action="search", query="test query",
            scope="user", project_id="proj",
            options={"max_results": 5, "focus": "deployment"},
        )
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args[1]
        assert call_kwargs["query"] == "test query"
        assert call_kwargs["scope"] == "user"
        assert call_kwargs["project_id"] == "proj"
        assert call_kwargs["max_results"] == 5
        assert call_kwargs["focus"] == "deployment"
        # Dispatcher injects verbose=False by default (#255)
        assert call_kwargs["verbose"] is False

    @pytest.mark.asyncio
    @patch("src.tools.list_memory.list_memory", new_callable=AsyncMock)
    async def test_list_dispatches(self, mock_list):
        mock_list.return_value = {"results": [], "count": 0, "has_more": False}
        await memory(
            action="list", scope="project", project_id="my-proj",
            options={"max_results": 50, "cursor": "2026-05-01T00:00:00"},
        )
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["scope"] == "project"
        assert call_kwargs["project_id"] == "my-proj"
        assert call_kwargs["max_results"] == 50
        assert call_kwargs["cursor"] == "2026-05-01T00:00:00"
        # Dispatcher injects verbose=False by default (#255)
        assert call_kwargs["verbose"] is False

    @pytest.mark.asyncio
    @patch("src.tools.read_memory.read_memory", new_callable=AsyncMock)
    async def test_read_dispatches(self, mock_read):
        mock_read.return_value = {"id": "abc"}
        await memory(
            action="read", memory_id="abc-123",
            options={"include_versions": True},
        )
        mock_read.assert_called_once()
        call_kwargs = mock_read.call_args[1]
        assert call_kwargs["memory_id"] == "abc-123"
        assert call_kwargs["include_versions"] is True

    @pytest.mark.asyncio
    @patch("src.tools.manage_session.manage_session", new_callable=AsyncMock)
    async def test_status_dispatches(self, mock_session):
        mock_session.return_value = {"user_id": "test"}
        await memory(action="status")
        mock_session.assert_called_once()
        assert mock_session.call_args[1]["action"] == "status"

    @pytest.mark.asyncio
    @patch("src.tools.manage_session.manage_session", new_callable=AsyncMock)
    async def test_set_focus_dispatches(self, mock_session):
        mock_session.return_value = {"focus": "test"}
        await memory(
            action="set_focus", project_id="my-proj",
            options={"focus": "deployment work"},
        )
        mock_session.assert_called_once()
        kw = mock_session.call_args[1]
        assert kw["action"] == "set_focus"
        assert kw["project"] == "my-proj"
        assert kw["focus"] == "deployment work"

    @pytest.mark.asyncio
    @patch("src.tools.manage_graph.manage_graph", new_callable=AsyncMock)
    async def test_relationships_maps_memory_id_to_node_id(self, mock_graph):
        mock_graph.return_value = {"relationships": []}
        await memory(
            action="relationships", memory_id="node-uuid",
        )
        kw = mock_graph.call_args[1]
        assert kw["action"] == "get_relationships"
        assert kw["node_id"] == "node-uuid"

    @pytest.mark.asyncio
    @patch("src.tools.manage_project.manage_project", new_callable=AsyncMock)
    async def test_describe_project_maps_project_id_to_project_name(self, mock_proj):
        mock_proj.return_value = {"project": {}}
        await memory(
            action="describe_project", project_id="my-proj",
        )
        kw = mock_proj.call_args[1]
        assert kw["action"] == "describe"
        assert kw["project_name"] == "my-proj"

    @pytest.mark.asyncio
    @patch("src.tools.write_memory.write_memory", new_callable=AsyncMock)
    async def test_write_dispatches(self, mock_write):
        mock_write.return_value = {"memory": {"id": "new"}}
        await memory(
            action="write", content="test content", scope="user",
            options={"weight": 0.9, "domains": ["test"]},
        )
        mock_write.assert_called_once()
        kw = mock_write.call_args[1]
        assert kw["content"] == "test content"
        assert kw["scope"] == "user"
        assert kw["weight"] == 0.9
        assert kw["domains"] == ["test"]

    @pytest.mark.asyncio
    @patch("src.tools.manage_graph.manage_graph", new_callable=AsyncMock)
    async def test_relate_dispatches(self, mock_graph):
        mock_graph.return_value = {"id": "rel-1"}
        await memory(
            action="relate",
            options={
                "source_id": "aaa",
                "target_id": "bbb",
                "relationship_type": "derived_from",
            },
        )
        kw = mock_graph.call_args[1]
        assert kw["action"] == "create_relationship"
        assert kw["source_id"] == "aaa"
        assert kw["target_id"] == "bbb"

    @pytest.mark.asyncio
    @patch("src.tools.manage_curation.manage_curation", new_callable=AsyncMock)
    async def test_set_rule_forwards_all_opts(self, mock_cur):
        mock_cur.return_value = {"created": True}
        await memory(
            action="set_rule",
            options={
                "name": "my_rule",
                "tier": "regex",
                "action_type": "block",
                "config": {"pattern": "secret"},
                "enabled": True,
                "priority": 5,
            },
        )
        kw = mock_cur.call_args[1]
        assert kw["action"] == "set_rule"
        assert kw["name"] == "my_rule"
        assert kw["tier"] == "regex"
        assert kw["action_type"] == "block"
        assert kw["priority"] == 5

    @pytest.mark.asyncio
    @patch("src.tools.update_memory.update_memory", new_callable=AsyncMock)
    async def test_update_forwards_content_from_top_level(self, mock_update):
        mock_update.return_value = {"id": "upd"}
        await memory(
            action="update", memory_id="mem-1",
            content="new content",
            options={"weight": 0.5},
        )
        kw = mock_update.call_args[1]
        assert kw["memory_id"] == "mem-1"
        assert kw["content"] == "new content"
        assert kw["weight"] == 0.5

    @pytest.mark.asyncio
    @patch("src.tools.manage_project.manage_project", new_callable=AsyncMock)
    async def test_list_projects_forwards_filter(self, mock_proj):
        mock_proj.return_value = {"projects": []}
        await memory(
            action="list_projects",
            options={"filter": "all"},
        )
        kw = mock_proj.call_args[1]
        assert kw["action"] == "list"
        assert kw["filter"] == "all"

    @pytest.mark.asyncio
    @patch("src.tools.manage_project.manage_project", new_callable=AsyncMock)
    async def test_create_project_dispatches_via_options(self, mock_proj):
        mock_proj.return_value = {"project": {}}
        await memory(
            action="create_project",
            options={"project_name": "new-proj", "description": "A project"},
        )
        kw = mock_proj.call_args[1]
        assert kw["action"] == "create"
        assert kw["project_name"] == "new-proj"
        assert kw["description"] == "A project"

    @pytest.mark.asyncio
    @patch("src.tools.manage_project.manage_project", new_callable=AsyncMock)
    async def test_create_project_accepts_project_id(self, mock_proj):
        """project_id works as the project name for consistency."""
        mock_proj.return_value = {"project": {}}
        await memory(
            action="create_project", project_id="my-new-proj",
        )
        kw = mock_proj.call_args[1]
        assert kw["project_name"] == "my-new-proj"

    @pytest.mark.asyncio
    @patch("src.tools.manage_project.manage_project", new_callable=AsyncMock)
    async def test_create_project_options_takes_precedence(self, mock_proj):
        """options.project_name overrides project_id when both set."""
        mock_proj.return_value = {"project": {}}
        await memory(
            action="create_project", project_id="fallback",
            options={"project_name": "explicit"},
        )
        kw = mock_proj.call_args[1]
        assert kw["project_name"] == "explicit"

    @pytest.mark.asyncio
    @patch("memoryhub_core.services.entity.list_entities", new_callable=AsyncMock)
    @patch("src.core.authz.get_tenant_filter", return_value="default")
    @patch("src.core.authz.get_claims_from_context", return_value={"sub": "user-1", "tenant_id": "default", "scopes": ["memory:read"]})
    @patch("src.tools._deps.release_db_session", new_callable=AsyncMock)
    @patch("src.tools._deps.get_db_session", new_callable=AsyncMock)
    async def test_list_entities_dispatches(self, mock_get_db, mock_release_db, mock_claims, mock_tenant, mock_list):
        mock_session = AsyncMock()
        mock_get_db.return_value = (mock_session, AsyncMock())
        mock_list.return_value = {"entities": [], "total": 0, "limit": 50, "offset": 0, "has_more": False}

        await memory(
            action="list_entities",
            options={"entity_type": "person", "limit": 10},
        )

        mock_list.assert_called_once()
        kw = mock_list.call_args[1]
        assert kw["tenant_id"] == "default"
        assert kw["owner_id"] == "user-1"
        assert kw["entity_type"] == "person"
        assert kw["limit"] == 10

    @pytest.mark.asyncio
    @patch("memoryhub_core.services.entity.merge_entities", new_callable=AsyncMock)
    @patch("src.tools._deps.get_embedding_service")
    @patch("src.core.authz.get_tenant_filter", return_value="default")
    @patch("src.core.authz.get_claims_from_context", return_value={"sub": "user-1", "tenant_id": "default", "scopes": ["memory:write"]})
    @patch("src.tools._deps.release_db_session", new_callable=AsyncMock)
    @patch("src.tools._deps.get_db_session", new_callable=AsyncMock)
    async def test_merge_entities_dispatches(self, mock_get_db, mock_release_db, mock_claims, mock_tenant, mock_embed, mock_merge):
        mock_session = AsyncMock()
        mock_get_db.return_value = (mock_session, AsyncMock())
        mock_embed.return_value = AsyncMock()
        mock_merge.return_value = {
            "surviving_entity": {"id": "12345678-1234-5678-1234-567812345678", "content": "Target", "aliases": []},
            "reassigned_mentions": 3,
            "skipped_duplicates": 0,
            "source_deleted": "87654321-4321-8765-4321-876543218765",
            "message": "Merged",
        }

        await memory(
            action="merge_entities",
            options={
                "source_id": "87654321-4321-8765-4321-876543218765",
                "target_id": "12345678-1234-5678-1234-567812345678",
            },
        )

        mock_merge.assert_called_once()
        kw = mock_merge.call_args[1]
        assert kw["tenant_id"] == "default"
        assert kw["owner_id"] == "user-1"

    @pytest.mark.asyncio
    @patch("memoryhub_core.services.entity.rename_entity", new_callable=AsyncMock)
    @patch("src.tools._deps.get_embedding_service")
    @patch("src.core.authz.get_tenant_filter", return_value="default")
    @patch("src.core.authz.get_claims_from_context", return_value={"sub": "user-1", "tenant_id": "default", "scopes": ["memory:write"]})
    @patch("src.tools._deps.release_db_session", new_callable=AsyncMock)
    @patch("src.tools._deps.get_db_session", new_callable=AsyncMock)
    async def test_rename_entity_dispatches(self, mock_get_db, mock_release_db, mock_claims, mock_tenant, mock_embed, mock_rename):
        mock_session = AsyncMock()
        mock_get_db.return_value = (mock_session, AsyncMock())
        mock_embed.return_value = AsyncMock()
        mock_rename.return_value = {
            "entity": {"id": "12345678-1234-5678-1234-567812345678", "content": "New Name", "entity_type": "person", "aliases": ["Old Name"], "content_hash": "abc123"},
            "old_name": "Old Name",
            "message": "Renamed",
        }

        await memory(
            action="rename_entity",
            memory_id="12345678-1234-5678-1234-567812345678",
            options={"new_name": "New Name"},
        )

        mock_rename.assert_called_once()
        kw = mock_rename.call_args[1]
        assert kw["tenant_id"] == "default"
        assert kw["owner_id"] == "user-1"
        assert kw["new_name"] == "New Name"


# ── Compact default at dispatcher level (#255) ────────────────────────────

class TestCompactDefault:
    """The dispatcher injects verbose=False so agents get compact output,
    while direct callers of search_memory/list_memory keep verbose=True."""

    @pytest.mark.asyncio
    @patch("src.tools.search_memory.search_memory", new_callable=AsyncMock)
    async def test_search_defaults_verbose_false(self, mock_search):
        """Dispatcher injects verbose=False when caller omits it."""
        mock_search.return_value = {"results": []}
        await memory(action="search", query="test")
        kw = mock_search.call_args[1]
        assert kw["verbose"] is False

    @pytest.mark.asyncio
    @patch("src.tools.search_memory.search_memory", new_callable=AsyncMock)
    async def test_search_respects_explicit_verbose_true(self, mock_search):
        """Caller can override to verbose=True via options."""
        mock_search.return_value = {"results": []}
        await memory(
            action="search", query="test",
            options={"verbose": True},
        )
        kw = mock_search.call_args[1]
        assert kw["verbose"] is True

    @pytest.mark.asyncio
    @patch("src.tools.search_memory.search_memory", new_callable=AsyncMock)
    async def test_search_forwards_current_step_id(self, mock_search):
        """current_step_id reaches search_memory through the compact tool."""
        mock_search.return_value = {"results": [], "query_ignored": True}
        step_id = "12345678-1234-5678-1234-567812345678"
        await memory(
            action="search",
            query="deploy",
            options={"current_step_id": step_id, "max_hops": 2},
        )
        kw = mock_search.call_args[1]
        assert kw["current_step_id"] == step_id
        assert kw["max_hops"] == 2

    @pytest.mark.asyncio
    @patch("src.tools.manage_graph.manage_graph", new_callable=AsyncMock)
    async def test_guidance_forwards_node_and_hops(self, mock_graph):
        mock_graph.return_value = {"guidance_text": "next"}
        step_id = "12345678-1234-5678-1234-567812345678"
        await memory(
            action="guidance",
            memory_id=step_id,
            options={"max_hops": 1},
        )
        kw = mock_graph.call_args[1]
        assert kw["action"] == "get_guidance"
        assert kw["node_id"] == step_id
        assert kw["max_hops"] == 1

    @pytest.mark.asyncio
    @patch("src.tools.list_memory.list_memory", new_callable=AsyncMock)
    async def test_list_defaults_verbose_false(self, mock_list):
        """Dispatcher injects verbose=False when caller omits it."""
        mock_list.return_value = {"results": [], "count": 0, "has_more": False}
        await memory(action="list")
        kw = mock_list.call_args[1]
        assert kw["verbose"] is False

    @pytest.mark.asyncio
    @patch("src.tools.list_memory.list_memory", new_callable=AsyncMock)
    async def test_list_respects_explicit_verbose_true(self, mock_list):
        """Caller can override to verbose=True via options."""
        mock_list.return_value = {"results": [], "count": 0, "has_more": False}
        await memory(
            action="list",
            options={"verbose": True},
        )
        kw = mock_list.call_args[1]
        assert kw["verbose"] is True


# ── Options isolation ──────────────────────────────────────────────────────

class TestOptionsIsolation:
    """Verify that options from one action don't leak to another."""

    @pytest.mark.asyncio
    @patch("src.tools.read_memory.read_memory", new_callable=AsyncMock)
    async def test_search_opts_not_forwarded_to_read(self, mock_read):
        mock_read.return_value = {"id": "abc"}
        await memory(
            action="read", memory_id="abc",
            options={"max_results": 5, "focus": "should-be-ignored"},
        )
        kw = mock_read.call_args[1]
        assert "max_results" not in kw
        assert "focus" not in kw

    @pytest.mark.asyncio
    @patch("memoryhub_core.services.entity.list_entities", new_callable=AsyncMock)
    @patch("src.core.authz.get_tenant_filter", return_value="default")
    @patch("src.core.authz.get_claims_from_context", return_value={"sub": "user-1", "tenant_id": "default", "scopes": ["memory:read"]})
    @patch("src.tools._deps.release_db_session", new_callable=AsyncMock)
    @patch("src.tools._deps.get_db_session", new_callable=AsyncMock)
    async def test_search_opts_not_forwarded_to_list_entities(self, mock_get_db, mock_release_db, mock_claims, mock_tenant, mock_list):
        mock_session = AsyncMock()
        mock_get_db.return_value = (mock_session, AsyncMock())
        mock_list.return_value = {"entities": [], "total": 0, "limit": 50, "offset": 0, "has_more": False}

        await memory(
            action="list_entities",
            options={"max_results": 5, "focus": "should-be-ignored", "entity_type": "person"},
        )

        kw = mock_list.call_args[1]
        assert "max_results" not in kw
        assert "focus" not in kw
        assert kw["entity_type"] == "person"
