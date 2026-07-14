# MemoryHub MCP Server -- System Prompt Guidance

Instructions for AI models consuming the MemoryHub MCP server (compact profile).

## Authentication

Call `register_session(api_key=...)` once at the start of every conversation. Your API key is stored at `~/.config/memoryhub/api-key`. All subsequent tool calls are scoped to your authenticated identity.

## Tools

The compact profile exposes three tools:

- **`register_session`** -- Authenticate. Call once per conversation.
- **`memory(action=...)`** -- All memory operations: search, read, write, update, delete, list, and more. See the tool docstring for the full action list.
- **`thread(action=...)`** -- Conversation persistence: create, append, get, list, archive threads.

## Reading memories

Search results return **content-only** by default: each entry is `{id, content, result_type}` with no structural metadata. This is the right default -- use the `content` field directly.

When you need full metadata (weight, scope, timestamps, branches) for curation decisions, pass `options: {verbose: true}`.

To expand a stub or get version history for a specific memory, use `memory(action="read", memory_id=...)`.

Large memories (S3-backed) may arrive truncated. Check `content_truncated` and `full_available` flags on each result. When `content_truncated` is true, call `memory(action="read", memory_id="...", options={"hydrate": true})` to get the full content.

## Hook-injected context

If a `<memoryhub-context>` block is present in your conversation context, a SessionStart hook has already loaded project and user memories for you. Use these as your working set:

- **Do not** call `register_session` or `search` redundantly -- the hook already did this.
- **Do** call `register_session` when you need to write, update, or delete memories (write operations require an active session).
- **Do** call `memory(action="search", ...)` when the conversation pivots to a new topic not covered by the pre-loaded set.

If no `<memoryhub-context>` block is present, fall back to the manual flow: register, then search.

## Writing memories

```
memory(action="write", content="...", scope="project", project_id="my-project")
```

Use `scope="project"` with a `project_id` for project-specific context. Use `scope="user"` for personal preferences.

Set `weight` deliberately: 1.0 for critical policies, 0.8-0.9 for strong preferences, 0.5-0.7 for useful context.

To revise an existing memory (preserving version history), use `memory(action="update", memory_id="...", content="...")` instead of writing a new one.

## What to remember

Write preferences, decisions, architectural choices, tool configurations, and workflow patterns. Skip ephemeral details like "user asked me to read a file."

Keep memories concise and self-contained -- another agent in a future session should understand them without additional context.

## Contradiction handling

When you notice a memory that conflicts with current reality, report it:

```
memory(action="report", memory_id="...", options={observed_behavior: "..."})
```

## Thread operations

Use threads for conversation persistence across sessions:

```
thread(action="create", options={title: "Feature discussion"})
thread(action="append", thread_id="...", content="Key decision: use FastAPI")
thread(action="get", thread_id="...")
```
