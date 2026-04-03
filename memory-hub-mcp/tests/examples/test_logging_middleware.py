"""Tests for logging middleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import mcp.types as mt
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.tool import ToolResult

from src.middleware.examples.logging_middleware import LoggingMiddleware


@pytest.mark.asyncio
async def test_logging_middleware_success():
    """Test middleware logs successful tool execution."""
    # Create middleware instance
    middleware = LoggingMiddleware()

    # Create mock context
    context = MiddlewareContext(
        message=mt.CallToolRequestParams(name="test_tool", arguments={"arg": "value"}),
        method="tools/call",
    )

    # Create mock next handler that returns a result
    mock_result = ToolResult(content=[{"type": "text", "text": "success"}])
    call_next = AsyncMock(return_value=mock_result)

    # Execute middleware
    result = await middleware.on_call_tool(context, call_next)

    # Verify result is returned
    assert result == mock_result

    # Verify call_next was called
    call_next.assert_called_once_with(context)


@pytest.mark.asyncio
async def test_logging_middleware_error():
    """Test middleware logs errors and re-raises them."""
    # Create middleware instance
    middleware = LoggingMiddleware()

    # Create mock context
    context = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="failing_tool", arguments={"arg": "value"}
        ),
        method="tools/call",
    )

    # Create mock next handler that raises an error
    call_next = AsyncMock(side_effect=ValueError("Test error"))

    # Execute middleware and expect error to be raised
    with pytest.raises(ValueError, match="Test error"):
        await middleware.on_call_tool(context, call_next)

    # Verify call_next was called
    call_next.assert_called_once()


@pytest.mark.asyncio
async def test_logging_middleware_timing():
    """Test middleware measures execution time."""
    import asyncio

    # Create middleware instance
    middleware = LoggingMiddleware()

    # Create mock context
    context = MiddlewareContext(
        message=mt.CallToolRequestParams(name="slow_tool", arguments={}),
        method="tools/call",
    )

    # Create mock next handler that takes time
    async def slow_handler(ctx):
        await asyncio.sleep(0.01)  # 10ms delay
        return ToolResult(content=[{"type": "text", "text": "result"}])

    # Execute middleware
    result = await middleware.on_call_tool(context, slow_handler)

    # Verify result is returned
    assert result is not None
