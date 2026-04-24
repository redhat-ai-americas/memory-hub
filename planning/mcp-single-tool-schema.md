# MCP Action-Dispatch Schema Design

**Issue:** #201 | **Parent:** #198 (context weight reduction)
**Status:** Draft | **Date:** 2026-04-23

## Context

MemoryHub's MCP server exposes 10 tools consuming ~13K tokens in agent
context. With models handling ~40-50 tools effectively, MemoryHub alone
uses 25% of an agent's tool budget before the agent loads any other MCP
servers. The Phase 6 consolidation (15 -> 10 tools) was a good first step
but preserved 5 atomic CRUD tools plus the 4 `manage_*` dispatchers plus
`register_session`. This design goes further: collapsing all 9 non-auth
tools into a single `memory` tool with action dispatch, following the
GitHub GraphQL MCP pattern.

**Goal:** 10 tools -> 2 tools. Target < 2K tokens total context cost
(down from ~13K).

## Decision: 1 Tool

### Recommendation: `register_session` + `memory` = 2 tools total

The primary constraint is tool count, not token cost. One dispatched tool
minimizes the tool budget impact while the `options` dict approach keeps
the JSON schema compact.

**Arguments for 1 tool:**
- Maximizes tool count savings (8 fewer tools)
- Single discovery point: agents never pick the wrong tool
- The `action` parameter provides sufficient narrowing
- Precedent: GitHub's GraphQL MCP, Stripe's resource tools
- The existing `manage_graph` already mixes reads and writes with no issues

**`register_session` stays separate** because it's a one-time auth gate
with a fundamentally different lifecycle. Folding it into `memory` would
muddy the intent and force agents to pass `action="register"` for an
operation that conceptually precedes all other actions.

### Alternative considered: read/write split (3 tools total)

`memory_read` (8 actions) + `memory_write` (11 actions) + `register_session`.

**Arguments for:** Annotation accuracy (`readOnlyHint`), RBAC alignment
with `memory:read`/`memory:write` scopes, shorter docstrings per tool.

**Why not chosen:** Saves 7 tool slots vs 8 for the 1-tool approach. The
annotation concern is already precedented by `manage_graph` mixing reads
and writes. The docstring length concern is addressed by the compact
reference table format. And agents already decide intent via the `action`
parameter, making the tool-level read/write split redundant.

**Escape hatch:** If real-world testing shows agents struggle with 19
actions in one tool, the split is a trivial refactor -- the action
handlers are independent functions, and the dispatcher is a match
statement. We can split without touching any handler code.

## The `memory` Tool

### Top-Level Parameters

The tool exposes 7 parameters in its JSON schema. Commonly-used params
are top-level for discoverability; action-specific params go in `options`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | str, **required** | The operation to perform. See action reference. |
| `memory_id` | str \| null | UUID of target memory. Required for: read, update, delete, similar, relationships, report. |
| `query` | str \| null | Natural language search text. Required for: search. |
| `content` | str \| null | Memory text. Required for: write. Optional for: update. |
| `scope` | str \| null | Scope: user, project, campaign, role, organizational, enterprise. Required for: write. Optional filter for: search. |
| `project_id` | str \| null | Project identifier for scoping. Required for: write (project/campaign scope), set_focus, focus_history, describe_project, add_member, remove_member. |
| `options` | dict \| null | Action-specific parameters. Keys validated per action. See options reference. |

**Why these 7?** `action` is universal. `memory_id` serves 6 actions.
`query` and `content` serve the two most common operations (search and
write). `scope` serves write (required) and search (optional filter).
`project_id` serves 10+ actions. `options` captures the long tail of
~45 action-specific parameters without bloating the schema.

**Why `options` dict instead of flat?** With 19 actions and ~55 unique
parameters, flat top-level params would produce a massive JSON schema
(~1.5K tokens just for parameter descriptions). The `options` dict
reduces schema overhead to ~15 tokens while the docstring's reference
table provides discoverability. The tradeoff (one level of nesting) is
minor for capable models.

### Action Reference

#### Read path

| Action | Top-level params | Options | Description |
|--------|-----------------|---------|-------------|
| `search` | `query` (req), `scope`, `project_id` | max_results, focus, session_focus_weight, domains, domain_boost_weight, include_branches, mode, max_response_tokens, raw_results, weight_threshold, current_only, owner_id, graph_depth, graph_relationship_types, graph_boost_weight | Semantic similarity search. Returns cache-optimized stable ordering by default. |
| `read` | `memory_id` (req), `project_id` | include_versions, history_offset, history_max_versions, hydrate | Retrieve memory by UUID. Optional paginated version history. |
| `similar` | `memory_id` (req), `project_id` | threshold, max_results, offset | Find near-duplicate memories by cosine distance. Use when write reports similar_count > 0. |
| `relationships` | `memory_id` (req), `project_id` | relationship_type, direction, include_provenance | Query graph edges for a node. Supports provenance tracing for derived_from chains. |
| `status` | *(none)* | *(none)* | Session identity, scopes, project memberships, expiry. Lightweight whoami. |
| `focus_history` | `project_id` (req) | start_date, end_date | Focus declaration histogram for a project over a date window. |
| `list_projects` | *(none)* | filter | List your projects (filter="mine", default) or all open ones (filter="all"). |
| `describe_project` | `project_id` (req) | *(none)* | Project details including member roster and memory count. |

#### Write path

| Action | Top-level params | Options | Description |
|--------|-----------------|---------|-------------|
| `write` | `content` (req), `scope` (req), `project_id` | weight, parent_id, branch_type, metadata, domains, project_description, force | Create a new memory node or branch in the tree. |
| `update` | `memory_id` (req), `content`, `project_id` | weight, metadata, domains | Create a new version. Old version preserved for history. Must target isCurrent=true version. |
| `delete` | `memory_id` (req), `project_id` | *(none)* | Soft-delete memory + entire version chain + branches. Rows kept with deleted_at for audit. |
| `set_focus` | `project_id` (req) | focus (**req**) | Declare session focus topic. Biases subsequent search retrieval. |
| `relate` | `project_id` | source_id (**req**), target_id (**req**), relationship_type (**req**), metadata | Create directed graph edge. Types: derived_from, supersedes, conflicts_with, related_to. |
| `report` | `memory_id` (req), `project_id` | observed_behavior (**req**), confidence | Flag behavior contradicting a stored memory. 5 reports trigger curator revision. |
| `resolve` | *(none)* | contradiction_id (**req**), resolution_action (**req**), resolution_note | Close contradiction. Actions: accept_new, keep_old, mark_both_invalid, manual_merge. |
| `set_rule` | *(none)* | name (**req**), tier, action_type, config, scope_filter, enabled, priority | Create/update user-layer curation rule. Cannot override system rules. |
| `create_project` | *(none)* | project_name (**req**), description, invite_only | Create a new open or invite-only project. |
| `add_member` | `project_id` (req) | user_id (**req**), role | Add user to project. role: member (default) or admin. |
| `remove_member` | `project_id` (req) | user_id (**req**) | Remove user from project. Self-removal always allowed. |

**Bold (req)** in options = required for that action, validated by handler.

### Options Reference

Full per-action options with types and defaults. Agents can use the action
reference table above for quick lookup; this section is the detailed
specification.

#### search options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_results` | int | 10 | Result limit (1-50) |
| `focus` | str | null | Session focus for retrieval bias (e.g., "OpenShift deployment") |
| `session_focus_weight` | float | 0.4 | Focus bias strength (0.0-1.0) |
| `domains` | list[str] | null | Domain tags to boost (e.g., ["React"]) |
| `domain_boost_weight` | float | 0.3 | Domain boost strength (0.0-1.0) |
| `include_branches` | bool | false | Nest branch memories under parents |
| `mode` | str | "full" | Result detail: full, index, full_only |
| `max_response_tokens` | int | 4000 | Soft cap on response size |
| `raw_results` | bool | false | Skip cache-optimized ordering, use similarity ranking |
| `weight_threshold` | float | 0.0 | Return stubs for memories below this weight |
| `current_only` | bool | true | Only current versions |
| `owner_id` | str | caller | Filter by owner ("" for all owners) |
| `graph_depth` | int | 0 | Graph traversal hops (0-3, 0 disables) |
| `graph_relationship_types` | list[str] | null | Limit graph to these relationship types |
| `graph_boost_weight` | float | 0.2 | Graph proximity boost (0.0-1.0) |

#### read options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `include_versions` | bool | false | Include paginated version history |
| `history_offset` | int | 0 | Skip N versions from newest |
| `history_max_versions` | int | 10 | Max versions to return (1-100) |
| `hydrate` | bool | false | Fetch full content from S3 if externally stored |

#### similar options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `threshold` | float | 0.80 | Minimum cosine similarity (0.0-1.0) |
| `max_results` | int | 10 | Result limit (1-50) |
| `offset` | int | 0 | Pagination offset |

#### relationships options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `relationship_type` | str | null | Filter: derived_from, supersedes, conflicts_with, related_to |
| `direction` | str | "both" | Edge direction: outgoing, incoming, both |
| `include_provenance` | bool | false | Trace derived_from ancestry chain |

#### focus_history options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `start_date` | str | 30 days ago | ISO date YYYY-MM-DD |
| `end_date` | str | today | ISO date YYYY-MM-DD |

#### list_projects options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `filter` | str | "mine" | "mine" (your projects) or "all" (all accessible) |

#### write options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `weight` | float | 0.7 | Injection priority (0.0-1.0) |
| `parent_id` | str | null | UUID of parent when creating a branch |
| `branch_type` | str | null | Required with parent_id: rationale, provenance, description, evidence, approval |
| `metadata` | dict | null | Arbitrary key-value pairs |
| `domains` | list[str] | null | Domain tags (e.g., ["React", "OpenShift"]) |
| `project_description` | str | null | Description when auto-creating a project |
| `force` | bool | false | Bypass near-duplicate gates (not regex rules) |

#### update options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `weight` | float | null | New injection priority (omit to keep existing) |
| `metadata` | dict | null | Metadata to merge with existing |
| `domains` | list[str] | null | New domain tags (replaces existing) |

#### set_focus options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `focus` | str | **required** | Short topic description (5-10 words) |

#### relate options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `source_id` | str | **required** | UUID of source memory node |
| `target_id` | str | **required** | UUID of target memory node |
| `relationship_type` | str | **required** | derived_from, supersedes, conflicts_with, related_to |
| `metadata` | dict | null | Edge metadata (e.g., merge_suggested, reasoning) |

#### report options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `observed_behavior` | str | **required** | Description of the conflicting observation |
| `confidence` | float | 0.7 | Contradiction confidence (0.0-1.0) |

#### resolve options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `contradiction_id` | str | **required** | UUID of the contradiction report |
| `resolution_action` | str | **required** | accept_new, keep_old, mark_both_invalid, manual_merge |
| `resolution_note` | str | null | Rationale for audit trail |

#### set_rule options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | str | **required** | Rule identifier (unique per user) |
| `tier` | str | "embedding" | "regex" or "embedding" |
| `action_type` | str | "flag" | flag, block, quarantine, reject_with_pointer, decay_weight |
| `config` | dict | null | Tier-specific: {threshold: float} or {pattern: string} |
| `scope_filter` | str | null | Scope to apply rule to |
| `enabled` | bool | true | Active flag |
| `priority` | int | 10 | Evaluation priority (lower = higher) |

#### create_project options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `project_name` | str | **required** | Project identifier |
| `description` | str | null | Project description |
| `invite_only` | bool | false | Enrollment policy |

#### add_member options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `user_id` | str | **required** | User to add |
| `role` | str | "member" | "member" or "admin" |

#### remove_member options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `user_id` | str | **required** | User to remove |

### Parameter Normalization

The compacted tool normalizes identifiers that varied across the old tools:

| Old param | Old tool | New param | Rationale |
|-----------|----------|-----------|-----------|
| `node_id` | manage_graph | `memory_id` | Same concept (UUID of a memory node) |
| `project_name` | manage_project | `project_id` | Unified project identifier |
| `project` | manage_session | `project_id` | Unified project identifier |

### Tool Annotations

```python
annotations={
    "readOnlyHint": False,   # write actions mutate state
    "destructiveHint": False, # delete is soft-delete (reversible)
    "idempotentHint": False,  # writes create new records
    "openWorldHint": False,   # closed system
}
```

The single tool can't distinguish read vs write annotations per action.
This matches the existing `manage_graph` pattern which mixes read and
write actions under `readOnlyHint: False`.

### Example Calls

#### Core operations

```python
# Search for relevant memories
memory(action="search", query="deployment preferences", project_id="memory-hub")

# Search with focus bias and domain boost
memory(action="search", query="container runtime",
       project_id="memory-hub",
       options={"focus": "OpenShift deployment", "domains": ["containers"],
                "max_results": 5})

# Read a specific memory with version history
memory(action="read", memory_id="7e0c9b61-...", options={"include_versions": True})

# Create a new memory
memory(action="write", content="Always use UBI base images for containers",
       scope="organizational", project_id="memory-hub",
       options={"weight": 1.0, "domains": ["containers"]})

# Update an existing memory
memory(action="update", memory_id="7e0c9b61-...",
       content="Always use UBI base images for production containers")

# Delete a memory
memory(action="delete", memory_id="7e0c9b61-...")
```

#### Graph operations

```python
# Create a relationship
memory(action="relate",
       options={"source_id": "aaa-...", "target_id": "bbb-...",
                "relationship_type": "derived_from"})

# Query relationships with provenance
memory(action="relationships", memory_id="aaa-...",
       options={"direction": "outgoing", "include_provenance": True})

# Find near-duplicates
memory(action="similar", memory_id="aaa-...",
       options={"threshold": 0.90, "max_results": 5})
```

#### Session operations

```python
# Check session status
memory(action="status")

# Set focus topic
memory(action="set_focus", project_id="memory-hub",
       options={"focus": "MCP tool consolidation"})

# Query focus history
memory(action="focus_history", project_id="memory-hub",
       options={"start_date": "2026-04-01"})
```

#### Curation operations

```python
# Report a contradiction
memory(action="report", memory_id="7e0c9b61-...",
       options={"observed_behavior": "User switched to Docker for client project",
                "confidence": 0.8})

# Resolve a contradiction
memory(action="resolve",
       options={"contradiction_id": "ccc-...",
                "resolution_action": "keep_old",
                "resolution_note": "One-off client requirement"})

# Set a curation rule
memory(action="set_rule",
       options={"name": "strict_dedup", "tier": "embedding",
                "config": {"threshold": 0.98}})
```

#### Project operations

```python
# List projects
memory(action="list_projects")

# Create a project
memory(action="create_project",
       options={"project_name": "new-service", "description": "API gateway"})

# Describe a project
memory(action="describe_project", project_id="memory-hub")

# Add a member
memory(action="add_member", project_id="memory-hub",
       options={"user_id": "jsmith", "role": "member"})

# Remove a member
memory(action="remove_member", project_id="memory-hub",
       options={"user_id": "jsmith"})
```

### Draft Docstring

Target: ~500-700 tokens. This is what agents see.

```
All-in-one memory operations. Call register_session(api_key=...) first.

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
  create_project(options: {project_name})
    Create a new project.
  add_member(project_id, options: {user_id})
    Add user to project.
  remove_member(project_id, options: {user_id})
    Remove user from project.

Params in () are top-level. {braces} in options = required for that action.
```

## Token Cost Estimate

### Current state (10 tools)

Each tool's context cost = tool name + description + JSON schema
(parameter types, descriptions, constraints).

| Tool | Est. tokens |
|------|-------------|
| register_session | ~200 |
| write_memory | ~550 |
| read_memory | ~450 |
| update_memory | ~400 |
| delete_memory | ~400 |
| search_memory | ~2,100 |
| manage_session | ~550 |
| manage_graph | ~800 |
| manage_curation | ~800 |
| manage_project | ~550 |
| **Total** | **~6,800** |

Note: Previous estimate of ~13K may include MCP protocol framing and
system prompt instructions. The numbers above count description +
schema tokens only. The system prompt integration rule
(`.claude/rules/memoryhub-integration.md`) adds another ~1K tokens on
top.

### After compaction (2 tools)

| Tool | Description | Schema (7 params) | Total |
|------|-------------|-------------------|-------|
| register_session | ~120 | ~35 | ~155 |
| memory | ~650 | ~245 | ~895 |
| **Total** | | | **~1,050** |

**Savings: ~5,750 tokens (~85% reduction), 8 fewer tool slots.**

The `options: dict` approach is key to the schema savings -- one
untyped dict param costs ~15 tokens vs ~1,500 tokens for 45 individual
typed parameters with descriptions.

### Context budget after compaction

| Component | Tokens |
|-----------|--------|
| Tool definitions (2 tools) | ~1,050 |
| System prompt integration rule | ~800 |
| **Total MemoryHub context** | **~1,850** |

This leaves substantial headroom for other MCP servers in the agent's
tool budget.

## Migration Strategy

### Phase 1: Parallel deployment (v0.9.0)

- Register `memory` tool alongside existing 9 tools
- Old tools become thin wrappers that delegate to the `memory` dispatcher
- System prompt and integration rules updated to recommend `memory()`
- SDK methods unchanged (they call whichever tool name the server exposes)
- No breaking changes

### Phase 2: Deprecation notices (v0.9.x)

- Old tools add `"_deprecated": "Use memory(action='...') instead"` to
  responses
- System prompt drops old tool documentation; only describes `memory`
- Old tools still functional but no longer documented

### Phase 3: Removal (v1.0.0)

- Old 9 tools removed from registration in `main.py`
- SDK v0.7.0+ maps to `memory` tool name
- CLI unaffected (CLI uses SDK methods, not tool names directly)
- Clean break: 2 tools total

### Thin wrapper pattern (Phase 1-2)

During transition, old tools delegate to the new dispatcher:

```python
async def write_memory(content, scope, weight=0.7, parent_id=None,
                       branch_type=None, metadata=None, domains=None,
                       project_id=None, project_description=None,
                       force=False, ctx=None):
    return await _memory_dispatch(
        action="write",
        content=content,
        scope=scope,
        project_id=project_id,
        options={
            "weight": weight,
            "parent_id": parent_id,
            "branch_type": branch_type,
            "metadata": metadata,
            "domains": domains,
            "project_description": project_description,
            "force": force,
        },
        ctx=ctx,
    )
```

The `_memory_dispatch` function is the shared handler that the new
`memory` tool also calls. No code duplication.

### Consumer audit checklist

Per the same-commit consumer audit rule, the compaction PR must grep:

- [ ] `memoryhub-ui/backend` -- BFF calls tool names via SDK, verify no
  hardcoded tool name references
- [ ] `sdk/` -- Client methods call tool names; update if tool name changes
- [ ] `memoryhub-cli/` -- CLI uses SDK, should be unaffected
- [ ] `.claude/rules/memoryhub-integration.md` -- Update for `memory()` usage
- [ ] `SYSTEM_PROMPT.md` -- Update tool reference

## Implementation Notes

### Dispatcher architecture

```
memory(action, ..., options)
  -> validate action enum
  -> extract + validate per-action params from top-level + options
  -> dispatch to _handle_{action}(validated_params, ctx)
  -> return result dict
```

Each `_handle_*` function is the existing tool handler with minimal
changes (parameter extraction from options dict instead of function args).

### Error handling

Unchanged from current pattern. All errors raise `ToolError` with
actionable messages:

```python
if action not in _VALID_ACTIONS:
    raise ToolError(
        f"Invalid action '{action}'. Must be one of: "
        f"{', '.join(sorted(_VALID_ACTIONS))}."
    )

# Per-action required params
if action == "search" and not query:
    raise ToolError(
        "action='search' requires 'query'. "
        "Example: memory(action='search', query='deployment preferences')"
    )
```

### File structure

```
src/tools/
  memory.py          # New: dispatcher + _handle_* functions
  register_session.py  # Unchanged
  # Old files kept during Phase 1-2, removed in Phase 3:
  write_memory.py    # Thin wrapper -> _memory_dispatch
  read_memory.py     # Thin wrapper -> _memory_dispatch
  ...
```

The handlers in `memory.py` import service-layer functions from the
existing tool files to avoid duplicating business logic. As old tools
are removed in Phase 3, the handler code moves fully into `memory.py`.

## Open Questions

1. **Action name length:** Should `describe_project` be shortened to
   `describe`? The `_project` suffix aids discoverability in a 19-action
   list, but adds verbosity. Same question for `list_projects`,
   `create_project`, `add_member`, `remove_member`.

2. **`options` discoverability:** Capable models (Claude, GPT-4) read
   docstrings well and handle free-form dicts. Less capable models may
   struggle. Should we provide a separate `tools/list` resource with
   the full per-action schema for agents that want to fetch it?

3. **Batch operations:** Should we add a `batch` meta-action that
   accepts a list of `{action, params}` objects? Defer unless agents
   demonstrate a pattern of sequential calls that could be batched.

4. **`register_session` folding:** Some agents may prefer a fully
   unified interface where `memory(action="register", options={api_key: ...})`
   handles auth too. Defer -- the separate tool provides clearer error
   messaging and lifecycle semantics.
