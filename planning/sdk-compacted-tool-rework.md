# SDK rework against compacted memory(action=...) tool surface

Status: Proposed — 2026-04-29
Tracks: (issue to be filed)
Author: @rdwj (drafted with Claude Code Opus 4.7)

## Why this exists

Issues #198/#201/#202 reduced the MemoryHub MCP server's tool surface from 10
per-action tools to a single `memory(action=...)` dispatcher (plus
`register_session`). That work shipped on the `memory-hub-mcp` (primary)
deployment, which is the only deployment exposing the full operation surface.
The minimal deployment retains a 4-tool subset for legacy integrations.

Issue #202's scope explicitly called for keeping the per-action tools as
temporary aliases for a deprecation window. That aliasing step was never
shipped, and the `memoryhub` Python SDK (currently v0.6.0) still calls the
old per-action tool names (`search_memory`, `read_memory`, `write_memory`,
etc.). The result: `MemoryHubClient` cannot talk to the primary deployment
at all — `register_session` succeeds but every operational method raises
`ToolError: Unknown tool: '<name>'`.

This was caught when the kagenti-adk integration in
[kagenti/adk PR #231](https://github.com/kagenti/adk/pull/231) was tested
against the live primary server. The PR is paused until this is fixed.

## What this rework is

The cutover. We take the SDK forward to the new surface instead of
back-porting compatibility aliases on the server. Wes confirmed
2026-04-29: "we did flag the SDK as necessary follow-on work and we
should have done that very next thing and did not. This is our chance
to rectify that."

## Scope

1. Rewrite `MemoryHubClient` internals so every method dispatches via
   `memory(action=..., memory_id=..., query=..., content=..., scope=...,
   project_id=..., options={...})` instead of calling per-action tool
   names directly.
2. Keep all public method signatures stable. The kagenti-adk wrapper
   already calls `client.search(query, scope=..., project_id=...,
   max_results=...)`, etc.; that surface must not change. Only the wire
   format the SDK emits to the MCP server changes.
3. `register_session` stays a separate tool call — it is unchanged on
   the server.
4. Update `sdk/tests/test_client.py` to assert the new payload shape:
   `call_tool("memory", {"action": "search", ...})` instead of
   `call_tool("search_memory", ...)`.
5. Bump SDK version `0.6.0 → 0.7.0`. Update `sdk/CHANGELOG.md` with a
   "BREAKING (wire format)" entry that links this rework, #198, and
   #202.
6. Bump kagenti-adk's `memoryhub>=0.5.0` pin to `memoryhub>=0.7.0` in a
   coordinated PR-#231 follow-up commit.

## Action mapping

The `memory` tool's accepted actions are documented in
`memory-hub-mcp/src/tools/memory.py`. The mapping for each public SDK
method:

| SDK method | action | top-level args | options keys |
|---|---|---|---|
| `search` | `search` | `query`, `scope`, `project_id` | `max_results`, `weight_threshold`, `current_only`, `mode`, `max_response_tokens`, `include_branches`, `focus`, `session_focus_weight`, `domains`, `domain_boost_weight`, `raw_results`, `owner_id` |
| `read` | `read` | `memory_id`, `project_id` | `include_versions`, `history_offset`, `history_max_versions`, `hydrate` |
| `write` | `write` | `content`, `scope`, `project_id` | `weight`, `parent_id`, `branch_type`, `metadata`, `domains`, `force`, `owner_id` |
| `update` | `update` | `memory_id`, `content`, `project_id` | `weight`, `metadata`, `domains` |
| `delete` | `delete` | `memory_id`, `project_id` | (none) |
| `report_contradiction` | `report` | `memory_id`, `project_id` | `observed_behavior`, `confidence` |
| `resolve_contradiction` | `resolve` | (none) | `contradiction_id`, `resolution_action`, `resolution_note` |
| `get_similar` | `similar` | `memory_id`, `project_id` | `threshold`, `max_results`, `offset` |
| `get_relationships` | `relationships` | `memory_id`, `project_id` | `relationship_type`, `direction`, `include_provenance` |
| `create_relationship` | `relate` | `project_id` | `source_id`, `target_id`, `relationship_type`, `metadata` |
| `set_curation_rule` | `set_rule` | (none) | `name`, `tier`, `action_type`, `config`, `scope_filter`, `enabled`, `priority` |
| `list_projects` | `list_projects` | (none) | `filter` |
| `create_project` | `create_project` | `project_id` | `project_name`, `description`, `invite_only` |
| `add_project_member` | `add_member` | `project_id` | `user_id`, `role` |
| `remove_project_member` | `remove_member` | `project_id` | `user_id` |
| `get_session` | `status` | (none) | (none) |
| `set_session_focus` | `set_focus` | `project_id` | `focus` |
| `get_focus_history` | `focus_history` | `project_id` | `start_date`, `end_date` |

Two server-side normalizations to remember when wiring the dispatch:

- `relationships` action takes `memory_id` at the top level but the
  server's `manage_graph` tool internally renames it to `node_id`. The
  SDK should pass `memory_id` per the dispatcher contract; the server
  handles the rename.
- `describe_project`, `add_member`, `remove_member`, `create_project`
  take `project_id` at the top level, not `project_name`. The
  dispatcher normalizes.

## Implementation shape

Add one private helper:

```
async def _call_action(
    self,
    action: str,
    *,
    memory_id: str | None = None,
    query: str | None = None,
    content: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    options: dict | None = None,
) -> dict:
    payload = {"action": action}
    if memory_id is not None: payload["memory_id"] = memory_id
    if query is not None: payload["query"] = query
    if content is not None: payload["content"] = content
    if scope is not None: payload["scope"] = scope
    if project_id is not None: payload["project_id"] = project_id
    if options: payload["options"] = options
    return await self._call("memory", payload)
```

Each public method becomes a thin wrapper that builds its own `options`
dict and calls `_call_action`. The error-classification logic in
`_call` is unchanged — the server returns the same error envelopes for
the dispatched action as it did for the per-action tools.

## Backwards compatibility

- Public Python API: **stable**. No method signature changes, no
  imports moved. Existing callers (kagenti-adk wrapper, internal
  scripts) continue to compile after a version bump.
- Wire format: **breaking**. SDK 0.6.0 cannot talk to a server with
  per-action tools removed. SDK 0.7.0 cannot talk to a server that
  only exposes per-action tools. We pin kagenti-adk to 0.7.0+; the
  minimal-tool deployment is for legacy connectors and is not in the
  SDK's target set.

## Out of scope

- Re-introducing server-side per-action tools as aliases. Decision
  recorded above.
- Updating fipsagents/agent-template SDK consumers. Track separately
  if any are pinned <0.7.0.
- `manage_curation` / `set_curation_rule` parity with the dispatcher.
  The server still exposes `manage_curation` independently for tier-2
  callers; the SDK uses the dispatcher path for `set_rule`, `report`,
  `resolve`. No behavioral change.

## Open questions

- Do we want a `--use-legacy-tools` flag on the SDK for talking to the
  minimal deployment? Recommend **no** — minimal is a 4-tool subset
  used by legacy connectors, not a full target. Document in the README
  instead.
- Should the rework also update the SDK's docstrings to describe the
  dispatcher path? Recommend **yes**, but only on methods where the
  new wire format affects observable behavior (e.g., error messages
  reference the action name).

## References

- `planning/mcp-single-tool-schema.md` — the original action-dispatch design.
- `memory-hub-mcp/src/tools/memory.py` — the dispatcher implementation.
- `sdk/src/memoryhub/client.py` — the SDK to be reworked.
- `sdk/tests/test_client.py` — the test suite to update.
- `kagenti/adk` PR #231 — the integration that surfaced the gap.
