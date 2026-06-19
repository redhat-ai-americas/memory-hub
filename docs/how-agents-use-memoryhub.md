# How Agents Use MemoryHub

MemoryHub doesn't extract memories automatically. It gives the agent instructions, pre-loaded context, and tools -- then trusts the agent's judgment about what's worth remembering. This document explains the three layers that make that work.

For the API and tool reference, see the [Agent Integration Guide](agent-integration-guide.md). For the hook setup walkthrough, see the [Hooks Integration Guide](hooks-integration.md). This document covers the conceptual "why and how" rather than the mechanical "what to call."

## Layer 1: Rules

Claude Code loads every `.md` file in `.claude/rules/` at the start of each session. MemoryHub uses this to inject a rule file called `memoryhub-loading.md` that tells the agent how to behave with memory.

The rule file is generated, not hand-written. Running `memoryhub config init` from your project root reads `.memoryhub.yaml` (the project's memory configuration) and produces `.claude/rules/memoryhub-loading.md` with instructions tailored to the project's loading pattern. Four patterns are available -- eager, lazy, lazy-with-rebias, and just-in-time -- each generating different session-start and mid-session behavior.

The rule covers four concerns. First, what to do at session start: check for pre-loaded memories, and fall back to manual search if the hook didn't fire. Second, when to search again mid-session: on topic pivots, unknown concepts, or explicit user direction. Third, memory hygiene: what's worth writing (decisions, preferences, architecture choices) and what isn't (ephemeral actions like "user asked me to read a file"). Fourth, contradiction handling: when to flag a memory that no longer matches reality.

The rule file is committed to the repository. Every contributor's agent loads the same instructions. After editing `.memoryhub.yaml`, run `memoryhub config regenerate` to re-render the rule file without re-running the interactive wizard.

## Layer 2: Hooks

Rules tell the agent what to do, but the agent still has to spend tool calls to load memories at session start. The SessionStart hook eliminates that cost entirely.

Claude Code supports hooks that run a shell command when a session starts. MemoryHub's hook (`.claude/hooks/load-memories.sh`) calls the CLI to search for relevant project memories and prints the results to stdout. Claude Code injects that output into the conversation context before the first prompt, wrapped in a `<memoryhub-context>` tag.

The agent sees something like this before the user's first message:

```
<memoryhub-context project="memory-hub">
- FastAPI is the preferred web framework for new services
- Deploy scripts must be run in main conversation context, never sub-agents
- Use Podman, not Docker; Containerfile, not Dockerfile
</memoryhub-context>
```

No memory IDs, no timestamps, no weights. Just the content the agent needs to do its job. This is deliberate: structural metadata in the context window activates model reasoning about memory management instead of the user's task. The compact format keeps the agent focused.

The hook completes in under a second and fails silently on any error (missing CLI, unreachable server, expired key). A failed hook never blocks a session from starting. The MCP server remains available as a fallback for the agent to search manually via tool calls.

The hook and the MCP server are complementary. The hook handles read-at-startup with zero tool-token overhead. The MCP server handles mid-session searches, writes, updates, and all other operations that require tool calls.

## Layer 3: The agent's judgment

The first two layers set the stage. The agent decides what happens on it.

The rule file gives guidelines -- "write preferences, decisions, architectural choices" -- but it doesn't define a rigid extraction pipeline. The agent reads the conversation, recognizes when something is worth persisting, and calls `write_memory` or `update_memory` at its own discretion. This is an instruction to exercise judgment, not an automated extraction system.

What gets stored:

- Architecture decisions ("We chose pgvector over a dedicated vector DB because PostgreSQL was already in the stack")
- User preferences ("Wes prefers em-dash-free prose")
- Workflow patterns ("Deploy scripts must never run in sub-agents")
- Tool configuration ("The MCP server uses the compact tool profile by default")
- Lessons learned ("File permissions must be 644 before container builds")

What doesn't get stored:

- Ephemeral actions ("Read the README," "Ran pytest")
- Conversation logistics ("User asked me to explain X")
- Information already captured in committed documentation
- Transient debugging context that won't matter next session

The agent also manages its working set during the session. When the user pivots to a different subsystem, the rule instructs the agent to search for memories related to the new topic and add them to its context -- not replace what it already has, since the prior topic might come back.

## Setting it up in a new project

Three commands:

```bash
pip install memoryhub-cli
memoryhub login
memoryhub config init
```

`memoryhub login` stores your API key and server URL in `~/.config/memoryhub/`. `memoryhub config init` runs an interactive wizard that asks about your project's session shape and generates three files: `.memoryhub.yaml`, `.claude/rules/memoryhub-loading.md`, and `.claude/hooks/load-memories.sh`. It also merges the hook configuration into `.claude/settings.json`.

Commit `.memoryhub.yaml`, the rule file, and the hook script to your repository. Do not commit credentials -- those stay in `~/.config/memoryhub/`.

After setup, the next Claude Code session in that project will automatically load relevant memories at startup and have the MCP tools available for mid-session operations.
