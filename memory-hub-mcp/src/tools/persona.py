"""Persona operations with action dispatch.

Exposes retrieval, compilation, and pin management through one ``persona``
tool while reusing the existing persona implementations.
"""

from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp

_VALID_ACTIONS = frozenset({"get", "compile", "edit"})


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def persona(
    action: Annotated[
        str,
        Field(description="Persona operation: 'get', 'compile', or 'edit'."),
    ],
    user_id: Annotated[
        str | None,
        Field(description="User ID. Defaults to the authenticated session user."),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(description="Project scope for 'get' and 'compile' actions."),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Action-specific parameters. For 'edit', provide "
                "edit_action='add_pin' or 'list_pins'; 'add_pin' also requires content."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Retrieve, compile, or edit a user's standing persona profile.

    Actions:
      get([user_id, project_id])
        Retrieve the compiled synopsis and its staleness status.
      compile([user_id, project_id])
        Compile and store a new version of the synopsis from behavioral facts.
      edit(options: {edit_action: add_pin|list_pins, content?})
        Add a user-declared pin (content required for add_pin) or list pins.

    Examples:
      persona(action="get")
      persona(action="compile", project_id="project-a")
      persona(
          action="edit",
          options={"edit_action": "add_pin", "content": "I prefer concise summaries."},
      )
    """
    if not isinstance(action, str) or action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    opts = options or {}

    if action == "get":
        from src.tools.get_persona import get_persona

        return await get_persona(user_id=user_id, project_id=project_id, ctx=ctx)

    if action == "compile":
        from src.tools.compile_persona import compile_persona

        return await compile_persona(user_id=user_id, project_id=project_id, ctx=ctx)

    edit_action = opts.get("edit_action")
    if not isinstance(edit_action, str) or edit_action not in {"add_pin", "list_pins"}:
        raise ToolError(
            "action='edit' requires options.edit_action to be 'add_pin' or "
            "'list_pins'. Example: persona(action='edit', "
            "options={'edit_action': 'add_pin', 'content': '...'})."
        )

    content = opts.get("content")
    if edit_action == "add_pin" and (
        not isinstance(content, str) or not content.strip()
    ):
        raise ToolError(
            "options.content is required for options.edit_action='add_pin'."
        )

    from src.tools.edit_persona import edit_persona

    return await edit_persona(
        action=edit_action,
        content=content,
        user_id=user_id,
        ctx=ctx,
    )
