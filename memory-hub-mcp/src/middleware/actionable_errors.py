"""Return actionable, structured results for expected MCP tool failures."""

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import ToolResult

_logger = logging.getLogger(__name__)


def _next_action(message: str) -> str:
    """Choose a recovery hint from the public tool error message."""
    normalized = message.lower()

    if any(
        marker in normalized
        for marker in ("authentication", "invalid api key", "no authenticated session")
    ):
        return "Run 'memoryhub doctor' to verify the connection and credentials."
    if any(marker in normalized for marker in ("not authorized", "access denied", "permission")):
        return "Check the account's permissions or ask an administrator to grant access."
    if "not found" in normalized:
        return "Verify the identifier and confirm the resource is available to this session."
    if any(
        marker in normalized
        for marker in ("invalid ", " must be ", "cannot be empty")
    ):
        return "Correct the tool arguments and retry."
    if any(
        marker in normalized
        for marker in ("unavailable", "connection", "timeout", "database")
    ):
        return "Run 'memoryhub doctor' to check the server, then retry."
    return "Run 'memoryhub doctor' to verify the connection, then retry."


class ActionableToolErrorsMiddleware(Middleware):
    """Convert tool exceptions into readable structured MCP errors."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        try:
            return await call_next(context)
        except ToolError as exc:
            message = str(exc)
            # FastMCP converts unexpected exceptions into a ToolError such as
            # "Error calling tool 'name': <exception>" when detail masking is
            # disabled. Never pass that wrapper (which may contain secrets) to
            # the caller; the server also enables FastMCP's masking option.
            if message.startswith("Error calling tool "):
                message = "MemoryHub could not complete the tool request."
            next_action = _next_action(message)
            payload = {"error": message, "next_action": next_action}
            return ToolResult(
                content=f"{message}\nNext action: {next_action}",
                structured_content=payload,
                is_error=True,
            )
        except Exception:
            _logger.exception("Unhandled error while executing MCP tool")
            message = "MemoryHub could not complete the tool request."
            next_action = (
                "Run 'memoryhub doctor' to check server health. Retry, and contact an "
                "administrator if the problem continues."
            )
            return ToolResult(
                content=f"{message}\nNext action: {next_action}",
                structured_content={"error": message, "next_action": next_action},
                is_error=True,
            )
