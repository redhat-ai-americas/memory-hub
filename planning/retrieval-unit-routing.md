# Retrieval-Unit Routing

Status: design-complete
Issue: #447
Epic: dreaming-followon

## Problem

The 2026-07-20 source ablation benchmark showed that naive pooling of
extracted facts with full conversation transcripts produces negligible
lift (+0.1pp: 72.8% combined vs 72.7% library-only). Dreaming-only
achieves 50.9%, proving the facts contain useful information, but full
transcripts dominate the top-k retrieval window and crowd facts out.

Raw SQL confirms dreaming facts appear at cosine rank ~13-15 per persona,
behind ~12 agent memories whose embedding similarity is inflated by shared
persona-header prefixes. With k=70 and ~100 agent memories per persona,
facts rarely surface in results.

Hindsight (86.6%, #1 on PersonaMem) uses LLM fact extraction into a
semantic graph searched separately -- the architecture pattern this
design addresses.

A secondary problem: the retrieval pipeline returns a fixed k memories
regardless of total token size. This is fine for a 1M-context LLM like
Claude but harmful for smaller models (120k context) where 70 memories
could consume 50k+ tokens, starving the prompt and answer generation.

## Decision: Split routing + token budget (A-lite + C's framing)

Blend of Approach A (separate searches) and Approach C (enrichment
framing), with a token budget layer on top.

**Two searches, facts as enrichment, budget-aware merge.**

### Retrieval pipeline

```
                   ┌─────────────────┐
                   │  Query arrives   │
                   └────────┬────────┘
                            │
               ┌────────────┴────────────┐
               │                         │
    ┌──────────▼──────────┐   ┌──────────▼──────────┐
    │ Search: source=agent│   │Search: source=dream. │
    │ k = over_fetch_k    │   │ k = over_fetch_k     │
    └──────────┬──────────┘   └──────────┬───────────┘
               │                         │
               └────────────┬────────────┘
                            │
                   ┌────────▼────────┐
                   │  Merge & score  │
                   │  (interleave)   │
                   └────────┬────────┘
                            │
                   ┌────────▼────────┐
                   │  Fill token     │
                   │  budget (greedy)│
                   └────────┬────────┘
                            │
                   ┌────────▼────────┐
                   │  Return docs    │
                   └─────────────────┘
```

### Step 1: Over-fetch from both pools

Two parallel searches against the same query:

- **Transcripts**: `source=agent`, `k=over_fetch_k` (default 100)
- **Facts**: `source=dreaming`, `k=over_fetch_k` (default 50)

Over-fetching is cheap (the embedding lookup and reranker run regardless).
The real filtering happens in the merge/budget step.

### Step 2: Merge

Interleave results to guarantee both sources get representation. Two
strategies (configurable, default round-robin):

**Round-robin** (simple, default): Take top transcript, top fact, top
transcript, top fact, ... until both pools are exhausted. Within each
pool, the server's relevance ordering is preserved.

**Weighted-score merge** (future option): Compute a combined score:
`combined = relevance_score * (1 - weight_factor) + weight * weight_factor`
and sort by combined score. This lets high-weight memories (critical
policies, weight=1.0) surface ahead of lower-weight but higher-relevance
memories. Requires tuning `weight_factor`.

Round-robin is the right starting point because:
- It guarantees a minimum number of facts (roughly 1:1 ratio)
- It doesn't require tuning a weight_factor hyperparameter
- The ablation will tell us if this is enough or if we need weighted merge

### Step 3: Fill token budget

Walk the merged list. For each memory:
1. Count tokens via tiktoken (`count_tokens` in `memory_bench/utils.py`)
2. If adding it would exceed `max_context_tokens`, skip it
3. Otherwise, add it to the output list and decrement remaining budget

When `max_context_tokens` is unset (default), all merged results pass
through -- preserving current behavior for large-context LLMs.

Weight plays in here naturally: in a budget-constrained scenario, the
interleaving ensures facts get slots, and within each pool the server
already returns the most relevant results first. A future refinement
could re-sort by `weight * relevance_score` before budget filling, but
round-robin + budget is the right v1.

### Step 4: Return

The final document list is returned to the benchmark runner. Documents
from both sources appear in interleaved order. The LLM sees both
transcript context and fact context without either being crowded out.

## Configuration

All via existing env-var pattern in the harness:

| Env var | Values | Default | Description |
|---------|--------|---------|-------------|
| `MEMORYHUB_ROUTING_MODE` | `pooled`, `split` | `pooled` | `pooled` = current single-search behavior; `split` = two-search routing |
| `MEMORYHUB_FACT_K` | int | 50 | Over-fetch k for facts pool (split mode only) |
| `MEMORYHUB_TRANSCRIPT_K` | int | 100 | Over-fetch k for transcripts pool (split mode only) |
| `MEMORYHUB_MAX_CONTEXT_TOKENS` | int | (none) | Token budget for returned context; unlimited when unset |
| `MEMORYHUB_MERGE_STRATEGY` | `round_robin`, `weighted` | `round_robin` | How to interleave results from the two pools |

All new env vars are optional. When none are set, behavior is identical
to today (single search, k=70, no token budget). This is important for
backward compatibility -- existing benchmark configs and smaller-model
deployments continue to work without changes.

The existing `MEMORYHUB_K` continues to work in `pooled` mode. In `split`
mode, `MEMORYHUB_TRANSCRIPT_K` and `MEMORYHUB_FACT_K` replace it.

`MEMORYHUB_MAX_CONTEXT_TOKENS` works in both modes. Even in `pooled`
mode, it provides value by capping context size for small-model
deployments.

## Implementation scope

**Harness only** -- no server or SDK changes needed. The server already
supports `source` and `exclude_source` filtering on search (SQL-level
WHERE clause, end-to-end through MCP tool and SDK).

### Files to modify

- `benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py`:
  - Add new env vars to `prepare()`
  - Modify `_run_retrieve()` to support split routing
  - Add `_merge_results()` for interleaving
  - Add `_apply_token_budget()` for budget-aware truncation
- `benchmarks/amb-harness/tests/test_retrieval_routing.py` (new):
  - Test split routing produces results from both sources
  - Test round-robin interleaving order
  - Test token budget truncation
  - Test pooled mode unchanged (regression)

### Existing infrastructure used

- `memory_bench.utils.count_tokens` (tiktoken, cl100k_base encoding)
- SDK `client.search(source=..., exclude_source=...)` kwargs
- `Memory.relevance_score`, `Memory.weight`, `Memory.source`, `Memory.content`

## Benchmark validation

Baseline: 72.7% library-only, 72.8% combined naive (Flash Lite).
Target: measurable lift from split routing (>= +2pp on combined).
Method: same ablation protocol, same dataset (PersonaMem 32k).

Benchmark runs:
1. `pooled` mode (current) -- reproduce 72.8% baseline
2. `split` + `round_robin` -- measure delta
3. `split` + `round_robin` + `max_context_tokens=20000` -- verify
   budget-constrained retrieval still produces useful results

## Alternatives considered

### B. Fact-aware RRF scoring

Boost `source=dreaming` memories in the RRF blend with a configurable
weight multiplier, similar to the existing domain boost.

Rejected: requires server-side changes to the RRF scoring pipeline.
The split routing achieves the same goal (fact representation) without
touching the server. Could revisit if split routing proves insufficient.

### C. Two-stage retrieve-then-enrich (pure form)

Retrieve transcripts first, then for each result find related facts
by thread linkage or entity overlap, and append them to context.

Partially adopted: we took C's framing (facts as enrichment) but
replaced the graph traversal with a simpler second search. The graph
traversal adds latency and complexity for uncertain benefit. If the
second search doesn't provide enough lift, graph-based enrichment
is the next thing to try.
