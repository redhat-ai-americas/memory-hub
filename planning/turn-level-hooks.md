# Turn-Level Hooks for MemoryHub

Status: Implemented (CLI + Claude Code hooks)
Date: 2026-07-08
Implemented: 2026-08-21

## Problem

MemoryHub's current hook integration is session-level only: a `SessionStart` shell hook pre-loads memories via the CLI, and mid-session operations require the agent to explicitly call MCP tools. This creates two gaps:

1. **Write-back depends on agent initiative.** The agent must decide "I should save this" and call `write_memory`. Agents frequently forget, especially under context pressure or when the conversation shifts quickly.
2. **Pivot detection is prompt-instruction-only.** The `.claude/rules/memoryhub-loading.md` file tells the agent to call `search_memory` on topic pivots, but compliance is inconsistent. A hook that fires on every user turn could automate relevance search without relying on agent judgment.

Turn-level hooks would let MemoryHub **automatically extract memories after each model response** and **re-bias context before each user turn is processed**, without the agent needing to do anything.

## Use Cases

**Post-turn write-back.** After the model responds, a hook extracts decisions, preferences, and facts from the conversation delta and persists them. The agent never needs to call `write_memory`.

**Pre-turn re-bias.** Before the model sees a new user message, a hook searches for memories relevant to the message content and injects them as context. This replaces the unreliable "detect pivots via prompt instructions" pattern.

**Contradiction detection.** A post-turn hook could compare newly extracted facts against existing memories and flag contradictions before they propagate.

## Harness Landscape

Research conducted July 2026. Sources verified via adversarial 3-vote protocol.

### Claude Code

The richest hook system of the four verified harnesses.

**Relevant events:**
- `UserPromptSubmit` -- fires after user submits, before model processes. Payload includes `prompt` (full user message text), `session_id`, `cwd`.
- `Stop` -- fires after model finishes responding. Payload includes `last_assistant_message`, `stop_reason`.
- `PreToolUse` / `PostToolUse` -- per-tool-call hooks with `tool_name`, `tool_input`, `tool_response`.

**Context injection:** All events support `additionalContext` in hook stdout (JSON). Injected as a system reminder, invisible in chat UI. 10K character cap.

**Blocking/modification:** Exit code 2 blocks the action. `PreToolUse` supports `updatedInput` to rewrite tool arguments. `PostToolUse` supports `updatedToolOutput`.

**Configuration:** `settings.json` at user or project scope. Shell commands with `matcher`, `timeout`, `type: "command"`.

**MemoryHub fit:** Excellent. `UserPromptSubmit` provides the user's message for relevance search; `additionalContext` injects results. `Stop` provides the model's response for extraction.

Sources: [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) (verified 3-0)

### OpenAI Codex CLI

Mirrors Claude Code's event model almost exactly.

**Relevant events:** Same 10 events as Claude Code: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`.

**Configuration:** `hooks.json` or inline TOML at `~/.codex/` (user) or `<repo>/.codex/` (project). Same `matcher`, `type`, `command`, `timeout` structure. Trust gating required.

**Limitations:** Only `command`-type handlers execute at runtime. `prompt` and `agent` handler types are parsed but not yet invoked. Payload schemas and `additionalContext` support are documented on the Hooks page but independent verification of Codex-specific payloads vs. Claude Code payloads was not fully established -- the two systems may share a schema wholesale.

**MemoryHub fit:** Good, assuming payload parity with Claude Code. Same integration pattern would work.

Sources: [developers.openai.com/codex/hooks](https://developers.openai.com/codex/hooks), [developers.openai.com/codex/config-reference](https://developers.openai.com/codex/config-reference), [developers.openai.com/codex/config-advanced](https://developers.openai.com/codex/config-advanced) (verified 3-0)

### OpenCode

Plugin-based middleware system, TypeScript/JavaScript.

**Relevant events:**
- `tool.execute.before` -- fires before tool runs. Receives tool name and modifiable args. Block by throwing an error.
- `message.updated` -- per-message event with `role` and `content` fields. User text is accessible.
- `experimental.session.compacting` -- fires before context compaction. Supports context injection via `output.context` array or full prompt replacement via `output.prompt`.
- `session.idle`, `session.created` -- session lifecycle.

**Context injection:** The compaction hook supports `output.context` injection. Per-message context injection paths are less well-documented.

**Blocking/modification:** `tool.execute.before` blocks via thrown error, modifies via `output.args`. A stop hook can re-prompt the agent via `client.session.prompt()`.

**Configuration:** TypeScript plugin modules exporting a hooks object. No shell-command hooks.

**MemoryHub fit:** Moderate. The plugin model means MemoryHub would need a published npm package or a TypeScript wrapper around the CLI. `message.updated` provides user text access but payload schemas aren't fully documented in official docs (community gist is the best source).

Sources: [opencode.ai/docs/plugins/](https://opencode.ai/docs/plugins/) (verified 3-0 for tool/compaction), [community gist](https://gist.github.com/johnlindquist/0adf1032b4e84942f3e1050aba3c5e4a) (2-1 for message payloads)

### Hermes Agent (Nous Research)

Three hook systems: Gateway YAML, Plugin Python, Shell config.

**Relevant events:**
- `pre_llm_call` (Plugin hook) -- fires once per turn before the LLM call. Receives `user_message` (full string) and `conversation_history` (OpenAI message format).
- `post_llm_call` (Plugin hook) -- fires after LLM response.
- Gateway hooks (`HOOK.yaml` in `~/.hermes/hooks/`) and Shell hooks (`hooks:` block in `~/.hermes/config.yaml`) provide additional integration points.

**Context injection:** `pre_llm_call` supports ephemeral context injection via `{"context": "text"}` return value. Context is appended to the user message (not the system prompt) to preserve prompt cache.

**Blocking/modification:** All hook systems are non-blocking by design -- errors are logged but never crash the agent. Whether `pre_llm_call` can block or rewrite the user message (beyond appending context) is undocumented.

**Configuration:** Plugin hooks via `ctx.register_hook()` in Python. Gateway hooks via YAML files. Shell hooks via config YAML.

**MemoryHub fit:** Good for the Python plugin path. `pre_llm_call` provides exactly the right payload (user message + history) for relevance search, and context injection is first-class. The Python plugin model aligns naturally with MemoryHub's Python SDK.

Sources: [hermes-agent.nousresearch.com/docs/user-guide/features/hooks/](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks/) (verified 3-0)

### OpenClaw

**Does not appear to exist** as a recognized AI coding agent harness. No documentation, repository, or credible sources were found. Dropped from scope.

## Proposed Architecture

### New CLI Subcommands

Two new subcommands on the `memoryhub` CLI, designed to be called from hook scripts:

```
memoryhub rebias <user-message-file>
    --project-id <id>
    --output compact
    --max 10
```

Reads the user's new message from a file (or stdin), runs a relevance search against existing memories, and prints results in the compact content-only format. Designed for pre-turn hooks (`UserPromptSubmit`, `pre_llm_call`, `message.updated`).

```
memoryhub extract <conversation-delta-file>
    --project-id <id>
    --session-id <id>
```

Reads a conversation delta (the latest assistant turn) from a file or stdin, extracts facts/decisions/preferences, and writes them as memories. Designed for post-turn hooks (`Stop`, `post_llm_call`). Calls the MCP server's extraction endpoint.

Both commands:
- Read credentials from `~/.config/memoryhub/api-key` (same as session-start hook)
- Exit 0 on all failures (graceful degradation)
- Respect the same `--output compact` format to avoid metadata leaking into agent context

### Harness Integration Matrix

| Capability | Claude Code | Codex CLI | OpenCode | Hermes |
|------------|------------|-----------|----------|--------|
| **Pre-turn re-bias** | `UserPromptSubmit` hook calls `memoryhub rebias`, injects via `additionalContext` | Same pattern | `message.updated` plugin calls rebias, injects via compaction hook | `pre_llm_call` plugin calls `memoryhub rebias`, returns `{"context": ...}` |
| **Post-turn extract** | `Stop` hook calls `memoryhub extract` with `last_assistant_message` | Same pattern | Plugin on model response event | `post_llm_call` plugin calls `memoryhub extract` |
| **Integration artifact** | Shell script + settings.json | Shell script + hooks.json | TypeScript plugin (npm package) | Python plugin (pip package) |
| **User message accessible?** | Yes (`prompt` field) | Yes (assumed parity) | Yes (`content` field, 2-1 confidence) | Yes (`user_message` field) |
| **Model response accessible?** | Yes (`last_assistant_message`) | Likely (assumed parity) | Unclear (payload underdocumented) | Yes (`post_llm_call` payload) |
| **Context injection method** | `additionalContext` (10K cap) | `additionalContext` (assumed) | `output.context` array | `{"context": "..."}` return |

### Reference Implementation Priority

1. **Claude Code** -- primary target, best-documented, already has session-start hook. Extend with `UserPromptSubmit` and `Stop` hooks.
2. **Hermes** -- Python-native, clean plugin model, good payload access.
3. **Codex CLI** -- near-identical to Claude Code, likely works with same scripts.
4. **OpenCode** -- requires TypeScript artifact, less mature payload docs.

### Hook Script Design (Claude Code reference)

**Pre-turn re-bias** (`.claude/hooks/rebias-memories.sh`):

```bash
#!/bin/bash
set -euo pipefail

API_KEY_FILE="$HOME/.config/memoryhub/api-key"
[ -f "$API_KEY_FILE" ] || exit 0
export MEMORYHUB_API_KEY=$(tr -d '\n' < "$API_KEY_FILE")

# User message arrives as JSON on stdin from Claude Code
USER_MSG=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('prompt',''))" 2>/dev/null) || exit 0
[ -n "$USER_MSG" ] || exit 0

MEMORYHUB_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.venv/bin/memoryhub"
[ -x "$MEMORYHUB_BIN" ] || MEMORYHUB_BIN=$(command -v memoryhub 2>/dev/null) || exit 0

PROJECT_ID=$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")

RESULTS=$("$MEMORYHUB_BIN" rebias "$USER_MSG" \
  --project-id "$PROJECT_ID" \
  --output compact \
  --max 10 2>/dev/null) || exit 0

[ -n "$RESULTS" ] || exit 0

# Inject as additionalContext
python3 -c "import json; print(json.dumps({'additionalContext': '$RESULTS'}))"
```

**Post-turn extract** (`.claude/hooks/extract-memories.sh`):

```bash
#!/bin/bash
set -euo pipefail

API_KEY_FILE="$HOME/.config/memoryhub/api-key"
[ -f "$API_KEY_FILE" ] || exit 0
export MEMORYHUB_API_KEY=$(tr -d '\n' < "$API_KEY_FILE")

# Model response arrives as JSON on stdin
RESPONSE=$(cat | python3 -c "import json,sys; print(json.load(sys.stdin).get('last_assistant_message',''))" 2>/dev/null) || exit 0
[ -n "$RESPONSE" ] || exit 0

MEMORYHUB_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.venv/bin/memoryhub"
[ -x "$MEMORYHUB_BIN" ] || MEMORYHUB_BIN=$(command -v memoryhub 2>/dev/null) || exit 0

PROJECT_ID=$(basename "${CLAUDE_PROJECT_DIR:-$PWD}")

"$MEMORYHUB_BIN" extract --project-id "$PROJECT_ID" --session-id "$SESSION_ID" <<< "$RESPONSE" 2>/dev/null || exit 0
```

**settings.json additions:**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/rebias-memories.sh",
          "timeout": 3
        }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/extract-memories.sh",
          "timeout": 5
        }]
      }
    ]
  }
}
```

## Performance Considerations

**Latency budget.** Pre-turn hooks add latency before the user sees the model start thinking. Target: < 500ms for rebias (relevance search is fast). Post-turn hooks run after the response and don't block the user.

**Token budget.** The `additionalContext` injection has a 10K character cap in Claude Code. The compact format keeps memories small (typically 50-100 chars each). 10 memories at ~80 chars = ~800 chars, well within budget.

**Extraction cost.** The `extract` command calls the server's extraction endpoint, which may use an LLM. This is the most expensive operation. Consider: (a) only extracting on turns longer than N characters, (b) batching extraction every K turns, (c) using a small/fast model for extraction.

**Deduplication.** The extraction endpoint must deduplicate against existing memories to avoid writing the same fact on every turn. This is a server-side concern, not a hook concern.

## Open Questions

1. **Codex payload parity.** Does Codex CLI actually support `additionalContext` injection, or did the research conflate it with Claude Code? Needs hands-on verification.
2. **OpenCode message payloads.** The `message.updated` event payload is documented only in a community gist. Is this stable enough to target?
3. **Hermes blocking.** Can `pre_llm_call` block a turn (e.g., if the memory system detects a dangerous contradiction), or is it inject-only?
4. **Extraction model.** Should extraction run locally (fast, no network) or server-side (better quality, shared extraction logic)?
5. **Opt-in granularity.** Should users be able to enable rebias but not extraction (or vice versa)?
6. **Other harnesses.** Aider, Continue, Cursor, and Windsurf were not researched. Should they be in scope?

## Relationship to Existing Work

- **SessionStart hook** (`docs/hooks-integration.md`): Turn-level hooks extend this. The session-start hook handles cold-start; turn-level hooks handle mid-session re-bias and continuous extraction.
- **MCP tools** (`search_memory`, `write_memory`): Turn-level hooks reduce but don't eliminate the need for explicit MCP calls. Agents may still want to search or write on their own initiative.
- **`.claude/rules/memoryhub-loading.md`**: The pivot-detection instructions become a fallback for harnesses that don't support turn-level hooks, rather than the primary mechanism.
- **Token compression** (`planning/token-compression.md`): Turn-level context injection interacts with compaction. PreCompact/PostCompact hooks may be relevant for preserving memory context across compactions.
