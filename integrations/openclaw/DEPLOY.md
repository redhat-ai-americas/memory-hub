# Deploying the MemoryHub Plugin for OpenClaw

## Prerequisites

- A running OpenClaw instance
- A running MemoryHub MCP server with a user entry configured in `users-configmap.yaml`
- The user's MemoryHub API key
- Node.js and npm installed on the OpenClaw host

## Install

From the OpenClaw installation directory:

```bash
npm install @memory-hub/openclaw-mh-plugin
```

## Configure

Add the plugin to your OpenClaw config file (`openclaw.json`):

```json
{
  "plugins": {
    "entries": {
      "openclaw-memoryhub": {
        "enabled": true,
        "package": "@memory-hub/openclaw-mh-plugin",
        "config": {
          "server": {
            "url": "https://<your-memoryhub-mcp-server>/mcp/"
          },
          "auth": {
            "apiKey": "${MEMORYHUB_API_KEY}"
          },
          "defaults": {
            "scope": "user"
          }
        }
      }
    },
    "slots": {
      "memory": "openclaw-memoryhub"
    }
  }
}
```

### Configuration options

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `server.url` | yes | — | MemoryHub MCP server endpoint URL |
| `auth.apiKey` | yes | — | API key from `users-configmap.yaml`. Use `${MEMORYHUB_API_KEY}` to read from environment. |
| `defaults.scope` | no | `user` | Default scope for memory writes: `user`, `project`, `organizational`, `enterprise` |
| `defaults.projectId` | no | — | Default project ID for project-scoped operations |
| `defaults.domains` | no | `[]` | Domain labels for writes and search boosting |
| `autoRecall.enabled` | no | `true` | Inject relevant memories before each agent turn |
| `autoRecall.maxResults` | no | `10` | Maximum memories returned per auto-recall |
| `autoRecall.maxResponseTokens` | no | `4000` | Token budget for auto-recalled content |
| `autoCapture.enabled` | no | `false` | Auto-capture after each turn (stub in V1) |

### Environment variable

Set the API key in the environment before starting OpenClaw:

```bash
export MEMORYHUB_API_KEY="<your-api-key>"
```

## Assign the memory slot

The `slots.memory` entry tells OpenClaw to use MemoryHub as the active memory provider. Only one memory plugin can occupy this slot. Setting it to `"openclaw-memoryhub"` replaces the default `memory-core` provider.

## Restart

Restart the OpenClaw gateway to pick up the new plugin:

```bash
openclaw gateway restart
```

## Verify

After restart, check the gateway logs for:

```
memoryhub: loaded memory protocol for system context
memoryhub: initialized (server: https://...)
memoryhub: session registered for <name> (<user_id>)
```

If the API key or server URL is missing, you will see:

```
memoryhub: missing server.url or auth.apiKey — plugin disabled.
```

## Update

To update to a newer version:

```bash
npm update @memory-hub/openclaw-mh-plugin
openclaw gateway restart
```

## Alternative: install from tarball

If npm registry access is not available, build and transfer the plugin manually.

From the plugin source repo root:

```bash
cd integrations/openclaw
npm run build
npm test
cd ../..
tar czf openclaw-memoryhub.tar.gz \
  --exclude='integrations/openclaw/node_modules' \
  integrations/openclaw
```

Transfer the tarball to the OpenClaw host, then:

```bash
tar xzf openclaw-memoryhub.tar.gz
cd integrations/openclaw
npm install --omit=dev
```

Update `openclaw.json` to point to the local path instead of the package name:

```json
"openclaw-memoryhub": {
  "enabled": true,
  "path": "./integrations/openclaw",
  "config": { ... }
}
```
