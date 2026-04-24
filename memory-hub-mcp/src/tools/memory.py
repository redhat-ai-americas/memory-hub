"""Unified memory tool with action dispatch (#201).

Consolidates all 9 non-auth tools into a single ``memory`` tool with
19 actions. Each action delegates to the existing tool function, so
business logic is not duplicated. See planning/mcp-single-tool-schema.md
for the design rationale.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({
    # Read path
    "search", "read", "similar", "relationships",
    "status", "focus_history", "list_projects", "describe_project",
    # Write path
    "write", "update", "delete", "set_focus", "relate",
    "report", "resolve", "set_rule",
    "create_project", "add_member", "remove_member",
})

# Per-action option keys accepted for forwarding.
_SEARCH_OPTS = frozenset({
    "max_results", "focus", "session_focus_weight", "domains",
    "domain_boost_weight", "include_branches", "mode",
    "max_response_tokens", "raw_results", "weight_threshold",
    "current_only", "owner_id", "graph_depth",
    "graph_relationship_types", "graph_boost_weight",
})
_READ_OPTS = frozenset({
    "include_versions", "history_offset", "history_max_versions", "hydrate",
})
_SIMILAR_OPTS = frozenset({"threshold", "max_results", "offset"})
_RELATIONSHIPS_OPTS = frozenset({
    "relationship_type", "direction", "include_provenance",
})
_FOCUS_HISTORY_OPTS = frozenset({"start_date", "end_date"})
_LIST_PROJECTS_OPTS = frozenset({"filter"})
_WRITE_OPTS = frozenset({
    "weight", "parent_id", "branch_type", "metadata", "domains",
    "project_description", "force", "owner_id",
})
_UPDATE_OPTS = frozenset({"weight", "metadata", "domains"})
_SET_RULE_OPTS = frozenset({
    "name", "tier", "action_type", "config", "scope_filter",
    "enabled", "priority",
})


def _require(action: str, name: str, value: Any) -> Any:
    """Validate that a required top-level parameter is present."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}'. "
            f"Example: memory(action='{action}', {name}='...')"
        )
    return value


def _opt_require(action: str, name: str, opts: dict) -> Any:
    """Validate that a required option key is present."""
    value = opts.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ToolError(
            f"action='{action}' requires '{name}' in options. "
            f"Example: memory(action='{action}', options={{'{name}': '...'}})"
        )
    return value


def _forward(opts: dict, valid_keys: frozenset) -> dict:
    """Extract only the option keys matching the valid set."""
    return {k: v for k, v in opts.items() if k in valid_keys}


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def memory(
    action: Annotated[
        str,
        Field(description=(
            "The operation to perform. See action reference in docstring."
        )),
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
        Field(description=(
            "Memory text. Required for: write. Optional for: update."
        )),
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
        Field(description=(
            "Project identifier. Required for: write (project/campaign scope), "
            "set_focus, focus_history, describe_project, add_member, remove_member."
        )),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(description=(
            "Action-specific parameters. See reference table in docstring."
        )),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """All-in-one memory operations. Call register_session(api_key=...) first.

    Read actions:
      search(query, [scope, project_id, options: max_results, focus, domains, ...])
        Semantic search. Returns cache-optimized stable ordering by default.
      read(memory_id, [project_id, options: include_versions, hydrate])
        Retrieve memory by UUID with optional version history.
      similar(memory_id, [project_id, options: threshold, max_results])
        Near-duplicate detection by cosine similarity.
      relationships(memory_id, [project_id, options: direction, include_provenance])
        Query graph edges for a memory node.
      status()
        Session identity, scopes, project memberships.
      focus_history(project_id, [options: start_date, end_date])
        Focus declaration histogram for a project.
      list_projects([options: filter])
        List your projects or all open ones.
      describe_project(project_id)
        Project detail with members.

    Write actions:
      write(content, scope, [project_id, options: weight, parent_id, branch_type, ...])
        Create memory node or branch.
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

    Params in () are top-level. {braces} in options = required for that action.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    opts = options or {}

    # --- Read path ---
    if action == "search":
        return await _dispatch_search(query, scope, project_id, opts, ctx)
    if action == "read":
        return await _dispatch_read(memory_id, project_id, opts, ctx)
    if action == "similar":
        return await _dispatch_similar(memory_id, project_id, opts, ctx)
    if action == "relationships":
        return await _dispatch_relationships(memory_id, project_id, opts, ctx)
    if action == "status":
        return await _dispatch_status(ctx)
    if action == "focus_history":
        return await _dispatch_focus_history(project_id, opts, ctx)
    if action == "list_projects":
        return await _dispatch_list_projects(opts, ctx)
    if action == "describe_project":
        return await _dispatch_describe_project(project_id, ctx)

    # --- Write path ---
    if action == "write":
        return await _dispatch_write(content, scope, project_id, opts, ctx)
    if action == "update":
        return await _dispatch_update(memory_id, content, project_id, opts, ctx)
    if action == "delete":
        return await _dispatch_delete(memory_id, project_id, ctx)
    if action == "set_focus":
        return await _dispatch_set_focus(project_id, opts, ctx)
    if action == "relate":
        return await _dispatch_relate(project_id, opts, ctx)
    if action == "report":
        return await _dispatch_report(memory_id, project_id, opts, ctx)
    if action == "resolve":
        return await _dispatch_resolve(opts, ctx)
    if action == "set_rule":
        return await _dispatch_set_rule(opts, ctx)
    if action == "create_project":
        return await _dispatch_create_project(project_id, opts, ctx)
    if action == "add_member":
        return await _dispatch_add_member(project_id, opts, ctx)
    # remove_member (last remaining action)
    return await _dispatch_remove_member(project_id, opts, ctx)


# ── Read-path dispatchers ──────────────────────────────────────────────────

async def _dispatch_search(query, scope, project_id, opts, ctx):
    from src.tools.search_memory import search_memory
    _require("search", "query", query)
    return await search_memory(
        query=query, scope=scope, project_id=project_id, ctx=ctx,
        **_forward(opts, _SEARCH_OPTS),
    )


async def _dispatch_read(memory_id, project_id, opts, ctx):
    from src.tools.read_memory import read_memory
    _require("read", "memory_id", memory_id)
    return await read_memory(
        memory_id=memory_id, project_id=project_id, ctx=ctx,
        **_forward(opts, _READ_OPTS),
    )


async def _dispatch_similar(memory_id, project_id, opts, ctx):
    from src.tools.manage_graph import manage_graph
    _require("similar", "memory_id", memory_id)
    return await manage_graph(
        action="get_similar", memory_id=memory_id,
        project_id=project_id, ctx=ctx,
        **_forward(opts, _SIMILAR_OPTS),
    )


async def _dispatch_relationships(memory_id, project_id, opts, ctx):
    from src.tools.manage_graph import manage_graph
    _require("relationships", "memory_id", memory_id)
    # Design normalizes node_id → memory_id; map back for manage_graph.
    return await manage_graph(
        action="get_relationships", node_id=memory_id,
        project_id=project_id, ctx=ctx,
        **_forward(opts, _RELATIONSHIPS_OPTS),
    )


async def _dispatch_status(ctx):
    from src.tools.manage_session import manage_session
    return await manage_session(action="status", ctx=ctx)


async def _dispatch_focus_history(project_id, opts, ctx):
    from src.tools.manage_session import manage_session
    _require("focus_history", "project_id", project_id)
    # Design normalizes project → project_id; map back for manage_session.
    return await manage_session(
        action="focus_history", project=project_id, ctx=ctx,
        **_forward(opts, _FOCUS_HISTORY_OPTS),
    )


async def _dispatch_list_projects(opts, ctx):
    from src.tools.manage_project import manage_project
    return await manage_project(action="list", ctx=ctx,
                                **_forward(opts, _LIST_PROJECTS_OPTS))


async def _dispatch_describe_project(project_id, ctx):
    from src.tools.manage_project import manage_project
    _require("describe_project", "project_id", project_id)
    # Design normalizes project_name → project_id; map back.
    return await manage_project(
        action="describe", project_name=project_id, ctx=ctx,
    )


# ── Write-path dispatchers ─────────────────────────────────────────────────

async def _dispatch_write(content, scope, project_id, opts, ctx):
    from src.tools.write_memory import write_memory
    _require("write", "content", content)
    _require("write", "scope", scope)
    return await write_memory(
        content=content, scope=scope, project_id=project_id, ctx=ctx,
        **_forward(opts, _WRITE_OPTS),
    )


async def _dispatch_update(memory_id, content, project_id, opts, ctx):
    from src.tools.update_memory import update_memory
    _require("update", "memory_id", memory_id)
    kwargs = _forward(opts, _UPDATE_OPTS)
    if content is not None:
        kwargs["content"] = content
    return await update_memory(
        memory_id=memory_id, project_id=project_id, ctx=ctx, **kwargs,
    )


async def _dispatch_delete(memory_id, project_id, ctx):
    from src.tools.delete_memory import delete_memory
    _require("delete", "memory_id", memory_id)
    return await delete_memory(
        memory_id=memory_id, project_id=project_id, ctx=ctx,
    )


async def _dispatch_set_focus(project_id, opts, ctx):
    from src.tools.manage_session import manage_session
    _require("set_focus", "project_id", project_id)
    _opt_require("set_focus", "focus", opts)
    return await manage_session(
        action="set_focus", focus=opts["focus"], project=project_id, ctx=ctx,
    )


async def _dispatch_relate(project_id, opts, ctx):
    from src.tools.manage_graph import manage_graph
    _opt_require("relate", "source_id", opts)
    _opt_require("relate", "target_id", opts)
    _opt_require("relate", "relationship_type", opts)
    return await manage_graph(
        action="create_relationship",
        source_id=opts["source_id"],
        target_id=opts["target_id"],
        relationship_type=opts["relationship_type"],
        metadata=opts.get("metadata"),
        project_id=project_id,
        ctx=ctx,
    )


async def _dispatch_report(memory_id, project_id, opts, ctx):
    from src.tools.manage_curation import manage_curation
    _require("report", "memory_id", memory_id)
    _opt_require("report", "observed_behavior", opts)
    return await manage_curation(
        action="report_contradiction",
        memory_id=memory_id,
        observed_behavior=opts["observed_behavior"],
        confidence=opts.get("confidence", 0.7),
        project_id=project_id,
        ctx=ctx,
    )


async def _dispatch_resolve(opts, ctx):
    from src.tools.manage_curation import manage_curation
    _opt_require("resolve", "contradiction_id", opts)
    _opt_require("resolve", "resolution_action", opts)
    return await manage_curation(
        action="resolve_contradiction",
        contradiction_id=opts["contradiction_id"],
        resolution_action=opts["resolution_action"],
        resolution_note=opts.get("resolution_note"),
        ctx=ctx,
    )


async def _dispatch_set_rule(opts, ctx):
    from src.tools.manage_curation import manage_curation
    _opt_require("set_rule", "name", opts)
    return await manage_curation(
        action="set_rule", ctx=ctx,
        **_forward(opts, _SET_RULE_OPTS),
    )


async def _dispatch_create_project(project_id, opts, ctx):
    from src.tools.manage_project import manage_project
    # Accept project_id as the project name for consistency with
    # describe_project, add_member, remove_member. options.project_name
    # takes precedence if both are set.
    project_name = opts.get("project_name") or project_id
    if not project_name or (isinstance(project_name, str) and not project_name.strip()):
        raise ToolError(
            "action='create_project' requires project_id or options.project_name. "
            "Example: memory(action='create_project', project_id='new-proj')"
        )
    kwargs = {}
    if "description" in opts:
        kwargs["description"] = opts["description"]
    if "invite_only" in opts:
        kwargs["invite_only"] = opts["invite_only"]
    return await manage_project(
        action="create", project_name=project_name, ctx=ctx,
        **kwargs,
    )


async def _dispatch_add_member(project_id, opts, ctx):
    from src.tools.manage_project import manage_project
    _require("add_member", "project_id", project_id)
    _opt_require("add_member", "user_id", opts)
    kwargs = {}
    if "role" in opts:
        kwargs["role"] = opts["role"]
    return await manage_project(
        action="add_member", project_name=project_id,
        user_id=opts["user_id"], ctx=ctx, **kwargs,
    )


async def _dispatch_remove_member(project_id, opts, ctx):
    from src.tools.manage_project import manage_project
    _require("remove_member", "project_id", project_id)
    _opt_require("remove_member", "user_id", opts)
    return await manage_project(
        action="remove_member", project_name=project_id,
        user_id=opts["user_id"], ctx=ctx,
    )
