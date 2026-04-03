"""Tests for report_contradiction tool."""

import pytest
from unittest.mock import AsyncMock

from src.tools.report_contradiction import report_contradiction


@pytest.mark.asyncio
async def test_report_contradiction_import():
    """Verify the tool imports and is callable."""
    assert report_contradiction is not None
    assert callable(report_contradiction)


@pytest.mark.asyncio
async def test_report_contradiction_invalid_uuid():
    """Test that an invalid UUID returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await report_contradiction(
            memory_id="not-a-uuid",
            observed_behavior="User used Docker",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_empty_behavior():
    """Test that empty observed_behavior returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="observed_behavior cannot be empty"):
        await report_contradiction(
            memory_id="550e8400-e29b-41d4-a716-446655440000",
            observed_behavior="   ",
            ctx=ctx,
        )
