"""Tests for the persona action dispatcher."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.tools.persona import persona


@pytest.mark.asyncio
async def test_get_delegates_to_existing_tool():
    expected = {"synopsis": {"content": "Profile"}}
    with patch(
        "src.tools.get_persona.get_persona",
        new_callable=AsyncMock,
        return_value=expected,
    ) as get_persona:
        result = await persona(
            action="get", user_id="alice", project_id="project-a"
        )

    assert result == expected
    get_persona.assert_awaited_once_with(
        user_id="alice", project_id="project-a", ctx=None
    )


@pytest.mark.asyncio
async def test_compile_delegates_to_existing_tool():
    expected = {"version": 2}
    with patch(
        "src.tools.compile_persona.compile_persona",
        new_callable=AsyncMock,
        return_value=expected,
    ) as compile_persona:
        result = await persona(action="compile", user_id="alice")

    assert result == expected
    compile_persona.assert_awaited_once_with(
        user_id="alice", project_id=None, ctx=None
    )


@pytest.mark.asyncio
async def test_edit_add_pin_delegates_to_existing_tool():
    expected = {"pin_id": "pin-1"}
    with patch(
        "src.tools.edit_persona.edit_persona",
        new_callable=AsyncMock,
        return_value=expected,
    ) as edit_persona:
        result = await persona(
            action="edit",
            user_id="alice",
            options={
                "edit_action": "add_pin",
                "content": "I prefer concise summaries.",
            },
        )

    assert result == expected
    edit_persona.assert_awaited_once_with(
        action="add_pin",
        content="I prefer concise summaries.",
        user_id="alice",
        ctx=None,
    )


@pytest.mark.asyncio
async def test_edit_list_pins_delegates_to_existing_tool():
    expected = {"pins": [], "count": 0}
    with patch(
        "src.tools.edit_persona.edit_persona",
        new_callable=AsyncMock,
        return_value=expected,
    ) as edit_persona:
        result = await persona(
            action="edit", options={"edit_action": "list_pins"}
        )

    assert result == expected
    edit_persona.assert_awaited_once_with(
        action="list_pins", content=None, user_id=None, ctx=None
    )


@pytest.mark.asyncio
async def test_unknown_action_raises_tool_error():
    with pytest.raises(ToolError, match="Invalid action 'delete'"):
        await persona(action="delete")


@pytest.mark.asyncio
async def test_edit_requires_valid_edit_action():
    with pytest.raises(ToolError, match="options.edit_action"):
        await persona(action="edit")

    with pytest.raises(ToolError, match="options.edit_action"):
        await persona(action="edit", options={"edit_action": "delete_pin"})


@pytest.mark.asyncio
async def test_edit_add_pin_requires_nonempty_content():
    with pytest.raises(ToolError, match="options.content is required"):
        await persona(
            action="edit", options={"edit_action": "add_pin", "content": " "}
        )
