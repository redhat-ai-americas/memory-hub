# Agent Memory Ergonomics — Design

How memory-hub feels from the consuming agent's perspective, and what design changes would make it work better. This doc covers two related concerns: the *shape* of `search_memory` responses (branches, stubs, modes), and the *policy* of when an agent should call memory-hub at all (loading patterns, session focus, project config).

**Status: Design.** Captured from a working session on 2026-04-07 where the consuming agent walked through the current behavior and proposed targeted changes. Implementation tracked via the issues linked in the [Implementation Candidates](#implementation-candidates) section.

**Companion documents** in this folder:
- [`overview.md`](overview.md) — Narrative landing page for the effort.
- [`open-questions.md`](open-questions.md) — Tracked list of unresolved design questions, with what would resolve each.
- [`research/fastmcp-3-push-notifications.md`](research/fastmcp-3-push-notifications.md) — Evidence behind the Pattern E (real-time push) feasibility claims.
- [`research/two-vector-retrieval.md`](research/two-vector-retrieval.md) — Ranking math options for session-focus biasing (#58).
- [`research/pivot-detection.md`](research/pivot-detection.md) — Server-side vs agent-side pivot detection for Pattern C (#58 adjacent).

## Context

memory-hub provides 12 MCP tools, but tools without policy don't get used well. Two distinct problems shape the agent experience today:

1. **Response shape.** When an agent calls `search_memory`, what comes back determines whether the agent has the context it needs in one round-trip, or has to make follow-up calls, or wastes tokens on things it didn't need. Today's response is "full inline content for everything matching, ranked by similarity, including branches as independent top-level results." That works at the current scale (~30-50 memories per user) but has rough edges that will get worse.
2. **Loading policy.** Tools are mechanism. The *when* and *how* of calling them lives in agent instructions (CLAUDE.md, `.claude/rules/`, system prompts). Today every project hand-writes its own rule for memory loading. memory-hub could ship a configuration moment that generates the right rule for the project's workflow shape.

These are separate problems but they interact. A project that runs broad multi-domain sessions wants both eager loading *and* full content in responses. A project that runs tightly-scoped single-thread sessions wants lazy loading *and* possibly stubbed responses with on-demand expansion. Configuring one without the other leaves money on the table.

## Search Response Shape

### Branch Handling

**Current behavior.** When `search_memory` returns results, branches (rationale/provenance children of parent memories) appear as their own top-level entries with `parent_id` populated. They are ranked by their own similarity score, which means the rationale for a high-relevance parent might appear at result position #17 with a much lower score, separated from its parent by 15 unrelated entries.

**Problem.** The agent has to mentally re-associate branches with parents by walking `parent_id`. When the parent itself is a strong hit, the branch arriving as a separate ranked entry is noise — the agent already saw the parent and knows it has rationale (the `has_rationale: true` flag is right there). When the branch is independently relevant (e.g., a query about "rootless containers" hits the Podman rationale more strongly than the parent "Prefers Podman over Docker"), the current behavior is correct: surface the branch with a pointer to the parent.

**Proposal.** Change the default so branches are not surfaced as siblings of their parent in the same result set. If the parent is in the result set, trust the `has_rationale` / `has_children` flags — the agent can call `read_memory` to expand if it decides the rationale is load-bearing. If the branch is independently relevant *and the parent is not in the result set*, surface the branch as a top-level result (current behavior, correct case). Add an optional `include_branches: true` parameter for forensic/audit workflows that want everything.

If branches *are* returned alongside their parent (because the caller asked), nest them under the parent in the response structure rather than ranking them as siblings:

```json
{
  "results": [
    {
      "id": "...",
      "content": "...",
      "has_rationale": true,
      "branches": [
        {"id": "...", "branch_type": "rationale", "content": "..."}
      ]
    }
  ]
}
```

### Stub Policy

**Current behavior.** The tool docstring describes weight-based stubbing: high-weight memories return as full content, low-weight memories return as stubs. In practice (~30-50 record store, mostly weight ≥0.8) every result returns as full content.

**A proposal that's worth pushing back on.** Size-based stubbing — "any memory over N bytes returns as a topic-label stub, fetch full content if you want it" — sounds efficient but is risky:

- **Topic-label stubs are too lossy.** A label like `[stub]"database type"` doesn't tell the agent whether the memory covers vector search, graph queries, FIPS rationale, or embedding dimensions. The agent either fetches every stub defensively (worse than full) or skips relevant memories (silent failure).
- **The most token-dense memories are often the most fact-dense.** Multi-fact memories like "Deployment lessons (4 distinct items)" stubbed to `[stub]"deployment"` would cause the agent to skip them when one of the four lessons was exactly what they needed.
- **Size and importance are orthogonal.** "User's name is Wes Jackson" is short and load-bearing. "Dashboard has six panels" is longer and decorative. Stubbing by size protects the wrong things.

**Asymmetry that matters.** When the agent skips a relevant memory because it judged a stub wrong, neither the agent nor the user notices — the agent just gives a worse answer. When the agent wastes tokens on an irrelevant full memory, the waste is visible and bounded. Given that asymmetry, the system should err on the side of more content with smarter pagination, not aggressive stubbing.

**Proposal.**

1. **Keep weight-based stubbing**, but improve the stub format. Current snippet+metadata is good (it's like a search-engine result preview). A topic-label-only form would be a regression.
2. **Add a token-budget cap** on the entire response. `max_response_tokens: 4000` packs as many full memories as fit in budget, then degrades remaining results to stubs. This protects against responses blowing up regardless of individual memory size.
3. **Add an explicit `mode` parameter** for cases where the agent knows what it wants:
   - `mode: "full"` (default) — current behavior, full for high-weight, stub for low-weight
   - `mode: "index"` — stub everything regardless of weight; for exploratory "what's in here?" searches and audit/cleanup workflows
   - `mode: "full_only"` — never stub even for low-weight matches; for when the agent is answering a specific question and wants zero round-trips
4. **Optional: very-large memory preview form.** For memories above a hard threshold (5000+ chars — multi-paragraph design dumps), default to a richer "preview" stub: first paragraph or two, not a label. Treat as a preview rather than a topic.

## Session Focus and Retrieval Biasing

### Single-Thread vs Swarm Projects

Two project shapes drive opposite retrieval needs:

**Single-thread projects** work on one big thing at a time. memory-hub itself is one of these — a session is usually about deployment, or about MCP tool design, or about UI work, but rarely all three. For these projects, loading every project-scope memory at session start is wasteful: most of them will never be referenced.

**Swarm / needle-in-haystack projects** run many agents looking across the entire knowledge surface. Every project-scope memory is potentially relevant. For these, eager loading is correct because the cost of a missed cross-domain connection is higher than the token cost of holding everything in context.

A project-level config knob should let the project declare which mode it operates in.

### Two-Vector Retrieval

**Mechanism for "knowing what we're going to talk about".** Three sources, in increasing order of robustness:

1. **Inferred from environment** — working directory, current git branch, staged files, recent commits. For memory-hub itself, sitting in `memory-hub-mcp/` with deployment scripts staged is a strong signal. Free, no user effort, brittle when wrong.
2. **Inferred from the first user turn** — the opening prompt usually telegraphs intent. "Help me fix the Dockerfile" → infrastructure. Robust but late: the agent has already initialized before the first turn.
3. **Declared at session start** — explicit `register_session(focus="deployment")` or a project-level config that sets a default focus. Most reliable, requires the most ceremony.

In practice these compose: project config sets the *mode* (focused vs broad); within focused mode, the topic comes from declaration → first-turn inference → environment inference, in that order.

**Mechanism for filtering.** Tag-based topic labels (`topic: deployment`) are brittle — someone has to decide where "deployment" ends and "infra" begins, and tags drift from content over time. The store already has pgvector. The cleaner approach is **two-vector retrieval**:

- At session start, embed the focus string into a stable "session vector".
- Subsequent `search_memory` calls combine the immediate query vector with the session vector (weighted sum, or rerank-after-recall).
- Out-of-focus memories aren't excluded — they're down-weighted unless the immediate query is strong enough to surface them anyway.
- Topic shifts within the session degrade gracefully because the immediate query still drives most of the ranking.

A `session_focus_weight: 0.4` knob controls the bias strength.

### Coverage Gap Risk

Focused mode creates a **contradiction-detection coverage gap.** If today's session is scoped to "deployment" and partway through the user makes a UI-architecture decision that contradicts a UI memory the agent never loaded, the agent won't catch it. `report_contradiction` only fires on memories in the working set.

For tightly-scoped single-thread projects this is usually fine — the user genuinely won't touch unrelated areas. But it's a tradeoff worth surfacing explicitly at config time, not discovering later. The config dialog should ask the user directly: *"Do you value cross-domain contradiction detection over token efficiency?"*

## Loading Patterns

There are three load patterns worth supporting, plus a corner case. The *wording* of the rule matters more than the policy name — vague instructions produce inconsistent agent behavior.

### Pattern A: Eager

> At session start, call `register_session()`, then immediately call `search_memory(query="", mode="index", max_results=50)` to load the full working set headers. Hold all results in context for the entire session.

**Best for:** broad/swarm projects, or projects where session scope is unpredictable. Token cost is paid upfront whether the session is short or long. Fewer in-session searches because everything is already loaded.

### Pattern B: Lazy after first turn

> At session start, call `register_session()` only. Do NOT search yet. After the first user message, derive a 1-2 sentence intent summary from it and call `search_memory(query=<intent>)`. Use those results as your working set.

**Best for:** tightly-scoped single-thread projects. Matches token cost to actual conversation depth. Ambiguous opening turns ("can you take a look at this?") produce vague queries that miss relevant memories — that's the failure mode.

### Pattern C: Lazy + pivot rebias

> Pattern B, plus: watch for pivots. A pivot is when (a) the user changes subsystems, (b) the user references a concept not in your working set, or (c) the user explicitly says "let's switch to." When you detect a pivot, call `search_memory` with a query for the new topic and ADD the results to your working set — don't replace.

**Best for:** long sessions that span topics, debugging sessions where the problem domain shifts as understanding grows. The current `.claude/rules/memoryhub-integration.md` "search again when topic shifts" rule is an informal version of this pattern.

**Pivot detection has to be specified, not assumed.** "Watch for pivots" alone produces inconsistent agent behavior. The three concrete triggers (subsystem change, unknown concept, explicit switch) give the agent something to actually check against.

### Pattern D (corner case): Just-in-time

> Call `search_memory` only when you encounter a question whose answer might be in memory. Never load eagerly.

Pure on-demand. Zero startup cost. Maximum risk of missing context. Probably right only for one-shot tooling sessions where the agent has a single narrow task.

**Pattern E (real-time push) composes with any of A-D rather than replacing them.** It's covered in its own section below because it changes the transport relationship, not just the load timing.

## Real-Time Push (Pattern E)

Patterns A-D all describe *pull* behavior: the agent decides when to call `search_memory` or `read_memory`. For active agent swarms where one agent's write is immediately relevant to other connected agents, pull-only patterns have a latency floor — the next-pull interval. Pattern E adds a server-push channel: when a memory is written, the server broadcasts a notification to subscribed agents so they don't have to wait for their next pull.

This pattern is **additive**, not exclusive. An agent can combine Pattern A (eager pull at session start) with live subscription (push for updates after that), or Pattern C (lazy pull with rebias) with live subscription. Push-only without any pull is a degenerate case worth mentioning — some swarm scenarios might use it where the server-side focus filter decides what the agent cares about — but most agents will combine push with one of the pull patterns.

### Feasibility

FastMCP 3 supports this end-to-end via its streamable-http transport and the existing `ResourceUpdatedNotification` primitive. The distributed notification queue (Valkey-backed) that already powers task status updates is reusable for memory broadcasts. The key open verification item is the subscriber-lifecycle hook for pure-listener agents that don't submit tasks.

See [`research/fastmcp-3-push-notifications.md`](research/fastmcp-3-push-notifications.md) for the full investigation, source pointers, and the items that still need in-cluster verification before implementation.

### What memory-hub needs on top of FastMCP's primitives

1. **Agent session registry.** A Valkey set (e.g., `memoryhub:active_sessions`) populated when an agent calls `register_session` and torn down via session-close hooks. Without this, there's no way to enumerate "all connected agents" for broadcast.
2. **Broadcast helper.** A `broadcast_to_sessions(notification, session_ids)` function that wraps `push_notification` and iterates the registry. Cost is O(N) per write — fine up to ~100 agents, may need rethinking at higher fanout.
3. **Hooks in mutating tools.** `write_memory`, `update_memory`, and `delete_memory` need post-persistence broadcast calls.
4. **Subscriber lifecycle for pure-listener agents.** FastMCP currently spins up notification subscribers when a task is submitted. Agents that don't submit tasks but want to listen for broadcasts need a subscriber loop started at session-registration time. This needs verification against FastMCP internals before committing to the design.

### Design coupling with session focus

Server-push and session-focus retrieval are solving the same scoping problem from opposite ends. On the pull side, the session focus vector down-weights out-of-scope memories so the agent doesn't load them. On the push side, the same focus vector should pre-filter broadcasts so an agent that declared `focus="auth"` doesn't get notifications about UI writes.

This makes the session-focus-vector work a **hard prerequisite** for Pattern E — the broadcast filter reuses the embedding and weight knob already established for retrieval. The two issues should be designed and reviewed together even if they ship in separate increments.

### Config knobs Pattern E adds

```yaml
memory_loading:
  live_subscription: false       # subscribe to push notifications from other writers
  push_payload: uri_only         # or: full_content (custom non-spec notification)
  push_filter_weight: 0.6        # how strictly to filter broadcasts by session focus (0.0-1.0)
  push_transport: queue          # or: pubsub
```

For memory-hub itself (single developer, low fanout, no swarm), `live_subscription: false` is the right default. For a swarm project, `live_subscription: true, push_transport: queue, push_filter_weight: 0.6`.

## Project Configuration

### memory-hub config CLI

A setup command (`memory-hub config init`) walks the project through three or four questions and writes two files: a machine-readable YAML config and a hand-readable rule file the agent reads. Subsequent runs of `memory-hub config` regenerate the rule file from the YAML, keeping them in sync.

Sample interaction:

```text
$ memory-hub config init

What's this project's typical session shape?
  1) One topic per session, narrow scope (focused)
  2) Multiple topics per session, broad context needed (broad)
  3) Sessions evolve — start narrow, may pivot (adaptive)
Choice [1]: 3

How should memories load?
  1) Eager — load at session start (best for broad)
  2) Lazy — load after first user turn (best for focused)
  3) Lazy + rebias on pivot (best for adaptive)
Choice [auto]: 3

How should session focus be inferred?
  1) Declared — agent will ask
  2) Inferred from working directory
  3) Inferred from first user turn
  4) Auto (try inference, fall back to ask)
Choice [4]: 4

Cross-domain contradiction detection:
  Focused mode loads only memories matching session topic. If you make
  a decision in this session that contradicts a memory from a different
  topic, the agent won't catch it. You can value this coverage over
  token efficiency by switching to broad mode.

  Keep contradiction detection across all domains? [y/N]: N

✓ Wrote .memoryhub.yaml
✓ Wrote .claude/rules/memoryhub-loading.md
```

### .memoryhub.yaml schema

```yaml
memory_loading:
  mode: focused                  # or: broad
  pattern: lazy_with_rebias      # or: eager, lazy, jit
  focus_source: auto             # or: declared, directory, first_turn
  session_focus_weight: 0.4      # how strongly the session vector biases retrieval (0.0-1.0)
  on_topic_shift: rebias         # or: warn, ignore
  cross_domain_contradiction_detection: false

  # Pattern E: real-time push (composes with the pull pattern above)
  live_subscription: false       # subscribe to push notifications from other writers
  push_payload: uri_only         # or: full_content (custom non-spec notification)
  push_filter_weight: 0.6        # filter broadcasts by session focus (0.0-1.0)
  push_transport: queue          # or: pubsub

retrieval_defaults:
  max_results: 15
  max_response_tokens: 4000
  default_mode: full             # or: index, full_only
```

For memory-hub itself, the right defaults are `mode: focused, pattern: lazy_with_rebias, focus_source: auto, session_focus_weight: 0.4, live_subscription: false`. For a swarm project, `mode: broad, pattern: eager, session_focus_weight: 0.0, live_subscription: true, push_transport: queue`.

### Generated rule file

The CLI generates `.claude/rules/memoryhub-loading.md` from the YAML. The current hand-written `.claude/rules/memoryhub-integration.md` is essentially a manual version of this. The generated file would replace it (or live alongside it for behaviors the generator doesn't yet cover).

For Pattern C the generated rule looks something like:

```markdown
## MemoryHub Loading Pattern: Lazy + Rebias

### At session start
Call `register_session(api_key=...)` to authenticate. Do NOT call `search_memory` yet.

### After the first user turn
Derive a 1-2 sentence summary of the user's intent. Call `search_memory(query=<summary>, max_results=15)`. Use the returned memories as your working set.

### During the session
Watch for topic pivots. A pivot is any of:
- The user changes subsystems (e.g., from "deployment" to "UI")
- The user references a concept not in your working set
- The user explicitly says "let's switch to..."

When you detect a pivot, call `search_memory` with a query for the new topic. ADD the results to your working set; do not replace it.
```

### Session focus history as a usage signal

The focus declarations themselves become data worth keeping. If memory-hub records the focus string of the last 20 sessions, that's a usage histogram: "this project is actually 60% deployment, 30% MCP tools, 10% UI." That signal could feed back into weight tuning — memories tagged or matching frequently-used focuses could get gentle weight bumps; memories never matching any session focus could decay toward stub-only. This is a phase-2 idea, not a v1 requirement.

## Open Questions

The nine open questions that surfaced while drafting this design have been lifted into their own tracking doc at [`open-questions.md`](open-questions.md), where each one has a "what would resolve it" note and a dependency pointer. Deep investigations that need their own space (FastMCP feasibility, ranking math, pivot detection) live under [`research/`](research/).

## Implementation Candidates

This design generates several implementation candidates. Each gets a backlog issue linked to this doc.

1. **Search response shape: branch nesting and `include_branches` parameter.** Stop surfacing branches as siblings of their parent in the same result set. Trust the `has_rationale` / `has_children` flags. Add `include_branches: true` for forensic workflows. When branches are returned, nest them under the parent.
2. **Search response: token budget and `mode` parameter.** Add `max_response_tokens` cap and `mode: full | index | full_only` parameter. Improve the stub format to remain a snippet, not a topic label. Optional: large-memory preview form.
3. **Two-vector retrieval with session focus.** Embed a session focus string at `register_session` time. Bias subsequent `search_memory` calls by the session vector with configurable weight. Benchmark the ranking math. **Note: the session vector embedded here is reused on the push side by Pattern E (#7) — broadcast notifications are pre-filtered against the same session vector so subscribers only receive writes that match their declared focus.** The two efforts should be designed and reviewed together.
4. **Project configuration: `.memoryhub.yaml` schema and loader.** Define the schema, write the loader, surface the config to the SDK and the server.
5. **`memory-hub config` CLI with rule generation.** Interactive setup command that writes both `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md`. Templates for Patterns A/B/C/D, plus the optional Pattern E live-subscription overlay.
6. **Session focus history as a usage signal.** Record focus declarations per session, aggregate into a per-project histogram. Phase 2 — don't block on this.
7. **Real-time push (Pattern E): server-push notifications for swarm broadcast.** Add `ResourceUpdatedNotification` broadcast on memory writes via FastMCP 3's distributed notification queueing (Valkey-backed). Maintain an agent session registry. Pre-filter broadcasts by session focus vector (reuses #3). Add `live_subscription` and related config knobs to the YAML schema (#4). Phase 2 — depends on #3 landing first.

## Cross-references

- `../mcp-server.md` — current tool surface, including `search_memory` parameters and response shape
- `../memory-tree.md` — branch model (rationale, provenance) that motivates the branch-handling discussion
- `../storage-layer.md` — pgvector usage that the two-vector retrieval proposal builds on
- `../../.claude/rules/memoryhub-integration.md` — current hand-written loading rule, the manual precursor to the generated rule file

## History

This file was originally at `docs/agent-memory-ergonomics.md` as a single flat document. It was moved into `docs/agent-memory-ergonomics/` on 2026-04-07 when the accompanying research files were added. The seven implementation candidate issues (#56–#62) reference the old path in their issue bodies — that path still resolves via git history, and the issues will be updated when each is picked up.
