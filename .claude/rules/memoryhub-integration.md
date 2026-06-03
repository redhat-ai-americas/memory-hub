## MemoryHub MCP Integration

This project has a MemoryHub MCP server that provides persistent, centralized memory across conversations. You MUST use it.

### Session Setup

At the START of every conversation, before doing any other work:

1. Run `scripts/cluster-health-check.sh` to verify cluster deployment state. If it reports issues, tell the user before proceeding. Use `--full` when the session involves deployment, migrations, or the DB.
2. Check for a `<memoryhub-context>` block in your conversation context. If present, the SessionStart hook has already pre-loaded project and user memories -- skip steps 3-4 and use these memories directly.
3. If no `<memoryhub-context>` block is present (hook not configured, CLI missing, or API unreachable), fall back to the manual flow: read your API key from `~/.config/memoryhub/api-key`, call `register_session(api_key="...")`, then call `search_memory` with a query relevant to the current task. **Always pass `project_id="memory-hub"`**.
4. Use the returned or pre-loaded memories to inform your work.

### During Work

- **Defer `register_session` until you need it.** If startup memories came via the hook, you do not need to register immediately. Call `register_session` the first time you need to search (topic pivot) or write.
- **Search memory on topic pivots.** If work moves to a different area (e.g., from implementation to deployment), call `register_session` if not already registered, then `search_memory` for the new topic. Always include `project_id="memory-hub"`.
- When you learn something important about the user's preferences, project context, or decisions, call `write_memory` to persist it
- When the user tells you something that should be remembered across conversations, write it to memory
- Add rationale branches (via `parent_id` + `branch_type: "rationale"`) when the "why" behind a preference matters
- Use appropriate scopes: `user` for personal preferences, `project` for project-specific context, `organizational` for team/org patterns, `enterprise` for mandated policies
- When writing project-scoped memories, pass `project_id="memory-hub"` -- the server tags the memory to this project and verifies your membership
- When you notice behavior contradicting a stored memory, call `manage_curation(action="report_contradiction", ...)`
- When updating an existing memory, use `update_memory` (not write_memory) to preserve version history

### Memory Hygiene

- Keep memories concise and self-contained — another agent should understand them without additional context
- Don't write trivial or ephemeral things (e.g., "user asked me to read a file")
- DO write preferences, decisions, project architecture choices, tool configurations, workflow patterns
- Set appropriate weights: 1.0 for critical policies, 0.8-0.9 for strong preferences, 0.5-0.7 for nice-to-know context

### API Key Storage

The api key is stored at `~/.config/memoryhub/api-key` (mode 0600). This is intentional:
- It MUST NOT be committed to the repository.
- Each operator maintains their own key corresponding to a user in the deployed `memoryhub-users` ConfigMap on the cluster.
- If the server moves to a different auth mechanism (e.g., OAuth 2.1 client_credentials only, no `register_session` shim), update this section accordingly.

### Server URL

The server URL is stored at `~/.config/memoryhub/config.json` (mode 0600) as `{"url": "https://..."}`. The SessionStart hook and all CLI commands resolve the URL from `MEMORYHUB_URL` env var first, then this file. Without a configured URL, the hook degrades silently and CLI commands fail with a clear error.

Run `memoryhub config init` to set this interactively, or create the file manually. This file is per-operator and MUST NOT be committed.
