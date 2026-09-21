# Procedural Graph Retrieval: Design Doc (#553)

**Status:** Traversal and guidance generation implemented on `feat/procedural-graph-retrieval`.
Search-path integration is not started: Decisions 5a and 5b are still unsigned.
**Date:** 2026-09-21

## Problem

Issue #553: implement localized graph retrieval for procedural memories. Per the Procedural
Graphs paper (arXiv 2609.09153, "generative guidance"), the retrieval shape that outperforms
both flat search and full-graph injection is:

1. Localize the agent's current position in the procedural graph (current step node).
2. Retrieve a bounded neighborhood (up to 2 hops) around that node.
3. Convert the localized subgraph into natural-language guidance via an LLM (conditions,
   guidance, pitfalls for the current step and its neighbors).
4. Inject only that guidance into the agent's context — not the raw graph, not the full graph.

The paper reports this reduces token overhead by up to 71% vs. full-graph injection while
*improving* task performance across all ablations — more context is measurably worse here, not
just more expensive.

`#552`'s design doc (`planning/procedural-graphs.md`) already flagged the shape of this work in
its "Retrieval and traversal — explicitly deferred to #553" section and named the two service
functions this doc has to choose between. This doc makes that choice, and the three others the
issue leaves open: how "current step" is identified, whether generation is synchronous or
cached, and where this surfaces in the MCP tool layer.

## What already exists — an inventory, not a blank slate

Before designing anything, it's worth being precise about what `src/memoryhub_core/services/graph.py`
already has, because two of the five functions there look like exactly what #553 needs and one
of them almost is. None of this was written for #553 specifically — it predates the procedural
content type entirely — but the shapes line up closely enough that this doc is mostly about
which existing piece to extend, not what to build from scratch.

| Function | Hop limit | Tenant-scoped? | Returns | Wired to an MCP tool? | Backend |
|---|---|---|---|---|---|
| `get_relationships(node_id, ...)` | 1 (direct edges only) | Yes, SQL-level | `list[RelationshipRead]` | Yes — `manage_graph` `get_relationships` | Portable (ORM) |
| `get_subtree(node_id, max_depth)` | ≤10 (`parent_id` tree only) | No (see note) | `{node, children, total_nodes}` | No | Portable (ORM) |
| `trace_provenance(node_id, max_hops)` | ≤10, single-edge-type walk (`derived_from` only) | No — filtered post-hoc | `[{node, relationship, hop}]` | Yes — `manage_graph` `include_provenance` | Portable (ORM) |
| `find_related(node_id, max_hops, relationship_types)` | ≤5 (`_MAX_HOPS_CAP`) | **No — not even post-hoc** (fixed in this PR; see implementation record) | `[{node, path, distance}]` | **No production callers.** #552 added unit tests. The "zero tests" claim below was wrong. | Portable (ORM) |
| `collect_graph_neighbors(seed_ids, ..., tenant_id, max_depth)` | ≤3 (`_MAX_NEIGHBORS_CAP`) | Yes, SQL-level (recursive CTE) | `{node_id: min_hop_distance}` — IDs and depth only, no content | Yes — internal to `search_memories_with_focus`'s graph-boosted reranking | **Postgres-only** (raw CTE, `unnest`/`ANY` array ops) |

Two things fell out of this inventory that change the shape of the work:

- **`find_related` is the closest match to what #553 needs, and it had a real
  tenant-isolation gap.** It already does bounded BFS with a relationship-type filter and a
  sane default (`max_hops=2` — matches the paper's own best-performing neighborhood size), and
  it returns full `MemoryNodeRead`/`RelationshipRead` objects (including each node's
  `metadata_` and each edge's `metadata_`), which is exactly the granularity the NL-generation
  step needs. But it takes no `tenant_id` and its internal node fetch (`_fetch_node_by_id`)
  has no tenant filter either — unlike `get_relationships`, which threads `tenant_id` through
  every query. Nothing in production calls it (no post-hoc authorization backstop). #552 does
  call it from unit tests; those call sites are updated to pass `tenant_id`. An earlier draft
  of this doc said the function was untested. That was wrong.
- **`trace_provenance` has the same missing SQL-level tenant filter, but it's not
  hypothetical for that one — it's live**, wired into `manage_graph`'s `include_provenance`
  option today. It's *not* an open leak: `manage_graph.py` (lines ~502-515) fetches
  provenance steps unfiltered and then drops any step whose node fails
  `authorize_read(claims, proxy, ...)` before returning results. That's a real backstop, but
  it's the only one — there's no SQL-level filter as defense in depth, so a gap in
  `authorize_read`'s logic for this code path would be a silent cross-tenant leak with nothing
  else catching it. This is a pre-existing issue, unrelated to #552 or #553's actual scope, and
  fixing it isn't blocking work here — but it's real enough that it deserves its own follow-up
  issue rather than staying buried in this doc's research notes. Filed as a note under
  "Out of scope" below.

## Decision 1: current-step localization is an explicit caller-supplied ID

The issue doesn't specify how the agent's "current position" is determined. Two options:

- **Infer it** — e.g. take the highest-scoring result from the agent's most recent search and
  assume that's where it is.
- **Explicit** — the caller (agent or orchestrating client) passes a `current_step_id`, and the
  first entry into a procedure (via `reconstruct`-adjacent lookup or an initial
  `content_type="procedural"` search) returns the procedure's entry step ID so the caller has
  something to hold onto and pass forward on subsequent calls.

**Recommendation: explicit.** Inferring position from search relevance conflates "what's
semantically similar to what I just asked" with "where I am in a specific execution," which are
different questions — an agent asking a clarifying question about step 3 while working on step
1 would get localized to the wrong node. It also adds a new heuristic with its own failure modes
(ties, drift) for no clear benefit over just tracking an ID, which every agent framework capable
of running a multi-step procedure already does for its own state anyway. This means #553 needs
one small addition on the write/read side: the procedure root's `metadata_.procedure` should
carry an explicit `entry_step_id` (already sketched as optional in #552's doc, §3c) so a fresh
lookup has somewhere to start; #552's open question 2 is resolved by this doc in favor of making
that field required for graphs that want to support entry via #553, not just optional.

## Decision 2: traversal primitive — extend `find_related`, not `collect_graph_neighbors`

**Recommendation: fix `find_related`'s tenant gap and use it directly; leave
`collect_graph_neighbors` untouched.**

They serve different jobs even though both do bounded graph BFS:

- `collect_graph_neighbors` is optimized for "which of these many candidate IDs have graph
  neighbors at all" (id → depth only, batched over many seeds, one round-trip via CTE) — the
  right shape for expanding a vector-recall candidate pool before reranking, which is its only
  current caller. It doesn't fetch node content or edge attributes, so using it here would mean
  re-fetching every node and edge in the neighborhood by hand afterward, effectively
  reimplementing `find_related`'s hydration logic anyway.
- `find_related` already returns exactly what generation needs: each neighbor's full
  `MemoryNodeRead` (content, `metadata_.procedure.action`/`preconditions`/`pitfalls`/etc.), the
  path of `RelationshipRead` edges to reach it (each with its own `metadata_.condition`/
  `guidance`/`pitfalls`), and hop distance. Nothing to add on the data-shape side.
- `find_related` is portable SQLAlchemy ORM, testable against SQLite in the fast unit suite
  (`tests/test_services/`, no `podman-compose` needed). `collect_graph_neighbors` is a raw
  Postgres CTE with array-typed bind params (`unnest(CAST(:seed_ids AS uuid[]))`,
  `= ANY(:rel_types)`) that doesn't run on SQLite at all — it's only exercised by the slower
  integration suite. Building #553's core traversal on the portable function keeps the fast
  suite meaningful for it, matching this repo's existing SQLite-unit / Postgres-integration
  split (the same reasoning #552's doc used for why the `ContentType` CHECK constraint needed
  to live in both the ORM `__table_args__` and the migration).

The fix itself is small and self-contained — worth landing as its own PR before the generation
work, since it's independently useful (closes a real gap) and easy to review in isolation:

```python
async def find_related(
    node_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
    max_hops: int = 2,
    relationship_types: list[str] | None = None,
) -> list[dict]:
    ...
    await _fetch_current_node(node_id, session, tenant_id=tenant_id)
    ...
    filters = [
        or_(...),
        MemoryRelationship.tenant_id == tenant_id,
        _active_edges_filter(),
    ]
    ...
    neighbor_node = await _fetch_node_by_id(neighbor_id, session, tenant_id=tenant_id)
```

`_fetch_node_by_id` needs the same optional-but-should-be-required-here `tenant_id` parameter
`_fetch_current_node` already has (it's optional there for `trace_provenance`'s sake, which this
doc isn't touching — see "Out of scope"). `max_hops` stays defaulted to 2, matching the paper;
`_MAX_HOPS_CAP` (currently 5) stays as the hard ceiling regardless of what a caller requests.

## Decision 3: neighbors carry a directional role, not an undifferentiated hop distance

`find_related` walks edges in both directions unconditionally —
`or_(MemoryRelationship.source_id == current_id, MemoryRelationship.target_id == current_id)`
(`graph.py:480-482`). For the symmetric relationship types that predate this work
(`related_to`, `conflicts_with`) that's fine. For the three types #552 added it is not: all
three are directional, and two of them mean opposite things depending on which end the current
node sits at.

Walking bidirectionally is still correct — an agent on step 3 needs to know both what comes
next *and* what it depends on. What's wrong is returning both as a flat "neighbor at distance
1" list, because the generation step then can't tell a prerequisite from a consequence, and the
guidance text will confidently present "what must happen before this" as "what to do next."

So the traversal result must tag every neighbor with the role it plays relative to the current
node, derived from (relationship_type, which end the current node is on):

| Edge | Current node is… | Neighbor's role |
|---|---|---|
| `precedes` | target | `predecessor` — ran before this step |
| `precedes` | source | `successor` — the step this one leads to |
| `requires` | source | `prerequisite` — must hold before this step runs |
| `requires` | target | `dependent` — something else needs this step first |
| `alternative_to` | either | `alternative` — symmetric, direction carries no extra meaning |

This role, not the raw edge direction, is what goes into the generation prompt and into the
response shape. Two consequences for implementation: `find_related`'s return value needs the
role (it currently returns `{node, path, distance}`, which is enough to *derive* the role for a
1-hop neighbor but ambiguous at 2 hops, where the path has two edges and the roles compose —
"prerequisite of my successor" is not the same as "successor of my prerequisite"); and the
composition rule for 2-hop roles needs to be explicit rather than left to the generator to
infer. Recommendation: return the full typed path (each edge with its type and traversal
direction) and let the prompt template render the chain literally ("step X, which is a
prerequisite of step Y, which follows the current step") rather than collapsing 2-hop
relationships into a single invented label.

## Decision 4: NL guidance generation — synchronous, no cache, reuse the Stage-3 LLM config

Three sub-decisions bundled together because they're the same call site:

**Synchronous, not pre-cached.** A cache keyed on `(node_id, max_hops, relationship_types)`
with invalidation on graph edits would reduce latency for repeated queries against a stable
neighborhood, but it's exactly the kind of abstraction this repo's own coding conventions
(`CLAUDE.md`/`CONTRIBUTING.md`: "no early optimization... don't add abstraction for hypothetical
future requirements") say to defer until there's a measured reason. #553 has no latency
benchmark yet — building the cache before knowing whether the plain synchronous call is even a
problem is exactly that hypothetical-future-requirement case. Ship synchronous first; if
benchmarking (see #273, which is about exactly this kind of retrieval-quality/latency trade-off)
shows guidance generation is a bottleneck, caching is a well-scoped follow-up with a real number
to justify it.

**Reuse `AppSettings.llm_extraction_url` / `llm_extraction_model` / `llm_extraction_timeout`**
(config.py, "LLM Stage 3 (#249)"), not `conv_extraction_*`. Both existing configs point at an
OpenAI-compatible `/v1/chat/completions` endpoint, but `conv_extraction_*` carries fields
specific to conversation-window extraction (`conv_extraction_window_size`,
`conv_extraction_api_key`) that don't apply here, while `llm_extraction_*` is already the
"structured JSON-object generation from a system prompt" config used by `_LLMExtractor` in
`extraction.py` — the same shape this needs. If a deployment later wants guidance generation on
a different model than entity extraction, split them then (mirroring how `conv_extraction_*` and
`llm_extraction_*` are already two independent configs for two independent LLM-calling
call sites) — don't pre-split speculatively.

**New prompt file, new thin wrapper class, same resilience pattern.** Add
`prompts/procedural_guidance.yaml` alongside the existing three (`entity_extraction.yaml`,
`fact_extraction.yaml`, `conversation_extraction.yaml`). Add a `_GuidanceGenerator` in a new
`src/memoryhub_core/services/procedural_guidance.py` (not appended to `graph.py`, which is
relationship CRUD/traversal, not generation) that mirrors `_LLMExtractor`'s shape: `httpx`
client from `AppSettings`, prompt loaded once at construction, retry-with-correction on
malformed output, exponential backoff on service errors via the same
`LLMExtractionServiceError`/`LLMExtractionServiceUnavailableError` exception pair (reused as-is
— this is the same failure mode, not a new one). Unlike Stage-3 extraction, the output here is
free text, not a JSON object needing Pydantic validation — so the retry-with-correction loop
simplifies to "empty or clearly-truncated response → retry," no schema-validation branch needed.

Input to the prompt: the current step's full node (content + `metadata_.procedure`), each
neighbor node at hop 1 and hop 2 with the same, and each edge on the path with its
`relationship_type` and `metadata_` (condition/guidance/pitfalls). Output: a single guidance
text block, not JSON — this is prose meant to go straight into an agent's context, not a
structured object something downstream parses.

The prompt itself must constrain the model against inventing procedural structure, since a
fabricated prerequisite or a hallucinated "next step" in an agent's execution guidance is worse
than no guidance at all — it is confidently wrong instruction the agent will act on. Required
prompt constraints:

- Use only facts present in the supplied subgraph. Do not introduce steps, transitions,
  conditions, tools, or prerequisites that are not in the input.
- Do not fill gaps with plausible-sounding domain knowledge. If a step has no recorded
  `pitfalls` or `preconditions`, say nothing about them rather than generating likely ones.
- Preserve the directional roles from Decision 3 exactly: a `prerequisite` is never described as
  a next step, a `predecessor` is never described as something still to do.
- Distinguish the current step from its neighbors explicitly in the output text.
- Surface recorded conditions and pitfalls for the current step and its immediate neighbors.
- Be concise and actionable — this text is injected into an agent's context, and the entire
  point of localized retrieval (per the paper's 71% token reduction) is lost if the generator
  pads it.

## Decision 5: retrieval-path integration is the deliverable; the graph action is a helper

**Correction to an earlier draft of this doc.** A previous revision recommended exposing this
only as `manage_graph(action="get_guidance", node_id=...)` and explicitly argued *against*
touching `search_memory`, on the grounds that a deterministic graph walk doesn't belong in a
tool built around similarity ranking. That reasoning is architecturally tidy and it
under-delivers against the issue. #553's scope section says, in as many words: *"Integration
with the existing search pipeline so procedural queries return localized guidance rather than
flat memory entries."* A standalone graph action leaves procedural search returning exactly the
flat memory entries the issue names as the thing to replace, and pushes the entire localization
flow onto every caller. The integration is the acceptance criterion; the action is at best a
convenience on top of it.

So: `search_memory` gains one optional `current_step_id` parameter, and
`manage_graph(action="get_guidance", node_id=..., max_hops=2)` is added alongside it as the
lower-level entry point — what you reach for to inspect what the generator actually saw, or to
get the raw neighborhood without an LLM round-trip. Its response shape:
`{node_id, guidance_text, neighborhood: {nodes: [...], edges: [...]}, hop_count}`, the raw
neighborhood travelling alongside the generated text so a caller inspecting the generation isn't
forced into a second `get_relationships` call per neighbor. Both surfaces call the same service
function; neither reimplements the other.

### 5a. What `query` means alongside `current_step_id` — NOT settled, needs a human decision

**This is the one decision in this doc that an implementer must not make silently.** An earlier
revision asserted the answer (short-circuit; `ToolError` if both are set) without weighing it
against the contract `search_memory` already has. That was wrong, and the relevant evidence is
this:

`search_memory` already carries a graph-traversal semantics, and it is the *opposite* of a
short-circuit. `graph_depth` (0-3, default 0), `graph_relationship_types` and
`graph_boost_weight` are existing parameters, and `graph_depth`'s own description reads:
*"When > 0, follows relationships from vector search results to surface connected memories."*
That is: **query first, graph expands the result set, then boost and rerank** — the path through
`search_memories_with_focus` → `collect_graph_neighbors`. Adding a `current_step_id` that
*ignores* the query would put two contradictory meanings of "this tool does graph traversal"
into one tool, and a caller who has learned the `graph_depth` behavior would reasonably expect
the other one.

Three candidate semantics, with what each costs:

- **(A) Short-circuit.** `current_step_id` present → skip embedding and ranking entirely; walk,
  generate, return. Closest to the paper, which localizes purely structurally. Cheapest: no
  embedding call on this path. Defensible on the grounds that the query really is redundant —
  a step ID already determines its procedure via `parent_id`, so there is nothing left for
  semantic search to narrow. Cost: the inconsistency with `graph_depth` described above.
- **(B) Query narrows, then localize.** Run the search, let the top procedural hit determine the
  procedure, then localize within it. Note that this is only meaningful when `current_step_id`
  is *absent* — if the caller supplied a step ID, the procedure is already pinned and there is
  nothing for the query to narrow. So (B) is not really an alternative to (A); it is an answer
  to 5b below.
- **(C) Localize structurally, then let the query rank within the neighborhood.** Walk by
  `current_step_id`, then use the query to order or trim which neighbors reach the generation
  prompt. This is the only option that makes the query meaningful *and* keeps localization
  deterministic, and it reads as a natural extension of the existing "query + graph" spirit.
  Cost, and it is a serious one: trimming by semantic similarity can drop a `prerequisite`
  precisely because the agent's question didn't mention it — which is the failure mode
  execution guidance can least afford. If (C) is chosen, ranking must not be allowed to drop
  prerequisites; at most it should reorder.

**Recommendation: (A), with `query` remaining required and explicitly ignored — documented in
the parameter description — rather than raising `ToolError` when both are set.** A hard error
for supplying a query is hostile given that `query` is currently a required positional; ignoring
it loudly (in the response, e.g. a `query_ignored: true` marker) is kinder and is reversible if
(C) later proves worth building. But this is a recommendation, not a settled decision: it
changes what an existing, widely-used tool means, and it should be signed off by a human before
implementation, not chosen by whoever picks up the ticket.

### 5b. Cold start: what a procedural query does with no `current_step_id` — also needs sign-off

An earlier revision asserted "flat ranked list, unchanged" in a parenthetical. That is the
conservative answer and it is probably right, but it has a cost worth stating out loud: it means
the *first* procedural query never returns guidance. The agent must search, read the root's
`metadata_.procedure.entry_step_id`, and search again — two round trips before any guidance
exists, on the single most common entry path.

The alternative is that a `content_type="procedural"` query with no `current_step_id`
auto-localizes to the entry step of the top hit and returns guidance directly. That is one round
trip, and it is much closer to what "procedural queries return localized guidance rather than
flat memory entries" says on its face — but it changes the return shape of an existing query
pattern that works today, which the backward-compatibility contract below otherwise forbids.

**Recommendation: keep the flat list (conservative, additive, no existing behavior changes), and
revisit once there is a real client.** Again — recommendation, not settled. If the reviewer of
#553 reads the issue as requiring one-round-trip guidance, that reading is defensible and this
should flip before implementation, not after.

### 5c. Response shape — implementer's call, once the envelope is in front of them

Either a dedicated top-level `guidance` field alongside an empty/suppressed `results` list, or a
single `results` entry with a new `result_type: "guidance"` next to the existing
`"full"`/`"stub"`. The second keeps every existing client's result-iteration loop working
without a new branch; the first is more honest about the fact that this isn't a ranked result at
all. Lean toward `result_type: "guidance"` for consumer compatibility, but check
`_format_entry`/`_compact_entry` in `search_memory.py` first — they assume
`MemoryNodeRead | MemoryNodeStub`, and a guidance entry is neither. Unlike 5a and 5b, this one
is safe to settle during implementation.

After the shape settles, run the same-commit consumer audit this repo's `CONTRIBUTING.md`
requires for MCP response-shape changes. `CONTRIBUTING.md` names `memoryhub-ui/backend/`,
`sdk/`, and `memoryhub-cli/`; add `memory-hub-mcp/` itself (note the hyphenation — the package
directory is `memory-hub-mcp`, unlike its `memoryhub-*` siblings) since `search_memory`'s own
response is being extended, not just consumed. A new optional parameter is additive and
non-breaking for dynamic callers, but the SDK types its client methods explicitly, so its
`search()` signature needs the parameter added in the same commit or the SDK simply cannot
reach the new mode.

## Schema changes

None. No new columns, no new tables, no migration. This is the payoff of #552's Decision 1
(procedural is a first-class `content_type`, not a bolt-on) and Decision 3c (attributes already
live in existing `metadata_` JSON) — #553 is pure service-layer code, a prompt file, one new
optional `search_memory` parameter, and one new `manage_graph` action. The only data-shape
addition is making `metadata_.procedure.entry_step_id` a populated convention on procedure roots
going forward (Decision 1 above), which needs no schema change since it's already inside the
existing JSON blob.

## Backward compatibility

Everything in this doc is additive. Specifically:

- **`search_memory` without `current_step_id` is byte-for-byte unchanged**, including
  `content_type="procedural"` searches, which keep returning flat ranked results. The new
  behavior is reachable only by passing the new parameter, so no existing caller can fall into
  it accidentally. The regression bar for this PR is that the existing `search_memory` suite
  passes unmodified — if a test needed changing, the change was not additive. **This bullet
  holds only under Decision 5b's conservative recommendation.** If 5b flips to auto-localizing
  procedural queries that carry no `current_step_id`, this is no longer an additive change: an
  existing query pattern changes its return shape, existing tests legitimately need updating,
  and that tradeoff has to be accepted deliberately rather than discovered halfway through.
- **`find_related` gaining a required `tenant_id`** is a signature break in the service layer,
  but it has zero callers today (Decision 2), so the blast radius is the function itself and its
  new tests. This is the one place a normally-breaking change is free, and the reason to make
  `tenant_id` required rather than optional-with-a-default: there is no legacy caller whose
  behavior a default would have to preserve, and an optional tenant filter is exactly the shape
  that let the gap exist in the first place.
- **`_fetch_node_by_id` gains an optional `tenant_id`**, defaulting to today's unfiltered
  behavior, because `trace_provenance` still calls it and this PR is not changing
  `trace_provenance` (see "Out of scope"). New call sites pass it; the existing one doesn't.
  This is a deliberate, documented exception to the "required, not optional" reasoning above —
  and it is the thing a reviewer should push back on if `trace_provenance`'s own fix ever lands,
  at which point the parameter should become required there too.
- **No migration, no `CHECK` constraint change, no column change** — so no forward/backward
  database compatibility question at all. A deployment can roll this code back without touching
  the schema.
- **Procedural graphs written before this work** (i.e. everything #552's PR can produce today)
  have no `entry_step_id` in `metadata_.procedure`, since Decision 1 introduces that convention.
  They remain fully readable through every existing path; only the "start me at the beginning of
  this procedure" entry point degrades, and Open Question 1 covers what it degrades to. No
  backfill is required, and none should be written — the fallback exists precisely so the
  feature doesn't require rewriting existing data.
- **The new prompt file and `AppSettings` reuse add no new required configuration.** A
  deployment that never sets `llm_extraction_url` already can't run Stage-3 entity extraction;
  it now also can't generate guidance, and should fail with the same existing
  `LLMExtractionServiceUnavailableError` rather than a new error type or a silent empty result.
  Guidance generation must not become a second reason for an otherwise-healthy deployment to
  start failing requests it used to serve — which is another argument for the
  `current_step_id`-gated design above: no LLM call happens on any path that didn't ask for one.

## Test plan

- `find_related` tenant isolation: two tenants, overlapping node IDs are impossible by
  construction but overlapping *graph shapes* aren't — build a procedural graph for tenant A,
  call `find_related` with tenant B's `tenant_id`, assert `MemoryNotFoundError` (root doesn't
  resolve) rather than a leaked neighborhood. This test doesn't exist today for `find_related`
  at all (it doesn't exist for any code path, since nothing calls it) — this is net-new
  coverage of a real gap, not a regression guard.
- `find_related` correctness, now actually exercised: hop cap respected, `relationship_types`
  filter excludes non-matching edges, a 3-node cycle (A precedes B precedes C precedes A, the
  same construction #552's test plan proposed for the schema layer) terminates and each node
  appears once via the `visited` set, not infinitely.
- Guidance generation: mocked LLM client (no real endpoint in unit tests, same pattern as
  `_LLMExtractor`'s existing tests) — empty-response retry, service-error backoff, a
  well-formed neighborhood produces a prompt containing every neighbor's `action`/`pitfalls`
  text (regression guard against silently dropping a neighbor's attributes when building the
  prompt).
- Directional roles (Decision 3): a step with one `precedes` predecessor, one `precedes`
  successor, one `requires` prerequisite and one `alternative_to` sibling returns four neighbors
  at distance 1 with four *distinct* roles — the test that would have caught treating
  bidirectional traversal as role-free. Plus a 2-hop case asserting the composed path is
  returned intact (both edges, both directions) rather than flattened to a single label.
- `search_memory(current_step_id=...)` (Decision 5, the acceptance-criterion test): returns
  guidance rather than flat ranked entries for the same graph, and the *same* call without
  `current_step_id` still returns the ordinary ranked list — the pair is what proves the
  integration exists and that it didn't change the default path.
- `search_memory` existing suite passes **unmodified** (see "Backward compatibility") — if a
  pre-existing test needed editing, the change wasn't additive and the design is wrong, not
  the test.
- `manage_graph(action="get_guidance")`: end-to-end against a real procedural graph in the
  integration suite (Postgres) — root + 3 steps + mixed edge types, assert response contains
  `guidance_text` and a `neighborhood` matching what `find_related` would return directly.
- Prompt-construction guard (Decision 4's anti-hallucination constraints): assert the rendered
  prompt contains no neighbor the subgraph didn't include, and that a step with empty
  `pitfalls`/`preconditions` produces a prompt with no invented values for them. The generator's
  *output* can't be unit-tested against hallucination without a live model, but its *input*
  can — and a prompt that leaks or invents context is the failure mode that would make a live
  model hallucinate in the first place.
- Regression: `collect_graph_neighbors`'s existing unfiltered-default behavior for non-procedural
  callers is unchanged (this was #552's open question 3 in the "Retrieval and traversal"
  section — closed by this doc's Decision 2: `collect_graph_neighbors` isn't touched at all, so
  this is confirmed by construction, but the test from #552's plan is worth keeping as an
  explicit regression guard rather than relying on "we didn't change the file").

## Out of scope (this PR, or later phases)

- **`trace_provenance`'s missing SQL-level tenant filter** (relies solely on `manage_graph`'s
  post-hoc `authorize_read` filtering, no defense in depth). Found during this doc's research,
  real, but unrelated to #553's actual deliverable and not currently an open leak. Worth a small
  standalone follow-up issue rather than folding into this PR's diff or silently fixing it here.
- **Guidance caching** — deferred per Decision 3 above until a real latency number from #273's
  benchmarking work (or production) justifies it.
- **#454** (entity-aware search reimplementation) and **#273** (graph-traversal vs. flat-search
  benchmark) — both `Relates to`, neither blocks this work; #273 in particular is the natural
  place to eventually measure whether this retrieval shape earns its complexity against
  MemoryHub's own task set, the same "benchmark against the paper's claims in our own context"
  gap #552's doc flagged as unscoped for Phase 1.
- **#554** (automated extraction from dreaming) and **#555** (rejection tracking) — unchanged
  from #552's doc, still later phases.

## Implementation record (2026-09-21)

Checked against the code on this branch before the traversal change. The inventory above
matches, with two corrections:

- `find_related` had no production callers, but it was not untested. #552 calls it from
  `tests/test_services/test_graph_service.py` and `tests/test_services/test_procedural_graphs.py`.
  Making `tenant_id` required updates those call sites. Their assertions are unchanged.
- `get_subtree` is not tenant-scoped (`_fetch_current_node` is called with no tenant). That
  matches the table. It is untouched.
- `collect_graph_neighbors` filters `mr.tenant_id` and `mn.tenant_id` in the recursive CTE and
  returns only `{node_id: min_hop}`. Untouched. The #552 unfiltered-SQL regression test still
  passes.
- `trace_provenance` still calls `_fetch_current_node` and `_fetch_node_by_id` with no
  `tenant_id`. Untouched. `_fetch_node_by_id`'s new `tenant_id` stays optional for that reason.
  Follow-up: give `trace_provenance` the same SQL-level tenant filter. It is not an open leak
  today because `manage_graph` post-filters with `authorize_read`.
- The bidirectional walk is still an `OR` of `source_id` and `target_id`. The tenant predicate
  and the active-edge predicate sit on that same query. Neighbor hydration passes `tenant_id`.

#552 does not write `metadata_.procedure.entry_step_id`. The only in-tree occurrence before
this work is a test that sets it to `None`. There is no backfill and no write-path
auto-population: the entry step usually does not exist when the root is created. Readers honor
the field when it is present.

### Traversal contract (Decision 3, settled here)

- `find_related` excludes the start node. `build_localized_subgraph` loads that node separately
  as `LocalizedSubgraph.current` and does not put it in `neighbors`.
- `find_related(..., relationship_types=None)` still walks every type. An empty list matches
  nothing. Procedural guidance defaults to `PROCEDURAL_RELATIONSHIP_TYPES`
  (`precedes`, `requires`, `alternative_to`) so `related_to` does not enter an execution prompt.
- `distance` is the number of edges from the start. `max_hops=2` includes distances 1 and 2 and
  does not expand a node already at distance 2. Values below 0 become 0. Values above 5 are
  clamped to `_MAX_HOPS_CAP`.
- Ordering is contractual: BFS discovery order; at each node, edges expand in
  `(relationship_type, id)` order.
- A node is returned once, along the shortest path. A same-length tie uses that edge order.
  A second edge to an already-visited node is dropped. A step that is both a successor and a
  prerequisite of the same node therefore contributes only one role. That is a limitation, not
  a collapsed label: the path that is kept is intact.
- Cycles stop because of the visited set. A soft-deleted or wrong-tenant neighbor ends that
  branch (`_fetch_node_by_id` returns `None`) and is not enqueued.
- Each hop is `{relationship, direction, role, from_id, to_id}`. `direction` is `outgoing` when
  the expanded node is the edge source. `role` is relative to that expanded node, not to the
  start. Non-procedural types keep their type string as the role so they are not labeled
  `successor` or `prerequisite`.
- Tenant filter on every access: start node (`_fetch_current_node`), edge query
  (`MemoryRelationship.tenant_id`), neighbor hydration (`_fetch_node_by_id`). Entry resolution
  uses the same rule for the root, the explicit entry id, step children, and incoming
  `precedes` sources.

### Entry step (open question 1, settled)

`resolve_procedure_entry` returns `metadata_.procedure.entry_step_id` when it is a UUID of a
current in-tenant node. Blank or missing falls through. A non-UUID value raises
`EntryStepResolutionError` and does not fall through.

The fallback returns the only current `procedure_step` child with no incoming active
`precedes` edge whose source is a current in-tenant node. `requires` does not count. One
candidate returns that id (not the lowest UUID). Zero candidates (a cycle, or no steps) and
two or more candidates raise `EntryStepResolutionError` with `candidates` set, and the message
tells the caller to pass `current_step_id`. A deleted or other-tenant explicit id raises
`MemoryNotFoundError` rather than switching to the heuristic.

`build_localized_subgraph` does not call this. Its `node_id` is already the current step.

### Open questions 2 and 3, settled

- Single `node_id` only. No multi-seed guidance.
- `max_hops` stays a parameter, default 2, hard cap 5. The tool description, when the MCP
  action lands, should say 2 is the paper's neighborhood size.

### Guidance generation (Decision 4)

`prompts/procedural_guidance.yaml` and `_GuidanceGenerator` in
`src/memoryhub_core/services/procedural_guidance.py`. Same `llm_extraction_url` /
`llm_extraction_model` / `llm_extraction_timeout` settings, same `httpx` client, same
`/v1/chat/completions` path, same exception types. Empty or `finish_reason=length` retries
(3 attempts, sleep `2**attempt`). Service errors retry twice with delays 2s and 4s. No
`response_format`. An empty URL raises `LLMExtractionServiceUnavailableError` and does not
POST. No cache.

The rendered user message omits empty `pitfalls` / `preconditions` / `postconditions` rather
than writing a blank. Recorded facts on hop-2 nodes are included. Decision 4's "immediate
neighbors" wording would have dropped them; the test plan says every neighbor's action and
pitfalls must reach the prompt, so hop 2 is included. That is a widening, recorded here so
the prompt and the doc do not disagree.

### Decision 5c, settled; 5a and 5b, not settled

`_format_entry` and `_compact_entry` in `memory-hub-mcp/src/tools/search_memory.py` both take
`MemoryNodeRead | MemoryNodeStub` and set `result_type` to `"full"` or `"stub"` from that
check. A guidance payload is neither, so it must not go through those helpers.

When search integration is implemented, return one `results` entry built by the guidance path:

- `result_type: "guidance"`
- `id`: the current step
- `content`: the guidance prose (clients that read `content` still have a string)
- `guidance_text`, `neighborhood` (`neighborhood_payload`: current node first, then neighbors
  in walk order; edges carry `direction`, `role`, `from_id`, `to_id`), `hop_count`
- no `relevance_score`

**5a and 5b are still unsigned recommendations.** `search_memory` has not gained
`current_step_id`, and `manage_graph` has not gained `get_guidance`, until a human picks
those semantics. Do not treat the recommendations in Decision 5 as a decision.

## Open questions still requiring a human

Whether `query` is ignored, used to rank inside the neighborhood, or rejected when
`current_step_id` is set (5a), and whether a procedural query with no `current_step_id`
keeps returning a flat list or auto-localizes to the entry step (5b). Both change what
`search_memory` means. The recommendations in Decision 5 are not a sign-off.
