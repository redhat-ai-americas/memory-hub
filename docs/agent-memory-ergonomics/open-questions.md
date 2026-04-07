# Open Questions

Unresolved design questions surfaced while drafting [`design.md`](design.md). Each has a status, a "what would resolve it" note, and a dependency pointer to either an issue or a research file.

**Status legend:**
- **Open** — not yet investigated
- **Investigating** — research file or benchmark exists, no decision yet
- **Resolved** — decision made, design updated to reflect it
- **Superseded** — no longer applies because the design moved around it

## Q1. Two-vector retrieval ranking math

**Status:** Investigating
**Affects:** #58
**Research:** [`research/two-vector-retrieval.md`](research/two-vector-retrieval.md)

Given a query vector `q` and a session focus vector `f`, how should `search_memory` combine them into a single ranking?

Three candidate approaches: **weighted sum** of `q·m` and `f·m` per memory (simple, one pgvector call, hard to tune), **rerank-after-recall** that fetches top-K by `q·m` then reorders by a blend of `q·m` and `f·m` (two-stage, lets recall and precision tune separately, adds latency), and **pgvector composite query** that passes a single combined query vector `(1-w)·q + w·f` to one cosine-distance call (cheapest, but averaging embeddings is semantically fraught and needs empirical validation).

**What would resolve it:** A synthetic benchmark on 100–500 memories with tagged topics, measuring recall@10 and precision@10 for each approach at several `session_focus_weight` values (0.2, 0.4, 0.6). See the research file for the proposed benchmark harness shape.

## Q2. Pivot detection algorithm

**Status:** Investigating
**Affects:** #58 (adjacent — Pattern C in the design doc)
**Research:** [`research/pivot-detection.md`](research/pivot-detection.md)

Pattern C (lazy load + rebias on pivot) needs a concrete trigger for "a pivot just happened." Two candidate approaches: **server-side** (the MCP server measures embedding distance from the session vector on each query; if distance exceeds a threshold, surface a `pivot_suggested: true` hint in the response) and **agent-side** (the agent self-detects via LLM judgment against the three concrete triggers listed in the design doc: subsystem change, unknown concept, explicit switch).

Server-side is more consistent across agents; agent-side is more flexible. A hybrid — server provides a hint, agent can override — is probably the right answer, but needs verification that the hint-then-override pattern works reliably with real agents.

**What would resolve it:** Either (a) a benchmark showing server-side thresholding catches pivots with acceptable false-positive rate, or (b) an agent-side prompt template that reliably fires on the three triggers. Probably both, compared side by side.

## Q3. Where does focus source inference live?

**Status:** Resolved 2026-04-07
**Affects:** #58, #60

The design says focus can come from three sources: declared (agent calls `register_session(focus="...")`), inferred from working directory + git state, or inferred from the first user turn. Declared focus is obviously server-aware. But:

- **Working-directory inference** is project-specific and environment-specific. It probably belongs in the agent's environment (the Claude Code harness, for example) or in the SDK, not in the MCP server.
- **First-turn inference** belongs in the agent — the server never sees the user's messages directly.

That means only declared focus is genuinely server-aware. The SDK or the agent has to wrap the inference logic. This pushes #58's scope toward the SDK side of the line and simplifies the server side.

**Resolution:** Inference lives in the SDK, server only sees the final string. The `.memoryhub.yaml` schema shipped in #59 keeps `focus_source: declared | directory | first_turn | auto` so projects can declare their preferred source, but the actual inference helpers are owned by the SDK. #58 will add `memoryhub.infer_focus(cwd=..., first_turn=...)` (or similar) as part of its session-vector work; the MCP server's `register_session` tool continues to accept a plain focus string and knows nothing about how it was derived. Decided with @rdwj during the 2026-04-07 #59/#60/#73 session.

## Q4. Migration path for existing projects

**Status:** Resolved 2026-04-07
**Affects:** #60

Projects currently using `.claude/rules/memoryhub-integration.md` (a hand-written loading rule) should be able to run `memoryhub config init` without breaking anything. The CLI needs to detect existing rules and offer to merge or replace.

**Resolution:** Replace, not sidecar. The rationale ("what would we do if we didn't have the old rule? — write the new one; keeping two rule files is confusing") came up during the 2026-04-07 session with @rdwj. Implemented in commit `420bdb5`: `memoryhub config init` writes the new file at `.claude/rules/memoryhub-loading.md` and renames any pre-existing `memoryhub-integration.md` to `memoryhub-integration.md.bak` (numeric `.bak.N` for repeat runs). No merge path was built — freeform markdown is too hard to reconcile mechanically, and the backup is recoverable if the user wants to pull prose from the old rule into the YAML.

## Q5. Should `mode: index` results omit content entirely, or include short snippets?

**Status:** Open
**Affects:** #57

The `mode: "index"` parameter makes `search_memory` return stubs for everything regardless of weight. The question: what exactly is a "stub"? The current design keeps weight-based stubbing's snippet format (~100 chars of content + metadata), but `index` mode could be even lighter — just `(id, stub_title, scope, weight)`.

Snippets are more useful for the agent but cost more tokens. Bare IDs force a round-trip for anything interesting.

**What would resolve it:** A sub-knob on the `mode` parameter, e.g. `mode: "index"` keeps the snippet format and `mode: "index_bare"` drops it to ID-only. Or just ship `mode: "index"` with snippets and let real usage decide if a bare variant is needed.

## Q6. Push payload: URI-only or full content?

**Status:** Open
**Affects:** #62
**Research:** [`research/fastmcp-3-push-notifications.md`](research/fastmcp-3-push-notifications.md) §"Spec compliance vs latency"

MCP spec says `ResourceUpdatedNotification` carries only the resource URI — clients are expected to refetch via `resources/read` (or `read_memory`) to get content. This is spec-compliant and keeps notifications small, but adds a round-trip.

Memory-hub could define a custom notification method (`notifications/memoryhub/memory_written`) carrying the full record. This is non-spec but valid since MCP allows custom methods under the `notifications/$vendor/$method` pattern. Trade-off: spec compliance and small notifications vs. latency and round-trip count.

**What would resolve it:** Benchmark both under realistic swarm load. If the extra round-trip from URI-only is <50ms median and the notification fanout is <100 agents, spec-compliant URI-only is fine. If either exceeds those thresholds, ship the custom full-content notification as a `push_payload: full_content` YAML option.

## Q7. Subscriber lifecycle for pure-listener agents

**Status:** Open
**Affects:** #62 (hard blocker for implementation)
**Research:** [`research/fastmcp-3-push-notifications.md`](research/fastmcp-3-push-notifications.md) §"Subscriber lifecycle"

FastMCP 3 starts notification subscribers when a task is submitted. Agents that don't submit tasks but want to listen for broadcasts need a subscriber loop started at session-registration time. This hook may not exist in FastMCP 3 today.

**What would resolve it:** A small spike against the FastMCP 3 source at `/Users/wjackson/Developer/MCP/fastmcp`: find the task-submission code path, trace where the subscriber loop starts, and determine whether it can be hoisted to session-registration or whether it requires an upstream FastMCP change. If upstream work is needed, file an issue against FastMCP 3 before committing to #62's implementation.

## Q8. Reliable queue vs pub/sub for fanout

**Status:** Open
**Affects:** #62

FastMCP 3's notification queueing is Valkey LPUSH/BRPOP with retry — reliable but O(N) per write. Valkey pub/sub is fire-and-forget and scales better via Valkey-side fanout, but disconnected agents miss notifications and have to catch up via a search-on-reconnect.

The right answer is probably per-deployment, chosen by the `push_transport` YAML knob. But we need a decision on what the *default* is.

**What would resolve it:** Decide the default by looking at the expected first real use case. If the first consumer is memory-hub itself (single developer, low fanout), the default doesn't matter much. If the first consumer is a kagenti swarm deployment, the default should be reliable queue until the swarm grows enough to care about fanout cost.

## Q9. Push fanout cost at scale

**Status:** Open
**Affects:** #62

O(N) reliable-queue fanout is fine up to ~100 agents. Beyond that, benchmark before committing. A hybrid — pub/sub for transient updates, reliable queue for high-importance writes — is possible but adds implementation complexity.

**What would resolve it:** Not actionable until we have a real swarm deployment to benchmark against. Leave open, revisit when #62 is closer to implementation.

---

## How to Add a Question

If a new question surfaces while working in this area:

1. Add a new `## Q<N>. <title>` section to this file.
2. Set its **Status** to "Open."
3. Populate **Affects** (issue number) and **Research** (file path, if one exists).
4. Write a short "what would resolve it" note — the bar is "someone picking this up in three months should know what they need to produce."
5. If the question needs deep investigation (>1 page), create a new file under `research/` and link to it.
