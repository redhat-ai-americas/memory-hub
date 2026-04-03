"""Tests for get_memory_history tool."""

import pytest
from unittest.mock import AsyncMock

from src.tools.get_memory_history import get_memory_history


@pytest.mark.asyncio
async def test_get_memory_history_import():
    """Verify the tool imports and is callable."""
    assert get_memory_history is not None
    assert callable(get_memory_history)


@pytest.mark.asyncio
async def test_get_memory_history_invalid_uuid():
    """Test that an invalid UUID returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await get_memory_history(memory_id="not-a-uuid", ctx=ctx)
