# How Agents Use MemoryHub

MemoryHub doesn't extract memories automatically. It injects instructions and context into the agent's prompt, gives the agent tools to read and write memories, and trusts the agent's judgment about what's worth persisting. This document explains the concrete mechanism: what text gets injected, where it appears, and how the agent decides to act on it.

For the API and tool reference, see the [Agent Integration Guide](agent-integration-guide.md). For the hook setup walkthrough, see the [Hooks Integration Guide](hooks-integration.md).

## The three injection points

MemoryHub establishes itself in the agent's context through three mechanisms, each operating at a different layer of Claude Code's architecture. Together, they ensure the agent knows MemoryHub exists, has relevant memories pre-loaded, and has tools available to read and write more.

### 1. The rule file: instructions the agent must follow

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

### 2. The SessionStart hook: pre-loaded context

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
- The MCP server uses the compact tool profile (2 tools) by default.
- Python is the primary language for AI/ML work and backend services.
</memoryhub-context>
```

No memory IDs, no timestamps, no weights. Just the content the agent needs. This is deliberate: structural metadata in the context window activates model reasoning about memory management instead of the user's task. The compact format keeps the agent focused on doing work, not managing its own memory infrastructure.

The hook completes in under a second and exits silently on any error (missing CLI, unreachable server, expired key). A failed hook never blocks a session from starting. The rule file includes a fallback path: if no `<memoryhub-context>` block is present, the agent falls back to manual tool calls.

### 3. The MCP tools: mid-session operations

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

## What triggers a memory write

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

## How it all fits together

A typical session flow:

1. Session starts. Claude Code runs `load-memories.sh`, which searches MemoryHub and prints a `<memoryhub-context>` block.
2. Claude Code loads `.claude/rules/memoryhub-loading.md` into the system prompt.
3. The agent sees both: pre-loaded memories as context, and instructions about how to manage memory.
4. The user asks a question. The agent uses pre-loaded memories to inform its response.
5. Mid-session, the user pivots to a new subsystem. The agent detects the pivot (per the rule), calls `memory(action="search", query="new topic")`, and adds results to its working set.
6. The user makes a decision worth remembering. The agent calls `memory(action="write", content="...", scope="user")`.
7. Session ends. Memories persist in MemoryHub. The next session (possibly days later, possibly by a different agent) picks them up via the hook.

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

## Where memory fits: agents have a lot of places to store things

A common question when people first see MemoryHub is: "If something is important enough to remember, why leave it up to the agent? Shouldn't we make memory storage deterministic?" The short answer is that deterministic storage already exists -- it's called a database. What the agent needs is something different.

### The landscape of places to put information

An agent operating in an enterprise environment has access to many stores, each with a different purpose:

**Business systems of record.** Salesforce, ServiceNow, ERP, EHR, POS. These are authoritative sources for business data. A customer's account status lives in Salesforce. A patient's medication history lives in the EHR. An agent should *read* from these systems (often via RAG or MCP tools) but should never treat its own memory as a replacement for them. If the agent learns a customer's contract renewal date during a conversation, the right action is to update the CRM, not to write a memory about it.

**Knowledge bases and RAG.** Enterprise RAG, vector search over documentation, web search. These provide factual, curated information: product documentation, policy manuals, API references, regulatory text. The content is authored and maintained by humans or by dedicated curation pipelines. It's reference material, not experience.

**Project and harness configuration.** CLAUDE.md, AGENTS.md, SOUL.md (OpenClaw), `.cursorrules`. These are static, version-controlled instructions committed to a repository. They define how the agent should behave in this project: coding conventions, tool preferences, architectural constraints. They change when a human edits them and commits the change. They're not memories -- they're standing orders.

**Built-in agent memory.** Claude Code's MEMORY.md, ChatGPT's memory feature. These are per-user, per-tool memory stores built into a specific agent harness. They work well for personal preferences within that one tool but don't share across agents, don't have governance, and don't support organizational scoping.

**Agent episodic memory.** This is where MemoryHub sits. It stores what the agent *learned from experience*: preferences discovered during conversations, decisions made and why, workflow patterns that worked, lessons learned the hard way. It's not authoritative business data (that belongs in the system of record). It's not curated reference material (that belongs in the knowledge base). It's not static configuration (that belongs in CLAUDE.md). It's the experiential layer -- the things an agent picks up over time that make it better at its job.

### Why memory can't be deterministic

The question "shouldn't we make this deterministic?" assumes we can define in advance what's worth remembering. But the value of a piece of information as a memory depends on context that only the agent has at the moment of the conversation.

When a user says "use Podman, not Docker," is that a memory or a CLAUDE.md entry? It depends. If it's a project-wide standard, it belongs in CLAUDE.md (and someone should put it there). If it's a personal preference the user just expressed for the first time, it's a memory. If the project's CLAUDE.md already says to use Podman, there's nothing to remember at all. The agent has to evaluate the current context -- what's already documented, what scope this applies to, whether it's new information or a restatement -- and make a judgment call.

A deterministic rule like "always store user preferences" would flood the memory with noise. A rule like "store preferences that aren't already documented" requires the agent to check what's documented, which is itself a judgment. The agent is the only entity with enough context to make the call, so the system gives it guidelines and trusts it to apply them.

### Who writes the memory: the agent, a watcher, or both

Everything above describes the inline path: the working agent notices something worth remembering and writes it during the conversation. This works, but it has a cost. Every `memory(action="write")` call is a tool round-trip that the agent spends instead of doing work. For a coding agent mid-implementation, stopping to write a memory is a context switch.

The alternative is a watcher -- a second, lighter agent that observes the conversation asynchronously and proposes memories after the fact. Systems like Mem0, OpenClaw, and LibreChat's memory layer use variants of this pattern. MemoryHub supports it too, and the extraction pipeline design (issue #240) formalizes it as an SDK component that observes agent traces, identifies candidate memories, and writes them through the normal governed path.

The two approaches aren't mutually exclusive. In practice, the inline path handles the obvious cases -- the user says "remember this" or makes a decision the agent recognizes immediately. The watcher handles the subtler cases -- patterns that only become visible across multiple turns, or information the working agent was too focused to notice. Both write to the same store. Both go through the same governance (scope isolation, curation rules, version history). And both show up in the next session's retrieval, whether that retrieval happens via the hook or a tool call.

From MemoryHub's perspective, a memory written by a watcher agent is indistinguishable from one written by the working agent. The `owner_id` and `actor_id` fields track who wrote it, but the retrieval path doesn't care. When the hook runs at the next session start and searches for relevant memories, it returns whatever matches -- regardless of whether the original agent or a background watcher created the entry. The write path and the read path are decoupled by design.

This decoupling is important because it means you can start with the inline path (the agent writes its own memories, which is what MemoryHub does today) and layer on a watcher later without changing how retrieval works. The agent's rule file, the hook, the search tool -- none of them need to know that a watcher exists. They just see memories in the store.

### At inference time, provenance disappears

Here's the thing that clarifies most of the confusion: at inference time, none of these distinctions matter to the model. The LLM receives a JSON payload containing a system prompt and a conversation history. Every piece of context -- whether it came from MemoryHub, a RAG retrieval, a Salesforce query, CLAUDE.md, or a user message -- is just tokens in that payload. The model doesn't know or care where a token came from.

Provenance only matters if the developer chooses to signal it. When MemoryHub injects a `<memoryhub-context>` block, the agent can see that those tokens came from MemoryHub (because they're wrapped in a tag). When a Salesforce integration returns data in a `<salesforce_data>` block, the agent knows the source. But this is a developer choice, not a model capability. If you pasted the same text without the tags, the model would process it identically.

This means the real question isn't "where should I store this?" but "how should this information reach the context window?" Different stores have different retrieval characteristics:

- CLAUDE.md is loaded every session, unconditionally. Good for things every session needs.
- MemoryHub memories are loaded selectively, based on semantic relevance to the current task. Good for the long tail of context that matters sometimes.
- RAG results are loaded on-demand in response to a query. Good for factual lookups.
- Business system data is fetched when the agent needs it for a specific operation.

Each store has its own retrieval path into the context window. MemoryHub's path is: hook at session start (broad, semantic search) plus tool calls mid-session (targeted, on pivot). That path is optimized for experiential context -- things the agent learned that it doesn't know it'll need until a conversation makes them relevant.

### The practical test

When deciding whether something belongs in MemoryHub versus somewhere else, the test is straightforward:

- Is it authoritative business data? Put it in the system of record.
- Is it curated reference material? Put it in the knowledge base.
- Is it a project-wide standard that every session needs? Put it in CLAUDE.md.
- Is it something the agent learned from experience that will help future sessions? That's a memory.
