"""Conversation thread tool with action dispatch.

Exposes thread operations as a single ``thread`` tool with 8 actions:
create, append, get, list, archive, extract, fork, share.
"""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({
    "create", "append", "get", "list", "archive", "extract", "fork", "share", "delete",
})

_CREATE_OPTS = frozenset({
    "title", "participant_ids", "participant_access",
    "a2a_context_id", "scope_id", "owner_id", "metadata",
})
_APPEND_OPTS = frozenset({"actor_id", "tool_call_id", "metadata", "a2a_context_id"})
_GET_OPTS = frozenset({"limit", "before_sequence", "include_messages"})
_LIST_OPTS = frozenset({
    "scope_id", "status", "participant_id", "limit", "offset",
})
_ARCHIVE_OPTS = frozenset({"reason"})
_EXTRACT_OPTS = frozenset({"turn_range", "model", "model_url"})
_FORK_OPTS = frozenset({"from_sequence", "title"})
_SHARE_OPTS = frozenset({"grantee_id", "access_level", "authorized_by"})
_DELETE_OPTS = frozenset({"cascade"})


def _require(action: str, name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}'. "
            f"Example: thread(action='{action}', {name}='...')"
        )
    return value


def _forward(opts: dict, valid_keys: frozenset) -> dict:
    return {k: v for k, v in opts.items() if k in valid_keys}


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
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
        Field(description=(
            "Thread UUID. Required for: append, get, archive."
        )),
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
    ctx: Context = None,
) -> dict[str, Any]:
    """Conversation thread operations. Call register_session first.

    Actions:
      create(scope, [options: title, participant_ids, participant_access,
             a2a_context_id, metadata])
        Create a new conversation thread.
      append(thread_id, role, content, [options: actor_id, tool_call_id,
             metadata])
        Append a message to a thread. Sequence number auto-assigned.
      get(thread_id, [options: limit (50), before_sequence, include_messages])
        Retrieve thread metadata and paginated messages.
      list([scope, options: scope_id, status (active), participant_id,
           limit (20), offset])
        List threads visible to the caller.
      archive(thread_id, [options: reason])
        Archive a thread. Immutable thereafter.
      extract(thread_id, [options: turn_range, model, model_url])
        Trigger extraction pipeline. Produces memory nodes from messages.
      fork(thread_id, [options: from_sequence (required), title])
        Create a divergent copy of a thread up to from_sequence.
      share(thread_id, [options: grantee_id (required), access_level (required),
            authorized_by])
        Grant read/write/admin access to another agent or user.
      delete(thread_id, [options: cascade])
        Soft-delete a thread. Cascade: delete (default), orphan, preserve.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    opts = options or {}

    if action == "create":
        return await _dispatch_create(scope, opts, ctx)
    if action == "append":
        return await _dispatch_append(thread_id, role, content, opts, ctx)
    if action == "get":
        return await _dispatch_get(thread_id, opts, ctx)
    if action == "list":
        return await _dispatch_list(scope, opts, ctx)
    if action == "archive":
        return await _dispatch_archive(thread_id, opts, ctx)
    if action == "extract":
        return await _dispatch_extract(thread_id, opts, ctx)
    if action == "fork":
        return await _dispatch_fork(thread_id, opts, ctx)
    if action == "share":
        return await _dispatch_share(thread_id, opts, ctx)
    return await _dispatch_delete(thread_id, opts, ctx)


async def _dispatch_create(scope, opts, ctx):
    from memoryhub_core.models.schemas import ConversationThreadCreate
    from memoryhub_core.services.conversation import create_thread
    from src.core.authz import (
        PROJECT_ISOLATION_ENABLED,
        AuthenticationError,
        authorize_write,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    _require("create", "scope", scope)

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]

    project_ids: set[str] | None = None
    scope_id_value = opts.get("scope_id")
    if scope == "project" and PROJECT_ISOLATION_ENABLED and scope_id_value:
        from src.tools.write_memory import ensure_project_membership
        session_proj, gen_proj = await get_db_session()
        try:
            project_ids, _ = await ensure_project_membership(
                session_proj, scope_id_value, caller_id, tenant,
            )
            await session_proj.commit()
        finally:
            await release_db_session(gen_proj)

    if not authorize_write(
        claims, scope, owner_id=caller_id, tenant_id=tenant,
        project_ids=project_ids, scope_id=scope_id_value,
    ):
        raise ToolError(f"Not authorized to create threads in scope '{scope}'.")

    effective_owner = opts.get("owner_id") or caller_id
    create_opts = _forward(opts, _CREATE_OPTS)
    create_opts.pop("owner_id", None)
    data = ConversationThreadCreate(scope=scope, **create_opts)

    session, gen = await get_db_session()
    try:
        result = await create_thread(
            session,
            tenant_id=tenant,
            data=data,
            owner_id=effective_owner,
            actor_id=caller_id,
            driver_id=claims.get("driver_id"),
        )
        if ctx is not None:
            await ctx.info(f"Created thread {result.id}")
        return result.model_dump(mode="json")
    finally:
        await release_db_session(gen)


async def _dispatch_append(thread_id_str, role, content, opts, ctx):
    from memoryhub_core.models.schemas import ConversationMessageCreate
    from memoryhub_core.services.conversation import append_message, get_thread, lookup_thread_by_a2a_context
    from memoryhub_core.services.exceptions import (
        ThreadNotActiveError,
        ThreadNotFoundError,
    )
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_write,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, get_s3_adapter, release_db_session

    _require("append", "role", role)
    _require("append", "content", content)

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    s3_adapter = get_s3_adapter()

    append_opts = _forward(opts, _APPEND_OPTS)
    a2a_ctx = append_opts.pop("a2a_context_id", None)

    session, gen = await get_db_session()
    try:
        # A2A context lookup: resolve thread_id from a2a_context_id
        if not thread_id_str and a2a_ctx:
            resolved = await lookup_thread_by_a2a_context(
                session, tenant_id=tenant, a2a_context_id=a2a_ctx,
            )
            if resolved is not None:
                thread_id_str = str(resolved)

        _require("append", "thread_id", thread_id_str)

        try:
            tid = uuid.UUID(thread_id_str)
        except ValueError as exc:
            raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

        thread_data = await get_thread(
            session, tenant_id=tenant, thread_id=tid, include_messages=False,
        )
        if thread_data is None:
            raise ToolError("Thread not found.")

        # Auth check against the ORM object (re-query for the actual model)
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        result = await session.execute(stmt)
        thread_obj = result.scalar_one_or_none()

        if not authorize_thread_write(claims, thread_obj):
            raise ToolError("Not authorized to append to this thread.")

        data = ConversationMessageCreate(
            thread_id=tid,
            role=role,
            content=content,
            **append_opts,
        )

        msg = await append_message(
            session, tenant_id=tenant, thread_id=tid,
            data=data, s3_adapter=s3_adapter,
        )
        if ctx is not None:
            await ctx.info(f"Appended message seq={msg.sequence_number}")
        return msg.model_dump(mode="json")
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    except ThreadNotActiveError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await release_db_session(gen)


async def _dispatch_get(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation import get_thread
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_read,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, get_s3_adapter, release_db_session

    _require("get", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]
    s3_adapter = get_s3_adapter()
    get_opts = _forward(opts, _GET_OPTS)

    session, gen = await get_db_session()
    try:
        result = await get_thread(
            session, tenant_id=tenant, thread_id=tid,
            s3_adapter=s3_adapter, caller_id=caller_id, **get_opts,
        )
        if result is None:
            raise ToolError("Thread not found.")

        # Auth check
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if not authorize_thread_read(claims, thread_obj):
            raise ToolError("Thread not found.")

        # Serialize
        output: dict[str, Any] = {
            "thread": result["thread"].model_dump(mode="json"),
        }
        if "messages" in result:
            output["messages"] = [
                m.model_dump(mode="json") for m in result["messages"]
            ]
            output["has_more"] = result.get("has_more", False)
        return output
    finally:
        await release_db_session(gen)


async def _dispatch_list(scope, opts, ctx):
    from memoryhub_core.services.conversation import list_threads
    from src.core.authz import (
        AuthenticationError,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]
    list_opts = _forward(opts, _LIST_OPTS)

    session, gen = await get_db_session()
    try:
        threads, total = await list_threads(
            session,
            tenant_id=tenant,
            owner_id=caller_id,
            scope=scope,
            **list_opts,
        )
        return {
            "threads": [t.model_dump(mode="json") for t in threads],
            "total": total,
        }
    finally:
        await release_db_session(gen)


async def _dispatch_archive(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation import archive_thread
    from memoryhub_core.services.exceptions import (
        ThreadNotActiveError,
        ThreadNotFoundError,
    )
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_admin,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    _require("archive", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        # Auth check
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if thread_obj is None:
            raise ToolError("Thread not found.")
        if not authorize_thread_admin(claims, thread_obj):
            raise ToolError("Not authorized to archive this thread.")

        result = await archive_thread(session, tenant_id=tenant, thread_id=tid)
        if ctx is not None:
            await ctx.info(f"Archived thread {tid}")
        return result.model_dump(mode="json")
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    except ThreadNotActiveError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await release_db_session(gen)


async def _dispatch_extract(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation_extraction import extract_from_thread
    from memoryhub_core.services.exceptions import ThreadNotFoundError
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_read,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, get_embedding_service, get_s3_adapter, release_db_session

    _require("extract", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]
    s3_adapter = get_s3_adapter()
    embedding_service = get_embedding_service()

    extract_opts = _forward(opts, _EXTRACT_OPTS)

    turn_range = None
    if "turn_range" in extract_opts:
        tr = extract_opts["turn_range"]
        if isinstance(tr, list | tuple) and len(tr) == 2:
            turn_range = (int(tr[0]), int(tr[1]))
        elif isinstance(tr, str) and "-" in tr:
            parts = tr.split("-", 1)
            turn_range = (int(parts[0]), int(parts[1]))

    session, gen = await get_db_session()
    try:
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if thread_obj is None:
            raise ToolError("Thread not found.")
        if not authorize_thread_read(claims, thread_obj):
            raise ToolError("Thread not found.")

        result = await extract_from_thread(
            session,
            thread_id=tid,
            tenant_id=tenant,
            owner_id=caller_id,
            embedding_service=embedding_service,
            s3_adapter=s3_adapter,
            model_override=extract_opts.get("model"),
            url_override=extract_opts.get("model_url"),
            turn_range=turn_range,
        )

        if ctx is not None:
            await ctx.info(
                f"Extracted {result['extracted_count']} memories, "
                f"cursor={result['cursor']}, failures={result['failures']}"
            )
        return result
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await release_db_session(gen)


async def _dispatch_fork(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation import fork_thread
    from memoryhub_core.services.exceptions import ThreadNotFoundError
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_admin,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    _require("fork", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]

    fork_opts = _forward(opts, _FORK_OPTS)

    from_sequence = fork_opts.get("from_sequence")
    if from_sequence is None:
        raise ToolError(
            "action='fork' requires 'from_sequence' in options. "
            "Example: thread(action='fork', thread_id='...', options={'from_sequence': 10})"
        )

    session, gen = await get_db_session()
    try:
        # Auth check
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if thread_obj is None:
            raise ToolError("Thread not found.")
        if not authorize_thread_admin(claims, thread_obj):
            raise ToolError("Not authorized to fork this thread.")

        result = await fork_thread(
            session,
            tenant_id=tenant,
            thread_id=tid,
            from_sequence=int(from_sequence),
            owner_id=caller_id,
            actor_id=caller_id,
            title=fork_opts.get("title"),
        )
        if ctx is not None:
            await ctx.info(f"Forked thread {tid} -> {result.id}")
        return result.model_dump(mode="json")
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    finally:
        await release_db_session(gen)


async def _dispatch_share(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation import share_thread
    from memoryhub_core.services.exceptions import ThreadNotFoundError
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_admin,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    _require("share", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]

    share_opts = _forward(opts, _SHARE_OPTS)

    grantee_id = share_opts.get("grantee_id")
    if not grantee_id:
        raise ToolError(
            "action='share' requires 'grantee_id' in options. "
            "Example: thread(action='share', thread_id='...', "
            "options={'grantee_id': 'agent-b', 'access_level': 'read'})"
        )
    access_level = share_opts.get("access_level")
    if access_level not in ("read", "write", "admin"):
        raise ToolError(
            "action='share' requires 'access_level' in options (read, write, or admin)."
        )

    session, gen = await get_db_session()
    try:
        # Auth check
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if thread_obj is None:
            raise ToolError("Thread not found.")
        if not authorize_thread_admin(claims, thread_obj):
            raise ToolError("Not authorized to share this thread.")

        result = await share_thread(
            session,
            tenant_id=tenant,
            thread_id=tid,
            grantee_id=grantee_id,
            access_level=access_level,
            authorized_by=caller_id,
        )
        if ctx is not None:
            await ctx.info(f"Shared thread {tid} with {grantee_id} ({access_level})")
        return result.model_dump(mode="json")
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    finally:
        await release_db_session(gen)


async def _dispatch_delete(thread_id_str, opts, ctx):
    from memoryhub_core.services.conversation import soft_delete_thread
    from memoryhub_core.services.exceptions import ThreadNotFoundError
    from src.core.authz import (
        AuthenticationError,
        authorize_thread_admin,
        get_claims_from_context,
        get_tenant_filter,
    )
    from src.tools._deps import get_db_session, release_db_session

    _require("delete", "thread_id", thread_id_str)

    try:
        tid = uuid.UUID(thread_id_str)
    except ValueError as exc:
        raise ToolError(f"Invalid thread_id: {thread_id_str}") from exc

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    tenant = get_tenant_filter(claims)
    caller_id = claims["sub"]

    delete_opts = _forward(opts, _DELETE_OPTS)

    session, gen = await get_db_session()
    try:
        from sqlalchemy import select

        from memoryhub_core.models.conversation import ConversationThread

        stmt = select(ConversationThread).where(
            ConversationThread.id == tid,
            ConversationThread.tenant_id == tenant,
        )
        res = await session.execute(stmt)
        thread_obj = res.scalar_one_or_none()

        if thread_obj is None:
            raise ToolError("Thread not found.")
        if not authorize_thread_admin(claims, thread_obj):
            raise ToolError("Not authorized to delete this thread.")

        result = await soft_delete_thread(
            session,
            tenant_id=tenant,
            thread_id=tid,
            purged_by=caller_id,
            cascade_override=delete_opts.get("cascade"),
        )
        if ctx is not None:
            await ctx.info(f"Deleted thread {tid} (status={result.status})")
        return result.model_dump(mode="json")
    except ThreadNotFoundError as exc:
        raise ToolError("Thread not found.") from exc
    finally:
        await release_db_session(gen)
