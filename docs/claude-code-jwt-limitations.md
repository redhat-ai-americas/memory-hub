# Claude Code JWT / MCP HTTP Transport Limitations

Last updated: 2026-04-05

## Problem Statement

Claude Code's MCP HTTP transport **forces OAuth 2.0 Dynamic Client Registration** even when explicit `Authorization: Bearer <JWT>` headers are configured. Instead of sending configured headers, Claude Code issues discovery requests to `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`, then attempts client registration — bypassing any statically configured Bearer token.

This directly affects MemoryHub because our auth service (`memoryhub-auth/`) issues JWTs via `client_credentials` grant, not OAuth Dynamic Client Registration. Claude Code's forced discovery *will* hit our well-known endpoints, but the registration flow it attempts is incompatible with our grant type.

## Upstream Issues

### Currently Open

| Issue | Title | Filed | Notes |
|:------|:------|:------|:------|
| [#33817](https://github.com/anthropics/claude-code/issues/33817) | MCP Server Authorization Header Not Recognized, Falls Back to OAuth | 2026-03-13 | Regression in v2.1.74 |
| [#39271](https://github.com/anthropics/claude-code/issues/39271) | HTTP MCP server with Bearer token shows "needs-auth" in `claude -p` | 2026-03-26 | Regression between v2.1.81 and v2.1.83; tagged regression |
| [#34008](https://github.com/anthropics/claude-code/issues/34008) | No way to disable OAuth discovery (`skipOAuthDiscovery` requested) | 2026-03-13 | Feature request |
| [#34690](https://github.com/anthropics/claude-code/issues/34690) | Egress proxy JWT ignores "All domains" org setting | 2026-03-15 | Blocks WebFetch to private infra |

### Closed (Unresolved or Duplicate)

| Issue | Title | Filed | Notes |
|:------|:------|:------|:------|
| [#7290](https://github.com/anthropics/claude-code/issues/7290) | HTTP/SSE MCP Transport Ignores Authentication Headers | 2025-09-08 | Foundational report; auto-closed by bot despite being unresolved |
| [#29562](https://github.com/anthropics/claude-code/issues/29562) | Custom headers not sent during MCP session establishment | 2026-02-28 | Confirmed via server-side logs |
| [#35878](https://github.com/anthropics/claude-code/issues/35878) | HTTP/SSE MCP fails for non-OAuth servers (Jenkins) | 2026-03-18 | Closed as duplicate |
| [#38972](https://github.com/anthropics/claude-code/issues/38972) | Static Bearer token shown as "needs authentication" | 2026-03-25 | Closed as duplicate |

## Workarounds

### 1. Dummy X-API-Key Header (Quick Fix)

Per [#7290 comments](https://github.com/anthropics/claude-code/issues/7290), adding a dummy `X-API-Key` header alongside `Authorization` can trick Claude Code into skipping the OAuth flow and sending all configured headers.

```json
{
  "mcpServers": {
    "memoryhub": {
      "type": "http",
      "url": "https://memoryhub.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <jwt>",
        "X-API-Key": "unused-but-required"
      }
    }
  }
}
```

**Tradeoffs**: Fragile — depends on an undocumented code path that may break in future versions. The MCP server must tolerate the extra header.

### 2. stdio Proxy via mcp-remote (Recommended)

Wrap the HTTP MCP server with a local stdio process that handles auth, then configure Claude Code to connect via stdio transport. This sidesteps the OAuth enforcement entirely.

```json
{
  "mcpServers": {
    "memoryhub": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://memoryhub.example.com/mcp",
        "--header", "Authorization: Bearer <jwt>"
      ]
    }
  }
}
```

**Tradeoffs**: Adds a Node.js dependency. Requires `mcp-remote` to be available. Adds a process layer between Claude Code and the MCP server. But this is the most reliable approach because Claude Code treats it as a stdio server and never triggers OAuth.

### 3. curl via Bash Tool (One-Off Requests)

For one-off authenticated HTTP requests (e.g., token acquisition), use `curl` through the Bash tool instead of WebFetch:

```bash
curl -s -X POST https://auth.example.com/token \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET"
```

**Tradeoffs**: Not viable for MCP tool invocation — only useful for manual HTTP calls during a session.

### 4. Pin to Known-Working Version

For [#39271](https://github.com/anthropics/claude-code/issues/39271) specifically, v2.1.81 was the last version where Bearer token auth worked in `claude -p` (headless) mode.

**Tradeoffs**: Gives up all subsequent fixes and features. Not a long-term solution.

### 5. register_session Shim (Current MemoryHub Approach)

MemoryHub retains its `register_session(api_key=...)` tool as a compatibility shim. Agents authenticate by calling this tool at session start, avoiding the need for HTTP-level JWT auth entirely. The API key is passed as a tool argument, not an HTTP header.

**Tradeoffs**: Auth is at the application layer, not the transport layer. Does not provide the security properties of JWT (short-lived tokens, cryptographic verification, claims-based RBAC). Adequate for dev/demo but insufficient for production multi-tenant deployment.

## Impact on MemoryHub Auth Strategy

The `register_session` API-key shim remains necessary as a fallback until Claude Code resolves the upstream issues. Our auth roadmap:

1. **Now**: `register_session` shim for Claude Code; JWT auth for SDK and non-Claude agents
2. **When upstream fixes land**: Migrate Claude Code connections to JWT Bearer auth via MCP HTTP transport headers
3. **Production**: Full OAuth 2.1 with `client_credentials` grant, JWT verification at the transport layer

## Plugin Feasibility Assessment

We evaluated whether a Claude Code plugin could solve this long-term. See the analysis below.

### What Plugins Can Do

- Ship MCP servers (stdio only — declared in plugin `.mcp.json`)
- Add executables to the Bash tool's PATH (via `bin/`)
- Intercept tool calls via `PreToolUse` / `PostToolUse` hooks
- Inject environment variables via `SessionStart` hooks

### What Plugins Cannot Do

- Intercept or modify MCP HTTP transport connections (no hook event for this)
- Inject HTTP headers into outgoing MCP requests
- Disable or bypass OAuth discovery

### Viable Plugin Architecture: stdio Proxy

The only plugin approach that works is **Option B from the workarounds** — packaging the stdio proxy pattern as a plugin:

```
memoryhub-claude-plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json              # Declares memoryhub as stdio server via proxy
├── bin/
│   └── memoryhub-mcp-proxy  # Shell script wrapping mcp-remote or custom proxy
├── skills/
│   └── memoryhub-auth/
│       └── SKILL.md       # Skill to acquire/refresh JWT and configure proxy
└── hooks/
    └── hooks.json         # SessionStart hook to set up auth env vars
```

The plugin would:
1. On `SessionStart`, run a hook that acquires a JWT via `client_credentials` grant
2. Declare the MCP server as a stdio command that proxies to the real HTTP endpoint with the JWT injected
3. Provide a skill for manual token refresh if needed

This avoids the OAuth enforcement because Claude Code sees a stdio server, not an HTTP one. The proxy handles JWT injection transparently.

### Recommendation

A plugin is worth building **after** we validate the stdio proxy pattern manually (Workaround #2). If the upstream issues get fixed first, a plugin becomes unnecessary. Monitor [#33817](https://github.com/anthropics/claude-code/issues/33817) and [#39271](https://github.com/anthropics/claude-code/issues/39271) for resolution.
