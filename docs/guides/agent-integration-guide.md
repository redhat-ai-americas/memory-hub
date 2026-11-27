# MemoryHub Agent Integration Guide

How AI agents use MemoryHub for persistent, project-scoped memory — the conceptual model first, then the concrete integration reference.

MemoryHub doesn't extract memories automatically. It injects instructions and context into the agent's prompt, gives the agent tools to read and write memories, and trusts the agent's judgment about what's worth persisting. The first half of this guide explains that mechanism: what text gets injected, where it appears, and how the agent decides to act on it. The second half is the integration reference: tool profiles, `register_session`, scopes, weights, and examples.

> **Current default tool surface:** the **compact profile** — 4 tools: `register_session`, `memory` (28 actions), `thread` (9 actions), and `admin_memory`. The flat tool names used in some examples below (`search_memory`, `write_memory`, `manage_session`, etc.) are **deprecated aliases** from the full profile; prefer `memory(action="search", ...)` and friends.

For the hook setup walkthrough, see the [Hooks Integration Guide](hooks-integration.md).

## Part 1: How agents use MemoryHub

### The three injection points

MemoryHub establishes itself in the agent's context through three mechanisms, each operating at a different layer of Claude Code's architecture. Together, they ensure the agent knows MemoryHub exists, has relevant memories pre-loaded, and has tools available to read and write more.

#### 1. The rule file: instructions the agent must follow

Claude Code loads every `.md` file in `.claude/rules/` at the start of each session and includes their content in the system prompt. MemoryHub uses this to inject a rule file called `memoryhub-loading.md` that tells the agent what to do with memory.

The rule file is generated, not hand-written. Running `memoryhub config init` reads `.memoryhub.yaml` and produces `.claude/rules/memoryhub-loading.md` tailored to the project's loading pattern. Here is what the agent sees (abridged from the actual file in this repo):

```
# MemoryHub Loading: Lazy + Rebias on Pivot

This project uses MemoryHub for persistent, centralized agent memory across
conversations. You MUST use it.

## At session start

Check for a <memoryhub-context> block in your conversation context.
If present, the SessionStart hook has pre-loaded project and user
memories -- use them as your working set. ...

## During the session -- watch for pivots

A pivot is any of:
1. Subsystem change -- the user changes topic to a different area
2. Unknown concept -- the user references a term not in your working set
3. Explicit switch -- the user says "let's switch to..."

When you detect a pivot, call search_memory with a query for the new topic.

## Memory hygiene

- DO write preferences, decisions, architectural choices, tool
  configuration, and workflow patterns.
- Skip ephemeral things like "user asked me to read a file."
- Use update_memory (not write_memory) to revise an existing entry.
- Set weights deliberately: 1.0 for critical policies, 0.5-0.7 for
  nice-to-know context.
```

This is how the agent "knows" that MemoryHub is where it should store and retrieve memories. The rule is an instruction baked into the system prompt, at the same level as the project's CLAUDE.md and any other rules. The agent treats it the same way it treats any other project instruction -- it's not optional guidance, it's a directive.

The rule also tells the agent *when* to store memories. It doesn't say "store everything." It says: write preferences, decisions, architectural choices, and workflow patterns. Skip ephemeral actions. The agent exercises judgment about whether a given piece of information crosses that threshold. There is no automatic extraction pipeline -- the agent is the extraction pipeline.

#### 2. The SessionStart hook: pre-loaded context

Rules tell the agent what to do, but the agent would still need to spend tool calls searching for relevant memories at the start of every session. The SessionStart hook eliminates that cost.

Claude Code supports hooks in `.claude/settings.json` that run shell commands on session events. MemoryHub registers a hook for `startup`, `compact`, and `clear` events:

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
      }
    ]
  }
}
```

When a session starts, Claude Code runs `load-memories.sh`. The script reads the API key from `~/.config/memoryhub/api-key`, calls the CLI to search for relevant project memories, and prints the results to stdout. Claude Code captures that stdout and injects it into the conversation context before the agent sees the first user message.

The output uses a tagged format that the rule file references:

```
<memoryhub-context project="memory-hub">
- FastAPI is the preferred web framework for new Python projects.
- Use Podman, not Docker; Containerfile, not Dockerfile.
- Deploy scripts must run in main conversation context, never sub-agents.
- The MCP server uses the compact tool profile by default.
- Python is the primary language for AI/ML work and backend services.
</memoryhub-context>
```

No memory IDs, no timestamps, no weights. Just the content the agent needs. This is deliberate: structural metadata in the context window activates model reasoning about memory management instead of the user's task. The compact format keeps the agent focused on doing work, not managing its own memory infrastructure.

The hook completes in under a second (~0.3s, well within the 5s timeout). On failure (missing credentials or CLI, unreachable server, expired key), it injects a `<memoryhub-context>` warning with the reason and a `memoryhub doctor` suggestion, then exits successfully so the session can start. The generated rule tells the agent that this warning means no memories were loaded and to use the manual tool flow when memory is needed.

#### 3. The MCP tools: mid-session operations

The first two mechanisms handle session startup. For everything else -- searching for new context, writing memories, updating existing ones, reporting contradictions -- the agent uses MCP tools.

When the MCP server is configured in Claude Code's settings, Claude Code discovers its tools at startup and makes them available in the agent's tool list. The agent sees tool descriptions like:

```
register_session(api_key)
  Register this session with your API key. Call this once at the start
  of every conversation to establish your identity.

memory(action, query?, content?, scope?, ...)
  All-in-one memory operations. Call register_session first.
  Read actions: search, list, read, similar, relationships, ...
  Write actions: write, update, delete, set_focus, relate, ...
```

The agent calls these tools the same way it calls any other tool -- `Read`, `Bash`, `Edit`. The MCP server handles authentication, scope enforcement, and storage. The agent doesn't know or care that memories are stored in PostgreSQL with pgvector embeddings; it just calls `memory(action="write", content="...", scope="user")` and gets a confirmation.

### What triggers a memory write

Nothing triggers a write automatically. The rule file gives the agent guidelines, and the agent decides. In practice, the agent writes a memory when it recognizes that information from the current conversation will be useful in a future session. Common triggers:

- The user states a preference ("use Podman, not Docker")
- A non-obvious decision is made ("we chose pgvector because PostgreSQL was already in the stack")
- A workflow pattern is established ("deploy scripts must never run in sub-agents")
- A lesson is learned the hard way ("file permissions must be 644 before container builds")
- The user explicitly says "remember this"

The agent does *not* write memories for:

- Ephemeral actions ("I read the README," "I ran pytest")
- Things already captured in committed documentation (CLAUDE.md, README)
- Transient debugging context that won't matter next session
- Conversation logistics ("the user asked me to explain X")

The decision is always the agent's. Different agents (or the same agent in different sessions) may make different judgments about the same information. This is by design -- MemoryHub provides the infrastructure and the guidelines, not a rigid extraction pipeline.

### The session lifecycle

A typical session flow:

1. Session starts. Claude Code runs `load-memories.sh`, which searches MemoryHub and prints a `<memoryhub-context>` block.
2. Claude Code loads `.claude/rules/memoryhub-loading.md` into the system prompt.
3. The agent sees both: pre-loaded memories as context, and instructions about how to manage memory.
4. The user asks a question. The agent uses pre-loaded memories to inform its response.
5. Mid-session, the user pivots to a new subsystem. The agent detects the pivot (per the rule), calls `memory(action="search", query="new topic")`, and *adds* the results to its working set -- it does not replace it, because the prior topic may return.
6. The user makes a decision worth remembering. The agent calls `memory(action="write", content="...", scope="user")`.
7. Session ends. Memories persist in MemoryHub. The next session (possibly days later, possibly by a different agent) picks them up via the hook.

### Setting it up in a new project

Three commands:

```bash
pip install memoryhub-cli
memoryhub login
memoryhub config init
```

`memoryhub login` stores your API key and server URL in `~/.config/memoryhub/`. `memoryhub config init` runs an interactive wizard that asks about your project's session shape and generates `.memoryhub.yaml`, `.claude/rules/memoryhub-loading.md`, and the Claude Code startup hook. It also installs MemoryHub activity hooks in `.claude/settings.json` and `.codex/hooks.json`, using `.memoryhub/hooks/activity-hook.sh` as the shared runner.

The activity hooks give the agent a short summary of successful saves,
updates, and searches before a response, and remind it after 10 user turns
without a successful write. The summary uses local observations from the
current machine; it does not read prompts or memory contents. `SessionEnd`
records a local snapshot, which the next session's startup hook supplies to
the agent. See the [Hooks Integration Guide](hooks-integration.md) for the
host-specific setup and timestamp limits.

Commit `.memoryhub.yaml`, generated instructions, `.memoryhub/hooks/activity-hook.sh`, and the host hook configuration to your repository. Do not commit credentials or the local activity database; those stay in `~/.config/memoryhub/`.

After setup, the next Claude Code session in that project will automatically load relevant memories at startup and have the MCP tools available for mid-session operations.

### Where memory fits: agents have a lot of places to store things

A common question when people first see MemoryHub is: "If something is important enough to remember, why leave it up to the agent? Shouldn't we make memory storage deterministic?" The short answer is that deterministic storage already exists -- it's called a database. What the agent needs is something different.

#### The landscape of places to put information

An agent operating in an enterprise environment has access to many stores, each with a different purpose:

**Business systems of record.** Salesforce, ServiceNow, ERP, EHR, POS. These are authoritative sources for business data. A customer's account status lives in Salesforce. A patient's medication history lives in the EHR. An agent should *read* from these systems (often via RAG or MCP tools) but should never treat its own memory as a replacement for them. If the agent learns a customer's contract renewal date during a conversation, the right action is to update the CRM, not to write a memory about it.

**Knowledge bases and RAG.** Enterprise RAG, vector search over documentation, web search. These provide factual, curated information: product documentation, policy manuals, API references, regulatory text. The content is authored and maintained by humans or by dedicated curation pipelines. It's reference material, not experience.

**Project and harness configuration.** CLAUDE.md, AGENTS.md, SOUL.md (OpenClaw), `.cursorrules`. These are static, version-controlled instructions committed to a repository. They define how the agent should behave in this project: coding conventions, tool preferences, architectural constraints. They change when a human edits them and commits the change. They're not memories -- they're standing orders.

**Built-in agent memory.** Claude Code's MEMORY.md, ChatGPT's memory feature. These are per-user, per-tool memory stores built into a specific agent harness. They work well for personal preferences within that one tool but don't share across agents, don't have governance, and don't support organizational scoping.

**Agent episodic memory.** This is where MemoryHub sits. It stores what the agent *learned from experience*: preferences discovered during conversations, decisions made and why, workflow patterns that worked, lessons learned the hard way. It's not authoritative business data (that belongs in the system of record). It's not curated reference material (that belongs in the knowledge base). It's not static configuration (that belongs in CLAUDE.md). It's the experiential layer -- the things an agent picks up over time that make it better at its job.

#### Who writes the memory: the agent, a watcher, or both

Everything above describes the inline path: the working agent notices something worth remembering and writes it during the conversation. This works, but it has a cost. Every `memory(action="write")` call is a tool round-trip that the agent spends instead of doing work. For a coding agent mid-implementation, stopping to write a memory is a context switch.

The alternative is a watcher -- a second, lighter agent that observes the conversation asynchronously and proposes memories after the fact. Systems like Mem0, OpenClaw, and LibreChat's memory layer use variants of this pattern. MemoryHub supports it too, and the extraction pipeline design (issue #240) formalizes it as an SDK component that observes agent traces, identifies candidate memories, and writes them through the normal governed path.

The two approaches aren't mutually exclusive. In practice, the inline path handles the obvious cases -- the user says "remember this" or makes a decision the agent recognizes immediately. The watcher handles the subtler cases -- patterns that only become visible across multiple turns, or information the working agent was too focused to notice. Both write to the same store. Both go through the same governance (scope isolation, curation rules, version history). And both show up in the next session's retrieval, whether that retrieval happens via the hook or a tool call.

From MemoryHub's perspective, a memory written by a watcher agent is indistinguishable from one written by the working agent. The `owner_id` and `actor_id` fields track who wrote it, but the retrieval path doesn't care. When the hook runs at the next session start and searches for relevant memories, it returns whatever matches -- regardless of whether the original agent or a background watcher created the entry. The write path and the read path are decoupled by design.

This decoupling is important because it means you can start with the inline path (the agent writes its own memories, which is what MemoryHub does today) and layer on a watcher later without changing how retrieval works. The agent's rule file, the hook, the search tool -- none of them need to know that a watcher exists. They just see memories in the store.

#### At inference time, provenance disappears

At inference time, none of the distinctions above matter to the model. The LLM receives a JSON payload containing a system prompt and a conversation history. Every piece of context -- whether it came from MemoryHub, a RAG retrieval, a Salesforce query, CLAUDE.md, or a user message -- is just tokens in that payload. The model doesn't know or care where a token came from.

Provenance only matters if the developer chooses to signal it. When MemoryHub injects a `<memoryhub-context>` block, the agent can see that those tokens came from MemoryHub (because they're wrapped in a tag). When a Salesforce integration returns data in a `<salesforce_data>` block, the agent knows the source. But this is a developer choice, not a model capability. If you pasted the same text without the tags, the model would process it identically.

This means the real question isn't "where should I store this?" but "how should this information reach the context window?" Different stores have different retrieval characteristics:

- CLAUDE.md is loaded every session, unconditionally. Good for things every session needs.
- MemoryHub memories are loaded selectively, based on semantic relevance to the current task. Good for the long tail of context that matters sometimes.
- RAG results are loaded on-demand in response to a query. Good for factual lookups.
- Business system data is fetched when the agent needs it for a specific operation.

Each store has its own retrieval path into the context window. MemoryHub's path is: hook at session start (broad, semantic search) plus tool calls mid-session (targeted, on pivot). That path is optimized for experiential context -- things the agent learned that it doesn't know it'll need until a conversation makes them relevant.

For a concrete walkthrough showing how all of these sources get assembled into the actual JSON that goes to the LLM -- with code blocks for each source and the final API request -- see [Context Assembly at Inference Time](../design/context-assembly-at-inference.md).

#### The practical test

When deciding whether something belongs in MemoryHub versus somewhere else, the test is straightforward:

- Is it authoritative business data? Put it in the system of record.
- Is it curated reference material? Put it in the knowledge base.
- Is it a project-wide standard that every session needs? Put it in CLAUDE.md.
- Is it something the agent learned from experience that will help future sessions? That's a memory.

## Part 2: Integration reference

### Prerequisites

- **MCP endpoint**: `https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`
- **API key**: Obtain from the system administrator. Format: `mh-dev-<hex>`. Store at `~/.config/memoryhub/api-key` (mode 0600).
- **Transport**: Streamable HTTP (not SSE).

### Quick Start — 3 steps

> **Note:** These examples use the deprecated full-profile tool names (`search_memory`, `write_memory`). In the compact profile (default), use `memory(action="search", ...)` and `memory(action="write", ...)` instead. See [Tiered Integration Model](#tiered-integration-model) for profile details.

#### 1. Register your session

Call this **once at the start of every conversation**.

```
register_session(api_key="<your key>")
```

Returns your `user_id`, display `name`, accessible `scopes`, session `expires_at` timestamp, a list of your `projects` (with `memory_count` per project), and `quick_start` hints for next steps. All subsequent tool calls are scoped to your identity automatically.

**Session TTL:** Sessions expire after a configurable TTL (default 1 hour). The `expires_at` field tells you when. On expiry, call `register_session` again — you'll get a clear error directing you to re-register. Check TTL via `manage_session(action="status")`.

#### 2. Search for existing memories

```
search_memory(query="deployment preferences")
```

With project filter (restricts results to that project's memories):

```
search_memory(query="deployment preferences", project_id="my-project")
```

The `project_id` filter restricts project-scoped results to the specified project while still including user-scope and higher-scope memories. This filtering is reliable as of the #194 fix.

#### 3. Write a memory

```
write_memory(
    content="FastAPI is the preferred web framework for new services.",
    scope="project",
    project_id="my-project",
    project_description="Backend API service for customer onboarding",
    weight=0.8
)
```

If the project doesn't exist yet, it's **auto-created** and you're **auto-enrolled** on the first write. The `project_description` is set during auto-create and appears in `manage_project(action="list")` output.

### Tool Reference — What You Need

> The tables below use the **full-profile** tool names (e.g., `search_memory`, `write_memory`), now deprecated aliases. In the **compact profile** (default, `MEMORYHUB_TOOL_PROFILE=compact`), these are consolidated into a single `memory(action=...)` dispatcher — see [Tiered Integration Model](#tiered-integration-model) for details. Both forms work; the compact profile is recommended for frontier models.

| Tool | When to use |
|------|-------------|
| `register_session` | Start of every conversation |
| `search_memory` | Find relevant memories (semantic search) |
| `write_memory` | Store a preference, decision, or fact |
| `read_memory` | Expand a stub or get version history |
| `manage_project` | Discover, create, and manage projects and memberships |
| `manage_session(action="status")` | Check your auth state (lightweight whoami) |

#### Tools you probably won't need right away

| Tool | Purpose |
|------|---------|
| `update_memory` | Revise existing memory (preserves version history) |
| `delete_memory` | Remove a memory and its branches |
| `manage_curation(action="report_contradiction", ...)` | Flag a memory that conflicts with current reality |
| `manage_graph(action="create_relationship", ...)` | Link two memories (supports, contradicts, etc.) |
| `manage_graph(action="get_relationships", ...)` | Read links between memories |
| `manage_graph(action="get_similar", ...)` | Inspect near-duplicates flagged during write |
| `manage_curation(action="set_rule", ...)` | Tune duplicate-detection thresholds |
| `manage_session(action="set_focus", ...)` | Bias retrieval toward a topic across calls |
| `manage_session(action="focus_history", ...)` | View focus changes over time |

### Scopes

Memories have a scope that controls visibility:

| Scope | Visibility | When to use |
|-------|-----------|-------------|
| `user` | Only you | Personal preferences, workflow habits |
| `project` | Project members | Architecture decisions, project context |
| `campaign` | Campaign enrollees | Cross-project initiatives |
| `organizational` | Org-wide | Team standards, shared patterns |
| `enterprise` | Everyone | Mandated policies |

Most agent memories should be **`project`** scope with a `project_id`. Use `user` scope for personal preferences that shouldn't pollute the project.

### Weight Guidelines

Weight (`0.0`–`1.0`) controls how memories appear in search results:

| Weight | Use for |
|--------|---------|
| `1.0` | Critical policies, hard constraints |
| `0.8–0.9` | Strong preferences, architecture decisions |
| `0.5–0.7` | Useful context, nice-to-know |
| `0.1–0.3` | Low-priority, ephemeral observations |

### Common Patterns

#### Session startup

```python
# 1. Authenticate
register_session(api_key=key)

# 2. Load context for current work
search_memory(query="relevant topic", project_id="my-project")

# 3. Use returned memories to inform your work
```

#### Learning something worth remembering

```python
write_memory(
    content="The auth service requires RS256 keys, not HS256.",
    scope="project",
    project_id="my-project",
    weight=0.9
)
```

#### Checking if you're still authenticated

```python
manage_session(action="status")  # Returns user_id, name, scopes, authenticated
```

#### Discovering projects

```python
manage_project(action="list")  # Returns name, description, memory_count, is_member
manage_project(action="list", filter="all")  # Also shows open projects you could join
```

### Auto-Enrollment

You don't need to create projects or request membership ahead of time. When you write a project-scoped memory to a project that doesn't exist:

1. The project is created automatically
2. You are enrolled as a member
3. The response includes `auto_enrolled: {project_id, message}`

Subsequent writes to the same project skip enrollment (you're already a member).

### Tiered Integration Model

MemoryHub supports three integration paths, each optimized for a different
model capability tier. Choose based on your model's context budget and
tool-calling ability.

#### Which path should I use?

```
Do you control prompt assembly?
├── Yes → Path 1: Framework connector (SDK injection)
│         Best for: custom agents, small models, zero tool-token overhead
│
└── No
    ├── Does your host support hooks? (e.g., Claude Code)
    │   └── Yes → Hook-based injection + compact MCP profile
    │             Best for: Claude Code, lowest latency, content-only startup
    │
    └── Does your model handle action-dispatch well?
        ├── Yes → Path 3: Compact MCP profile (frontier models)
        │         Best for: Claude, GPT-4, low tool-token overhead
        │
        └── No → Path 2: Full MCP profile (mid-range models)
                  Best for: Llama 70B, Mixtral, explicit per-tool schemas
```

| Model tier | Integration path | Tool tokens | Tools |
|---|---|---|---|
| Small (7B, Granite 8B) | Framework connector (`self.memory`) | 0 | n/a |
| Mid-range (Llama 70B, Mixtral) | Full MCP profile (`MEMORYHUB_TOOL_PROFILE=full`) | ~7,500 | 12 |
| Frontier (Claude, GPT-4) | Compact MCP profile | ~1,200 | 4 |

#### Path 1: Framework connector (small models)

For models with limited context windows (8K–16K tokens), MCP tool
definitions alone can consume a significant fraction of the budget. The
framework connector path avoids this entirely: memories are loaded via the
SDK at session startup and injected as a text prefix — no tool tokens at
all.

Example using the fipsagents framework:

```python
from fipsagents.memory import build_memory_prefix

memories = self.memory.search("deployment preferences", project_id="my-project")
prefix = build_memory_prefix(memories)
# Inject prefix into system prompt or first message
```

See [`examples/tier1_sdk_injection.py`](../examples/tier1_sdk_injection.py) for
a complete standalone script showing this pattern.

**Requirements:**
- SDK v0.14.0+ (`pip install memoryhub>=0.14.0`). Earlier versions lack
  compact output support and hook integration.

**Known issue:** The fipsagents `build_memory_prefix()` default calls
`search("")`, which MemoryHub rejects (empty queries are not allowed).
Pass a non-empty query, or catch the error and fall back to no memories.

**Limitations:**
- Memories are read-only from the model's perspective (the framework loads
  them; the model doesn't call tools to retrieve them).
- Small models may not reliably follow prefix-injected memories as hard
  constraints. RAG-style extraction tends to work better (see
  [Granite 8B findings](#granite-8b-findings) below).

#### Hook-based startup injection (recommended for Claude Code)

The recommended approach for Claude Code and other MCP hosts that support
hooks, described in detail in [Part 1](#2-the-sessionstart-hook-pre-loaded-context). Memories are loaded at session start by a shell hook and injected
as a `<memoryhub-context>` block in the conversation context -- zero tool
calls, zero latency during the conversation. Set it up with
`memoryhub config init`.

**When to use this path:**
- Claude Code projects (primary use case)
- Any MCP host with SessionStart hook support
- When you want zero-tool-call memory at startup

This path complements the compact MCP profile (Path 3) -- hooks handle
read-at-startup, MCP tools handle writes and mid-session searches.

#### Path 2: Full MCP profile (mid-range models)

Twelve flat-parameter tools, each with its own JSON schema. Mid-range models
benefit from explicit parameter schemas that make each operation
independently discoverable. On the compact profile these names remain
available as deprecated aliases.

Set the profile via environment variable on the MCP server deployment:

```
MEMORYHUB_TOOL_PROFILE=full
```

Tools: `register_session`, `search_memory`, `write_memory`, `read_memory`,
`update_memory`, `delete_memory`, `list_memory`, `manage_session`,
`manage_graph`, `manage_curation`, `manage_project`, `thread`.

Full-profile search and list tools return verbose output (full metadata) by default for backward compatibility. Pass `verbose=false` to get compact content-only results.

#### Path 3: Compact MCP profile (frontier models, default)

Four tools: `register_session`, a `memory` dispatcher (28 actions for
memory operations), a `thread` dispatcher (9 actions for conversation
persistence), and `admin_memory` for administrative operations. Frontier
models handle the action-dispatch pattern well, and the reduced tool count
leaves more context for the actual conversation.

```
MEMORYHUB_TOOL_PROFILE=compact   # default
```

**Setup for Claude Code:** Run `memoryhub config init` in your project root
to scaffold hooks and the loading rule. This pairs hook-based startup
injection with the compact MCP profile for mid-session operations.

Compact-profile `search` and `list` actions return content-only results by default: each entry contains `{id, content, result_type}` with no structural metadata. This is complementary to [hook-based startup injection](#hook-based-startup-injection-recommended-for-claude-code) which is also content-only. Pass `options: {verbose: true}` when full metadata is needed (e.g., for curation decisions that depend on weight or scope).

#### Why not the minimal profile for small models?

The minimal profile (5 tools: `register_session`, `search_memory`,
`write_memory`, `read_memory`, `thread`) was designed as a middle ground for small
models. In practice, even 5 tools are too heavy for 7B context budgets:
`search_memory`'s docstring alone is ~2K tokens. The framework connector
path is the better choice for small models because it uses zero tool
tokens.

The minimal profile remains available (`MEMORYHUB_TOOL_PROFILE=minimal`)
for cases where a small model needs write-back capability and the token
budget can tolerate it.

#### Granite 8B findings

Testing with Granite 8B on RHOAI validated the framework connector path
but surfaced a grounding gap: small models don't reliably treat
prefix-injected memories as constraints. When memories are injected as a
block of context at the start of the conversation, the model may
acknowledge them but not consistently apply them to answers.

This is an agent-design problem, not a MemoryHub problem. Mitigations:

- **RAG-style extraction** — retrieve memories relevant to the current question and weave them into the answer, rather than relying on the model to internalize a block of prefixed facts.
- **Structured prompting** — explicitly reference specific memories in the prompt (e.g., "According to memory X, the policy is Y").
- **Fewer, higher-weight memories** — filter to only the most relevant memories rather than injecting everything.

### Tips

- **Be specific in search queries**: `"container runtime preferences"` works better than `"containers"`.
- **Set project_description on first write**: It shows up in `manage_project(action="list")` and helps other agents understand the project.
- **Keep memories concise and self-contained**: Another agent should understand the memory without additional context.
- **Don't write trivial things**: Skip "user asked me to read a file." Do write preferences, decisions, architecture choices.
- **Use `manage_curation(action="report_contradiction", ...)`** when you notice behavior contradicting a stored memory.
- **Use `update_memory`** (not `write_memory`) to revise an existing memory — it preserves version history.
