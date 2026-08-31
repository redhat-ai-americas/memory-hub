# MemoryHub plugin for opencode

Governed, versioned, graph-aware agent memory for [opencode](https://opencode.ai)
(the SST terminal coding agent), backed by a deployed
[MemoryHub](https://github.com/redhat-ai-americas/memory-hub) MCP server.

What it does:

- **Six memory tools** the agent can call: `memoryhub_search`, `memoryhub_read`,
  `memoryhub_list`, `memoryhub_write`, `memoryhub_update`, `memoryhub_delete`.
- **Auto-recall**: on every user message, semantically relevant memories are
  retrieved and injected into the request as a `<relevant-memories>` block
  (with an untrusted-data guard). Failures never break the turn.
- **Memory protocol**: `memoryhub-rules.md` is appended to the system prompt so
  the agent knows when to read, write, and update memories.
- **Host-side auth**: the plugin calls MemoryHub's `register_session` itself —
  your API key never enters the model's context. Expired sessions are
  re-registered transparently.

## Install

The package is not on npm yet, so install from a checkout of this repo.
In the project where you want memory:

```bash
mkdir -p .opencode/plugins

cat > .opencode/package.json <<'EOF'
{
  "dependencies": {
    "@memory-hub/opencode-mh-plugin": "file:/path/to/memory-hub/integrations/opencode"
  }
}
EOF

echo 'export { MemoryHubPlugin } from "@memory-hub/opencode-mh-plugin";' \
  > .opencode/plugins/memoryhub.ts
```

Build the plugin once in the checkout (`npm install && npm run build` in
`integrations/opencode/`). opencode's Bun runtime installs the dependency
automatically on next start. Put the same two files under
`~/.config/opencode/` instead to enable it globally.

Once published to npm this collapses to:

```bash
opencode plugin @memory-hub/opencode-mh-plugin
```

or `"plugin": ["@memory-hub/opencode-mh-plugin"]` in `opencode.json`.

## Configure

Configuration is resolved in this order (first hit wins, per value):

1. **Plugin options in `opencode.json`**:

   ```json
   {
     "plugin": [
       ["@memory-hub/opencode-mh-plugin", {
         "server": { "url": "https://<memoryhub-host>/mcp/" },
         "auth": { "apiKey": "mh-dev-..." },
         "autoRecall": { "enabled": true, "maxResults": 10, "maxResponseTokens": 4000 },
         "defaults": { "scope": "user", "projectId": "my-project", "domains": [] }
       }]
     ]
   }
   ```

   Avoid committing the API key — prefer the env var or credentials file below
   and keep only `server`/`defaults` in the JSON.

2. **Environment variables**: `MEMORYHUB_URL`, `MEMORYHUB_API_KEY`
   (and optionally `MEMORYHUB_CONTEXT` to pick a credentials section).

3. **`~/.config/memoryhub/credentials`** (same INI file the MemoryHub CLI and
   Claude Code hook use):

   ```ini
   [default]
   url = https://<memoryhub-host>/mcp/
   api_key = mh-dev-...
   ```

4. **`~/.config/memoryhub/api-key`** (flat file, API key only, backwards compat).

If no URL or API key is found the plugin logs a warning and stays inert —
opencode works normally without it.

Set `MEMORYHUB_DEBUG=1` for verbose logging in the opencode server log.

## How it hooks into opencode

| opencode hook | Role |
|---|---|
| `tool` | Registers the six `memoryhub_*` tools |
| `chat.message` | Runs the auto-recall search for the new user message (15s cap) |
| `experimental.chat.messages.transform` | Injects the recalled `<relevant-memories>` block into the latest user message (idempotent, marker-guarded) |
| `experimental.chat.system.transform` | Appends `memoryhub-rules.md` to the system prompt |
| `dispose` | Closes the MCP connection |

All MemoryHub traffic flows through the server's MCP interface
(`register_session` + the multiplexed `memory(action=...)` tool) over
streamable HTTP — the same governed path every other MemoryHub surface uses.

## Not yet implemented

- **Auto-capture** (writing memories automatically from conversation content).
  The MemoryHub way to do this is appending to a conversation thread and
  letting server-side dreaming extract facts — planned, not in V1.
- OAuth 2.1 auth (API keys only for now).
- Compaction-time memory re-injection and error-driven prefetch.

## Development

```bash
npm install
npm test          # vitest, 61 tests
npm run typecheck
npm run build     # tsup -> dist/
```

For a local (unpublished) install, build and point a project at it:

```bash
npm run build
mkdir -p ~/.config/opencode/plugins
cat > ~/.config/opencode/plugins/memoryhub.ts <<'EOF'
export { MemoryHubPlugin } from "/path/to/memory-hub/integrations/opencode/src/index.ts";
EOF
```

(opencode loads plugin files with Bun, so re-exporting the TypeScript source
directly also works.)
