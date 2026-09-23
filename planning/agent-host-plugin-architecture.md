# Shared Plugin Package for MemoryHub Integrations

**Date:** 2026-09-23
**Issue:** #581 (`subsystem: client`)
**Subsystem:** `client` — restructures existing `integrations/*` packages
**Related:** #310 (instruction file generation - separate concern), OpenClaw (merged), OpenCode (PR #549)

---

## 1. Problem

MemoryHub has no single source of truth for integration artifacts. Every plugin—whether TypeScript runtime (OpenClaw, OpenCode) or config-based (Claude Code, Codex)—duplicates the same content and patterns.

### 1.1 Evidence of Duplication Across ALL Plugin Types

**Protocol content (behavioral instructions):**
- OpenClaw ships `integrations/openclaw/memoryhub-rules.md` (133 lines)
- OpenCode ships `integrations/opencode/memoryhub-rules.md` (133 lines, **byte-identical**)
- Claude Code ships `.claude/rules/memoryhub-loading.md` (manually maintained, drifted content)
- Each new config-based plugin (Codex, Hermes, etc.) would duplicate the same pattern

**Tool contracts:**
- OpenClaw defines 6 tools in `tools.ts` with typebox schemas (339 lines)
- OpenCode defines same 6 tools in `tools.ts` with zod schemas (240 lines)
- Future TS plugins (Hermes Python) would redefine same contracts

**Config schema:**
- OpenClaw defines in `openclaw.plugin.json` `configSchema` (lines 74-120)
- OpenCode defines in `config.ts` validation (230 lines)
- Different validation rules, different defaults, drift risk

### 1.2 Evidence of Behavioral Drift (TypeScript Plugins)

Even when duplicating the *same* logic, OpenClaw and OpenCode have diverged:

| Module | OpenClaw | OpenCode | Divergence |
|--------|----------|----------|------------|
| `mcp-client.ts` connect | Creates transport on every call | Single-flight (`connectPromise`) | OpenClaw can open duplicate connections |
| `mcp-client.ts` resetSession | Sets `apiKey=null`, `connected=false` | Also closes stale transport | OpenClaw leaks client object |
| Session recovery | Retry on `"memory_expired"` (never returned by server) | Retry on real tokens, generation-guarded | OpenClaw retry is **dead code** |
| Recall timeout | `Promise.race` with timer never cleared | Clears timer in `finally` | OpenClaw leaks timer per turn |
| Config precedence | One source + env | Four tiers with defined precedence | Different resolution semantics |

### 1.3 Concrete Costs

**For TypeScript runtime plugins:**
- OpenClaw has 3 known bugs fixed in OpenCode (dead retry, timer leak, stale connection)
- Each plugin is ~1,045 lines to maintain
- Fixes land unevenly, manual backporting required

**For config-based plugins:**
- Claude Code integration is manual (user creates files)
- No shared hook scripts, each plugin rewrites credential resolution
- Future plugins (Codex, Hermes) would duplicate the same pattern

**Root cause:** No shared package providing:
1. Canonical protocol content
2. TypeScript MCP client wrapper for runtime plugins
3. Templates for config-based plugins
4. Tool contracts and config schema

**Wire protocol:** Both OpenClaw and OpenCode send identical MCP requests (`callTool("memory", {action, query, scope, project_id, options})`). The shared package extracts client-side logic only; no protocol changes.

---

## 2. Solution

Extract shared MemoryHub integration artifacts into one package that any plugin can use.

**Plugin types:**
- **TypeScript runtime plugins** (OpenClaw, OpenCode): Register tools directly in the agent host's runtime, wrap MCP client
- **Config-based plugins** (Claude Code, Codex, Hermes): Connect to MemoryHub MCP server via config, discover tools via handshake

```
integrations/common/
├── protocol.md                    # Behavioral instructions
├── tool-contracts.json            # 6 tools: signatures + MCP mapping
├── config-schema.json             # Valid config fields + validation
├── templates/
│   ├── .mcp.json.template        # MCP server config for Claude Code
│   ├── session-start.sh          # Hook script template
│   ├── recall.sh                 # Hook script template
│   └── capture.sh                # Hook script template
├── docs/
│   └── credential-resolution.md  # Standard credential lookup pattern
├── src/
│   ├── client.ts                 # TypeScript MCP client (for TS plugins)
│   ├── session.ts
│   ├── tools.ts
│   └── recall.ts
└── package.json                   # Package: @memory-hub/common
```

---

## 3. What Gets Shared

### 3.1 Protocol Content (protocol.md)

Canonical behavioral instructions: when to search, how to write, DURABLE/NOVEL/CONCRETE/SAFE gates, hygiene rules.

**How each plugin type uses it:**

| Plugin Type | Usage |
|-------------|-------|
| **Claude Code** (config plugin) | Ships as `.claude/rules/memoryhub-loading.md` → Claude reads as permanent rule |
| **Codex** (config plugin) | Ships as `.codex/rules/memoryhub-loading.md` → Codex reads as permanent rule |
| **OpenClaw** (TS runtime) | `import { PROTOCOL_CONTENT } from '@memory-hub/common'` → `api.prependSystemContext(PROTOCOL_CONTENT)` |
| **OpenCode** (TS runtime) | `import { PROTOCOL_CONTENT } from '@memory-hub/common'` → inject via `systemTransform` hook |
| **Hermes** (config plugin) | Ships as plugin hook file → plugin injects via `pre_llm_call` hook |
| **#310 adapters** | Reads `integrations/common/protocol.md` → writes to `.goosehints` / `AGENTS.md` / etc. |

### 3.2 Tool Contracts (tool-contracts.json)

Signature for 6 tools: `memoryhub_search`, `memoryhub_read`, `memoryhub_list`, `memoryhub_write`, `memoryhub_update`, `memoryhub_delete`.

**How each plugin type uses it:**

| Plugin Type | Usage |
|-------------|-------|
| **Claude Code** (config plugin) | ❌ NOT USED - tools come via MCP server, Claude discovers via `tools/list` |
| **Codex** (config plugin) | ❌ NOT USED - tools come via MCP server, Codex discovers via `tools/list` |
| **OpenClaw** (TS runtime) | `import { TOOL_CONTRACTS } from '@memory-hub/common'` → generate typebox schemas → `api.registerTool()` |
| **OpenCode** (TS runtime) | `import { TOOL_CONTRACTS } from '@memory-hub/common'` → generate zod schemas → return from `buildTools()` |
| **Hermes** (config plugin) | ❌ NOT USED - connects to MCP server, discovers tools via handshake |
| **#310 adapters** | ❌ NOT USED - artifact hosts get tools via MCP |

**Example contract:**
```json
{
  "name": "memoryhub_search",
  "description": "Search through long-term memories...",
  "parameters": [
    { "name": "query", "type": "string", "required": true },
    { "name": "limit", "type": "integer", "min": 1, "max": 50, "default": 10 },
    { "name": "scope", "type": "string", "enum": ["user", "project", ...] },
    { "name": "domains", "type": "array", "items": "string" },
    { "name": "content_type", "type": "string", "enum": ["factual", "behavioral", "all"] }
  ],
  "mcpMapping": {
    "action": "search",
    "topLevel": ["query"],
    "options": ["max_results", "domains", "content_type", "project_id", "focus", "max_response_tokens"]
  }
}
```

### 3.3 Config Schema (config-schema.json)

Validation rules for MemoryHub configuration.

**How each plugin type uses it:**

| Plugin Type | Usage |
|-------------|-------|
| **Claude Code** (config plugin) | ❌ NOT USED - config from env vars/INI, no plugin validation |
| **Codex** (config plugin) | ❌ NOT USED - config from env vars/config.toml, no plugin validation |
| **OpenClaw** (TS runtime) | `import { validateConfig } from '@memory-hub/common'` → validate `openclaw.json` section → throw on invalid |
| **OpenCode** (TS runtime) | `import { validateConfig } from '@memory-hub/common'` → validate `opencode.json` options → merge with env/INI |
| **Hermes** (config plugin) | ⚠️ Minimal - validates MCP server config (command, args, env), not plugin-specific fields |
| **#310 adapters** | Validates user input during `memoryhub config init --framework <name>` prompts |

**Schema:**
```json
{
  "server": { "url": "string (required)", "transport": "enum" },
  "auth": { "mode": "enum", "apiKey": "string (sensitive)" },
  "autoRecall": {
    "enabled": "boolean (default: true)",
    "maxResults": "integer (1-50, default: 10)",
    "maxResponseTokens": "integer (default: 4000)",
    "useFocus": "boolean (default: true)"
  },
  "autoCapture": {
    "enabled": "boolean (default: false)",
    "defaultScope": "string (default: user)",
    "defaultWeight": "number (0-1, default: 0.7)"
  },
  "defaults": {
    "scope": "string",
    "projectId": "string",
    "domains": "array<string>"
  }
}
```

### 3.4 MCP Connection Templates (templates/)

For config-based plugins (Claude Code, Codex).

**templates/.mcp.json:**
```json
{
  "mcpServers": {
    "memoryhub": {
      "command": "memoryhub",
      "args": ["mcp"],
      "env": {
        "MEMORYHUB_API_KEY": "${MEMORYHUB_API_KEY}"
      }
    }
  }
}
```

**templates/config.toml** (Codex alternative):
```toml
[mcp.servers.memoryhub]
command = "memoryhub"
args = ["mcp"]
env = { MEMORYHUB_API_KEY = "${MEMORYHUB_API_KEY}" }
```

**templates/config.yaml** (Hermes alternative):
```yaml
mcp_servers:
  memoryhub:
    command: "memoryhub"
    args: ["mcp"]
    env:
      MEMORYHUB_API_KEY: "${MEMORYHUB_API_KEY}"
```

**templates/hooks/session-start.sh:**
```bash
#!/bin/bash
# SessionStart hook - loads memories via CLI
# Works for both Claude Code and Codex (same event names)
memoryhub session register
memoryhub recall --output json
```

**How used:**
- **Claude Code plugin**: Ships `.mcp.json` + hook scripts in plugin bundle
- **Codex plugin**: Ships `config.toml` (or `.mcp.json`) + hook scripts in plugin bundle
- **Hermes plugin**: Ships `config.yaml` section + `pre_llm_call` hook to inject protocol
- **#310 adapters**: Reads templates → substitutes variables → writes to project

### 3.5 TypeScript MCP Client Wrapper (src/)

For TypeScript runtime plugins only (OpenClaw, OpenCode). This is the **MCP client wrapper**, not a high-level SDK — it handles MCP transport, session management, and tool calls.

**src/client.ts:**
```typescript
export class MemoryHubClient {
  constructor(config: MemoryHubConfig);
  async connect(): Promise<void>;           // single-flight
  async registerSession(apiKey: string): Promise<Session>;
  resetSession(): void;                     // closes stale transport
  async callMemory(action: string, params: Record<string, unknown>): Promise<unknown>;
  isConnected(): boolean;
}
```

**src/session.ts:**
```typescript
export class SessionManager {
  async withSession<T>(fn: () => Promise<T>): Promise<T>;  // generation-guarded recovery
}
```

**src/recall.ts:**
```typescript
export class RecallEngine {
  async search(query: string): Promise<string>;  // timeout, untrusted framing
  formatMemoriesXml(memories: Memory[]): string;
}
```

**src/config.ts:**
```typescript
export function resolveConfig(
  options?: Record<string, unknown>,
  env?: ConfigEnv
): MemoryHubConfig;  // Four-tier precedence: plugin > env > INI > flat file
export function validateConfig(config: MemoryHubConfig): void;  // Throws on invalid
```

**Config resolution precedence:**
1. Plugin options (from `openclaw.json` / `opencode.json`)
2. Environment variables (`MEMORYHUB_URL`, `MEMORYHUB_API_KEY`)
3. INI file (`~/.config/memoryhub/credentials`, section from `MEMORYHUB_CONTEXT`)
4. Flat file (`~/.config/memoryhub/api-key`, backward compat)

Per-field: first non-empty value wins. This matches CLI/SDK credential resolution.

**Migration impact for OpenClaw:**
- ✅ **Additive breaking change** — OpenClaw 2.0.0 gains env var support
- ✅ Backward compatible — plugin config still takes precedence
- ⚠️ Users with `MEMORYHUB_URL` env var set for other tools will now see it used
- 📝 Document in migration guide as new feature

**How used:**
- **OpenClaw** (TS runtime): `import { MemoryHubClient, RecallEngine, TOOL_CONTRACTS } from '@memory-hub/common'` → use directly
- **OpenCode** (TS runtime): Same imports → use directly
- **Claude Code** (config plugin): ❌ NOT USED - connects to MCP server, no TypeScript runtime
- **Codex** (config plugin): ❌ NOT USED - connects to MCP server, no TypeScript runtime
- **Hermes** (config plugin): ❌ NOT USED - connects to MCP server, uses Python SDK if needed

---

## 4. Plugin Architecture After Migration

### 4.1 TypeScript Runtime Plugins (OpenClaw, OpenCode)

**Before (OpenClaw):**
```
integrations/openclaw/
├── src/
│   ├── index.ts           154 lines  - Entry, registration
│   ├── mcp-client.ts      156 lines  - MCP client
│   ├── tools.ts           339 lines  - Tool definitions
│   ├── hooks.ts           144 lines  - Auto-recall
│   ├── config.ts          121 lines  - Config parsing
│   └── openclaw-plugin-sdk.d.ts  131 lines
├── memoryhub-rules.md     133 lines
└── openclaw.plugin.json   127 lines
Total: ~1,045 lines
```

**After (OpenClaw):**
```
integrations/openclaw/
├── src/
│   └── index.ts           ~150 lines  - Thin adapter
├── package.json           (adds @memory-hub/common dependency)
└── openclaw.plugin.json
Total: ~150 lines (85% reduction)
```

**What the thin adapter does:**
```typescript
import { MemoryHubClient, RecallEngine, TOOL_CONTRACTS, PROTOCOL_CONTENT } 
  from '@memory-hub/common';
import { Type } from '@sinclair/typebox'; // OpenClaw-specific
import { definePluginEntry } from 'openclaw/plugin-sdk/plugin-entry';

export default definePluginEntry({
  id: "openclaw-memoryhub",
  
  register(api) {
    const config = parseOpenClawConfig(api.pluginConfig);  // ~40 lines - reads openclaw.json
    const client = new MemoryHubClient(config);
    
    // Convert shared contracts to OpenClaw's typebox format (~30 lines)
    const tools = TOOL_CONTRACTS.map(contract => ({
      name: contract.name,
      description: contract.description,
      parameters: convertToTypebox(contract.parameters),
      execute: (id, params) => client.callTool(contract.name, params)
    }));
    
    // Register with OpenClaw API
    tools.forEach(tool => api.registerTool(tool));
    api.prependSystemContext(PROTOCOL_CONTENT);
    
    // Auto-recall hook (~20 lines)
    api.on('before_prompt_build', async (event) => {
      const recall = new RecallEngine(client, config);
      const memories = await recall.search(event.userMessage);
      event.prependContext(memories);
    });
  }
});
```

**OpenCode is similar** - same reduction, but uses `zod` instead of `typebox`.

### 4.2 Config-Based Plugins (Claude Code, Codex, Hermes)

Claude Code, Codex, and Hermes all use config-based plugin models (MCP server config + hooks/protocol injection). They connect to the MemoryHub MCP server rather than registering tools directly.

**Claude Code plugin structure:**
```
memoryhub-claude-plugin/
├── .claude-plugin/
│   └── plugin.json          # Metadata
├── rules/
│   └── memoryhub-loading.md # From @memory-hub/common/protocol.md
├── hooks/
│   ├── hooks.json           # Hook configuration
│   └── load-memories.sh     # From @memory-hub/common/templates/
└── .mcp.json                # From @memory-hub/common/templates/
```

**Codex plugin structure:**
```
memoryhub-codex-plugin/
├── .codex-plugin/           # Codex uses .codex-plugin/
│   └── plugin.json
├── rules/                   # Or AGENTS.md section (TBD based on Codex conventions)
│   └── memoryhub-loading.md
├── hooks/
│   ├── hooks.json           # Same hook events as Claude Code
│   └── load-memories.sh     # Same CLI calls
└── .mcp.json                # Or config.toml (Codex supports both)
```

**Hermes plugin structure:**
```
memoryhub-hermes-plugin/
├── plugin.py                # Plugin entry point
├── hooks/
│   └── pre_llm_call.py      # Injects protocol content
├── config/
│   └── mcp_server.yaml      # MCP server config snippet
└── docs/
    └── memoryhub-protocol.md # From @memory-hub/common/protocol.md
```

**Key differences:**
- Claude Code/Codex: event-driven hooks (SessionStart, etc.)
- Hermes: plugin hooks (`pre_llm_call`, `post_llm_call`, `on_session_start`, `on_session_end`)
- Hermes uses `config.yaml` for MCP server registration
- All three connect to MCP server (no tool registration)

**How they're built:**
- Read `protocol.md` from shared package → write to `rules/memoryhub-loading.md`
- Read template `.mcp.json` → write to plugin root (or generate `config.toml` for Codex)
- Read template hook scripts → write to `hooks/`

**Who builds them:**
- Could be part of #581 (example plugins)
- Could be part of #310 (artifact generation)
- Could be separate issue

---

## 5. Relationship to #310

**#310 (instruction file generation) is MOSTLY SEPARATE.**

The only connection: #310's adapters can read `protocol.md` from `@memory-hub/common` as the canonical source when generating instruction files.

**#310 scope:**
- CLI: `memoryhub config init --framework <name>`
- Generates instruction files for non-plugin frameworks (Goose, etc.)
- Validates user input using `config-schema.json` from shared package

**#581 scope:**
- Shared package for plugin authors
- Refactor OpenClaw/OpenCode to use it
- Provide building blocks for new plugins

**Overlap:** Both use `protocol.md` and `config-schema.json` from the shared package.

---

## 6. Migration Plan

### Phase 0: Drift Fix (no breaking changes)

Align OpenClaw to OpenCode's fixes without extracting anything.

**Tasks:**
1. Copy OpenCode's single-flight connect into OpenClaw
2. Copy OpenCode's stale-close `resetSession` into OpenClaw
3. Copy OpenCode's `SessionManager` into OpenClaw
4. Fix OpenClaw's timer leak (clear in `finally`)
5. Delete dead `"memory_expired"` retry in OpenClaw
6. Copy OpenCode's four-tier config resolution into OpenClaw (adds env var support)
7. Deduplicate `memoryhub-rules.md` (byte-identical, pick one as canonical)

**Exit criteria:** Both plugins pass identical conformance tests

**Impact:** Internal code only, no API changes, no breaking changes

### Phase 1: Extract Shared Package (breaking changes)

**Prerequisites:**
- [x] Confirm OpenClaw provenance → **In-repo original** (PR #490, no upstream coordination needed)
- [ ] JS workspace decision → **Deferred** (use path dependencies for now: `"@memory-hub/common": "file:../common"`)

**Tasks:**
1. Create `integrations/common/` package (`@memory-hub/common`)
   - Move shared code from OpenClaw/OpenCode
   - Export `MemoryHubClient`, `SessionManager`, `RecallEngine`
   - Export `TOOL_CONTRACTS`, `CONFIG_SCHEMA`, `PROTOCOL_CONTENT`
   - Ship templates in `templates/` directory
   - Document credential resolution pattern
3. Refactor OpenClaw as thin adapter (~150 lines)
4. Refactor OpenCode as thin adapter (~150 lines)
5. Write conformance suite
6. Prove behavior unchanged

**Exit criteria:** 
- Both plugins depend on `@memory-hub/common`
- Conformance suite passes
- No user-visible changes

**Impact:** 
- Breaking: New imports, new APIs
- Major version bump (2.0.0)
- Mixed versions safe (wire protocol unchanged)

### Phase 2: Documentation & Templates (optional)

**Tasks:**
1. Document "How to build a MemoryHub plugin"
2. Provide `integrations/plugin-template/` starter
3. Example: Build Claude Code plugin (or defer to #310)
4. Publish `@memory-hub/common` to npm (or keep private)

---

## 7. Migration Impact

### OpenClaw Migration

| Aspect | Before | After | Breaking? |
|--------|--------|-------|-----------|
| **Dependencies** | `@modelcontextprotocol/sdk`, `@sinclair/typebox` | Add `@memory-hub/common` | ✅ Yes - new dep |
| **Code size** | 1,045 lines | ~150 lines | No |
| **Imports** | `import { createMcpClient } from './mcp-client'` | `import { MemoryHubClient } from '@memory-hub/common'` | ✅ Yes - new paths |
| **API** | `createMcpClient(url)` | `new MemoryHubClient(config)` | ✅ Yes - different constructor |
| **Session** | Manual `ensureSession()` | `client.withSession()` | ✅ Yes - new pattern |
| **Config resolution** | Plugin config only | Four-tier: plugin > env > INI > flat file | ✅ Yes - **new env var support** |
| **Files deleted** | `mcp-client.ts`, `tools.ts`, `hooks.ts`, `config.ts` | Kept in shared package | No |
| **Version** | 0.1.x | 2.0.0 (major bump) | ✅ Yes - breaking |

**Config migration note:**
OpenClaw 2.0.0 now supports environment variables (`MEMORYHUB_URL`, `MEMORYHUB_API_KEY`) and INI files (`~/.config/memoryhub/credentials`), matching the CLI/SDK pattern. Plugin config still takes precedence, so existing configurations are unaffected. Users can now omit the plugin config and use environment variables instead.

### OpenCode Migration

Same pattern as OpenClaw, but uses `zod` instead of `typebox`.

### Deployment

**Coordinated release:**
1. Publish `@memory-hub/common@1.0.0`
2. Publish `openclaw-memoryhub@2.0.0` (depends on @memory-hub/common)
3. Publish `opencode-memoryhub@2.0.0` (depends on @memory-hub/common)

**Mixed version safety:**
- ✅ Users can upgrade OpenClaw and OpenCode independently
- ✅ Safe to run both 2.0.0 and 0.1.x against the same MemoryHub backend
- ✅ No wire protocol changes — both send identical MCP requests
- ✅ Different session tokens per client (no collision)
- ⚠️ Users with both hosts get bug fixes unevenly until both are upgraded

**Version pinning strategy:**
- `@memory-hub/common` uses exact semver in plugin dependencies (`1.0.0`, not `^1.0.0`)
- Plugins pin to same `@memory-hub/common` version for behavioral parity
- Rollback: patch release (1.0.1) or revert all three packages atomically

---

## 8. Testing Strategy

**Wire protocol:** OpenClaw and OpenCode send identical MCP requests. The shared package extracts client-side logic only; no protocol changes.

### Shared Package Tests

**Unit tests** (transport mocked):
- `MemoryHubClient`: single-flight connect, stale-close, auth retry
- `SessionManager`: generation-guarded recovery, no double retries
- `RecallEngine`: format, timeout, untrusted framing, budget
- Config validator: schema validation, precedence
- Tool contracts: valid JSON, complete mappings

### Conformance Suite

**Purpose:** Prevent "fix lands in one plugin but not another"

**Scope:** Given mocked MCP backend, every plugin must:

#### 1. Config Resolution
- ✅ **Four-tier precedence:** plugin > env > INI > flat file
- ✅ **Per-field resolution:** mix sources (e.g., URL from plugin, API key from env)
- ✅ **Validation:** reject invalid URL, wrong types, missing required fields
- ✅ **Context switching:** respect `MEMORYHUB_CONTEXT` env var for INI sections
- ✅ **Backward compat:** fall back to flat file `~/.config/memoryhub/api-key`

```typescript
// Test: plugin config wins over env
resolveConfig(
  { server: { url: "http://plugin" } },
  { env: { MEMORYHUB_URL: "http://env" } }
) → url === "http://plugin"

// Test: env wins when plugin empty
resolveConfig({}, { env: { MEMORYHUB_URL: "http://env" } })
  → url === "http://env"

// Test: per-field mix
resolveConfig(
  { server: { url: "http://plugin" } },
  { env: { MEMORYHUB_API_KEY: "env-key" } }
) → url === "http://plugin", apiKey === "env-key"

// Test: validation
resolveConfig({ server: { url: "not-a-url" } }) → throws
resolveConfig({}) → throws (missing url)
```

#### 2. Inert When Unconfigured
- ✅ No URL → plugin registers no tools
- ✅ No API key → plugin registers no tools
- ✅ No errors thrown (graceful degradation)

#### 3. Session Management
- ✅ Register session lazily (not on plugin load)
- ✅ Recover on auth error exactly once (generation-guarded)
- ✅ No double retries on same error
- ✅ Close stale transport on `resetSession()`

#### 4. Tool Registration
- ✅ Surface 6 tools: search, read, list, write, update, delete
- ✅ Each tool round-trips correctly (send params → receive result)
- ✅ Tool schemas valid (typebox for OpenClaw, zod for OpenCode)

#### 5. Auto-Recall
- ✅ Inject memories with untrusted framing (`<memoryhub-context>` tags)
- ✅ Respect `useFocus` flag (send focus when enabled)
- ✅ Honor `maxResponseTokens` budget

#### 6. Timeout & Error Handling
- ✅ Recall timeout (never stall indefinitely)
- ✅ Clear timers in `finally` (no timer leak)
- ✅ Degrade gracefully on MCP server error (return error, don't crash)
- ✅ Error framing: no stack trace leakage, consistent error messages

```typescript
// Test: MCP error is surfaced, not stack trace
mockMcp.callTool.mockResolvedValue({
  isError: true,
  content: [{ type: "text", text: "Memory not found: abc-123" }]
});

await expect(client.callMemory("read", { memory_id: "abc-123" }))
  .rejects.toThrow("Memory not found: abc-123");  // Clean message
  // NOT: Error: McpClientError: Memory not found: abc-123\n  at mcp-client.ts:76...
```

#### 7. Connection Management
- ✅ Single-flight connect (overlapping calls share one attempt)
- ✅ No duplicate transports (failed attempt cleaned up)
- ✅ Socket cleanup on close

**Coverage:**
- Run against OpenClaw adapter
- Run against OpenCode adapter
- (Future) Run against CLI + hooks for artifact hosts

### Adapter Tests

**OpenClaw-specific:**
- Typebox schema generation from contracts
- OpenClaw API registration
- `before_prompt_build` hook injection

**OpenCode-specific:**
- Zod schema generation from contracts
- OpenCode hook registration
- `systemTransform` injection

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Shared package breaks both plugins** | Both plugins fail | Comprehensive test suite, semver versioning, Phase 0 proves parity first |
| **OpenClaw-specific behavior lost** | OpenClaw users see regression | Phase 0 aligns behavior, conformance suite catches differences |
| **Breaking changes anger users** | Users resist upgrade | Clear migration guide, 0.1.x stays available, document benefits; mixed versions are safe |
| **Different host SDKs diverge** | Adapter breaks on SDK update | Adapter seam isolates host SDK, tests catch breakage |

---

## 10. Out of Scope

- ❌ Implementing the refactor (this is a design)
- ❌ Building Claude Code/Codex/Hermes plugins (defer to #310 or separate issue)
- ❌ Instruction file generation (#310)
- ❌ Turn-level hooks (#313)
- ❌ MCP tool surface changes

---

## 11. Follow-Up Issues

Ordered by dependency:

1. **`core: Reconcile OpenClaw + OpenCode to behavioral baseline`** *(Phase 0)* — copy OpenCode fixes into OpenClaw; fix timer leak, dead retry, stale connection cleanup; copy four-tier config resolution (adds env var support); dedupe memoryhub-rules.md. Exit: identical conformance run passes.

2. ~~**`build: Introduce JS workspace for integrations`**~~ *(Deferred)* — use path dependencies (`file:../common`) for now; workspace can be added later if needed.

4. **`core: Extract @memory-hub/common package`** *(Phase 1)* — create `integrations/common/`; move shared code (client, session, recall, tools, config, protocol); export contracts, schema, templates; document credential resolution.

5. **`adapters: Refactor OpenClaw as thin adapter`** *(Phase 1)* — rewrite to use `@memory-hub/common`; ~150 lines; typebox conversion.

6. **`adapters: Refactor OpenCode as thin adapter`** *(Phase 1)* — rewrite to use `@memory-hub/common`; ~150 lines; zod conversion.

7. **`test: Add conformance suite`** *(Phase 1)* — scenario matrix from §8; run against both adapters.

8. **`docs: Plugin authoring guide`** *(Phase 2, optional)* — "How to build a MemoryHub plugin" with template.

9. **`example: Claude Code plugin`** *(Phase 2, optional OR defer to #310)* — working example using shared package templates.

10. **`example: Codex plugin`** *(Phase 2, optional OR defer to #310)* — Codex variant (nearly identical to Claude Code, demonstrates portability).

11. **`example: Hermes plugin`** *(Phase 2, optional OR defer to #310)* — Hermes config-based plugin using `pre_llm_call` hook for protocol injection.

---

## 12. Success Criteria

**Phase 0:**
- [ ] OpenClaw and OpenCode pass identical conformance tests
- [ ] Both use four-tier config resolution (plugin > env > INI > flat file)
- [ ] No behavioral differences outside adapter seams
- [ ] All Phase 0 bugs fixed (timer leak, dead retry, stale connection, etc.)

**Phase 1:**
- [ ] `@memory-hub/common` package exists and exports all shared code
- [ ] OpenClaw is ~150 lines, depends on mcp-client
- [ ] OpenCode is ~150 lines, depends on mcp-client
- [ ] Conformance suite passes for both
- [ ] No user-visible behavior changes
- [ ] Breaking changes documented in migration guide

**Phase 2:**
- [ ] Plugin authoring guide published
- [ ] Template available for new plugins
- [ ] At least one example config-based plugin using shared package (Claude Code, Codex, or Hermes)
- [ ] Templates support Claude Code (`.mcp.json`), Codex (`config.toml`), and Hermes (`config.yaml`) formats

---

## Appendix: File Size Breakdown

### Shared Package (integrations/common/ → @memory-hub/common)

Extracted from OpenClaw/OpenCode:

| File | Lines | Source |
|------|-------|--------|
| `src/client.ts` | ~180 | OpenCode mcp-client.ts (has single-flight) |
| `src/session.ts` | ~60 | OpenCode session.ts (has generation guards) |
| `src/recall.ts` | ~120 | OpenCode hooks.ts recall logic |
| `src/tools.ts` | ~50 | Tool contract loader (new) |
| `src/config.ts` | ~230 | OpenCode config.ts (four-tier resolution + INI reader) |
| `protocol.md` | 133 | Existing (duplicated today) |
| `tool-contracts.json` | ~200 | Extracted from tools.ts |
| `config-schema.json` | ~80 | Extracted from configSchema |
| `templates/.mcp.json.template` | ~15 | Template (new) |
| `templates/session-start.sh` | ~20 | Template script (new) |
| `templates/recall.sh` | ~15 | Template script (new) |
| `templates/capture.sh` | ~15 | Template script (new) |
| `docs/credential-resolution.md` | ~50 | Documentation (new) |
| **Total** | ~1,168 lines | (**+150 from four-tier config**) |

### OpenClaw Adapter (after)

| File | Lines | What it does |
|------|-------|--------------|
| `src/index.ts` | ~150 | Plugin entry, converts contracts to typebox, registers with OpenClaw API |
| **Total** | ~150 lines | |

**Reduction:** 1,045 → 150 lines (85%)

### OpenCode Adapter (after)

| File | Lines | What it does |
|------|-------|--------------|
| `src/index.ts` | ~150 | Plugin factory, converts contracts to zod, registers with OpenCode hooks |
| **Total** | ~150 lines | |

**Reduction:** ~700 → 150 lines (78%)
