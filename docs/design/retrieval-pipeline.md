# Retrieval Pipeline

MemoryHub uses a multi-signal hybrid retrieval pipeline. Dense vector search, sparse keyword search, cross-encoder reranking, session focus, and metadata signals are fused through Reciprocal Rank Fusion (RRF) into a single ranked result set. There is one embedding model, not two; the "two-vector" label in older docs refers to two uses of that model (query embedding and focus embedding), not two separate embedding spaces.

## Signals

Every search produces up to five independent rankings of the candidate pool. Each ranking is a signal; absent signals redistribute their weight to the others.

| Signal | What it ranks by | Source | Always on? |
|--------|-----------------|--------|------------|
| **Query** | Relevance to the search query | pgvector cosine distance, optionally replaced by cross-encoder scores | Yes |
| **Keyword** | Term overlap with the query | PostgreSQL `tsvector` + `ts_rank` (weighted: stub=A, content=B) | Yes, when query has matchable terms |
| **Focus** | Proximity to the agent's working context | Cosine distance between candidate embeddings and the focus-string embedding | When a session focus is set |
| **Domain** | Tag overlap count | Intersection of requested domain tags with memory tags | When domain tags are requested |
| **Graph** | Hop distance in the knowledge graph | BFS traversal from seed candidates, up to depth 3 (recursive CTE) | When `graph_depth > 0` |

## Embedding and reranking models

**Embedding**: `all-MiniLM-L6-v2` (384-dim), served via HuggingFace Text Embeddings Inference (TEI) on-cluster. The personal/local edition uses `granite-embedding-small-english-r2` via ONNX Runtime, also 384-dim.

**Cross-encoder reranker**: `ms-marco-MiniLM-L12-v2`, also served via TEI. Re-scores the top 24 candidates (configurable via `MEMORYHUB_RERANK_POOL_SIZE`) by reading query-candidate pairs as a single sequence. When the reranker is unreachable or disabled, the pipeline falls back to cosine ranks. The fallback reason is logged and surfaced in the response.

## The pipeline

```
1. pgvector cosine recall
   Pull k_recall candidates by cosine distance to the query embedding.

2. Cross-encoder rerank (optional)
   Re-score the top pool_size candidates using the cross-encoder.
   Replace cosine ranks with cross-encoder ranks for those candidates.

3. Keyword recall
   Run tsvector full-text search against the same candidate pool.
   Rank by ts_rank score.

4. Focus ranking (when focus is set)
   Rank candidates by cosine distance to the focus-string embedding.

5. Domain + graph ranking (when requested)
   Rank by tag overlap count and graph hop distance respectively.

6. RRF fusion
   Blend all active signal ranks into a single score per candidate.
   Return the top max_results.
```

## RRF fusion

All signals are combined using Reciprocal Rank Fusion with K=60 (from the [original RRF paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)):

```
score(m) = w_q / (60 + rank_query(m))
         + w_k / (60 + rank_keyword(m))
         + w_f / (60 + rank_focus(m))
         + w_d / (60 + rank_domain(m))
         + w_g / (60 + rank_graph(m))
```

Candidates not found by a signal receive a miss rank of `k_recall + 1`.

### Default weights

| Parameter | Default | Controls |
|-----------|---------|----------|
| `session_focus_weight` | 0.4 | Focus signal share (query gets the complement) |
| `keyword_boost_weight` | 0.15 | Keyword signal share |
| `domain_boost_weight` | 0.3 | Domain tag signal share |
| `graph_boost_weight` | 0.2 | Graph proximity signal share |

Weights are carved proportionally and always sum to 1.0. When a signal is absent, its allocation redistributes to the remaining signals. All weights are tunable per-call via the SDK/MCP tool and per-project via `.memoryhub.yaml`.

## Personal edition

The personal edition (SQLite backend) implements the same algorithmic pipeline with different storage primitives:

| Cluster | Personal |
|---------|----------|
| pgvector cosine operator (`<=>`) | Brute-force cosine in Python |
| PostgreSQL `tsvector` + `ts_rank` | SQLite FTS5 + `bm25()` |
| TEI HTTP for embeddings | ONNX Runtime (local, `granite-embedding-small-english-r2`) |
| TEI HTTP for cross-encoder | Not available (cosine fallback) |

A `RecallBackend` protocol abstracts the four storage-specific operations (`vector_recall`, `keyword_recall`, `similarity_check`, `graph_neighbors`) so the hybrid search logic is shared.

## Ablation

Any signal can be individually disabled per-call via the `disabled_signals` parameter, which accepts a list of signal names: `reranker`, `focus`, `keyword`, `domain`, `graph`. This is used for benchmark ablation testing and for debugging retrieval quality.

## Semantic chunking

Oversized memories are split into child nodes at paragraph/sentence boundaries, each independently embedded. At search time, chunk hits are expanded back to their parent memory. Chunks are retrieval infrastructure; they are never returned to callers.

## Further reading

- [Two-vector retrieval](two-vector-retrieval.md) -- the focus-vector design, pivot detection, temporal awareness, and the benchmark that selected this approach
- [Graph-enhanced memory](graph-enhanced-memory.md) -- entity extraction and the graph ranking signal
- [Storage layer](storage-layer.md) -- pgvector schema, indexes, and MinIO object storage
- [Architecture](../ARCHITECTURE.md) -- how the retrieval pipeline fits into the overall system
