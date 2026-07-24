# MemoryHub Hooks Integration for Claude Code

Load project and user memories into Claude Code sessions at startup, before the first prompt. Memories are injected as plain text context with zero MCP overhead.

## How it works

Claude Code supports [SessionStart hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) that run a shell command when a session starts. The hook runs the `memoryhub` CLI to search for relevant memories and prints them to stdout in a compact, content-only format. Claude Code injects the output into the conversation context before your first message.

The result is a `<memoryhub-context>` block visible to the model:

```
<memoryhub-context project="my-project">
- FastAPI is the preferred web framework for new services
- Deploy scripts must be run in main conversation context, never sub-agents
- Auth service requires RS256 keys, not HS256
</memoryhub-context>
```

No memory IDs, timestamps, weights, or structural metadata. Just the content the model needs.

The MCP server remains available for mid-conversation searches and writes. The hook handles startup reads; the MCP server handles runtime reads and all writes.

## Prerequisites

1. **MemoryHub CLI** (v0.8.0+): `pip install memoryhub-cli>=0.8.0`
2. **API key**: Obtain from your MemoryHub administrator. Format: `mh-dev-<hex>`.
3. **Server URL**: The MemoryHub MCP server endpoint.
4. **Some memories written**: The hook searches existing memories. If the project has no memories yet, the hook produces no output (and that's fine).

## Setup

### 1. Store credentials

The CLI resolves credentials from environment variables first, then config files. For hooks (which run non-interactively), the config file approach is most reliable.

```bash
# Create the config directory
mkdir -p ~/.config/memoryhub

# Store your API key and server URL (mode 0600 -- never commit this)
cat > ~/.config/memoryhub/credentials << 'EOF'
[default]
api_key = mh-dev-your-key-here
url = https://your-memoryhub-server.example.com/mcp/
EOF
chmod 600 ~/.config/memoryhub/credentials
```

Alternatively, set `MEMORYHUB_API_KEY` and `MEMORYHUB_URL` environment variables in your shell profile. The legacy flat file `~/.config/memoryhub/api-key` is still supported as a fallback.

### 2. Initialize project configuration

Run the interactive wizard from your project root:

```bash
memoryhub config init
```

This creates two files:

- `.memoryhub.yaml` -- project-level configuration (loading pattern, campaigns, retrieval defaults)
- `.claude/rules/memoryhub-loading.md` -- agent instructions telling the model how to use MemoryHub during the session

Both files should be committed to your repository so that all collaborators get the same behavior.

The wizard asks about session shape (focused/broad/adaptive), loading pattern, and optional campaign enrollment. For most projects, the defaults (focused mode, lazy loading) work well.

### 3. Create the hook script

Create `.claude/hooks/load-memories.sh` in your project:

```bash
#!/bin/bash
# Inject MemoryHub memories at Claude Code session start.
# Stdout is added to the conversation context before the first prompt.
# Exits 0 silently on any failure -- the session starts normally and
# the MCP server remains available as a fallback.

set -euo pipefail

API_KEY_FILE="$HOME/.config/memoryhub/api-key"
[ -f "$API_KEY_FILE" ] || exit 0

API_KEY=$(tr -d '\n' < "$API_KEY_FILE")
[ -n "$API_KEY" ] || exit 0
export MEMORYHUB_API_KEY="$API_KEY"

# Resolve server URL from env var or config file
if [ -z "${MEMORYHUB_URL:-}" ]; then
  CONFIG_FILE="$HOME/.config/memoryhub/config.json"
  if [ -f "$CONFIG_FILE" ]; then
    MEMORYHUB_URL=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('url',''))" "$CONFIG_FILE" 2>/dev/null) || true
  fi
fi
[ -n "${MEMORYHUB_URL:-}" ] || exit 0
export MEMORYHUB_URL

# Find memoryhub CLI: project venv, then system PATH
MEMORYHUB_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.venv/bin/memoryhub"
if ! [ -x "$MEMORYHUB_BIN" ]; then
  MEMORYHUB_BIN=$(command -v memoryhub 2>/dev/null) || exit 0
fi

PROJECT_ID=$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")

"$MEMORYHUB_BIN" search \
  "project context architecture preferences decisions workflow" \
  --project-id "$PROJECT_ID" \
  --output compact \
  --max 20 2>/dev/null || exit 0
```

Make it executable:

```bash
chmod +x .claude/hooks/load-memories.sh
```

**Customizing the search query**: The hardcoded query `"project context architecture preferences decisions workflow"` is a broad sweep that works for most sessions. If your project has a narrow focus, you can replace it with more specific terms.

**Customizing the CLI path**: The script looks for `memoryhub` in your project's `.venv/bin/` first, then falls back to the system PATH. Adjust the `MEMORYHUB_BIN` line if you install the CLI elsewhere.

### 4. Configure the hook in Claude Code settings

Add the hook to your project's `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/load-memories.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Key choices:

- **`matcher: "startup"`**: Only runs on new sessions, not on resume or context compaction. This avoids re-injecting memories that are already in the transcript.
- **`timeout: 5`**: Five seconds is generous. A typical search completes in under 2 seconds. If the server is unreachable, the script fails silently within the timeout.

### 5. Update the generated rule file

The rule file generated by `memoryhub config init` instructs the agent to call `register_session` and `search_memory` at session start. With the hook in place, this is redundant for startup -- the hook pre-loads memories. Update the "At session start" section in `.claude/rules/memoryhub-loading.md`:

Replace the existing session-start block with:

```markdown
## At session start

Check for a `<memoryhub-context>` block in your conversation context.
If present, the SessionStart hook has pre-loaded project and user
memories -- use them as your working set. Do NOT call `register_session`
or `search_memory` yet.

If no `<memoryhub-context>` block is present (hook not configured or
failed silently), fall back to the manual flow: read your API key from
`~/.config/memoryhub/credentials` (INI file, section matching
`MEMORYHUB_CONTEXT` or `[default]`), call
`register_session(api_key="<key>")`, then after the first user turn
derive a 1-2 sentence summary and call `search_memory(query=<summary>)`.
```

This preserves the fallback path so sessions still work if the hook fails or the CLI isn't installed.

### 6. Test it

Start a new Claude Code session in your project directory. You should see the `<memoryhub-context>` block in the conversation context. You can verify by asking the agent: "What MemoryHub memories were loaded at startup?"

If nothing appears, check:

1. **Is the script executable?** `ls -la .claude/hooks/load-memories.sh`
2. **Does the CLI work standalone?** Run the search command manually:
   ```bash
   memoryhub search "project context" --project-id my-project --output compact --max 5
   ```
3. **Is the hook configured?** Check `.claude/settings.json` has the `SessionStart` block.
4. **Are there any memories?** If the project has no memories yet, the hook produces no output. Write a few memories first via the MCP server, then restart the session.

## What to commit

Commit these files to your repository:

- `.memoryhub.yaml` -- project configuration
- `.claude/rules/memoryhub-loading.md` -- agent instructions
- `.claude/hooks/load-memories.sh` -- hook script
- `.claude/settings.json` -- hook configuration (merge with existing settings)

Do NOT commit:

- `~/.config/memoryhub/credentials` -- per-operator API keys and server URLs
- `~/.config/memoryhub/config.json` -- per-operator OAuth/connection config

## Design rationale

**Why a CLI hook instead of an MCP tool hook?** MCP tool hooks on SessionStart typically fire before servers finish connecting. A shell command calling the CLI is reliable and doesn't depend on the MCP server lifecycle.

**Why content-only output?** Structural metadata (weights, scopes, timestamps) in the context window activates model reasoning about memory management instead of the user's task. Smaller models are especially sensitive to this. The compact format strips everything except the content.

**Why graceful degradation?** The hook exits 0 on every failure path. A missing CLI, unreachable server, or expired API key should never block a session from starting. The MCP server remains available as a fallback.

**Why `startup` matcher only?** On `resume`, the previous memories are already in the transcript. Re-injecting would waste context. On `clear` or `compact`, the user is explicitly managing context and injecting memories would interfere.

## Relationship to MCP server

The hook and MCP server serve complementary roles:

| Concern | Hook (startup) | MCP server (runtime) |
|---------|----------------|----------------------|
| Read memories | Yes (pre-loaded) | Yes (on-demand search) |
| Write memories | No | Yes |
| Update/delete | No | Yes |
| Contradiction reporting | No | Yes |
| Token cost | Zero (plain text) | Per-call (tool I/O) |
| Authentication | API key via credentials file | API key via `register_session` |

The agent should defer `register_session` until the first time it needs to search (topic pivot) or write. If the hook succeeded, no MCP calls are needed until then.

## Troubleshooting

**Hook produces no output**: Run the search command manually (see step 6). Check that the project has memories and the API key / server URL are correct.

**Hook times out**: The default timeout is 5 seconds. If your server is slow, increase the timeout in `.claude/settings.json`. If Python startup is the bottleneck (~0.5s on cold start), ensure the CLI is installed in a venv local to the project rather than a global install.

**Memories appear but agent ignores them**: Check that `.claude/rules/memoryhub-loading.md` has the hook-aware session-start block that references `<memoryhub-context>`. Without this instruction, the agent may not know to look for pre-loaded memories.

**Duplicate memory loading**: If the agent calls `register_session` and `search_memory` at startup despite the hook succeeding, the rule file's session-start block likely still has the old instructions. Update it per step 5.
