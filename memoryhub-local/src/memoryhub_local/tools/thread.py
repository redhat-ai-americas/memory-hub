"""Personal-edition thread tool with action dispatch.

Same interface as the cluster edition's thread() tool.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_local.tools._state import get_state

_VALID_ACTIONS = frozenset({
    "create", "append", "get", "list", "archive", "delete",
    "extract", "fork", "share",
})

_STUB_ACTIONS = frozenset({"extract", "fork", "share"})


async def thread(
    action: Annotated[
        str,
        Field(description=(
            "The operation to perform: create, append, get, list, archive, "
            "extract, fork, share, delete."
        )),
    ],
    thread_id: Annotated[
        str | None,
        Field(description="Thread UUID. Required for: append, get, archive."),
    ] = None,
    content: Annotated[
        str | None,
        Field(description="Message content. Required for: append."),
    ] = None,
    scope: Annotated[
        str | None,
        Field(description=(
            "Scope: user, project, campaign, role, organizational, enterprise. "
            "Required for: create. Optional filter for: list."
        )),
    ] = None,
    role: Annotated[
        str | None,
        Field(description=(
            "Message role: user, assistant, tool_call, tool_result, system. "
            "Required for: append."
        )),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(description="Action-specific parameters."),
    ] = None,
) -> dict[str, Any]:
    """Conversation thread operations. Call register_session first.

    Actions:
      create(scope, [options: title, participant_ids, metadata])
        Create a new conversation thread.
      append(thread_id, role, content, [options: actor_id, metadata])
        Append a message to a thread.
      get(thread_id, [options: limit, include_messages])
        Retrieve thread metadata and paginated messages.
      list([scope, options: status, limit])
        List threads visible to the caller.
      archive(thread_id)
        Archive a thread.
      delete(thread_id, [options: cascade])
        Soft-delete a thread.
      extract(thread_id) -- Not available in personal edition.
      fork(thread_id) -- Not available in personal edition.
      share(thread_id) -- Not available in personal edition.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    if action in _STUB_ACTIONS:
        return {
            "message": f"Action '{action}' is not available in the personal edition.",
            "edition": "personal",
        }

    opts = options or {}

    if action == "create":
        return await _do_create(scope, opts)
    if action == "append":
        return await _do_append(thread_id, role, content, opts)
    if action == "get":
        return await _do_get(thread_id, opts)
    if action == "list":
        return await _do_list(scope, opts)
    if action == "archive":
        return await _do_archive(thread_id)
    if action == "delete":
        return await _do_delete(thread_id, opts)

    raise ToolError(f"Unhandled action: {action}")


def _require(action: str, name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}'. "
            f"Example: thread(action='{action}', {name}='...')"
        )
    return value


async def _do_create(scope, opts):
    from memoryhub_local.services.thread import create_thread

    _require("create", "scope", scope)
    state = get_state()
    async with state.session_factory() as session:
        return await create_thread(
            session, scope,
            title=opts.get("title"),
            participant_ids=opts.get("participant_ids"),
            metadata=opts.get("metadata"),
        )


async def _do_append(thread_id, role, content, opts):
    from memoryhub_local.services.thread import append_message

    _require("append", "thread_id", thread_id)
    _require("append", "role", role)
    _require("append", "content", content)
    state = get_state()
    async with state.session_factory() as session:
        return await append_message(
            session, thread_id, role, content,
            actor_id=opts.get("actor_id"),
            metadata=opts.get("metadata"),
        )


async def _do_get(thread_id, opts):
    from memoryhub_local.services.thread import get_thread

    _require("get", "thread_id", thread_id)
    state = get_state()
    async with state.session_factory() as session:
        return await get_thread(
            session, thread_id,
            limit=opts.get("limit", 50),
            include_messages=opts.get("include_messages", True),
        )


async def _do_list(scope, opts):
    from memoryhub_local.services.thread import list_threads

    state = get_state()
    async with state.session_factory() as session:
        return await list_threads(
            session,
            scope=scope,
            status=opts.get("status", "active"),
            limit=opts.get("limit", 20),
        )


async def _do_archive(thread_id):
    from memoryhub_local.services.thread import archive_thread

    _require("archive", "thread_id", thread_id)
    state = get_state()
    async with state.session_factory() as session:
        return await archive_thread(session, thread_id)


async def _do_delete(thread_id, opts):
    from memoryhub_local.services.thread import delete_thread

    _require("delete", "thread_id", thread_id)
    state = get_state()
    async with state.session_factory() as session:
        return await delete_thread(
            session, thread_id,
            cascade=opts.get("cascade", "delete"),
        )
