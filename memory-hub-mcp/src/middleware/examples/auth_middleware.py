"""Authentication middleware example (commented pattern).

This file provides a pattern for implementing authentication middleware.
Uncomment and customize based on your authentication requirements.
"""

from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
import mcp.types as mt
from fastmcp.tools.tool import ToolResult
from fastmcp.exceptions import ToolError

from core.logging import get_logger

log = get_logger("middleware.auth")


class AuthMiddleware(Middleware):
    """Verify authentication before tool execution.

    This is a commented example showing how to implement authentication
    middleware. To activate:
    1. Uncomment the implementation below
    2. Add `mcp.add_middleware(AuthMiddleware())` to your loaders

    Example authentication checks:
    - Verify JWT tokens from request headers
    - Check user permissions/scopes
    - Validate API keys
    - Rate limiting per user

    Example usage:
        from src.middleware.auth_middleware import AuthMiddleware
        mcp.add_middleware(AuthMiddleware())
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Verify authentication before tool execution.

        Args:
            context: Middleware context with request parameters
            call_next: Next handler in the middleware chain

        Returns:
            Tool execution result

        Raises:
            ToolError: If authentication fails
        """
        tool_name = context.message.name

        # Example: Check for authorization header
        # Note: FastMCP middleware doesn't have direct access to HTTP headers
        # You would need to implement this through FastMCP context or custom auth
        # auth_header = getattr(context.fastmcp_context, "headers", {}).get("Authorization")
        # if not auth_header:
        #     raise ToolError("Authentication required: Missing Authorization header")

        # Example: Verify JWT token
        # try:
        #     from core.auth import verify_jwt
        #     token = auth_header.replace("Bearer ", "")
        #     claims = verify_jwt(token)
        #     # Attach user info to context if needed
        # except Exception as e:
        #     raise ToolError(f"Authentication failed: {e}")

        # Example: Check required scopes
        # required_scopes = self._get_required_scopes(tool_name)
        # user_scopes = claims.get("scopes", [])
        # if not all(scope in user_scopes for scope in required_scopes):
        #     raise ToolError(f"Insufficient permissions for {tool_name}")

        log.debug(f"Auth middleware (commented) - passing through for {tool_name}")

        # Execute the tool
        return await call_next(context)

    def _get_required_scopes(self, tool_name: str) -> list[str]:
        """Get required scopes for a tool.

        This is an example function showing how you might map tools
        to required authentication scopes.

        Args:
            tool_name: Name of the tool being invoked

        Returns:
            List of required scope strings
        """
        # Example scope mapping
        scope_map = {
            "fetch_user": ["read:users"],
            "update_user": ["write:users"],
            "delete_user": ["delete:users", "admin"],
            "admin_action": ["admin"],
        }
        return scope_map.get(tool_name, [])
