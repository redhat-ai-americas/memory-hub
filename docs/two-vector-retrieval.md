# Two-Vector Retrieval

MemoryHub's retrieval pipeline uses two embedding vectors per search -- the **query** and the **session focus** -- to surface memories that are both relevant to what the agent asked and contextually appropriate for what the agent is currently working on.

## The problem

Standard vector search uses one signal: cosine similarity between the query embedding and each stored memory. An agent working on a deployment task that asks "How do I configure health checks?" gets back every memory mentioning health checks -- React component lifecycle methods, database connection pooling, CI pipeline gates -- alongside the Kubernetes probe configuration it actually needs.

The agent *knows* it's working on deployment. That contextual awareness lives in the session focus, a short string like "OpenShift deployment and container configuration" set via `set_focus`. Single-vector search ignores it.

## How it works

When an agent calls `search_memory` with a session focus active, MemoryHub embeds both the query and the focus string, producing two independent rankings of the candidate pool:

- **rank_query**: how well each memory matches the search query (what you're looking for)
- **rank_focus**: how well each memory matches the session focus (what domain you're working in)

These are blended using [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) (RRF):

```
score(memory) = weight_q / (K + rank_query) + weight_f / (K + rank_focus)
```

The `session_focus_weight` parameter (default 0.4) controls the blend. At 0.0, pure query matching. At 1.0, pure focus matching. The default gives the query 60% influence and the focus 40%.

## The three-stage pipeline

The production function `search_memories_with_focus` runs three stages:

```
pgvector cosine recall (top-K by query embedding)
    ↓
cross-encoder rerank (re-score top 32 by query text)
    ↓
RRF blend (merge reranked query ranks with focus cosine ranks)
    ↓
top max_results
```

**Stage 1** is cheap -- pgvector does the cosine distance sort in PostgreSQL. It pulls a recall pool larger than the final result count to give later stages headroom.

**Stage 2** is expensive but accurate. A cross-encoder model (`ms-marco-MiniLM-L12-v2`) reads the query and each candidate memory as a single text pair, producing a relevance score that accounts for token-level interactions that cosine similarity misses. This replaces the query-cosine ranks for the top 32 candidates. When the reranker is unavailable, the pipeline falls back to cosine ranks gracefully.

**Stage 3** blends the (possibly reranked) query ranks with the focus-cosine ranks via RRF. When domain tags or graph neighbors are present, those become additional RRF signals with their own weights, all summing to 1.0.

## Additional ranking signals

The RRF blend can incorporate up to four signals:

| Signal | Source | What it measures |
|--------|--------|-----------------|
| Query rank | Cross-encoder (or cosine fallback) | Relevance to the search query |
| Focus rank | Cosine distance to focus embedding | Proximity to the agent's working context |
| Domain rank | Tag overlap count | How many domain tags match the request |
| Graph rank | Relationship hop distance | How close a memory is in the knowledge graph |

Weights are carved proportionally so they always sum to 1.0. When a signal isn't active (no focus set, no domains requested, no graph traversal), its weight redistributes to the remaining signals.

## Pivot detection

Since both embeddings are available, the pipeline measures the cosine distance between query and focus. When this distance exceeds a threshold (default 0.55), the search result includes a `pivot_suggested: true` flag with a reason string. This tells the consuming agent that its query is far from its declared focus -- a signal to re-declare focus and reload contextually relevant memories.

The `.memoryhub.yaml` config and the generated Claude Code rule file wire this into agent behavior automatically: on pivot detection, the agent calls `search_memory` for the new topic and adds the results to its working set.

## When the focus is empty

When no focus is set or `session_focus_weight` is 0, the function short-circuits to plain `search_memories` -- no focus embedding, no reranker call, no RRF blend. The focus vector is purely additive; disabling it gives you standard vector search.

## Configuration

These parameters control the pipeline, configurable per-project via `.memoryhub.yaml` or per-call via the `search_memory` tool:

| Parameter | Default | Effect |
|-----------|---------|--------|
| `session_focus_weight` | 0.4 | Focus influence in RRF blend (0.0-1.0) |
| `domain_boost_weight` | 0.3 | Domain tag signal weight |
| `graph_boost_weight` | 0.2 | Graph proximity signal weight |
| `pivot_threshold` | 0.55 | Cosine distance triggering pivot detection |
| `weight_threshold` | 0.8 | Minimum memory weight for injection |
| `max_results` | 20 | Final result count |

## Benchmark results

The approach was validated against a 200-memory synthetic corpus across four pipelines:

- **Baseline**: cosine similarity only
- **NEW-1** (shipped): RRF blend of cross-encoder reranked query + focus cosine
- **NEW-2** (rejected): focus-augmented query embedding (catastrophic cross-topic recall collapse)
- **NEW-3** (rejected): cross-encoder only, no focus signal (roughly neutral on short, topic-coherent memories)

NEW-1 strictly dominated on recall, precision, and MRR at `session_focus_weight` between 0.2 and 0.4, with the largest gains on ambiguous and cross-topic queries -- exactly the cases where contextual bias matters most. Full methodology and raw data are in [`research/agent-memory-ergonomics/two-vector-retrieval.md`](../research/agent-memory-ergonomics/two-vector-retrieval.md) and [`benchmarks/`](../benchmarks/).

## Further reading

- [Agent memory ergonomics design](agent-memory-ergonomics/design.md) -- the full design cluster covering search shape, session focus, loading patterns, and push notifications
- [Cross-encoder benchmark](../benchmarks/) -- cost/benefit analysis of reranking at various candidate set sizes
- [Architecture](ARCHITECTURE.md) -- how the retrieval pipeline fits into the overall system
