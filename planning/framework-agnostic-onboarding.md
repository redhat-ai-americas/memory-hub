# Framework-Agnostic Onboarding

**Status:** Design
**Date:** 2026-08-21
**Issue:** #310
**Related:** #536 (global install), #312 (multi-harness tracking), #489 (OpenClaw), #509 (OpenCode)

## Problem

`memoryhub config init` is Claude Code-specific. It writes `.claude/rules/`,
`.claude/hooks/`, and `.claude/settings.json` — artifacts only Claude Code
understands. The `--format` flag added `system-prompt`, `agents-md`, `ogx`,
and `raw` output formats, but these only print instructions to stdout for
manual copy-paste. There is no automated onboarding path for non-Claude-Code
frameworks.

The OpenClaw integration (`integrations/openclaw/`, PR #490) shipped a full
plugin that bypasses `config init` entirely — its own config format, protocol
doc, lifecycle hooks. Each new framework requires bespoke integration work.

## Design principles

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

## Three onboarding paths

Frameworks fall into three categories based on how the agent discovers
and uses MemoryHub:

### Instruction-driven (Claude Code, OpenCode, OGX)

The agent gets MCP tools via a native MCP connection and follows
instructions (a rule file, system prompt section, or `AGENTS.md`
block) that tell it when to search, how to write, and how to handle
contradictions. The agent drives all memory behavior.

Onboarding = MCP config + instruction file + optional hooks.

### Plugin-driven (OpenClaw)

A framework plugin handles the MCP connection, session registration,
auto-recall, memory slot ownership, and tool exposure programmatically.
The agent doesn't need instructions telling it when to search — the
plugin does it via hooks. The plugin IS the integration.

Onboarding = plugin installation + plugin config in the framework's
config file.

An instruction file is redundant for plugin-driven frameworks because
the plugin enforces the behavior the instructions would describe. The
adapter for a plugin-driven framework installs and configures the
plugin rather than writing instructions.

### MCP-discovered (custom agent loops, unknown frameworks)

The agent connects to MemoryHub's MCP server, discovers tools via the
standard MCP `tools/list`, and fetches behavioral instructions from an
MCP resource (`memoryhub://agent-instructions`). No local file
generation needed.

Onboarding = point the agent at the MCP server URL. Everything else
is discoverable.

This is the zero-config path for frameworks that have MCP support but
no dedicated adapter. It's also the fallback for frameworks where the
`raw` adapter's "paste into your system prompt" workflow is too manual.

### The adapter interface covers all three

The `Adapter` protocol's `setup` method has no constraints on what
it does. An instruction-driven adapter writes MCP config + instructions.
A plugin-driven adapter installs the plugin package + writes plugin
config. The MCP resource path needs no adapter at all — it's a server-
side feature.

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

### Layer 3: Adapter implementations

Each adapter is a single Python file, typically 40-80 lines. The adapter
has full control over what it writes.

#### `claude_code.py` (~80 lines) — instruction-driven

Refactors the existing `write_init_files`, `write_hook_script`, and
`merge_settings_hooks` into the adapter protocol. No behavior change.

```python
class ClaudeCodeAdapter:
    name = "claude-code"
    display_name = "Claude Code"

    def setup(self, content, credentials, project_dir, *,
                    scope, overwrite=False):
        if scope == "global":
            base = Path.home() / ".claude"
        else:
            base = project_dir / ".claude"

        # 1. Write rule file
        rules_dir = base / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rule_path = rules_dir / "memoryhub-loading.md"
        rule_path.write_text(render_rule_markdown(content))

        # 2. Write hook script
        hooks_dir = base / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "load-memories.sh"
        hook_path.write_text(HOOK_SCRIPT)
        hook_path.chmod(hook_path.stat().st_mode | 0o111)

        # 3. Merge hook entries into settings.json
        settings_path = base / "settings.json"
        merge_settings_hooks(settings_path)

        return AdapterResult(
            files_written=[rule_path, hook_path],
            files_modified=[settings_path],
        )

    def detect(self, project_dir):
        return (project_dir / ".claude").is_dir()
```

The `render_rule_markdown(content: MemoryInstruction) -> str` helper
assembles the sections into the markdown format with headers. This is a
shared utility, not adapter-specific — every adapter that writes a
markdown file uses it.

The hook script remains a static string constant (it doesn't vary per
project). It stays in `project_config.py` or moves to a separate
`hooks.py` module.

#### `openclaw.py` (~80 lines) — plugin-driven

Installs the MemoryHub plugin and configures it in `openclaw.json`. The
plugin handles MCP connection, auto-recall, session lifecycle, and memory
slot ownership. No instruction file is needed.

```python
class OpenClawAdapter:
    name = "openclaw"
    display_name = "OpenClaw"

    def setup(self, content, credentials, project_dir, *,
                    scope, overwrite=False):
        if scope == "global":
            config_path = Path.home() / ".config" / "openclaw" / "config.json"
        else:
            config_path = project_dir / "openclaw.json"

        # 1. Install the plugin package
        subprocess.run(
            ["npm", "install", "@memory-hub/openclaw-mh-plugin"],
            cwd=project_dir, check=True,
        )

        # 2. Merge plugin config into openclaw.json
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

        return AdapterResult(
            files_written=[],
            files_modified=[config_path],
        )

    def detect(self, project_dir):
        return (project_dir / "openclaw.json").exists()
```

The `MemoryInstruction` argument is unused — the plugin handles agent
behavior programmatically, not via instructions.

#### `opencode.py` (~50 lines) — instruction-driven

```python
class OpenCodeAdapter:
    name = "opencode"
    display_name = "OpenCode"

    def setup(self, content, credentials, project_dir, *,
                    scope, overwrite=False):
        if scope == "global":
            config_path = Path.home() / ".opencode" / "config.json"
        else:
            config_path = project_dir / ".opencode" / "config.json"

        # 1. Merge MCP server entry (OpenCode format: type + string array headers)
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        servers = config.setdefault("mcpServers", {})
        servers["memoryhub"] = {
            "type": "remote",
            "url": credentials.server_url,
            "headers": [
                f"Authorization: Bearer ${{{credentials.api_key_env}}}"
            ],
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        # 2. Instructions — OpenCode has no global rules mechanism
        if scope == "project":
            instr_path = project_dir / "memoryhub-loading.md"
            instr_path.write_text(render_rule_markdown(content))
            return AdapterResult(
                files_written=[instr_path],
                files_modified=[config_path],
            )

        return AdapterResult(
            files_written=[],
            files_modified=[config_path],
            instructions_text=render_rule_markdown(content),
        )

    def detect(self, project_dir):
        return (project_dir / ".opencode").is_dir()
```

#### `ogx.py` (~60 lines) — instruction-driven

OGX/LlamaStack uses YAML-based `config.yaml` with a connectors list.
The adapter writes the MCP connector entry and appends an OGX-specific
snippet showing how to reference MemoryHub tools in Responses API calls.

```python
class OgxAdapter:
    name = "ogx"
    display_name = "OGX / LlamaStack"

    def setup(self, content, credentials, project_dir, *,
                    scope, overwrite=False):
        # OGX config is YAML, not JSON
        config_path = project_dir / "config.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text()) or {}
        else:
            config = {}

        # Add MCP connector
        connectors = config.setdefault("connectors", [])
        if not any(c.get("connector_id") == "memoryhub" for c in connectors):
            connectors.append({
                "connector_id": "memoryhub",
                "provider_id": "model-context-protocol",
                "url": credentials.server_url,
            })
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))

        # Write instructions (print to stdout — OGX has no rules file convention)
        text = render_rule_markdown(content) + "\n" + OGX_API_SNIPPET
        return AdapterResult(
            files_written=[],
            files_modified=[config_path],
            instructions_text=text,
        )

    def detect(self, project_dir):
        return (project_dir / "config.yaml").exists()
```

`OGX_API_SNIPPET` is the existing `_OGX_SNIPPET` block showing `run.yaml`
connector config and Responses API tool reference.

#### `raw.py` (~20 lines)

Prints instructions to stdout, writes no files. The output is universal
markdown suitable for pasting into any system prompt or `AGENTS.md` file.

```python
class RawAdapter:
    name = "raw"
    display_name = "Raw (print to stdout)"

    def setup(self, content, credentials, project_dir, *,
                    scope, overwrite=False):
        return AdapterResult(
            files_written=[],
            files_modified=[],
            instructions_text=render_rule_markdown(content),
        )

    def detect(self, project_dir):
        return False  # never auto-detected
```

The `raw` adapter replaces three former `--format` values:
- `system-prompt` → `raw` (paste the output into a system prompt)
- `agents-md` → `raw` (paste into `AGENTS.md` for Codex CLI, OpenCode)
- `raw` → `raw` (unchanged)

These were all print-to-stdout with minor header variations. The
differences weren't worth separate adapters — the user pastes the
output wherever their framework reads instructions.

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

## What this design does NOT cover

- **OpenClaw plugin development.** The OpenClaw adapter installs and
  configures the existing plugin. Changes to the plugin itself (e.g.,
  removing tool wrappers now that native MCP handles tool exposure) are
  a separate task.

- **Turn-level hooks** (#313) — automatic rebias and extraction on each
  turn. Independent of onboarding.

- **Auto-detection of framework** — the `detect` method is defined but
  not wired into the CLI. A follow-up can add `--framework auto` that
  calls `detect_adapter()`. The interface is ready.

## Adding a new framework

To add support for a new framework, a contributor:

1. Creates `memoryhub_cli/adapters/newframework.py` (~40-80 lines)
2. Implements `setup`, `detect`, and the two name fields
3. Registers it in `adapters/__init__.py` (one line)
4. Adds a test file `tests/test_adapter_newframework.py`

The contributor reads an existing adapter (50 lines of Python) and
writes a similar one. The adapter has full control over file formats,
merge semantics, and framework-specific quirks — whether that's JSON
merge for OpenCode, YAML merge for OGX, or `npm install` for OpenClaw.

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

## Implementation plan

| Step | What | Behavior change | Est. lines |
|------|------|----------------|------------|
| 1 | Extract `MemoryInstruction` dataclass + `build_instructions()` | None (internal refactor) | +60, -40 |
| 2 | Create `adapters/claude_code.py` wrapping existing functions | None (existing behavior preserved) | +80 |
| 3 | Create `adapters/openclaw.py` (plugin-driven) | New: `--framework openclaw` installs plugin + config | +80 |
| 4 | Create `adapters/opencode.py` | New: `--framework opencode` works | +50 |
| 5 | Create `adapters/ogx.py` | New: `--framework ogx` works | +60 |
| 6 | Create `adapters/raw.py` | Replaces `system-prompt`, `agents-md`, `raw` | +20 |
| 7 | Adapter registry + `--framework` / `--global` CLI flags | New flags, `--format` deprecated | +40 |
| 8 | `--dry-run` flag | New: safe preview | +30 |
| 9 | MCP resource `memoryhub://agent-instructions` | New: agents fetch instructions via MCP | +30 |
| 10 | Tests for each adapter + MCP resource | | +250 |
| 11 | Simplify OpenClaw plugin (remove tool wrappers) | Separate PR | -340 |
