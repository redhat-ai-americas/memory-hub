"""Personal-edition memory tool with action dispatch.

Same interface as the cluster edition's memory() tool. Agents cannot tell
the difference. All operations go through the local service layer with
no auth, no multi-tenancy, and SQLite storage.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_local.tools._state import get_state

_VALID_ACTIONS = frozenset({
    "search", "read", "list", "similar", "relationships",
    "status", "reconstruct",
    "write", "update", "delete", "relate", "report",
    # Stubs for cluster-only features
    "set_focus", "resolve", "set_rule",
    "create_project", "add_member", "remove_member",
    "promote", "graduate", "checkpoint",
    "focus_history", "list_projects", "describe_project",
    "list_entities", "merge_entities", "rename_entity",
    "backfill_entities",
})

_STUB_ACTIONS = frozenset({
    "set_focus", "resolve", "set_rule",
    "create_project", "add_member", "remove_member",
    "promote", "graduate", "checkpoint",
    "focus_history", "list_projects", "describe_project",
    "list_entities", "merge_entities", "rename_entity",
    "backfill_entities",
})


async def memory(
    action: Annotated[
        str,
        Field(description="The operation to perform. See action reference in docstring."),
    ],
    memory_id: Annotated[
        str | None,
        Field(description=(
            "UUID of target memory. "
            "Required for: read, update, delete, similar, relationships, report."
        )),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Natural language search text. Required for: search."),
    ] = None,
    content: Annotated[
        str | None,
        Field(description="Memory text. Required for: write. Optional for: update."),
    ] = None,
    scope: Annotated[
        str | None,
        Field(description=(
            "Scope: user, project, campaign, role, organizational, enterprise. "
            "Required for: write. Optional filter for: search."
        )),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(description="Project identifier."),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(description="Action-specific parameters."),
    ] = None,
) -> dict[str, Any]:
    """All-in-one memory operations. Call register_session(api_key=...) first.

    Read actions:
      search(query, [scope, project_id, options: max_results, focus, domains, ...])
        Semantic search. Returns cache-optimized stable ordering by default.
      list([scope, project_id, options: max_results, cursor, include_branches])
        Enumerate memories without semantic ranking. Ordered by creation time.
      read(memory_id, [project_id, options: include_versions, hydrate])
        Retrieve memory by UUID with optional version history.
      similar(memory_id, [project_id, options: threshold, max_results])
        Near-duplicate detection by cosine similarity.
      relationships(memory_id, [project_id, options: direction, include_provenance])
        Query graph edges for a memory node.
      reconstruct([options: owner_id])
        Retrieve behavioral memories sorted by weight desc. Convenience alias
        for search(content_type="behavioral") with weight-based ordering.
      status()
        Session identity, scopes, project memberships.
      focus_history(project_id, [options: start_date, end_date])
        Focus declaration histogram for a project.
      list_projects([options: filter])
        List your projects or all open ones.
      describe_project(project_id)
        Project detail with members.

    Write actions:
      write(content, [scope, project_id, options: weight, parent_id, branch_type, ...])
        Create memory node or branch. scope defaults to "user" if omitted.
      update(memory_id, [content, options: weight, metadata, domains])
        New version; old preserved for history.
      delete(memory_id, [project_id])
        Soft-delete with cascade.
      set_focus(project_id, options: {focus})
        Declare session focus for retrieval bias.
      relate(options: {source_id, target_id, relationship_type})
        Create directed graph edge between memories.
      report(memory_id, options: {observed_behavior})
        Flag contradiction against a stored memory.
      resolve(options: {contradiction_id, resolution_action})
        Close contradiction: accept_new|keep_old|mark_both_invalid|manual_merge.
      set_rule(options: {name}, [options: tier, action_type, config])
        Create/update curation rule.
      create_project(project_id -or- options: {project_name})
        Create a new project.
      add_member(project_id, options: {user_id})
        Add user to project.
      remove_member(project_id, options: {user_id})
        Remove user from project.
      promote(memory_id, options: {target_scope}, [options: target_scope_id])
        Promote memory to broader scope. Creates new memory linked via derived_from.
      graduate(memory_id, [options: evidence, reviewer_note])
        Graduate experiential memory to knowledge. Creates new knowledge
        node linked via derived_from.
      checkpoint(options: {workflow_name}, [options: state, scope, scope_id])
        Durable key-value state for recurring agents. Upsert when state provided,
        read when only workflow_name given.

    Params in () are top-level. {braces} in options = required for that action.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    if action in _STUB_ACTIONS:
        return _stub_response(action)

    opts = options or {}

    if action == "search":
        return await _do_search(query, scope, opts)
    if action == "list":
        return await _do_list(scope, opts)
    if action == "read":
        return await _do_read(memory_id, opts)
    if action == "similar":
        return await _do_similar(memory_id, opts)
    if action == "relationships":
        return await _do_relationships(memory_id, opts)
    if action == "reconstruct":
        return await _do_reconstruct(scope, opts)
    if action == "status":
        return await _do_status()
    if action == "write":
        return await _do_write(content, scope, opts)
    if action == "update":
        return await _do_update(memory_id, content, opts)
    if action == "delete":
        return await _do_delete(memory_id)
    if action == "relate":
        return await _do_relate(opts)
    if action == "report":
        return await _do_report(memory_id, opts)

    return _stub_response(action)


def _require(action: str, name: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}'. "
            f"Example: memory(action='{action}', {name}='...')"
        )
    return value


def _parse_uuid(action: str, name: str, value: str) -> str:
    """Validate UUID format, returning the original string."""
    import uuid as uuid_mod
    try:
        uuid_mod.UUID(value)
    except (ValueError, AttributeError):
        raise ToolError(f"Invalid UUID format for {name}: '{value}'")
    return value


def _opt_require(action: str, name: str, opts: dict) -> Any:
    value = opts.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}' in options. "
            f"Example: memory(action='{action}', options={{'{name}': '...'}})"
        )
    return value


def _stub_response(action: str) -> dict[str, Any]:
    return {
        "message": f"Action '{action}' is not available in the personal edition.",
        "edition": "personal",
    }


async def _do_search(query, scope, opts):
    from memoryhub_local.services.memory import search_memories

    _require("search", "query", query)
    state = get_state()
    async with state.session_factory() as session:
        return await search_memories(
            session, query, state.embedding_service, state.recall_backend,
            scope=scope,
            max_results=opts.get("max_results", 10),
            content_type=opts.get("content_type"),
        )


async def _do_list(scope, opts):
    from memoryhub_local.services.memory import list_memories

    state = get_state()
    async with state.session_factory() as session:
        return await list_memories(
            session,
            scope=scope,
            max_results=opts.get("max_results", 100),
            current_only=opts.get("current_only", True),
            content_type=opts.get("content_type"),
        )


async def _do_read(memory_id, opts):
    from memoryhub_local.services.memory import get_memory_history, read_memory

    _require("read", "memory_id", memory_id)
    _parse_uuid("read", "memory_id", memory_id)
    state = get_state()
    async with state.session_factory() as session:
        node = await read_memory(session, memory_id)
        if node is None:
            raise ToolError(f"Memory {memory_id} not found.")

        result = {
            "id": str(node.id),
            "logical_id": str(node.logical_id) if node.logical_id else None,
            "content": node.content,
            "scope": node.scope,
            "weight": node.weight,
            "version": node.version,
            "is_current": node.is_current,
            "content_type": node.content_type,
            "owner_id": node.owner_id,
            "domains": node.domains or [],
            "metadata": node.metadata_ or {},
            "source": node.source,
            "created_at": node.created_at.isoformat() if node.created_at else None,
        }

        if opts.get("include_versions"):
            history = await get_memory_history(
                session, memory_id,
                max_versions=opts.get("history_max_versions", 10),
            )
            result["version_history"] = history

        return result


async def _do_similar(memory_id, opts):
    from memoryhub_local.services.memory import get_similar_memories

    _require("similar", "memory_id", memory_id)
    _parse_uuid("similar", "memory_id", memory_id)
    state = get_state()
    async with state.session_factory() as session:
        results = await get_similar_memories(
            session, memory_id, state.recall_backend,
            threshold=opts.get("threshold", 0.80),
            max_results=opts.get("max_results", 10),
        )
        return {"results": results, "count": len(results)}


async def _do_relationships(memory_id, opts):
    from memoryhub_local.services.memory import get_relationships

    _require("relationships", "memory_id", memory_id)
    _parse_uuid("relationships", "memory_id", memory_id)
    state = get_state()
    async with state.session_factory() as session:
        return await get_relationships(
            session, memory_id,
            direction=opts.get("direction", "both"),
        )


async def _do_reconstruct(scope, opts):
    from memoryhub_local.services.memory import search_memories

    state = get_state()
    async with state.session_factory() as session:
        return await search_memories(
            session,
            "successful approaches and demonstrated patterns",
            state.embedding_service,
            state.recall_backend,
            scope=scope,
            content_type="behavioral",
        )


async def _do_status():
    import os

    try:
        user_id = os.getlogin()
    except OSError:
        user_id = os.environ.get("USER", "local")

    return {
        "user_id": user_id,
        "session_id": "local",
        "scopes": ["user", "project"],
        "edition": "personal",
    }


async def _do_write(content, scope, opts):
    from memoryhub_local.services.memory import create_memory

    _require("write", "content", content)
    scope = scope or "user"
    state = get_state()
    async with state.session_factory() as session:
        node = await create_memory(
            session, content, state.embedding_service,
            scope=scope,
            weight=opts.get("weight", 0.7),
            parent_id=opts.get("parent_id"),
            branch_type=opts.get("branch_type"),
            metadata=opts.get("metadata"),
            domains=opts.get("domains"),
            content_type=opts.get("content_type", "declarative"),
            driver_id=opts.get("driver_id"),
        )
        return {
            "memory": {
                "id": str(node.id),
                "logical_id": str(node.logical_id) if node.logical_id else None,
                "scope": node.scope,
                "weight": node.weight,
                "version": node.version,
                "content": node.content,
                "created_at": node.created_at.isoformat() if node.created_at else None,
            },
            "curation": {
                "blocked": False,
                "gated": False,
                "similar_count": 0,
                "nearest_score": None,
                "flags": [],
            },
        }


async def _do_update(memory_id, content, opts):
    from memoryhub_local.services.memory import update_memory

    _require("update", "memory_id", memory_id)
    _parse_uuid("update", "memory_id", memory_id)
    state = get_state()
    async with state.session_factory() as session:
        node = await update_memory(
            session, memory_id, state.embedding_service,
            content=content,
            weight=opts.get("weight"),
            metadata=opts.get("metadata"),
            domains=opts.get("domains"),
        )
        if node is None:
            raise ToolError(f"Memory {memory_id} not found or not active.")
        return {
            "id": str(node.id),
            "logical_id": str(node.logical_id) if node.logical_id else None,
            "content": node.content,
            "scope": node.scope,
            "weight": node.weight,
            "version": node.version,
            "is_current": node.is_current,
            "previous_version_id": (
                str(node.previous_version_id) if node.previous_version_id else None
            ),
            "created_at": node.created_at.isoformat() if node.created_at else None,
        }


async def _do_delete(memory_id):
    from memoryhub_local.services.memory import delete_memory

    _require("delete", "memory_id", memory_id)
    _parse_uuid("delete", "memory_id", memory_id)
    state = get_state()
    async with state.session_factory() as session:
        return await delete_memory(session, memory_id)


async def _do_relate(opts):
    from memoryhub_local.services.memory import create_relationship

    _opt_require("relate", "source_id", opts)
    _opt_require("relate", "target_id", opts)
    _opt_require("relate", "relationship_type", opts)
    state = get_state()
    async with state.session_factory() as session:
        return await create_relationship(
            session,
            opts["source_id"],
            opts["target_id"],
            opts["relationship_type"],
            metadata=opts.get("metadata"),
        )


async def _do_report(memory_id, opts):
    from memoryhub_local.services.memory import report_contradiction

    _require("report", "memory_id", memory_id)
    _parse_uuid("report", "memory_id", memory_id)
    _opt_require("report", "observed_behavior", opts)
    state = get_state()
    async with state.session_factory() as session:
        return await report_contradiction(
            session, memory_id,
            opts["observed_behavior"],
            confidence=opts.get("confidence", 0.7),
        )
