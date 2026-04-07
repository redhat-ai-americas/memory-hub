# Research: Two-Vector Retrieval Ranking Math

**Status:** Options identified 2026-04-07. No empirical data yet. Benchmark harness is sketched below but not yet built.

**Feeds into:** [`../design.md`](../design.md) §Session Focus and Retrieval Biasing, issue #58, open question Q1.

## Question

Given a query vector `q` (from the current `search_memory` call) and a session focus vector `f` (embedded once at `register_session` time from a declared or inferred focus string), how should `search_memory` combine them into a single ranking?

The constraint: out-of-focus memories should be **down-weighted, not excluded**. A focused "deployment" session should still surface a UI memory if the user asks a pointed UI question — the session bias should lose to a strong direct query match. But a vague query during a focused session should drift toward memories in the session's focus area rather than the global top-K.

## Three Candidate Approaches

### Option A: Weighted sum at query time

For each candidate memory `m`, compute:

```
score(m) = (1 - w) * cosine_sim(q, m) + w * cosine_sim(f, m)
```

where `w` is the `session_focus_weight` knob (0.0 = pure query, 1.0 = pure focus, default ~0.4).

**Implementation.** Two pgvector cosine-distance calls per memory, or one pgvector call for `q·m` plus an in-memory loop for `f·m` (since `f` is a single vector known at request time, the second comparison can happen in Python). Rank by the weighted sum.

**Pros:**
- Simple to reason about mathematically
- Honest about what the weight means (direct linear interpolation)
- Easy to expose as a single `session_focus_weight` knob

**Cons:**
- Two similarity computations per memory (though both are cheap)
- Requires pulling a larger candidate set into memory and ranking in Python, because the combined score can't easily be pushed into a single pgvector ORDER BY
- The "right" value of `w` depends on how similar the domain vocabulary is across topics — tuning is empirical

**Performance hit:** On a ~50-memory store, doing two cosine computations in Python is free. On a ~5000-memory store, this starts to matter and the `ORDER BY` can no longer happen in pgvector — you're fetching all candidates with their embeddings and sorting in Python. That's a meaningful regression from the current single-query pgvector path.

### Option B: Rerank-after-recall

Two-stage retrieval:

1. **Recall stage** — use pgvector to fetch the top-K candidates (e.g., K=50) by `cosine_sim(q, m)` alone. This is exactly the current behavior.
2. **Rerank stage** — for each of the K candidates, compute `rerank_score = (1 - w) * recall_score + w * cosine_sim(f, m)` and sort by that.

**Implementation.** One pgvector query (unchanged). Then a Python loop over K candidates to compute the rerank score. Return the top N from the reranked list (N < K, e.g., N=10 from K=50).

**Pros:**
- The expensive pgvector call stays the same — no regression on the recall stage
- Rerank is cheap because K is small and the focus vector is known
- Decouples "how many candidates to consider" (recall breadth) from "how strongly to bias" (rerank weight)
- Natural home for a future LLM-based reranker or a multi-feature rerank that includes recency, weight, etc.

**Cons:**
- Recall stage might miss a memory that would rank high after focus biasing but ranks outside the top-K by query alone. This is the fundamental weakness of rerank-after-recall: **you can only rerank what you recall.**
- Needs a K knob in addition to the N knob (and `session_focus_weight`). More parameters.
- Two-pass latency is slightly worse than single-pass, though the second pass is in-memory

**The recall miss risk is real but bounded.** If `session_focus_weight` is moderate (≤0.5), the rerank can only move a candidate up by at most half its position. So a memory at recall-rank 30 can't jump to final-rank 1. This means as long as K is large enough (K ≥ 3×N as a rule of thumb), the miss rate is low. But it's nonzero.

### Option C: Composite query vector

Pre-combine `q` and `f` into a single vector before the pgvector call:

```
q_combined = normalize((1 - w) * q + w * f)
```

Pass `q_combined` to the existing pgvector cosine-distance query. One call, top-N back.

**Implementation.** The simplest of the three from a code perspective — the existing search code just swaps which vector gets passed to `MemoryNode.embedding.cosine_distance(...)`. Adds a 5-line helper to compute `q_combined`.

**Pros:**
- Single pgvector call, no performance regression
- Trivial to implement (smallest code change of the three)
- Keeps everything in the database layer where it's cheap

**Cons:**
- **Averaging embeddings is semantically suspect.** Embedding models are trained such that semantically similar texts cluster, but the arithmetic mean of two unrelated embeddings is not guaranteed to sit in a meaningful place in the space. In practice it often "works" for similar reasons bag-of-words averaging works — related concepts cluster, so the average lands somewhere in the neighborhood — but there's no theoretical guarantee and the behavior is model-dependent.
- Interpretability suffers. With Option A the weight has a clear linear meaning. With Option C, a `w` of 0.4 doesn't mean "40% of the ranking comes from focus" — it means "search is looking for things near the average of the query and a 40%-weighted focus direction," which is harder to reason about.
- Can't easily be extended to a multi-feature rerank later

**Empirical risk:** This option is the cheapest to try and also the most likely to produce surprising results. If it works on a synthetic benchmark, it's the winner. If it doesn't, Option A or B win.

## Recommendation (Provisional)

**Start with Option B (rerank-after-recall).** Reasoning:

1. It preserves the current pgvector recall path, so there's no performance regression on the hot path.
2. The K knob gives us a clean escape valve if recall-miss becomes a real problem (just raise K).
3. It's the most extensible option — if we later want to add recency biasing, weight biasing, or even LLM-based reranking, the rerank stage is the right place for all of them.
4. Option C is tempting for its simplicity but the "averaging embeddings" risk is hard to assess without the benchmark, and if it fails we'd have to rewrite anyway.
5. Option A is reasonable but hits a pgvector limitation at scale that we'd eventually have to work around.

**Validate with a benchmark before committing.** The recommendation above is a prior, not a conclusion. The benchmark should test all three.

## Proposed Benchmark Harness

### Dataset

Build a synthetic test set of **200 memories** across 4 topic areas (50 memories each):

- `deployment` — OpenShift, containerfiles, image registries, deploy scripts
- `mcp-tools` — tool design, response shapes, fastmcp patterns
- `ui` — dashboard panels, PatternFly, React, backend routes
- `auth` — OAuth, JWT, RBAC, session management

Each memory should have:
- 100–400 character content
- A ground-truth topic label (for measuring recall/precision)
- A weight drawn from a realistic distribution (mostly 0.7–0.9, some 0.5, few at 0.95)

The content should mimic real memory-hub memories — project context, decisions, rationale — not Wikipedia paragraphs. Borrow phrasing from the actual current memory store where possible.

### Queries

For each topic, define **10 queries** at three specificity levels:

- **Specific** (4 queries) — mentions topic-specific terms that should match even without session bias. Example for `deployment`: "how do we handle image digest pinning in the deploy script?"
- **Ambiguous** (4 queries) — could match multiple topics depending on context. Example: "what's the pattern for this?"
- **Cross-topic** (2 queries) — intentionally pulls from a different topic than the session focus. Example during a `deployment` session: "how does the UI handle PF6 Label colors?"

Total: 40 queries (10 per topic × 4 topics).

### Sessions

For each query, evaluate under three session focuses:

- **Matching focus** — session focus matches the query's ground-truth topic
- **Cross focus** — session focus is a different topic
- **No focus** — baseline, session vector is zero or absent

### Metrics

For each (query, session) combination, compute:

- **Recall@10** — fraction of ground-truth-relevant memories that appear in the top 10 results
- **Precision@10** — fraction of top-10 results that are ground-truth-relevant
- **MRR (mean reciprocal rank)** — how high the first correct result appears
- **Cross-topic recall** — for cross-topic queries under a session focus, did the relevant cross-topic memory still surface?

The key tension is **recall vs. cross-topic surfacing**. Good session biasing improves recall on specific and ambiguous queries without tanking cross-topic recall.

### Sweep

Run each option (A, B, C) at several `session_focus_weight` values: `[0.0, 0.2, 0.4, 0.6, 0.8]`. For Option B also sweep `K ∈ [20, 50, 100]`.

This gives 3 options × 5 weights × 3 focus conditions × 40 queries = 1800 data points, plus the Option B K sweep adds another 3×40 = 120 more per weight. Roughly 3000 total evaluations — small enough to run in a few minutes, large enough to see signal.

### Harness location

Place under `tests/perf/test_two_vector_retrieval.py` with the synthetic dataset as a fixture in `tests/perf/fixtures/topics/`. Mark the test with `@pytest.mark.benchmark` so it doesn't run in CI. Expose a runner script at `scripts/bench-two-vector.py` that prints a results table and saves raw data to `benchmarks/two-vector-retrieval-<timestamp>.json`.

## Open Sub-Questions

1. **Should `f` be re-normalized?** Embeddings are typically L2-normalized. If the session focus string is much shorter than typical memories, its raw embedding might have different magnitude characteristics. Test both normalized and raw.
2. **How does `f` interact with stub-mode results?** If Option B (rerank) promotes a low-weight memory above the stub threshold, does it still return as a stub? Probably yes — stubbing is weight-based, not rank-based. Clarify in the #57 design.
3. **Does the recommended approach change for very small memory stores?** At ~30–50 memories (current state), the K tuning for Option B is meaningless — K is basically "all of them." Option C might be better in this regime. Worth checking.
4. **Should `session_focus_weight` be auto-tuned?** Start with a manual knob. Auto-tuning is a phase 2 concern — would need the #61 usage signal histogram to feed it.

## References

- `../design.md` §Two-Vector Retrieval — the design this research supports
- `../open-questions.md` Q1, Q2 — related unresolved items
- `../../storage-layer.md` — pgvector capabilities this research builds on
- Issue #58 — implementation tracking
