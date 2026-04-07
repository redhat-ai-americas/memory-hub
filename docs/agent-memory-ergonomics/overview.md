# Agent Memory Ergonomics — Overview

## What This Is

An effort to make memory-hub usable — not just functional — from the consuming agent's perspective. memory-hub ships 13 MCP tools that cover every operation an agent needs, but tools without policy don't get used well, and response shapes that are "technically correct" can still force agents into multi-round-trip dances or silent misses. This effort captures the current rough edges and proposes targeted changes.

This folder is the design artifact for that effort. It is not a spec; it is a living set of proposals, research notes, and open questions that seven GitHub issues (#56–#62) are pulling implementation from.

## Why Now

Two forcing functions converged in early April 2026:

1. **The `/exercise-tools` session on 2026-04-06** surfaced seven structural issues with the Phase 1/2 tool set, most of them about response shape (empty results from `get_similar_memories`, `total_accessible` ambiguity, `read_memory`'s `depth` footgun, etc.). Those eight shipped fixes landed in the 2026-04-07 Wave 1–4 session (see `retrospectives/2026-04-07_wave1-4-mcp-fixes/RETRO.md`). While fixing them, a second, deeper category of issues surfaced: the tools were fine but the *loading patterns* around them were underdefined.
2. **Kagenti integration research** started in parallel. Swarm-style deployments have fundamentally different memory-loading needs than the single-developer single-thread workflow memory-hub has been tuned for. Sitting down to write the kagenti integration docs made it clear that "how should agents actually use memory-hub" was not something we had an answer for.

The result is this effort: document the two problems (response shape, loading policy), propose designs for each, and carve out the research that needs to happen before the bigger pieces can ship.

## The Two Core Concerns

**Response shape.** What comes back from `search_memory` determines whether the agent has enough context in one round-trip, has to fetch more, or wastes tokens on things it didn't need. Current behavior is "full inline content for everything matching, ranked by similarity, including branches as independent top-level results." That works at the current scale (~30-50 memories per user) but has rough edges that will get worse. The design covers branch nesting, stub policy, mode parameters, and token budget caps.

**Loading policy.** Tools are mechanism. The *when* and *how* of calling them lives in agent instructions. Today every project hand-writes its own rule for memory loading. memory-hub could ship a configuration moment that generates the right rule for the project's workflow shape. The design covers session focus, two-vector retrieval, loading patterns A–E, and a `memory-hub config` CLI that generates both machine-readable YAML and human-readable rule files.

These are separate problems that interact. A project that runs broad multi-domain sessions wants both eager loading and full content in responses. A project that runs tightly-scoped single-thread sessions wants lazy loading and possibly stubbed responses with on-demand expansion. Configuring one without the other leaves money on the table.

## How the Pieces Compose

The design organizes into three concentric layers:

**Layer 1 — Response shape knobs** are pure server-side changes to `search_memory`. They ship first because they're low-risk, well-scoped, and unblock the higher layers. Tracked as #56 (branch nesting) and #57 (token budget + mode).

**Layer 2 — Session focus and retrieval biasing** introduces a session-wide focus vector that biases retrieval toward declared or inferred topics. This is where the design gets interesting — it sits between "hand-written topic tags" (brittle) and "load everything always" (wasteful). The math has open questions, which is why there's a dedicated research file on ranking options. Tracked as #58.

**Layer 3 — Project configuration and rule generation** is the user-facing output of all the above. A `memory-hub config init` CLI walks a project through three or four questions about session shape, writes `.memoryhub.yaml`, and generates `.claude/rules/memoryhub-loading.md` from a template per loading pattern. Tracked as #59 (schema) and #60 (CLI).

Two Phase 2 items sit on top of the above:
- **Pattern E (real-time push)** reuses Layer 2's session focus vector to pre-filter broadcasts, so a swarm agent that declared `focus="auth"` only receives notifications about auth-related writes. Tracked as #62. Hard-depends on #58.
- **Session focus history as a usage signal** records the declared focus per session and builds a per-project histogram that could later feed weight tuning. Tracked as #61. Phase 2, not blocking.

## Where to Read Next

- **[`design.md`](design.md)** — The full design document. If you only read one file, read this one. Covers all three layers in narrative order, with code sketches and config examples.
- **[`open-questions.md`](open-questions.md)** — Nine unresolved questions, each with "what would resolve it" and dependency pointers. Pick a question and read its linked research file if one exists.
- **[`research/fastmcp-3-push-notifications.md`](research/fastmcp-3-push-notifications.md)** — Evidence for the Pattern E feasibility claims. Read this before implementing #62.
- **[`research/two-vector-retrieval.md`](research/two-vector-retrieval.md)** — Three options for the ranking math behind session-focus biasing. Read this before implementing #58.
- **[`research/pivot-detection.md`](research/pivot-detection.md)** — Server-side vs agent-side options for Pattern C's pivot detection trigger.

## Implementation Status

As of 2026-04-07, nothing in this design has been implemented. All seven issues (#56–#62) are in Backlog, waiting on a design-first pass and the completion of the currently-scheduled small session (BFF walker fix + #36/#43 decision) plus kagenti research.

Expected order of implementation:

1. **#56 + #57** (Layer 1) — One session, four commits, server-side only. Natural to land together.
2. **#59 + #60** (Layer 3 without Layer 2 knobs) — Depends on #56/#57's field names being locked. SDK build-out starts here.
3. **#58** (Layer 2) — Design-first session: pick ranking math, write benchmarks, then code.
4. **#62** (Pattern E) — Only after #58 lands.
5. **#61** (usage signal) — Phase 2, order TBD.

## Cross-references

- `../mcp-server.md` — current tool surface and `search_memory` parameters
- `../memory-tree.md` — branch model that motivates the branch-handling proposal
- `../storage-layer.md` — pgvector usage that Layer 2 builds on
- `../kagenti-integration/` — the swarm use case that motivated Layer 2
- `../../.claude/rules/memoryhub-integration.md` — current hand-written loading rule
- `retrospectives/2026-04-07_wave1-4-mcp-fixes/RETRO.md` — the session where this effort was scoped
