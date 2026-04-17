"""Return the current session state without re-authenticating.

Lightweight 'whoami' tool for agents to verify their identity and
check whether a session is still active after errors or reconnects.
"""

from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from src.core.app import mcp
from src.core.authz import AuthenticationError, get_claims_from_context
from src.tools.auth import get_current_user


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_session(
    ctx: Context = None,
) -> dict[str, Any]:
    """Check your current session state.

    Returns your user_id, name, and accessible scopes if authenticated.
    Raises an error if no session is registered — call register_session
    to fix.
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No active session. Call register_session(api_key=...) first."
        ) from None

    # Prefer the display name from the session user dict (set by
    # register_session) over the claims sub, which is the login ID.
    session_user = get_current_user()
    display_name = (
        session_user.get("name", claims["sub"]) if session_user
        else claims.get("name", claims["sub"])
    )

    return {
        "user_id": claims["sub"],
        "name": display_name,
        "scopes": claims.get("scopes", []),
        "authenticated": True,
    }
