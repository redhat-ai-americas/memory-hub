"""Register an authenticated session using an API key.

Agents must call this tool once at the start of every conversation to
establish identity. The authenticated user_id is then used automatically
by write_memory and search_memory when no explicit owner_id is supplied.
"""

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from src.core.app import mcp
from src.tools.auth import authenticate, set_session


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def register_session(
    api_key: Annotated[
        str,
        Field(
            description=(
                "Your MemoryHub API key. Provided by the system administrator. "
                "Format: mh-dev-<username>-<year>."
            ),
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Register this session with your API key.

    Call this once at the start of every conversation to establish your identity.
    After registration, write_memory and search_memory will automatically scope
    operations to your user_id. Returns your identity and accessible memory scopes.
    """
    # When JWT auth is active, session registration is unnecessary
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
    except Exception:
        token = None

    if token is not None:
        jwt_claims = token.claims
        return {
            "user_id": jwt_claims.get("sub", token.client_id),
            "name": jwt_claims.get("name", jwt_claims.get("sub", token.client_id)),
            "scopes": list(token.scopes),
            "auth_method": "jwt",
            "message": (
                f"JWT authentication active for {jwt_claims.get('sub', token.client_id)}. "
                "Session registration is not needed when using JWT auth."
            ),
        }

    user = authenticate(api_key)

    if user is None:
        return {
            "error": True,
            "message": (
                "Invalid API key. Contact your system administrator for a valid key. "
                "Keys follow the format: mh-dev-<username>-<year>."
            ),
        }

    set_session(user)

    if ctx:
        await ctx.info(f"Session registered for user: {user['user_id']}")

    return {
        "user_id": user["user_id"],
        "name": user["name"],
        "scopes": user["scopes"],
        "message": (
            f"Session registered for {user['name']} ({user['user_id']}). "
            f"Accessible scopes: {', '.join(user['scopes'])}."
        ),
    }
