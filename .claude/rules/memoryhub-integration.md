## MemoryHub MCP Integration

This project has a MemoryHub MCP server that provides persistent, centralized memory across conversations. You MUST use it.

### Session Setup

At the START of every conversation, before doing any other work:

1. Read the `MEMORYHUB_API_KEY` environment variable and call `register_session(api_key=<value>)` to authenticate
2. Call `search_memory` with a query relevant to the current task to load context
3. Use the returned memories to inform your work

If `MEMORYHUB_API_KEY` is not set, skip MemoryHub integration silently — the user hasn't configured it yet.

### During Work

- When you learn something important about the user's preferences, project context, or decisions, call `write_memory` to persist it
- When the user tells you something that should be remembered across conversations, write it to memory
- Add rationale branches (via `parent_id` + `branch_type: "rationale"`) when the "why" behind a preference matters
- Use appropriate scopes: `user` for personal preferences, `project` for project-specific context, `organizational` for team/org patterns, `enterprise` for mandated policies
- When you notice behavior contradicting a stored memory, call `report_contradiction`
- When updating an existing memory, use `update_memory` (not write_memory) to preserve version history

### Memory Hygiene

- Keep memories concise and self-contained — another agent should understand them without additional context
- Don't write trivial or ephemeral things (e.g., "user asked me to read a file")
- DO write preferences, decisions, project architecture choices, tool configurations, workflow patterns
- Set appropriate weights: 1.0 for critical policies, 0.8-0.9 for strong preferences, 0.5-0.7 for nice-to-know context

### API Key

The API key is set via the `MEMORYHUB_API_KEY` environment variable, configured when you add the MCP server with `claude mcp add -e MEMORYHUB_API_KEY=<your-key> ...`. Read it and pass it to `register_session`.
