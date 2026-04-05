## MemoryHub MCP Integration

This project has a MemoryHub MCP server that provides persistent, centralized memory across conversations. You MUST use it.

### Session Setup

At the START of every conversation, before doing any other work:

1. Call `register_session(api_key="mh-dev-wjackson-2026")` to authenticate
2. Call `search_memory` with a query relevant to the current task to load context
3. Use the returned memories to inform your work

### During Work

- **Search memory again when the topic shifts.** The initial search covers the conversation's starting topic, but if work moves to a different area (e.g., from implementation to deployment, or from one subsystem to another), search memory for the new topic. Memories are retrieved on demand, not loaded once — use that.
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

The API key is hardcoded above for the HTTP transport configuration. If the server moves to a different auth mechanism (e.g., Authorino), update the session setup instructions accordingly.
