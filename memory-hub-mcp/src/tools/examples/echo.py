from typing import Annotated
from ...core.app import mcp
from fastmcp import Context


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def echo(
    message: Annotated[str, "The message to echo back"],
    ctx: Context = None,
) -> str:
    """Echo back the provided message and log it."""
    await ctx.info(f"echo called with: {message}")
    return message
