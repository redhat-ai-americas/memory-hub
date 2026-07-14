# RRF Signal Ablation Matrix -- Flash Lite (2026-07-13)

## Summary

All 7 ablation configs produced identical results because the deployed MCP
server has only vector similarity active. Reranker, focus, keyword, domain,
and graph signals are not configured in the current deployment, so disabling
them has no effect. The matrix validates the infrastructure (EvalHub pipeline,
memoryhub provider, skip_ingestion, tenant isolation) and establishes a
vector-only baseline through the MCP search path.

## Results

| Config | disabled_signals | mcq_accuracy | delta vs baseline |
|--------|-----------------|-------------|-------------------|
| baseline | (none) | 48.39% | -- |
| no-reranker | reranker | 48.39% | 0.00 |
| no-focus | focus | 48.39% | 0.00 |
| no-keyword | keyword | 48.22% | -0.17 |
| no-domain | domain | 48.39% | 0.00 |
| no-graph | graph | 48.56% | +0.17 |
| bm25-only | reranker,focus,keyword,domain,graph | 48.39% | 0.00 |

**Answer model:** gemini-3.1-flash-lite
**Dataset:** PersonaMem 32k (589 queries)
**Memory provider:** memoryhub (MCP search, skip_ingestion)
**Tenant:** amb-benchmark
**Commit:** 42be4ed (post-PR #368)

## Key finding

The ablation matrix is valid infrastructure but **not yet informative for
signal contribution** because no RRF signals beyond vector similarity are
active in the deployed MCP server. The signal implementations exist in
`memoryhub_core/services/memory.py` (reranker at L1354, focus at L1220,
keyword/domain/graph throughout the `search_memories_with_focus` function)
but require:

- **Reranker:** TEI GPU service deployed and `MEMORYHUB_RERANKER_URL` set (#342)
- **Focus:** Session focus set via `set_focus` tool (no active focus in benchmark mode)
- **Keyword:** `search_vector` tsvector column and GIN index exist in deployed
  schema (migration `024_add_search_vector`), but keyword recall only runs
  inside `search_memories_with_focus()` -- the benchmark's non-focus search
  path does not invoke it. Activation is #372.
- **Domain:** Domain tags on memories (benchmark data has no domain tags)
- **Graph:** Relationship edges between memories (benchmark data has no edges)

## Comparison with prior results

| Provider | Mode | mcq_accuracy | Notes |
|----------|------|-------------|-------|
| bm25 (local) | library | 67.7% | Local BM25 on raw documents, no MCP |
| memoryhub (MCP) | library | 48.4% | Vector-only through MCP search |
| bm25 (local, prior session) | library | 60.0% | 20-query smoke |

The 19pp gap (67.7% BM25 local vs 48.4% MCP vector) suggests BM25 keyword
matching outperforms embedding-only retrieval on PersonaMem's MCQ format.
This is expected -- MCQ questions often contain exact terms from the source
conversations, favoring keyword match over semantic similarity.

## EvalHub job IDs

| Config | Job ID |
|--------|--------|
| baseline | 1148b0a7-b1de-4202-84bd-2b3543e98421 |
| no-reranker | 66b12387-1ac2-4e13-9af9-da54676e38e8 |
| no-focus | fb2bdb94-0b0d-4d70-a896-3b945fe87e66 |
| no-keyword | 49bcd6b7-17bb-4c41-a511-e12ad79d2ab9 |
| no-domain | 1d809671-4f0f-457e-9842-0f3c7a1fc5bd |
| no-graph | 198342a1-751f-4227-8222-def225b0acfa |
| bm25-only | 63cf17f2-3210-47fb-a47c-2c77ccbf2f00 |

## Baseline discrepancy investigation (#369)

**Question:** Why 48.4% here vs 70.8% in the #332 Flash Lite baseline?

### H1: Corpus contamination -- CONFIRMED (primary cause)

The amb-benchmark corpus contains 6,614 nodes: 195 parent documents and
6,419 chunk nodes (`branch_type='chunk'`). All have `is_current=true` and
populated embeddings. The 70.8% baseline was measured against an unchunked
corpus (195 parents only); this matrix reused the chunked corpus via
`skip_ingestion=True`.

**Evidence (SQL, `memoryhub-db` via port-forward 2026-07-14):**

```
SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE branch_type='chunk') as chunks,
       COUNT(*) FILTER (WHERE branch_type IS NULL OR branch_type != 'chunk') as parents
FROM memory_nodes WHERE tenant_id = 'amb-benchmark';

 total | chunks | parents
-------+--------+---------
  6614 |   6419 |     195
```

**Mechanism:** `_build_search_filters()` (`memory.py:693`) does not filter on
`branch_type`. The SQL recall query (`search_memories()` L953-961) returns
`max_results=10` by cosine distance from all 6,614 nodes. At a 33:1
chunk-to-parent ratio, chunks dominate the top-k. Parent documents are
displaced, reducing context from ~27K tokens (unchunked) to ~1.2K tokens
(chunked), which directly explains the accuracy drop.

The 48.4% result is within noise of the #344 chunked diagnostic (51.6%,
1,193 avg context tokens). Both reflect the same underlying issue: chunk
nodes competing with parents in the vector recall pool without exclusion
or deduplication.

**RESULTS.md line 86** previously documented this mechanism:

> Parent documents are now competing with their own chunks in the vector
> index, diluting retrieval scores.

### H2: Retrieval path difference -- ELIMINATED (subsumed by H1)

Both the 70.8% and 48.4% runs use identical retrieval code:

- Same provider: `memoryhub.py:retrieve()` with `k=10`,
  `weight_threshold=0.0`, `mode="full_only"`
- Same service function: `search_memories()` (non-focus path, cosine-only)
- No focus parameter passed; the benchmark never triggers
  `search_memories_with_focus()` or keyword/RRF logic
- No code changes between runs (`e2cbea6` provider rewrite predates both)

The gap is corpus state, not retrieval logic.

### H3: Tenant/scope pool difference -- ELIMINATED (subsumed by H1)

Both runs search `tenant_id='amb-benchmark'` with
`owner_id='amb-{user_id}'` and `scope='project'`. The pool difference is
chunk contamination (6,419 additional nodes), not tenant or scope isolation.

```
SELECT COUNT(DISTINCT owner_id) FROM memory_nodes
WHERE tenant_id = 'amb-benchmark';
-- Result: 37 (same distinct owners for both runs)
```

### H4: tsvector contradiction -- RESOLVED (results doc was wrong)

The `search_vector` column EXISTS in the deployed schema and is fully
operational:

| Artifact | Claim | Actual state |
|----------|-------|--------------|
| `models/memory.py:110` | Declares weighted `to_tsvector` (generated column) | Correct |
| Migration `024_add_search_vector` | Adds column + GIN index | Applied |
| Deployed DB schema | `search_vector tsvector`, `ix_memory_nodes_search_vector GIN` | Present |
| All 6,614 amb-benchmark nodes | `search_vector IS NOT NULL` | 6,614/6,614 populated |
| `ts_rank()` query test | Returns ranked results for `'favorite food'` | Works |
| **This doc, line 40** | **"requires tsvector column, not yet in schema"** | **WRONG** |

The keyword signal is inactive for the benchmark, but not because the
schema is missing. The actual reason: the benchmark provider does not pass
a `focus` parameter, so the MCP tool routes to `search_memories()` (the
non-focus path at `search_memory.py:922`), which is cosine-only. Keyword
recall via `plainto_tsquery` only runs inside `search_memories_with_focus()`
at L1445-1469, which requires a focus string to activate.

**Correction applied:** line 40 "not yet in schema" replaced below.

### Attribution summary

| Factor | Contribution | Verdict |
|--------|-------------|---------|
| Chunk contamination of vector recall pool | ~22 points (48.4% vs 70.8%) | CONFIRMED |
| Retrieval code path difference | 0 points | ELIMINATED |
| Tenant/scope pool difference | 0 points | ELIMINATED |
| Missing tsvector schema | n/a (column exists; doc was wrong) | RESOLVED |

The entire 22-point gap is attributable to corpus contamination: 6,419
chunk nodes in the amb-benchmark search pool that were not present during
the 70.8% baseline run. No other factor contributes.

### Corpus statement for Matrix A

**Matrix A must run against a clean corpus of exactly 195 PersonaMem 32k
parent documents, produced by fresh ingestion with `reset=True` and
`semantic_chunk()` disabled (i.e., no chunk children).** The current
amb-benchmark corpus (195 parents + 6,419 chunks) must be reset before
Matrix A. The reset procedure is: run the benchmark with
`skip_ingestion=False`, which triggers the DELETE at
`memoryhub.py:131` followed by fresh ingestion. Chunking must be
disabled in the provider's `ingest()` path or the server's
`semantic_chunk()` must be bypassed.

Verify pre-Matrix-A corpus state:
```sql
SELECT COUNT(*) as total,
       COUNT(*) FILTER (WHERE branch_type = 'chunk') as chunks
FROM memory_nodes WHERE tenant_id = 'amb-benchmark';
-- Expected: total=195, chunks=0
```

## Next steps

1. **#372 (keyword signal activation):** Wire the keyword recall path into
   the non-focus search function, or ensure the benchmark triggers the
   focused path. The tsvector column and GIN index are already deployed;
   only the code path needs activation.
2. **#342 (reranker upgrade):** Deploy bge-reranker-v2-m3 on TEI GPU
3. **#371 (system map + preflight):** Encode the corpus check above as a
   preflight assertion
4. **#360 re-scoped (Matrix A):** Re-run with clean corpus + active signals
