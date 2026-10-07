# Framework-Agnostic Onboarding

**Status:** Design
**Date:** 2026-08-21
**Issue:** #310
**Related:** #536 (global install), #312 (multi-harness tracking), #489 (OpenClaw), #509 (OpenCode)

## Core Principle: One Abstraction, Two Patterns

**The adapter protocol is deliberately generic enough to handle fundamentally different integration patterns.**

MemoryHub integrations fall into two categories:

### Pattern 1: Instruction-Driven (Claude Code, Goose, OGX)
- Agent gets MCP tools via native MCP connection
- Follows written instructions (rule file, system prompt section, AGENTS.md)
- Agent drives all memory behavior by reading the instructions
- **Onboarding = MCP config + instruction file + optional hooks**

### Pattern 2: Plugin-Driven (OpenClaw, OpenCode)
- Framework plugin handles MCP connection, session lifecycle, auto-recall
- Plugin enforces behavior programmatically (no instruction file needed)
- Plugin IS the integration — agent doesn't need to read instructions
- **Onboarding = `npm install` plugin + plugin config in framework's JSON**

**The adapter protocol doesn't constrain what `setup()` does.** Both patterns return the same `AdapterResult` reporting what happened. An instruction-driven adapter writes files. A plugin-driven adapter runs `npm install` and merges JSON. New patterns require new adapters, not changes to the core abstraction.

## Current Landscape

| Framework | Integration | Pattern | Config Format | Automated install? | Status |
|-----------|-------------|---------|---------------|-------------------|--------|
| **Claude Code** | Built-in CLI | Instruction-driven | `.claude/` files | ✅ `config init` | Shipped |
| **OpenClaw** | Plugin (#490) | Plugin-driven | `openclaw.json` | ❌ Manual | Shipped |
| **OpenCode** | Plugin (#549) | Plugin-driven | `opencode.json` | ❌ Manual | PR open |
| **Goose** | Unknown | Likely instruction | YAML (unverified) | ❌ None | Not started |
| **OGX** | None | Instruction | `config.yaml` | ❌ None | Speculative |
| **LibreChat** | Planned (#82) | MCP-discovered | `librechat.yaml` | ❌ None | Not started |

**The problem:** Only Claude Code has automated setup. Every other framework requires manual config file editing, plugin installation, and following scattered docs.

## What This PR Delivers

This PR ships **the framework only — no concrete adapters**:

1. ✅ **Core abstraction**: `MemoryInstruction` dataclass + `Adapter` protocol
2. ✅ **Adapter registry**: Discovery and invocation plumbing
3. ✅ **CLI wiring**: `--framework`, `--global`, `--dry-run` flags
4. ✅ **Documented examples**: Code samples showing instruction-driven (Goose) and plugin-driven (OpenClaw/OpenCode) patterns
5. ✅ **MCP resource**: `memoryhub://agent-instructions` for zero-config discovery

**Explicitly NOT in scope:**
- ❌ Working adapters (Claude Code, OpenClaw, OpenCode, Goose, OGX)
- ❌ Refactoring existing `config init` into an adapter
- ❌ Plugin installation automation

**Why no adapters?** Each concrete adapter requires framework-specific decisions:
- Claude Code: Convert to plugin first, or keep instruction-driven?
- OpenClaw/OpenCode: Plugins already exist — is config merging even needed?
- Goose: MCP config pattern needs verification
- OGX: No working integration to test against

Shipping the framework proves the abstraction. Each adapter becomes its own issue with clear prerequisites.

## Design Principles

1. **Single-command setup.** `memoryhub config init --framework X` should
   leave MemoryHub fully working — MCP config, agent instructions, and
   any required plugins or extensions. The user should not need a second
   manual install step.

2. **Separate content from placement.** The instructions an agent receives
   are universal. Where those instructions go is framework-specific. These
   are different concerns and should be different abstractions.

3. **Adapters are small Python functions.** Each adapter is a thin Python
   class that takes a content bundle and writes the right files. Fully
   testable, composable with framework-specific logic, no abstraction
   layers between the adapter and the filesystem.

4. **The protocol handles both patterns.** Instruction-driven and plugin-driven
   integrations use the same adapter interface. The difference is what
   `setup()` does, not the signature it implements.

## How the Adapter Protocol Handles Both Patterns

The `Adapter` protocol's `setup` method has **no constraints on what it does**. Both patterns fit the same interface:

**Instruction-driven adapter** (Claude Code):
```python
def setup(self, content, credentials, project_dir, *, scope, overwrite):
    # Uses 'content' to write rule file
    rule_path.write_text(render_rule_markdown(content))
    hook_path.write_text(HOOK_SCRIPT)
    merge_settings_hooks(settings_path)
    return AdapterResult(files_written=[rule_path, hook_path])
```

**Plugin-driven adapter** (OpenClaw, OpenCode):
```python
def setup(self, content, credentials, project_dir, *, scope, overwrite):
    # Ignores 'content' - plugin handles instructions
    subprocess.run(["npm", "install", "@memory-hub/openclaw-mh-plugin"])
    merge_plugin_config(config_path, credentials)
    return AdapterResult(files_modified=[config_path])
```

Both return `AdapterResult`. The protocol doesn't care how you got there.

### MCP-Discovered Path (zero-config)

The agent connects to MemoryHub's MCP server, discovers tools via the
standard MCP `tools/list`, and fetches behavioral instructions from an
MCP resource (`memoryhub://agent-instructions`). No local file
generation needed.

Onboarding = point the agent at the MCP server URL. Everything else
is discoverable.

This is the zero-config path for frameworks that have MCP support but
no dedicated adapter. It's also the fallback for frameworks where the
`raw` adapter's "paste into your system prompt" workflow is too manual.
This is a server-side feature, not an adapter.

## Design

### Layer 1: Instruction content model

Extract all instruction content into a single `MemoryInstruction` dataclass
that captures what an agent should be told, built from the template blocks
in `project_config.py`.

```python
@dataclass(frozen=True)
class MemoryInstruction:
    """Agent instruction content, independent of framework."""

    # Structural
    pattern: LoadingPattern
    pattern_title: str

    # Sections (each is a rendered markdown string)
    session_start: str       # "At session start" — varies by pattern
    during_session: str      # "During the session" — varies by pattern
    hygiene: str             # weights, scopes, update-vs-write
    contradiction: str       # enabled or disabled variant
    campaigns: str | None    # campaign enrollment, if any

    # Raw config for adapters that need programmatic access
    config: ProjectConfig
```

The current code maintains two parallel pattern block dictionaries —
Claude Code-specific and universal. Whether to keep both or collapse
them into one (with adapter-specific preambles for framework details)
is an open question — see "Open questions" below.

```python
def build_instructions(config: ProjectConfig) -> MemoryInstruction:
    """Build the instruction content for a config."""
```

### Layer 2: Adapter protocol

An adapter is a Python module in `memoryhub_cli/adapters/` that implements
a simple protocol:

```python
class Adapter(Protocol):
    """What a framework adapter must implement."""

    name: str
    display_name: str

    def setup(
        self,
        content: MemoryInstruction,
        credentials: ResolvedCredentials,
        project_dir: Path,
        *,
        scope: Literal["project", "global"],
        overwrite: bool = False,
    ) -> AdapterResult: ...

    def detect(self, project_dir: Path) -> bool: ...
```

```python
@dataclass
class ResolvedCredentials:
    """Credentials resolved by the universal core."""
    server_url: str       # from env or ~/.config/memoryhub/credentials
    api_key_env: str      # always "MEMORYHUB_API_KEY" (the env var name)

@dataclass
class AdapterResult:
    """What the adapter wrote."""
    files_written: list[Path]
    files_modified: list[Path]   # existing files that were merged into
    instructions_text: str | None  # for stdout-only adapters
```

Three things to implement:

- **`setup`** — write MCP config, instructions, and whatever else
  the framework needs. The adapter owns all framework-specific logic:
  file paths, merge semantics, config format, extras.
- **`detect`** — check whether this framework is in use in a project
  directory (look for config files). Used for auto-detection (deferred
  to follow-up, but the interface is ready).
- **`name`/`display_name`** — for CLI display and `--framework` flag
  matching.

### Layer 3: Adapter Patterns (Documented Examples)

The following show what adapters look like when implemented. **None of these ship in this PR.**
Each is a single Python file, typically 40-80 lines. The adapter has full control over what it writes.

#### Pattern A: Instruction-Driven Adapter (Goose example)

An instruction-driven adapter writes MCP config + instruction files the agent reads at startup.

```python
class GooseAdapter:
    name = "goose"
    display_name = "Goose"

    def setup(self, content, credentials, project_dir, *, scope, overwrite=False):
        # Goose uses YAML config in platform-specific config dir
        if scope == "global":
            config_path = Path.home() / ".config" / "goose" / "config.yaml"
        else:
            config_path = project_dir / ".goose" / "config.yaml"

        # 1. Add MCP server to extensions config (YAML merge)
        config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
        extensions = config.setdefault("extensions", {})
        extensions["memoryhub"] = {
            "type": "mcp",
            "url": credentials.server_url,
            "auth": {"api_key": f"${{{credentials.api_key_env}}}"},
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump(config))

        # 2. Write agent instructions (Goose reads from project .goosehints or system prompt)
        # This assumes .goosehints is the instruction file - actual pattern TBD
        instr_path = project_dir / ".goosehints"
        instr_path.write_text(render_rule_markdown(content))

        return AdapterResult(
            files_written=[instr_path],
            files_modified=[config_path],
        )

    def detect(self, project_dir):
        return (project_dir / ".goose").is_dir()
```

**Note:** Goose's MCP config pattern is unverified. This example shows the structure;
actual implementation requires investigating Goose's extension config format.

#### Pattern B: Plugin-Driven Adapter (OpenClaw example)

A plugin-driven adapter assumes the plugin is already installed and just writes framework
config pointing to the MemoryHub server. The plugin handles MCP connection, auto-recall,
and session lifecycle programmatically — no instruction file needed.

```python
class OpenClawAdapter:
    name = "openclaw"
    display_name = "OpenClaw"

    def setup(self, content, credentials, project_dir, *, scope, overwrite=False):
        # Assumes plugin already installed via: npm install @memory-hub/openclaw-mh-plugin
        if scope == "global":
            config_path = Path.home() / ".config" / "openclaw" / "config.json"
        else:
            config_path = project_dir / "openclaw.json"

        # Merge plugin config into openclaw.json
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        plugins = config.setdefault("plugins", {})
        plugins.setdefault("slots", {})["memory"] = "openclaw-memoryhub"
        plugins.setdefault("entries", {})["openclaw-memoryhub"] = {
            "enabled": True,
            "package": "@memory-hub/openclaw-mh-plugin",
            "config": {
                "server": {"url": credentials.server_url},
                "auth": {"apiKey": f"${{{credentials.api_key_env}}}"},
                "defaults": {"scope": "user"},
            },
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        return AdapterResult(files_written=[], files_modified=[config_path])

    def detect(self, project_dir):
        return (project_dir / "openclaw.json").exists()
```

**Note:** The `content` parameter is unused — the plugin bundles its own instructions.
This adapter just writes ~15 lines of JSON config.

OpenCode follows the same pattern with slightly different JSON structure:

```python
class OpenCodeAdapter:
    name = "opencode"
    display_name = "OpenCode"

    def setup(self, content, credentials, project_dir, *, scope, overwrite=False):
        # Assumes plugin already installed via: opencode plugin @memory-hub/opencode-mh-plugin
        if scope == "global":
            config_path = Path.home() / ".config" / "opencode" / "config.json"
        else:
            config_path = project_dir / "opencode.json"

        # Merge plugin config into opencode.json (different structure than OpenClaw)
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        plugins = config.setdefault("plugin", [])
        plugins.append([
            "@memory-hub/opencode-mh-plugin",
            {
                "server": {"url": credentials.server_url},
                "auth": {"apiKey": f"${{{credentials.api_key_env}}}"},
                "defaults": {"scope": "user"},
            }
        ])
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        return AdapterResult(files_written=[], files_modified=[config_path])

    def detect(self, project_dir):
        return (project_dir / ".opencode").is_dir()
```

**Note:** OpenCode's plugin array format differs from OpenClaw's object-based format,
but the adapter pattern is the same — merge config, return what changed.

#### Other Frameworks

Additional frameworks (OGX, Cursor, Aider, LibreChat, etc.) would follow similar patterns:
- **Instruction-driven**: Write MCP config + instruction files (like Goose example)
- **Plugin-driven**: Merge plugin config JSON (like OpenClaw/OpenCode examples)

The pattern is determined by framework capabilities, not adapter design.

**These examples demonstrate the adapter pattern. None are implemented in this PR.**

### Layer 4: Universal core (orchestration)

The `config init` command orchestrates:

```
User
 │
 │  memoryhub config init --framework openclaw --global
 │
 ├─ 1. Resolve adapter (by --framework flag or auto-detect)
 │
 ├─ 2. Interactive questionnaire (unchanged)
 │     → InitChoices
 │
 ├─ 3. build_project_config(choices) → ProjectConfig
 │
 ├─ 4. Write .memoryhub.yaml (project scope only)
 │
 ├─ 5. Resolve credentials
 │     → ResolvedCredentials
 │
 ├─ 6. build_instructions(config) → MemoryInstruction
 │
 ├─ 7. adapter.setup(content, credentials, project_dir, scope=...)
 │     → AdapterResult
 │
 └─ 8. Display summary of files written/modified
```

The adapter registry is a simple dict built at import time:

```python
# memoryhub_cli/adapters/__init__.py

from .claude_code import ClaudeCodeAdapter
from .openclaw import OpenClawAdapter
from .opencode import OpenCodeAdapter
from .ogx import OgxAdapter
from .raw import RawAdapter

ADAPTERS: dict[str, Adapter] = {
    a.name: a for a in [
        ClaudeCodeAdapter(),
        OpenClawAdapter(),
        OpenCodeAdapter(),
        OgxAdapter(),
        RawAdapter(),
    ]
}

def get_adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise ValueError(
            f"Unknown framework: {name!r}. "
            f"Available: {', '.join(ADAPTERS)}"
        )
    return ADAPTERS[name]

def detect_adapter(project_dir: Path) -> Adapter | None:
    for adapter in ADAPTERS.values():
        if adapter.detect(project_dir):
            return adapter
    return None
```

### CLI changes

```
memoryhub config init --framework openclaw          # explicit framework
memoryhub config init --framework openclaw --global  # global scope (#536)
memoryhub config init                                # defaults to claude-code
memoryhub config init --dry-run                      # show what would be written
```

- `--format` kept as deprecated alias for `--framework`.
- `--dry-run` shows file paths and content previews without writing.
  Makes re-running safe.
- `memoryhub config regenerate` reads `.memoryhub.yaml`, rebuilds
  `MemoryInstruction`, and calls the adapter's `setup` again.

### MCP-discoverable instructions

Any MCP-capable agent can fetch behavioral instructions directly from
the MemoryHub server without file generation. The MCP server already
has a resources package with auto-discovery
(`memory-hub-mcp/src/resources/`):

```python
@mcp.resource("memoryhub://agent-instructions")
async def agent_instructions() -> str:
    """Behavioral instructions for agents using MemoryHub.

    Returns the universal memory protocol: when to search, how to write,
    hygiene rules, contradiction handling. Any MCP-capable agent can
    fetch this at startup instead of reading a local file.
    """
    return UNIVERSAL_INSTRUCTIONS
```

`UNIVERSAL_INSTRUCTIONS` is the same content that `render_rule_markdown()`
produces for the `raw` adapter — the universal pattern blocks + hygiene +
contradiction handling. The resource returns the generic version (not
framework-specific) since the consumer is any MCP client.

This complements the adapter system rather than replacing it:
- **Adapters** handle framework-specific setup (config files, hooks,
  plugins) that can't be served over MCP.
- **The MCP resource** handles the "custom agent loop with no framework"
  case — the agent connects to MemoryHub's MCP server, discovers tools
  AND instructions, and needs nothing else.

For frameworks that don't have a rule file convention (like OGX's stdout
fallback), the agent could fetch instructions from this resource at
session start instead of requiring the user to paste them.

### Shared utilities

Two helpers used across adapters:

```python
def render_rule_markdown(content: MemoryInstruction) -> str:
    """Assemble MemoryInstruction into a markdown document."""
    sections = [
        f"# MemoryHub Loading: {content.pattern_title}\n",
        "This project uses MemoryHub for persistent, centralized agent memory "
        "across conversations. You MUST use it.\n",
        content.session_start,
        content.during_session,
        content.hygiene,
        content.contradiction,
    ]
    if content.campaigns:
        sections.append(content.campaigns)
    return "\n".join(sections)


def merge_json_key(path: Path, key: str, value: Any) -> None:
    """Read-modify-write a single top-level key in a JSON file."""
    data = json.loads(path.read_text()) if path.exists() else {}
    data.setdefault(key, {}).update(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
```

These are optional conveniences, not a required engine. An adapter that
needs different merge logic just does it inline.

## Open questions

- **Do we need Claude Code-specific pattern blocks?** The current code
  maintains two parallel dictionaries: `_PATTERN_BLOCKS` (Claude Code-
  specific) and `_UNIVERSAL_PATTERN_BLOCKS` (framework-agnostic). The
  Claude Code variant adds the `<memoryhub-context>` tag name, specific
  credential file paths, and a "hook misconfigured" fallback flow. The
  universal variant covers both pre-loading and self-serve cases already.
  Could the Claude Code-specific content be a small preamble the adapter
  prepends, collapsing the two dictionaries into one and eliminating
  drift between them?

- **Should `<memoryhub-context>` be in the universal instructions?** The
  `<memoryhub-context>` tag is a MemoryHub convention for wrapping
  pre-loaded memories, not a Claude Code-specific concept. Any framework
  that pre-loads memories could (and probably should) use the same tag so
  the agent recognizes them consistently. If so, the universal pattern
  blocks should reference it, and the distinction between the two
  variants shrinks further.

- **Generator drift from committed rule file.** The committed
  `.claude/rules/memoryhub-loading.md` in this repo contains a "Content
  delivery" section (S3 truncation, `hydrate`, `content_mode`) and
  updated credential resolution text that the template blocks in
  `project_config.py` do not produce. This may be intentional content
  that should be added to the templates, or it may be a hand-edit (by a
  person or agent) that happened to get committed. Before implementing,
  decide: should `MemoryInstruction` include these sections so the
  generator produces them for all projects, or should they remain
  repo-specific additions outside the generator's scope?

## What This PR Does NOT Cover

- **Full working adapters for OpenClaw, OpenCode, Goose, OGX.** Those are
  follow-up PRs. This PR ships the framework + documented examples showing
  how they would work.

- **OpenClaw plugin simplification.** The plugin (#490) wraps MCP tools.
  Native MCP eliminates the need for wrappers. Separate cleanup PR.

- **Turn-level hooks** (#313) — automatic rebias and extraction on each
  turn. Independent of onboarding.

- **Auto-detection of framework** — the `detect` method is defined in the
  protocol but not wired into the CLI. A follow-up can add `--framework auto`
  that calls `detect_adapter()`. The interface is ready.

- **Publishing plugins to npm.** OpenClaw and OpenCode plugins exist but
  aren't published. Packaging and publishing are separate efforts.

## Adding a New Framework (After This PR)

Once the framework lands, adding support for a new framework is straightforward:

1. Create `memoryhub_cli/adapters/newframework.py` (~40-80 lines)
2. Implement `setup`, `detect`, and the two name fields
3. Register it in `adapters/__init__.py` (one line)
4. Add a test file `tests/test_adapter_newframework.py`

The contributor reads an existing adapter (Claude Code for instruction-driven,
or the openclaw/opencode examples for plugin-driven) and writes a similar one.
The adapter has full control over file formats, merge semantics, and framework-
specific quirks — whether that's JSON merge, YAML merge, or `npm install`.

## Summary: What Ships vs What's Next

### This PR Ships ✅

**Framework only:**
- `MemoryInstruction` dataclass (universal content model)
- `Adapter` protocol (generic enough for both patterns)
- `AdapterResult` (what happened, not how)
- Adapter registry (`ADAPTERS` dict, `get_adapter()`, `detect_adapter()`)
- CLI wiring (`--framework`, `--global`, `--dry-run`)
- MCP resource `memoryhub://agent-instructions` for zero-config discovery
- Tests for protocol, registry, and MCP resource
- **Documented adapter patterns** (code examples in this doc showing how to implement adapters)

**Estimated:** ~270 lines of production code + pattern documentation

**No concrete adapters ship.** The framework is proven through examples, not implementations.

### Follow-Up Issues 📋

Each adapter becomes its own issue with clear prerequisites:

**High Priority (plugins exist):**
1. **Claude Code plugin** — Bundle existing rules + hooks, submit to claude.com/plugins directory
   - Blocks: Decision on whether to keep `config init` instruction-driven support
2. **OpenClaw config adapter** — Merge plugin config into `openclaw.json` (if needed)
   - Prerequisite: Verify plugin can't handle config interactively
3. **OpenCode config adapter** — Merge plugin config into `opencode.json` (if needed)
   - Prerequisite: Verify plugin can't handle config interactively

**Medium Priority (MCP-capable, no plugin yet):**
4. **Goose adapter** — Add MCP server to YAML config + write instructions
   - Prerequisite: Verify Goose MCP config pattern
5. **LibreChat adapter** — Configure MCP server with OAuth (#82)
   - Prerequisite: LibreChat integration complete

**Low Priority (speculative):**
6. **OGX adapter** — YAML config + Responses API snippet
   - Prerequisite: Working OGX/LlamaStack integration
7. **Auto-detection** — `--framework auto` using adapter `detect()` methods

Each follow-up is ~80 lines of adapter code + ~100 lines of tests.

## Impact on existing code

The refactor is additive until the final switchover:

1. **Extract `MemoryInstruction`** from the existing block dictionaries.
   `build_instructions()` replaces the current `render_instructions()` +
   `render_rule_file()` split.

2. **Create `memoryhub_cli/adapters/` package** with `claude_code.py`
   that wraps the existing `write_init_files`, `write_hook_script`, and
   `merge_settings_hooks`. Existing behavior is preserved.

3. **Add `openclaw.py`, `opencode.py`, `ogx.py`, `raw.py`** adapters.

4. **Update CLI** — `--framework` flag, deprecated `--format` alias,
   `--dry-run`.

5. **Add MCP resource** — `memoryhub://agent-instructions` in the MCP
   server for agent-discoverable instructions.

6. **Migrate tests** — existing `test_project_config.py` (738 lines)
   tests the rendering and file-writing logic. The rendering tests stay;
   file-writing tests move to per-adapter test files.

Steps 1-2 are the core refactor with no behavior change for existing
users. Steps 3-5 add new capability. Step 6 is cleanup.

## Implementation Plan

This PR delivers **the framework only**:

| Step | What | Est. lines |
|------|------|------------|
| 1 | Extract `MemoryInstruction` dataclass + `build_instructions()` | +60 |
| 2 | Define `Adapter` protocol + `AdapterResult` | +30 |
| 3 | Adapter registry + discovery (`ADAPTERS` dict, `get_adapter()`) | +30 |
| 4 | CLI wiring: `--framework`, `--global`, `--dry-run` flags | +40 |
| 5 | MCP resource `memoryhub://agent-instructions` | +30 |
| 6 | Tests for protocol + registry + MCP resource | +80 |
| 7 | Document adapter patterns in this design doc (examples below) | +200 (doc) |

**Total estimated:** ~270 lines of code + pattern documentation

**No adapters ship in this PR.** Examples in the design doc show how to implement them.
