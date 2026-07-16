# Session Summary: 2026-07-16 -- Extraction Model Comparison + Pipeline Implementation

## What landed

### Part 1: Extraction model comparison (negative result)

Ran gemini-3.5-flash as the extraction model against the Flash Lite
baseline. 195 PersonaMem docs, 589 queries at k=70.

| Extraction model | Facts in DB | Accuracy | Avg memories/query | Avg ctx chars | Empty contexts |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 6,697 | **63.3%** | 70.0 | 6,030 | 0 |
| gemini-3.5-flash | 6,522 | 57.7% | 64.3 | 6,949 | 43 |

Delta: -5.6pp. Root causes:

1. **JSON parse errors:** 35 of 195 docs (18%) failed extraction due to
   malformed JSON from 3.5-flash (extra content after the array). This
   left 43 queries with zero retrieved facts.
2. **Wordier facts:** 3.5-flash produced longer fact statements (6,949
   avg chars vs 6,030), meaning fewer distinct facts fit in the
   retrieval window despite similar total counts.
3. **Slightly fewer facts:** 6,522 vs 6,697 (coverage gap from parse
   failures).

Conclusion: extraction model quality is NOT the lever for PersonaMem.
The cheapest viable model (Flash Lite) wins. A stronger model
over-elaborates and has worse JSON compliance. The pipeline should
default to the cheapest model that can reliably produce structured
output.

Note: gemini-2.5-flash was the originally planned model but is
deprecated ("no longer available to new users"). gemini-3.5-flash was
the next available step up.

### Part 2: Write-time fact extraction pipeline (PR #407, merged)

Built eager fact extraction into the MemoryHub write path using MCP
sampling, per `planning/eager-fact-extraction.md`. Four commits:

1. **Extraction prompt + create_fact_children()** -- versioned YAML
   prompt at `prompts/fact_extraction.yaml`, public `create_fact_children()`
   function in memory service. Facts are `branch_type="fact"` children
   with extraction_run_id metadata for #348 provenance.

2. **retrieval_unit search preference** -- new parameter
   (`facts|chunks|parents|auto`) on both `search_memories()` and
   `search_memories_with_focus()`. Pool discipline: one unit class per
   RRF pool, preventing the #344 regression pattern.

3. **MCP sampling integration** -- `write_memory` calls `ctx.sample()`
   with `result_type=FactExtractionResult` when content is oversized.
   15s timeout; on failure, sets `facts_extracted="deferred"`. Writes
   never fail on extraction failure.

4. **SDK parameters** -- `extract_facts` (eager|background|off) on
   `write()`, `retrieval_unit` on `search()`. Both forwarded via
   `_WRITE_OPTS`/`_SEARCH_OPTS` whitelists.

### Issue filed

- #406: Fact extraction gap for SDK/CLI callers (no MCP sampling
  available). Design issue in Backlog.

### Other

- Committed CLAUDE.md competitor-citation rule (on feat/chunk-params-sweep)
- Merged PR #402 (design docs: eager-fact-extraction, client-supplied
  intelligence, d5-readiness-audit)

## What didn't land

- **Deployment of sampling-enabled MCP server.** The pipeline is
  implemented but not deployed. Deployment changes the client-server
  contract (stop-and-ask gate from session plan).
- **Integration test with live sampling.** Requires a deployed server
  with a sampling-capable client connected.
- **Haiku extraction test.** Part 1 showed model quality doesn't help,
  so the Haiku ceiling test was skipped (session plan said: only if
  Flash extraction beats Flash Lite meaningfully).

## Follow-ups

- Deploy the sampling-enabled MCP server (next session, with explicit
  approval per stop-and-ask gate)
- Re-run PersonaMem benchmark with production pipeline facts (vs
  prototype's standalone extraction)
- #406: design solution for SDK/CLI callers
- Container deployment: add `prompts/` to the Containerfile COPY and
  build-context.sh
- Clean up sweep projects (`amb-c32-o0-k10`, etc.) and
  `amb-facts-flash` from the database
