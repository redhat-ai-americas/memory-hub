"""Tests for the unified memory() tool dispatcher (#201).

Tests the dispatcher routing, parameter validation, and forwarding logic.
Underlying tool functions are patched to isolate the dispatcher.
"""

import pytest
from unittest.mock import AsyncMock, patch

from fastmcp.exceptions import ToolError

from src.tools.memory import (
    memory,
    _VALID_ACTIONS,
    _require,
    _opt_require,
    _forward,
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
        assert len(_VALID_ACTIONS) == 19


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
    async def test_write_requires_scope(self):
        with pytest.raises(ToolError, match="action='write' requires 'scope'"):
            await memory(action="write", content="test")

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
