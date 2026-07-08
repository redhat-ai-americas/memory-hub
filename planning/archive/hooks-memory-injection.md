# Zero-Overhead Memory Injection via Agent Hooks

**Status:** Phases 1-4 complete; Phase 5 (performance) is future work
**Date:** June 2026
**Related issues:** #255, #256, #246, #203

---

## 1. Problem

MemoryHub's MCP server returns full memory objects (id, owner_id, scope, weight,
created_at, updated_at, content_type, metadata) alongside the actual content.
For a search returning 10 memories, hundreds of tokens go to structural JSON the
model doesn't need. This cost compounds because it stays in context for the
entire conversation.

Beyond raw token count, there is a cognitive load dimension. Structural metadata
in the context window can activate follow-on reasoning about that metadata (e.g.,
the model starts reasoning about weights, scopes, and timestamps instead of the
task at hand). This affects model output quality, especially with smaller models
where context is more precious and reasoning capacity more limited.


## 2. Tiered Integration Model

The right access path depends on how much control the developer has over prompt
assembly. Three tiers:

### Tier 1: Full control (SDK in custom agents)

BaseAgent or any custom agent framework calls the SDK, extracts `.content`, and
injects it as a `<memory></memory>` block in the system prompt. Zero overhead.
This is the golden path for fips-agents, custom agents, and any framework where
you own the prompt assembly.

### Tier 2: Partial control (MCP in agentic tools)

Claude Code, LibreChat, etc. The user configures the MCP server but the tool
call/response flow is handled by the host. Compact-by-default matters most here.

### Tier 3: No control (pure MCP, no prompt customization)

Generic MCP clients where you can't touch the system prompt. Compact responses
are the only lever.

### Recommendation

If a developer has *any* control over prompt assembly, they should use Tier 1.
The MCP server remains valuable for scenarios where the agent needs to read and
write mid-conversation, but startup context should come through the SDK or CLI
whenever possible.


## 3. Claude Code Hook Design

### Hook dimensions

Claude Code's hook system has two dimensions:

1. **Hook types** -- lifecycle events the harness fires: `SessionStart`,
   `PreToolUse`, `PostToolUse`, `Notification`, etc.
2. **Matchers** -- filters within a hook type that select when to fire.

For `SessionStart`, the available matchers are:

| Matcher | When it fires | Inject memories? | Reason |
|---------|---------------|------------------|--------|
| `startup` | New session | Yes | Fresh context, no prior memories |
| `compact` | Auto or manual context compaction | Yes | Original injection may be summarized away |
| `clear` | `/clear` command | Yes | Conversation wiped, same as fresh start |
| `resume` | `--resume`, `--continue`, `/resume` | No | Prior memories still in transcript |

### Scope boundary: memory-hub vs agent template

Memory-hub provides the **service-side primitives** that agent hooks call:
the CLI, the SDK, and reference hook scripts. It does not own the agent-side
hook infrastructure -- that belongs to the agent template (fips-agents).

What memory-hub provides:

1. **CLI commands** -- search, write, list, checkpoint, etc. The stable
   interface that hook scripts call.
2. **Reference hook scripts** -- `.claude/hooks/load-memories.sh` and
   similar, demonstrating the pattern for each memory-relevant lifecycle
   event.
3. **Config wizard** -- `memoryhub config init` generates settings.json
   hook wiring for the chosen memory access profile.

The agent template owns the full hook lifecycle (all hook types, matcher
conventions, hook composition patterns). Memory-hub hooks into the subset
of lifecycle events where memory access matters.

### Transport: CLI via bash

Hook scripts call the MemoryHub CLI binary. This is a deliberate choice
over alternatives:

| Transport | Startup | Auth handling | Maintenance | Verdict |
|-----------|---------|---------------|-------------|---------|
| CLI (`memoryhub search ...`) | ~0.5s Python import | Encapsulated (env var, file, config) | Hook script doesn't change when API evolves | **Use this** |
| curl to REST API | Near-zero | Must duplicate in bash | Breaks on API changes | Too fragile |
| `python3 -c` with SDK | ~0.5s Python import | Encapsulated, but no stable CLI interface | Worse CLI | No benefit |
| MCP tool hook | N/A | N/A | Servers not reliably connected at SessionStart | Not viable for startup |

The CLI is a stable abstraction layer. Auth resolution, server URL lookup,
output formatting, and API shape changes are all encapsulated -- the hook
script stays the same. Current round-trip is ~2.1s, well within the 5s
timeout. A compiled CLI (Rust/Go) is the Phase 5 optimization if Python
startup becomes a bottleneck.

For non-Claude-Code agents (fips-agents, custom frameworks), the SDK is the
right path -- Tier 1 in section 2. The CLI path is for Tier 2 scenarios
where you don't control prompt assembly but do have shell hook access.

### Memory-relevant hook types

Not all agent lifecycle hooks need memory access. The ones that do:

| Hook type | Memory operation | Example |
|-----------|-----------------|---------|
| SessionStart (startup, compact, clear) | Read: inject context | `memoryhub search --output compact` |
| PostCompact | Read: re-inject after compression | Same script as SessionStart |
| SessionEnd | Write: save learnings | `memoryhub write "..." --scope project` |
| SubagentStart | Read: scoped injection for sub-agent | `memoryhub search --scope project` |

Other hook types (PreToolUse, PostToolUse, UserPromptSubmit, etc.) are
agent-template concerns. A project *could* wire MemoryHub into those
(e.g., a PostToolUse hook that checkpoints state after deploys), but
that's project-specific customization, not something memory-hub ships
by default.

### Authentication

The CLI supports API key auth via `MEMORYHUB_API_KEY` env var or auto-read
from `~/.config/memoryhub/api-key`. This enables non-interactive use in hooks.

### Query strategy

Without knowing the user's intent at session start, options:

1. **All project + user memories.** Safest, heaviest. Works for broad sessions.
2. **High-weight memories only.** `--min-weight 0.7` narrows to critical context.
3. **CLAUDE.md-informed query.** If `.memoryhub.yaml` exists, use the project_id.
   If a `CLAUDE.md` or `AGENTS.md` exists, extract keywords for a semantic query.
   Interesting but fragile and slow.
4. **Pre-configured query set.** `.memoryhub.yaml` specifies a `startup_query`
   field with default search terms.

**Recommendation:** Start with option 2 (high-weight for project + user scope),
configurable via `.memoryhub.yaml`. This is fast, predictable, and covers the
most valuable memories without overwhelming smaller-model context windows.

### Output format

The hook prints to stdout, which Claude Code injects as context before the first
prompt. Format as clean text, not JSON:

```
<memoryhub-context project="memory-hub">
- Wes prefers Podman over Docker, Red Hat UBI base images only
- MCP tool reduction 10→1-2 decided 2026-04-23; CLI-first strategy
- Deploy scripts must be run in main conversation context, never sub-agents
- ...
</memoryhub-context>
```

Do not include: memory IDs, timestamps, weights, scope labels, branch counts,
or child stubs. These activate model reasoning about memory structure rather than
the task. The goal is injecting context, not data.

### Size budget

Claude Code truncates `.claude/rules/` files around 200 lines. The
`additionalContext` field caps at 10,000 characters. Target 15-20 memories,
content only, well under both limits.

### Graceful degradation

If the CLI is not installed, the API is unreachable, or the timeout fires: exit 0
with no output. The session starts normally. The MCP server is still available as
a fallback for mid-conversation searches.

### Hook configuration

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/load-memories.sh",
          "timeout": 5
        }]
      },
      {
        "matcher": "compact",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/load-memories.sh",
          "timeout": 5
        }]
      },
      {
        "matcher": "clear",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/load-memories.sh",
          "timeout": 5
        }]
      }
    ]
  }
}
```

### Hook script sketch

```bash
#!/bin/bash
# .claude/hooks/load-memories.sh
# Inject MemoryHub memories at session start. Fails silently.

API_KEY_FILE="$HOME/.config/memoryhub/api-key"
[ -f "$API_KEY_FILE" ] || exit 0

API_KEY=$(tr -d '\n' < "$API_KEY_FILE")
[ -n "$API_KEY" ] || exit 0

# Use the CLI with API key auth and compact output
memoryhub search "" \
  --api-key "$API_KEY" \
  --project-id "$(basename "$CLAUDE_PROJECT_DIR")" \
  --min-weight 0.7 \
  --max 20 \
  --compact 2>/dev/null || exit 0
```


## 4. Compact Output Mode

### CLI: `--compact` flag

New flag on `memoryhub search` that outputs only memory content, one per line,
wrapped in a clean XML block. No IDs, no metadata, no JSON structure.

### MCP server: compact by default

Make the `memory` tool return only `id` + `content` for `search` and `list`
results by default. Add an `options.verbose` flag to get full metadata. The model
can call `read` with the id if it needs details.

### SDK: no change needed

The SDK already returns structured objects. The developer extracts `.content` in
their own code. The SDK is inherently Tier 1.


## 5. Startup Context vs Runtime Retrieval

Most memory value is in **startup context** -- loading relevant memories once at
session start. Runtime searches (mid-conversation topic pivots) are rarer,
higher-value, and paying the MCP overhead on those is acceptable.

This distinction means:

- **Startup:** Hook + CLI path. Zero overhead. Pre-loaded before first prompt.
- **Runtime:** MCP server path. Pays the JSON tax but provides dynamic search
  and write capabilities the hook cannot.

The existing `memoryhub-loading.md` rule needs to be updated to reflect this
split. Instead of instructing the agent to `register_session` and
`search_memory` after the first user turn, the rule should say:

- Memories are pre-loaded via hook; check the `<memoryhub-context>` block.
- Only call `register_session` + `search_memory` on topic pivots or when you
  need to write.
- The MCP server is the write path. The hook is read-only.


## 6. CLI/SDK Feature Parity Gaps

The audit found the CLI is behind the MCP server:

| Operation        | MCP | CLI | SDK |
|------------------|-----|-----|-----|
| list             | Yes | Yes | Yes |
| promote          | Yes | Yes | Yes |
| graduate         | Yes | Yes | Yes |
| checkpoint       | Yes | Yes | Yes |
| describe_project | Yes | Yes | Yes |

All parity gaps closed as of CLI 0.9.0 / SDK 0.12.0 (2026-06-08, #257).

Going forward, new MCP actions should be accompanied by CLI and SDK equivalents
in the same PR. This is a same-commit consumer audit rule, matching the pattern
from CONTRIBUTING.md.


## 7. Performance Considerations

### Current state

The CLI takes ~0.45s just to start (Python import time). A search adds network
latency on top. For the hook use case, we need the full round trip under 3
seconds, ideally under 2.

### Polyglot performance path

Every layer needs to be fast. Python startup overhead is a real cost for a CLI
that runs on every session start. Candidates for performance-critical layers:

- **Rust:** CLI binary with near-zero startup. Would eliminate the 0.45s Python
  import tax. Natural fit for a thin CLI wrapper over HTTP calls.
- **Go:** Similar startup characteristics to Rust. Strong HTTP client ecosystem.

This does not mean rewriting the whole stack. The server stays Python/FastAPI.
The SDK stays Python (it's used from Python agents). But the CLI could be a
compiled binary that makes HTTP calls directly to the API, bypassing the Python
SDK entirely for read operations.

This is a future optimization. The Python CLI is fine for now if we can keep the
total round trip under the 5-second hook timeout.

### MCP server performance

The CLI and SDK should serve as performance benchmarks for the MCP server. If a
search takes 200ms via the REST API (measured by the CLI) but 800ms via MCP,
that delta is MCP protocol overhead we should investigate. Regularly compare the
three paths.


## 8. Memory API Standard

There is no emerging standard for agent memory APIs. MemoryHub's REST API could
be a candidate for one. Key properties a standard would need:

- **CRUD:** write, read, update, delete
- **Search:** semantic similarity with scope/project filtering
- **Scoping:** user, project, organizational, enterprise
- **Versioning:** immutable version chains
- **Governance:** contradiction detection, curation rules
- **Compact retrieval:** content-only mode for token-efficient injection

This is a strategic consideration, not an implementation item. Worth monitoring
what emerges from the MCP ecosystem and A2A protocol space.


## 9. Cognitive Load and Model Quality

Token efficiency is necessary but not sufficient. Two concerns:

**Structural metadata activates reasoning.** When a model sees `weight: 0.85,
scope: "project", created_at: "2026-05-19"`, it may start reasoning about
whether the weight is high enough, whether the scope is relevant, or whether the
memory is stale. This consumes reasoning capacity on memory management rather
than the user's task.

**Follow-on network effects.** Returning branch counts, child stubs, and
relationship metadata can trigger the model to fetch those children "just in
case." Each fetch adds more context, more reasoning, more latency. For the
startup context use case, we should inject only the memory content and nothing
that invites further exploration.

**Smaller models are more sensitive.** A frontier model can ignore irrelevant
metadata. A Haiku-class model may not. Our compact output mode should be the
default precisely because it works across the model spectrum.


## 10. Interaction with Existing Loading Rule

The current `.claude/rules/memoryhub-loading.md` instructs the agent to:

1. Read API key and call `register_session`
2. After the first user turn, call `search_memory`
3. On topic pivots, search again

With the hook pre-loading memories, the rule should be updated to:

1. Check the `<memoryhub-context>` block for pre-loaded memories.
2. On topic pivots, call `register_session` if not already registered, then
   `search_memory` for the new topic.
3. For write operations, call `register_session` if not already registered.
4. The hook handles startup reads. The MCP server handles runtime reads and all
   writes.


## 11. Implementation Plan

### Phase 1: CLI foundations (blocks hook work)
1. Add API key auth to CLI (`MEMORYHUB_API_KEY` env var + `--api-key` flag)
2. Add `--compact` flag to `memoryhub search`
3. Add missing `list` command

### Phase 2: Hook integration
4. Write `.claude/hooks/load-memories.sh`
5. Add hook configuration to `.claude/settings.json`
6. Update `memoryhub-loading.md` rule for hybrid startup/runtime flow
7. Test with Claude Code sessions

### Phase 3: MCP compact mode
8. Make MCP `search`/`list` return `id` + `content` by default
9. Add `options.verbose` flag for full metadata

### Phase 4: CLI catch-up
10. Add `promote`, `graduate`, `checkpoint`, `describe_project` commands
11. Establish same-commit consumer audit rule for future MCP actions

### Phase 5: Performance baseline (measured 2026-06-12)

Benchmarks on macOS (Apple Silicon), CLI v0.10.0, Python 3.11:

| Measurement | Time |
|---|---|
| CLI startup (`--version`) | ~0.5s |
| CLI search (20 results, compact) | ~1.7s |
| Hook script end-to-end | ~0.3s |
| Hook timeout budget | 5.0s |
| Headroom | ~4.7s |

The hook script is well within the 5-second timeout. The hook is
faster than a standalone CLI search because it reuses a simpler
code path and the bash overhead is minimal.

The Python CLI startup cost (~0.5s) is acceptable. A compiled
Rust/Go CLI would eliminate this but is not justified given the
current headroom. Revisit if the hook grows to include multiple
queries or if the MCP server latency increases.

12. ~~Benchmark CLI startup + search latency~~ (done)
13. ~~Evaluate Rust/Go CLI for sub-second startup~~ (not needed, Python is fast enough)
14. Use CLI/SDK benchmarks to identify MCP server optimization targets (future)
