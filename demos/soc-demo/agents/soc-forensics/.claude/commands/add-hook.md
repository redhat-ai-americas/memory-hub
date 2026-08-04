# Add Hook

Add a lifecycle hook to the agent. Hooks are shell commands that fire at specific points in the agent lifecycle, configured via YAML files in `hooks/`.

**Prerequisite: `/create-agent` must have been run first.** Verify `src/agent.py` exists before proceeding.

## Process

### Step 1: Understand the Hook

Ask the developer:

1. **What event should it fire on?** Built-in events:
   - `setup_complete` — after `setup()` finishes (stdout injected as context)
   - `shutdown` — before cleanup
   - `pre_tool_use` — before tool execution (non-zero exit blocks)
   - `post_tool_use` — after tool execution
   - `pre_mcp_connect` — before each MCP connection (stdout `KEY=VALUE` → env)
   - `post_mcp_connect` — after MCP connection + tool discovery
   - `mcp_auth_refresh` — on 401/403 from MCP tool call (stdout `KEY=VALUE` → env)
   - Or a custom event name (fired from agent code via `self.hooks.fire("event_name")`)

2. **What does the hook do?** Get a one-sentence description.

3. **For tool events: which tools?** If the hook targets specific tools, get the fnmatch pattern (e.g., `"db_*"`, `"execute_*"`). Null means all tools.

4. **Does it need external credentials or endpoints?** If yes, these should be env vars referenced in the script.

### Step 2: Check for Conflicts

- Verify no existing hook in `hooks/` targets the same event with the same matcher:
  ```bash
  cat hooks/*.yaml 2>/dev/null
  ```
- For `pre_tool_use` hooks, warn that non-zero exit **blocks** the tool call. Make sure the developer intends this gating behavior.

### Step 3: Known Patterns

If the developer asks for one of these, use the tested pattern:

#### MCP Gateway Auth (`/add-hook mcp-auth`)

Generates a token acquisition hook for Keycloak-authenticated MCP gateways. Works for both initial connection (`pre_mcp_connect`) and mid-session refresh (`mcp_auth_refresh`).

**hooks/acquire-token.yaml:**
```yaml
event: pre_mcp_connect
command: ./hooks/acquire-token.sh
timeout: 10
name: mcp-token-acquire
```

**hooks/refresh-token.yaml:**
```yaml
event: mcp_auth_refresh
command: ./hooks/acquire-token.sh
timeout: 10
name: mcp-token-refresh
```

**hooks/acquire-token.sh:**
```bash
#!/usr/bin/env bash
set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-}"
CLIENT_ID="${MCP_CLIENT_ID:-}"
CLIENT_SECRET="${MCP_CLIENT_SECRET:-}"
[ -n "$KEYCLOAK_URL" ] || exit 0

TOKEN=$(curl -s -X POST "$KEYCLOAK_URL/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "MCP_AUTH_TOKEN=${TOKEN}"
```

Also update `agent.yaml` `mcp_servers` entry to include headers:
```yaml
mcp_servers:
  - url: ${MCP_GATEWAY_URL}
    headers:
      Authorization: "Bearer ${MCP_AUTH_TOKEN}"
```

And add env var placeholders to `chart/values.yaml` if it exists:
```yaml
env:
  KEYCLOAK_URL: ""
  MCP_CLIENT_ID: ""
  MCP_CLIENT_SECRET: ""
  MCP_GATEWAY_URL: ""
```

### Step 4: Generate the Hook Files

Create two files per hook:

**hooks/<name>.yaml** — the binding:
```yaml
event: <event_name>
command: ./hooks/<name>.sh
timeout: 10
name: <descriptive-name>
# matcher: "pattern_*"  # only for tool events
```

**hooks/<name>.sh** — the script:
```bash
#!/usr/bin/env bash
set -euo pipefail

# Available env vars:
#   AGENT_NAME, AGENT_PROJECT_DIR, HOOK_EVENT
#   (plus event-specific vars — see docs/hooks.md)

# Your logic here

exit 0
```

Make the script executable:
```bash
chmod +x hooks/<name>.sh
```

### Step 5: Verify

1. Run the hook manually to check it works:
   ```bash
   AGENT_NAME=test HOOK_EVENT=<event> ./hooks/<name>.sh
   ```

2. If it's a custom event, verify the agent code fires it:
   ```bash
   grep -r "hooks.fire.*<event_name>" src/
   ```

3. Run `make test` to ensure no regressions.

### Step 6: Summary

Tell the developer:
- What hook was created and which event it fires on
- How to test it manually
- If it's a `pre_tool_use` hook, remind them that non-zero exit blocks tool calls
- If it uses env vars, remind them to set those in their deployment config
- Point them to `docs/hooks.md` for the full reference
