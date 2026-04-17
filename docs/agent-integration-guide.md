# MemoryHub Agent Integration Guide

How to connect an AI agent to MemoryHub for persistent, project-scoped memory.

## Prerequisites

- **MCP endpoint**: `https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`
- **API key**: Obtain from the system administrator. Format: `mh-dev-<hex>`. Store at `~/.config/memoryhub/api-key` (mode 0600).
- **Transport**: Streamable HTTP (not SSE).

## Quick Start — 3 steps

### 1. Register your session

Call this **once at the start of every conversation**.

```
register_session(api_key="<your key>")
```

Returns your `user_id`, display `name`, and accessible `scopes`. All subsequent tool calls are scoped to your identity automatically.

### 2. Search for existing memories

```
search_memory(query="deployment preferences")
```

With project filter (restricts to that project only):

```
search_memory(query="deployment preferences", project_id="my-project")
```

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

| Tool | When to use |
|------|-------------|
| `register_session` | Start of every conversation |
| `search_memory` | Find relevant memories (semantic search) |
| `write_memory` | Store a preference, decision, or fact |
| `read_memory` | Expand a stub or get version history |
| `manage_project` | Discover, create, and manage projects and memberships |
| `get_session` | Check your auth state (lightweight whoami) |

### Tools you probably won't need right away

| Tool | Purpose |
|------|---------|
| `update_memory` | Revise existing memory (preserves version history) |
| `delete_memory` | Remove a memory and its branches |
| `report_contradiction` | Flag a memory that conflicts with current reality |
| `create_relationship` | Link two memories (supports, contradicts, etc.) |
| `get_relationships` | Read links between memories |
| `get_similar_memories` | Inspect near-duplicates flagged during write |
| `set_curation_rule` | Tune duplicate-detection thresholds |
| `set_session_focus` | Bias retrieval toward a topic across calls |
| `get_focus_history` | View focus changes over time |

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
get_session()  # Returns user_id, name, scopes, authenticated
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

## Tips

- **Be specific in search queries**: `"container runtime preferences"` works better than `"containers"`.
- **Set project_description on first write**: It shows up in `manage_project(action="list")` and helps other agents understand the project.
- **Keep memories concise and self-contained**: Another agent should understand the memory without additional context.
- **Don't write trivial things**: Skip "user asked me to read a file." Do write preferences, decisions, architecture choices.
- **Use `report_contradiction`** when you notice behavior contradicting a stored memory.
- **Use `update_memory`** (not `write_memory`) to revise an existing memory — it preserves version history.
