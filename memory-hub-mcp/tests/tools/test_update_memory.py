"""Tests for update_memory tool."""

import inspect

import pytest
from unittest.mock import AsyncMock

from src.tools.update_memory import update_memory


def test_update_memory_is_importable():
    """Verify the tool module imports and the decorated function exists."""
    assert update_memory is not None
    assert callable(update_memory)


def test_update_memory_has_required_parameters():
    """Verify memory_id is a required parameter."""
    sig = inspect.signature(update_memory)
    params = sig.parameters

    assert "memory_id" in params
    assert "content" in params
    assert "weight" in params
    assert "metadata" in params
    assert "ctx" in params

    # memory_id has no default -- it is required
    assert params["memory_id"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_update_memory_rejects_no_changes():
    """Calling with no update fields should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="No changes provided"):
        await update_memory(memory_id="00000000-0000-0000-0000-000000000001", ctx=ctx)


@pytest.mark.asyncio
async def test_update_memory_rejects_invalid_uuid():
    """Calling with a bad UUID should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await update_memory(memory_id="not-a-uuid", content="new content", ctx=ctx)
