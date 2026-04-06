"""Tests for delete_memory tool."""

import inspect

import pytest
from unittest.mock import AsyncMock

from src.tools.delete_memory import delete_memory


def test_delete_memory_is_importable():
    """Verify the tool module imports and the decorated function exists."""
    assert delete_memory is not None
    assert callable(delete_memory)


def test_delete_memory_has_required_parameters():
    """Verify memory_id is the only required parameter."""
    sig = inspect.signature(delete_memory)
    params = sig.parameters

    assert "memory_id" in params
    assert "ctx" in params

    # memory_id has no default — it is required
    assert params["memory_id"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_delete_memory_has_destructive_annotation():
    """Verify the tool is annotated as destructive and not idempotent.

    Tool annotations are how the consuming agent's harness knows to surface
    delete operations to the user. If these regress to the scaffold defaults
    (readOnlyHint=True, idempotentHint=True) the tool will silently lose its
    destructive disclosure.
    """
    from src.core.app import mcp

    tool = await mcp.get_tool("delete_memory")
    assert tool is not None, "delete_memory must be registered with the mcp instance"

    annotations = tool.annotations
    assert annotations is not None, "delete_memory must have tool annotations"
    assert annotations.readOnlyHint is False, "delete_memory must not be readOnly"
    assert annotations.destructiveHint is True, "delete_memory must be marked destructive"
    assert annotations.idempotentHint is False, "delete_memory must not be marked idempotent"
    assert annotations.openWorldHint is False, "delete_memory does not touch external systems"


@pytest.mark.asyncio
async def test_delete_memory_rejects_invalid_uuid():
    """Calling with a bad UUID should raise ToolError before any DB work."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await delete_memory(memory_id="not-a-uuid", ctx=ctx)
