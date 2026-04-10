## MemoryHub MCP Integration

This project has a MemoryHub MCP server that provides persistent, centralized memory across conversations. You MUST use it.

### Session Setup

At the START of every conversation, before doing any other work:

1. Run `scripts/cluster-health-check.sh` to verify cluster deployment state. If it reports issues, tell the user before proceeding. Use `--full` when the session involves deployment, migrations, or the DB.
2. Read your personal api key from `~/.config/memoryhub/api-key` (trim the trailing newline). This file is per-operator and lives outside the repo — it is not committed. If the file does not exist, ask the user to create it before continuing.
3. Call `register_session(api_key="<the value you just read>")` to authenticate.
4. Call `search_memory` with a query relevant to the current task to load context.
5. Use the returned memories to inform your work.

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

### API Key Storage

The api key is stored at `~/.config/memoryhub/api-key` (mode 0600). This is intentional:
- It MUST NOT be committed to the repository.
- Each operator maintains their own key corresponding to a user in the deployed `memoryhub-users` ConfigMap on the cluster.
- If the server moves to a different auth mechanism (e.g., OAuth 2.1 client_credentials only, no `register_session` shim), update this section accordingly.
