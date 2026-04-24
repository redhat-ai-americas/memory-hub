# MemoryHub Agent Integration Guide

How to connect an AI agent to MemoryHub for persistent, project-scoped memory.

## Prerequisites

- **MCP endpoint**: `https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`
- **API key**: Obtain from the system administrator. Format: `mh-dev-<hex>`. Store at `~/.config/memoryhub/api-key` (mode 0600).
- **Transport**: Streamable HTTP (not SSE).

## Quick Start — 3 steps

> **Note:** These examples use the full-profile tool names (`search_memory`, `write_memory`). In the compact profile (default), use `memory(action="search", ...)` and `memory(action="write", ...)` instead. See [Tiered Integration Model](#tiered-integration-model) for profile details.

### 1. Register your session

Call this **once at the start of every conversation**.

```
register_session(api_key="<your key>")
```

Returns your `user_id`, display `name`, accessible `scopes`, session `expires_at` timestamp, a list of your `projects` (with `memory_count` per project), and `quick_start` hints for next steps. All subsequent tool calls are scoped to your identity automatically.

**Session TTL:** Sessions expire after a configurable TTL (default 1 hour). The `expires_at` field tells you when. On expiry, call `register_session` again — you'll get a clear error directing you to re-register. Check TTL via `manage_session(action="status")`.

### 2. Search for existing memories

```
search_memory(query="deployment preferences")
```

With project filter (restricts results to that project's memories):

```
search_memory(query="deployment preferences", project_id="my-project")
```

The `project_id` filter restricts project-scoped results to the specified project while still including user-scope and higher-scope memories. This filtering is reliable as of the #194 fix.

### 3. Write a memory

```
write_memory(
    content="FastAPI is the preferred web framework for new services.",
    scope="project",
    project_id="my-project",
    project_description="Backend API service for customer onboarding",
    weight=0.8
)
```

If the project doesn't exist yet, it's **auto-created** and you're **auto-enrolled** on the first write. The `project_description` is set during auto-create and appears in `manage_project(action="list")` output.

## Tool Reference — What You Need

> The tables below use the **full-profile** tool names (e.g., `search_memory`, `write_memory`). In the **compact profile** (default, `MEMORYHUB_TOOL_PROFILE=compact`), these are consolidated into a single `memory(action=...)` dispatcher — see [Tiered Integration Model](#tiered-integration-model) for details. Both forms work; the compact profile is recommended for frontier models.

| Tool | When to use |
|------|-------------|
| `register_session` | Start of every conversation |
| `search_memory` | Find relevant memories (semantic search) |
| `write_memory` | Store a preference, decision, or fact |
| `read_memory` | Expand a stub or get version history |
| `manage_project` | Discover, create, and manage projects and memberships |
| `manage_session(action="status")` | Check your auth state (lightweight whoami) |

### Tools you probably won't need right away

| Tool | Purpose |
|------|---------|
| `update_memory` | Revise existing memory (preserves version history) |
| `delete_memory` | Remove a memory and its branches |
| `manage_curation(action="report_contradiction", ...)` | Flag a memory that conflicts with current reality |
| `manage_graph(action="create_relationship", ...)` | Link two memories (supports, contradicts, etc.) |
| `manage_graph(action="get_relationships", ...)` | Read links between memories |
| `manage_graph(action="get_similar", ...)` | Inspect near-duplicates flagged during write |
| `manage_curation(action="set_rule", ...)` | Tune duplicate-detection thresholds |
| `manage_session(action="set_focus", ...)` | Bias retrieval toward a topic across calls |
| `manage_session(action="focus_history", ...)` | View focus changes over time |

## Scopes

Memories have a scope that controls visibility:

| Scope | Visibility | When to use |
|-------|-----------|-------------|
| `user` | Only you | Personal preferences, workflow habits |
| `project` | Project members | Architecture decisions, project context |
| `campaign` | Campaign enrollees | Cross-project initiatives |
| `organizational` | Org-wide | Team standards, shared patterns |
| `enterprise` | Everyone | Mandated policies |

Most agent memories should be **`project`** scope with a `project_id`. Use `user` scope for personal preferences that shouldn't pollute the project.

## Weight Guidelines

Weight (`0.0`–`1.0`) controls how memories appear in search results:

| Weight | Use for |
|--------|---------|
| `1.0` | Critical policies, hard constraints |
| `0.8–0.9` | Strong preferences, architecture decisions |
| `0.5–0.7` | Useful context, nice-to-know |
| `0.1–0.3` | Low-priority, ephemeral observations |

## Common Patterns

### Session startup

```python
# 1. Authenticate
register_session(api_key=key)

# 2. Load context for current work
search_memory(query="relevant topic", project_id="my-project")

# 3. Use returned memories to inform your work
```

### Learning something worth remembering

```python
write_memory(
    content="The auth service requires RS256 keys, not HS256.",
    scope="project",
    project_id="my-project",
    weight=0.9
)
```

### Checking if you're still authenticated

```python
manage_session(action="status")  # Returns user_id, name, scopes, authenticated
```

### Discovering projects

```python
manage_project(action="list")  # Returns name, description, memory_count, is_member
manage_project(action="list", filter="all")  # Also shows open projects you could join
```

## Auto-Enrollment

You don't need to create projects or request membership ahead of time. When you write a project-scoped memory to a project that doesn't exist:

1. The project is created automatically
2. You are enrolled as a member
3. The response includes `auto_enrolled: {project_id, message}`

Subsequent writes to the same project skip enrollment (you're already a member).

## Tiered Integration Model

MemoryHub supports three integration paths, each optimized for a different
model capability tier. Choose based on your model's context budget and
tool-calling ability.

| Model tier | Integration path | Tool tokens | Tools |
|---|---|---|---|
| Small (7B, Granite 8B) | Framework connector (`self.memory`) | 0 | n/a |
| Mid-range (Llama 70B, Mixtral) | Full MCP profile (`MEMORYHUB_TOOL_PROFILE=full`) | ~6,800 | 10 |
| Frontier (Claude, GPT-4) | Compact MCP profile | ~895 | 2 |

### Path 1: Framework connector (small models)

For models with limited context windows (8K–16K tokens), MCP tool
definitions alone can consume a significant fraction of the budget. The
framework connector path avoids this entirely: memories are loaded via the
SDK at session startup and injected as a text prefix — no tool tokens at
all.

Example using the fipsagents framework:

```python
from fipsagents.memory import build_memory_prefix

memories = self.memory.search("deployment preferences", project_id="my-project")
prefix = build_memory_prefix(memories)
# Inject prefix into system prompt or first message
```

**Requirements:**
- SDK v0.6.0+ (`pip install memoryhub>=0.6.0`). Earlier versions fail on
  stub results returned by cache-optimized search.

**Known issue:** The fipsagents `build_memory_prefix()` default calls
`search("")`, which MemoryHub rejects (empty queries are not allowed).
Pass a non-empty query, or catch the error and fall back to no memories.

**Limitations:**
- Memories are read-only from the model's perspective (the framework loads
  them; the model doesn't call tools to retrieve them).
- Small models may not reliably follow prefix-injected memories as hard
  constraints. RAG-style extraction tends to work better (see
  [Granite 8B findings](#granite-8b-findings) below).

### Path 2: Full MCP profile (mid-range models)

Ten flat-parameter tools, each with its own JSON schema. Mid-range models
benefit from explicit parameter schemas that make each operation
independently discoverable.

Set the profile via environment variable on the MCP server deployment:

```
MEMORYHUB_TOOL_PROFILE=full
```

Tools: `register_session`, `search_memory`, `write_memory`, `read_memory`,
`update_memory`, `delete_memory`, `manage_session`, `manage_graph`,
`manage_curation`, `manage_project`.

### Path 3: Compact MCP profile (frontier models)

Two tools: `register_session` and a single `memory` dispatcher that
accepts an `action` parameter with 19 possible actions. Frontier models
handle the action-dispatch pattern well, and the reduced tool count
leaves more context for the actual conversation.

```
MEMORYHUB_TOOL_PROFILE=compact   # default
```

Tools: `register_session`, `memory(action=...)`.

### Why not the minimal profile for small models?

The minimal profile (4 tools: `register_session`, `search_memory`,
`write_memory`, `read_memory`) was designed as a middle ground for small
models. In practice, even 4 tools are too heavy for 7B context budgets:
`search_memory`'s docstring alone is ~2K tokens. The framework connector
path is the better choice for small models because it uses zero tool
tokens.

The minimal profile remains available (`MEMORYHUB_TOOL_PROFILE=minimal`)
for cases where a small model needs write-back capability and the token
budget can tolerate it.

### Granite 8B findings

Testing with Granite 8B on RHOAI validated the framework connector path
but surfaced a grounding gap: small models don't reliably treat
prefix-injected memories as constraints. When memories are injected as a
block of context at the start of the conversation, the model may
acknowledge them but not consistently apply them to answers.

This is an agent-design problem, not a MemoryHub problem. Mitigations:

- **RAG-style extraction** — retrieve memories relevant to the current question and weave them into the answer, rather than relying on the model to internalize a block of prefixed facts.
- **Structured prompting** — explicitly reference specific memories in the prompt (e.g., "According to memory X, the policy is Y").
- **Fewer, higher-weight memories** — filter to only the most relevant memories rather than injecting everything.

## Tips

- **Be specific in search queries**: `"container runtime preferences"` works better than `"containers"`.
- **Set project_description on first write**: It shows up in `manage_project(action="list")` and helps other agents understand the project.
- **Keep memories concise and self-contained**: Another agent should understand the memory without additional context.
- **Don't write trivial things**: Skip "user asked me to read a file." Do write preferences, decisions, architecture choices.
- **Use `manage_curation(action="report_contradiction", ...)`** when you notice behavior contradicting a stored memory.
- **Use `update_memory`** (not `write_memory`) to revise an existing memory — it preserves version history.
