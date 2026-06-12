"""Tests for the thread MCP tool dispatch layer."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError


class TestThreadActionValidation:
    @pytest.mark.asyncio
    async def test_invalid_action_raises(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="Invalid action"):
            await thread(action="explode")

    @pytest.mark.asyncio
    async def test_create_requires_scope(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_create") as mock:
            mock.side_effect = ToolError("action='create' requires 'scope'")
            with pytest.raises(ToolError, match="requires 'scope'"):
                await thread(action="create")

    @pytest.mark.asyncio
    async def test_append_requires_thread_id(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_append") as mock:
            mock.side_effect = ToolError("action='append' requires 'thread_id'")
            with pytest.raises(ToolError, match="requires 'thread_id'"):
                await thread(action="append", role="user", content="hello")

    @pytest.mark.asyncio
    async def test_append_requires_role(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_append") as mock:
            mock.side_effect = ToolError("action='append' requires 'role'")
            with pytest.raises(ToolError, match="requires 'role'"):
                await thread(action="append", thread_id=str(uuid.uuid4()), content="hello")

    @pytest.mark.asyncio
    async def test_append_requires_content(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_append") as mock:
            mock.side_effect = ToolError("action='append' requires 'content'")
            with pytest.raises(ToolError, match="requires 'content'"):
                await thread(action="append", thread_id=str(uuid.uuid4()), role="user")

    @pytest.mark.asyncio
    async def test_get_requires_thread_id(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_get") as mock:
            mock.side_effect = ToolError("action='get' requires 'thread_id'")
            with pytest.raises(ToolError, match="requires 'thread_id'"):
                await thread(action="get")

    @pytest.mark.asyncio
    async def test_archive_requires_thread_id(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_archive") as mock:
            mock.side_effect = ToolError("action='archive' requires 'thread_id'")
            with pytest.raises(ToolError, match="requires 'thread_id'"):
                await thread(action="archive")


class TestThreadDispatchRouting:
    @pytest.mark.asyncio
    async def test_create_routes_to_dispatch_create(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_create", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": str(uuid.uuid4()), "scope": "user"}
            result = await thread(action="create", scope="user")
            mock.assert_awaited_once()
            # _dispatch_create(scope, opts, ctx)
            assert mock.call_args[0][0] == "user"  # scope
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert "id" in result

    @pytest.mark.asyncio
    async def test_append_routes_to_dispatch_append(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_append", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "id": str(uuid.uuid4()),
                "thread_id": tid,
                "sequence_number": 1,
                "role": "user",
                "content": "hello",
            }
            result = await thread(action="append", thread_id=tid, role="user", content="hello")
            mock.assert_awaited_once()
            # _dispatch_append(thread_id, role, content, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert mock.call_args[0][1] == "user"  # role
            assert mock.call_args[0][2] == "hello"  # content
            assert result["thread_id"] == tid

    @pytest.mark.asyncio
    async def test_get_routes_to_dispatch_get(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_get", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "thread": {"id": tid, "scope": "user"},
                "messages": [],
                "has_more": False,
            }
            result = await thread(action="get", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_get(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["thread"]["id"] == tid

    @pytest.mark.asyncio
    async def test_list_routes_to_dispatch_list(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_list", new_callable=AsyncMock) as mock:
            mock.return_value = {"threads": [], "total": 0}
            result = await thread(action="list")
            mock.assert_awaited_once()
            # _dispatch_list(scope, opts, ctx)
            assert mock.call_args[0][0] is None  # scope (optional)
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_scope_forwards_scope(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_list", new_callable=AsyncMock) as mock:
            mock.return_value = {"threads": [], "total": 0}
            await thread(action="list", scope="project")
            mock.assert_awaited_once()
            assert mock.call_args[0][0] == "project"  # scope

    @pytest.mark.asyncio
    async def test_archive_routes_to_dispatch_archive(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_archive", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": tid, "status": "archived"}
            result = await thread(action="archive", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_archive(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["status"] == "archived"


class TestThreadOptionsForwarding:
    @pytest.mark.asyncio
    async def test_create_forwards_valid_options(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_create", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": str(uuid.uuid4())}
            await thread(
                action="create",
                scope="user",
                options={
                    "title": "My Thread",
                    "participant_ids": ["user-1", "agent-2"],
                    "metadata": {"key": "value"},
                },
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][1]
            assert opts["title"] == "My Thread"
            assert opts["participant_ids"] == ["user-1", "agent-2"]
            assert opts["metadata"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_append_forwards_valid_options(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_append", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": str(uuid.uuid4()), "sequence_number": 1}
            await thread(
                action="append",
                thread_id=tid,
                role="user",
                content="hello",
                options={"actor_id": "agent-1", "tool_call_id": "tc-123"},
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][3]  # Fourth arg is opts
            assert opts["actor_id"] == "agent-1"
            assert opts["tool_call_id"] == "tc-123"

    @pytest.mark.asyncio
    async def test_append_opts_include_a2a(self):
        from src.tools.thread import _APPEND_OPTS

        assert "a2a_context_id" in _APPEND_OPTS

    @pytest.mark.asyncio
    async def test_get_forwards_valid_options(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_get", new_callable=AsyncMock) as mock:
            mock.return_value = {"thread": {"id": tid}, "messages": []}
            await thread(
                action="get",
                thread_id=tid,
                options={"limit": 25, "before_sequence": 100, "include_messages": True},
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][1]
            assert opts["limit"] == 25
            assert opts["before_sequence"] == 100
            assert opts["include_messages"] is True

    @pytest.mark.asyncio
    async def test_list_forwards_valid_options(self):
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_list", new_callable=AsyncMock) as mock:
            mock.return_value = {"threads": [], "total": 0}
            await thread(
                action="list",
                options={
                    "scope_id": "proj-123",
                    "status": "archived",
                    "participant_id": "user-1",
                    "limit": 10,
                    "offset": 20,
                },
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][1]
            assert opts["scope_id"] == "proj-123"
            assert opts["status"] == "archived"
            assert opts["participant_id"] == "user-1"
            assert opts["limit"] == 10
            assert opts["offset"] == 20

    @pytest.mark.asyncio
    async def test_archive_forwards_valid_options(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_archive", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": tid, "status": "archived"}
            await thread(
                action="archive",
                thread_id=tid,
                options={"reason": "user_request"},
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][1]
            assert opts["reason"] == "user_request"

    @pytest.mark.asyncio
    async def test_options_forwarded_unfiltered_to_dispatcher(self):
        """Options are passed through to dispatchers; filtering happens inside each dispatcher."""
        from src.tools.thread import thread

        with patch("src.tools.thread._dispatch_create", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": str(uuid.uuid4())}
            await thread(
                action="create",
                scope="user",
                options={"title": "Valid", "extra": "ignored_by_forward"},
            )
            mock.assert_awaited_once()
            opts = mock.call_args[0][1]
            assert "title" in opts
            assert "extra" in opts  # Passed through; _forward filters inside dispatcher


class TestExtractAction:
    @pytest.mark.asyncio
    async def test_extract_in_valid_actions(self):
        from src.tools.thread import _VALID_ACTIONS

        assert "extract" in _VALID_ACTIONS

    @pytest.mark.asyncio
    async def test_extract_requires_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="requires 'thread_id'"):
            await thread(action="extract")

    @pytest.mark.asyncio
    async def test_extract_invalid_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="Invalid thread_id"):
            await thread(action="extract", thread_id="not-a-uuid")

    @pytest.mark.asyncio
    async def test_extract_opts_forwarded(self):
        from src.tools.thread import _EXTRACT_OPTS, _forward

        test_opts = {
            "turn_range": [1, 5],
            "model": "test-model",
            "model_url": "http://test",
            "garbage": "ignored",
        }
        result = _forward(test_opts, _EXTRACT_OPTS)

        assert "turn_range" in result
        assert "model" in result
        assert "model_url" in result
        assert "garbage" not in result
        assert result["turn_range"] == [1, 5]
        assert result["model"] == "test-model"
        assert result["model_url"] == "http://test"

    @pytest.mark.asyncio
    async def test_extract_action_dispatched(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_extract", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "extracted_count": 3,
                "cursor": 10,
                "failures": 0,
            }
            result = await thread(action="extract", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_extract(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["extracted_count"] == 3


class TestForkAction:
    @pytest.mark.asyncio
    async def test_fork_in_valid_actions(self):
        from src.tools.thread import _VALID_ACTIONS

        assert "fork" in _VALID_ACTIONS

    @pytest.mark.asyncio
    async def test_fork_requires_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="requires 'thread_id'"):
            await thread(action="fork")

    @pytest.mark.asyncio
    async def test_fork_invalid_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="Invalid thread_id"):
            await thread(action="fork", thread_id="not-a-uuid")

    @pytest.mark.asyncio
    async def test_fork_opts_forwarded(self):
        from src.tools.thread import _FORK_OPTS, _forward

        test_opts = {
            "from_sequence": 5,
            "title": "test",
            "garbage": "x",
        }
        result = _forward(test_opts, _FORK_OPTS)

        assert "from_sequence" in result
        assert "title" in result
        assert "garbage" not in result
        assert result["from_sequence"] == 5
        assert result["title"] == "test"

    @pytest.mark.asyncio
    async def test_fork_action_dispatched(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_fork", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": "test"}
            result = await thread(action="fork", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_fork(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["id"] == "test"


class TestShareAction:
    @pytest.mark.asyncio
    async def test_share_in_valid_actions(self):
        from src.tools.thread import _VALID_ACTIONS

        assert "share" in _VALID_ACTIONS

    @pytest.mark.asyncio
    async def test_share_requires_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="requires 'thread_id'"):
            await thread(action="share")

    @pytest.mark.asyncio
    async def test_share_invalid_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="Invalid thread_id"):
            await thread(action="share", thread_id="not-a-uuid")

    @pytest.mark.asyncio
    async def test_share_opts_forwarded(self):
        from src.tools.thread import _SHARE_OPTS, _forward

        test_opts = {
            "grantee_id": "agent-b",
            "access_level": "read",
            "authorized_by": "admin",
            "junk": "x",
        }
        result = _forward(test_opts, _SHARE_OPTS)

        assert "grantee_id" in result
        assert "access_level" in result
        assert "authorized_by" in result
        assert "junk" not in result
        assert result["grantee_id"] == "agent-b"
        assert result["access_level"] == "read"
        assert result["authorized_by"] == "admin"

    @pytest.mark.asyncio
    async def test_share_action_dispatched(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_share", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": "test"}
            result = await thread(action="share", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_share(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["id"] == "test"


class TestDeleteAction:
    @pytest.mark.asyncio
    async def test_delete_in_valid_actions(self):
        from src.tools.thread import _VALID_ACTIONS

        assert "delete" in _VALID_ACTIONS

    @pytest.mark.asyncio
    async def test_delete_requires_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="requires 'thread_id'"):
            await thread(action="delete")

    @pytest.mark.asyncio
    async def test_delete_invalid_thread_id(self):
        from src.tools.thread import thread

        with pytest.raises(ToolError, match="Invalid thread_id"):
            await thread(action="delete", thread_id="not-a-uuid")

    @pytest.mark.asyncio
    async def test_delete_opts_forwarded(self):
        from src.tools.thread import _DELETE_OPTS, _forward

        test_opts = {
            "cascade": "orphan",
            "garbage": "x",
        }
        result = _forward(test_opts, _DELETE_OPTS)

        assert "cascade" in result
        assert "garbage" not in result
        assert result["cascade"] == "orphan"

    @pytest.mark.asyncio
    async def test_delete_action_dispatched(self):
        from src.tools.thread import thread

        tid = str(uuid.uuid4())
        with patch("src.tools.thread._dispatch_delete", new_callable=AsyncMock) as mock:
            mock.return_value = {"id": "test", "status": "deleted"}
            result = await thread(action="delete", thread_id=tid)
            mock.assert_awaited_once()
            # _dispatch_delete(thread_id, opts, ctx)
            assert mock.call_args[0][0] == tid  # thread_id
            assert isinstance(mock.call_args[0][1], dict)  # opts
            assert result["id"] == "test"
            assert result["status"] == "deleted"
