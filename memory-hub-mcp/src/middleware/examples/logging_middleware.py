"""Logging middleware for tracking tool invocations.

This middleware logs all tool calls with execution time and status.
"""

import time
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
import mcp.types as mt
from fastmcp.tools.tool import ToolResult

from core.logging import get_logger

log = get_logger("middleware.logging")


class LoggingMiddleware(Middleware):
    """Log tool invocations with timing information.

    This middleware captures:
    - Tool name
    - Execution start time
    - Execution duration
    - Success/failure status

    Example usage:
        from src.middleware.logging_middleware import LoggingMiddleware
        mcp.add_middleware(LoggingMiddleware())
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Log tool invocation before and after execution.

        Args:
            context: Middleware context with request parameters
            call_next: Next handler in the middleware chain

        Returns:
            Tool execution result
        """
        tool_name = context.message.name

        # Log request start
        start_time = time.time()
        log.info(f"Tool invoked: {tool_name}")
        log.debug(f"Tool arguments: {context.message.arguments}")

        try:
            # Execute the tool
            result = await call_next(context)

            # Log successful completion
            duration = time.time() - start_time
            log.info(f"Tool completed: {tool_name} (duration: {duration:.3f}s)")

            return result
        except Exception as e:
            # Log failure
            duration = time.time() - start_time
            log.error(
                f"Tool failed: {tool_name} (duration: {duration:.3f}s) - "
                f"{type(e).__name__}: {e}"
            )
            raise
