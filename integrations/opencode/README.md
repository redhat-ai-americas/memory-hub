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

The plugin is published on npm as
[`@memory-hub/opencode-mh-plugin`](https://www.npmjs.com/package/@memory-hub/opencode-mh-plugin).
In the project where you want memory:

```bash
opencode plugin @memory-hub/opencode-mh-plugin
```

This installs the package and adds it to your opencode config. Equivalently,
add it to `opencode.json` by hand — opencode's Bun runtime installs it
automatically on next start:

```json
{
  "plugin": ["@memory-hub/opencode-mh-plugin"]
}
```

Put the same entry in `~/.config/opencode/opencode.json` to enable the plugin
globally. Then [configure](#configure) the server URL and API key.

### Install from source (development)

To run an unreleased checkout, point a project at the local package instead:

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
`integrations/opencode/`).

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

## Verify

Start opencode with `MEMORYHUB_DEBUG=1` and check the server log for
`memoryhub: initialized` followed by `memoryhub: session registered for …`
on the first message. Then ask the agent something only memory would know,
or tell it to "search your memory for …" and watch `memoryhub_search` run.
If the plugin logs `missing server URL or API key`, see
[Configure](#configure).

## Update

opencode caches npm plugins by dist-tag (observed on 1.17.9:
`~/.cache/opencode/packages/@memory-hub/opencode-mh-plugin@latest/`), so a
new release is **not** picked up automatically. To upgrade, remove
`~/.cache/opencode/packages/@memory-hub` and restart opencode.

## Not yet implemented

- **Auto-capture.** Today a memory is saved only when the agent decides to
  call `memoryhub_write` (the injected memory protocol tells it when).
  Automatic post-turn capture is planned as an opt-in feature that reuses
  MemoryHub's shared `memoryhub extract` pipeline — tracked in
  [#585](https://github.com/redhat-ai-americas/memory-hub/issues/585).
- OAuth 2.1 auth (API keys only for now).
- Compaction-time memory re-injection and error-driven prefetch — ideas
  from other memory plugins, not on the MemoryHub roadmap yet.

## Development

```bash
npm install
npm test          # vitest
npm run typecheck
npm run build     # tsup -> dist/
```

See [Install from source](#install-from-source-development) to run a
checkout inside a real opencode project. Design notes live in
[`docs/design/agent-host-integrations.md`](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/design/agent-host-integrations.md).
