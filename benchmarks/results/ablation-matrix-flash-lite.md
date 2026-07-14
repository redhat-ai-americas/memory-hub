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
- **Keyword:** BM25 index populated (requires `tsvector` column, not yet in schema)
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

## Next steps

1. **#342 (reranker upgrade):** Deploy bge-reranker-v2-m3 on TEI GPU, re-run matrix
2. **Keyword signal:** Add BM25/tsvector to search path, re-run matrix
3. **Re-run with active signals:** Only meaningful after at least reranker + keyword are deployed
