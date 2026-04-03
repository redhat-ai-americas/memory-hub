from typing import Annotated
from dataclasses import dataclass
from fastmcp import Context
from ...core.app import mcp


@dataclass
class Confirm:
    ok: bool


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": False,
    }
)
async def delete_all(ctx: Context = None) -> str:
    """Dangerous example: asks user to confirm via elicitation before proceeding."""
    result = await ctx.elicit(
        message="DELETE ALL DATA in workspace?", response_type=Confirm
    )

    if result.action == "accept":
        return "deleted" if result.data.ok else "cancelled"
    elif result.action == "decline":
        return "User declined to provide confirmation"
    else:  # cancel
        return "Operation cancelled"


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def get_weather(
    location: Annotated[str | None, "City or location for weather lookup"] = None,
    ctx: Context = None,
) -> str:
    """Get weather for a location, asking user if not specified."""
    if not location:
        # Ask user for the location
        result = await ctx.elicit(
            message="Which city would you like weather for?", response_type=str
        )

        if result.action == "accept":
            location = result.data
        else:
            return "Weather request cancelled - no location provided"

    # In a real implementation, you would fetch actual weather data here
    return f"Weather for {location}: Sunny, 72°F (this is demo data)"
