# MemoryHub Retrieval Benchmark Results

Living document tracking retrieval quality and performance across MemoryHub releases. Each section records the configuration, metrics, and the retrieval pipeline state at the time of measurement. Re-run after each improvement to track deltas.

Raw result JSON files are committed alongside this document in `benchmarks/`.

## Metric Definitions

**Recall@k (R@k):** Of all the relevant items in the dataset, what fraction appears in the top-k results? R@5 = 0.80 means 80% of relevant items were found in the top 5. Higher is better. A system with perfect R@10 never misses a relevant item in its top-10 results.

**Precision@k (P@k):** Of the top-k results returned, what fraction is actually relevant? P@10 = 0.60 means 6 of the 10 returned items were relevant. Higher is better. Precision penalizes returning irrelevant results.

**MRR (Mean Reciprocal Rank):** How high does the first relevant result appear? MRR = 1.0 means the first relevant item is always rank 1. MRR = 0.5 means it's on average at rank 2. Computed as the mean of 1/rank_of_first_relevant_item across all queries. Higher is better.

**NDCG@k (Normalized Discounted Cumulative Gain):** Like precision, but gives more credit for relevant items appearing higher in the ranking. A relevant item at rank 1 contributes more than one at rank 10. Normalized against the ideal ranking so the score is always 0-1.

**Latency (p50/p95/p99):** The 50th/95th/99th percentile search latency in milliseconds. p50 is the median; p99 is the worst-case-excluding-outliers. Measured end-to-end from query submission to result return, including embedding, database query, reranking, and RRF blending.

## Competitive Context

| System | Benchmark | R@5 | R@10 | MRR | Source |
|--------|-----------|-----|------|-----|--------|
| **MemoryHub v0.2** | LongMemEval oracle (500q) | **0.999** | **1.000** | **1.000** | This document, 2026-07-10 |
| MemPalace (hybrid) | LongMemEval | 0.984 | -- | -- | Wu et al., ICLR 2025 |
| MemPalace (semantic only) | LongMemEval | 0.966 | -- | -- | Wu et al., ICLR 2025 |
| GPT-4o (no memory layer) | LongMemEval | ~0.30-0.70 | -- | -- | Wu et al., ICLR 2025 |

| **MemoryHub v0.3 (Combined)** | PersonaMem 32k (589q) | **84.9%** | -- | -- | This document, 2026-07-19 |
| **MemoryHub v0.3 (Granite)** | PersonaMem 32k (589q) | **84.9%** | -- | -- | This document, 2026-07-16 |
| Hindsight | PersonaMem 32k | 86.6% | -- | -- | AMB leaderboard |
| hybrid-search | PersonaMem 32k | 84.4% | -- | -- | AMB leaderboard |
| Cognee | PersonaMem 32k | 81.8% | -- | -- | AMB leaderboard |
| MemoryHub v0.2 (MiniLM) | PersonaMem 32k (589q) | 81.2% | -- | -- | This document, 2026-07-12 |
| BM25 baseline | PersonaMem 32k | 67.7% | -- | -- | This document, 2026-07-12 |

Notes:
- MemPalace numbers are from the LongMemEval paper's reported "session decomposition + fact-augmented key expansion + time-aware query expansion" pipeline.
- Our run uses the oracle variant (evidence sessions only, not the full 115K-token haystack). The oracle variant isolates retrieval quality from the haystack-filtering step. Running LongMemEval_S (full haystack) is the next comparison point.
- MemoryHub v0.3 uses granite-embedding-english + granite-reranker-english-r2 (GPU). MemoryHub v0.2 used all-MiniLM-L6-v2 (384-dim). MemPalace uses text-embedding-3-large (3072-dim).
- PersonaMem accuracy column shows MCQ exact-match accuracy (not R@k). All MemoryHub and leaderboard runs use Gemini 3.1 Pro Preview as the answer LLM. BM25 number shown is the Flash Lite run (67.7%).

## Benchmark Inventory

### 1. AMB PersonaMem (Jiang et al., 2025) -- Long-Horizon Preference Tracking

**What it measures:** End-to-end agent memory quality on personal preference tracking across 195 multi-turn conversation transcripts. 589 MCQ questions test whether the memory system retrieves the correct preference from long conversation histories. Scoring is exact letter match (no LLM judge needed).

**Dataset:** PersonaMem 32k split. 195 documents (full conversation transcripts, multi-thousand tokens each), 589 MCQ queries across multiple synthetic personas with stable and evolving preferences.

**MemoryHub adapter:** Each conversation transcript is ingested as a memory node via the MemoryHub provider in the AMB harness. Documents are ingested into `amb-*` tenants to isolate benchmark data. Queries use the hybrid search pipeline (vector + keyword + reranker fallback + RRF).

#### Run: 2026-07-12 (v0.2, post-hybrid-search, Gemini 3.1 Pro Preview)

**Pipeline state:** pgvector cosine recall -> cross-encoder rerank attempt (413 on all PersonaMem transcripts, falls back to cosine) -> RRF blend (query + focus + keyword signals). Keyword boost weight = 0.15. No document chunking active in benchmark path.

**Answer LLM:** Gemini 3.1 Pro Preview (matches AMB leaderboard standard).

| Provider | Model | Queries | Correct | Accuracy |
|----------|-------|---------|---------|----------|
| **MemoryHub** | **Gemini 3.1 Pro Preview** | **589** | **478** | **81.2%** |
| MemoryHub | Gemini 3.1 Flash Lite | 589 | 417 | 70.8% |
| BM25 baseline | Gemini 3.1 Flash Lite | 589 | 399 | 67.7% |

**AMB Leaderboard comparison (all using Gemini 3.1 Pro Preview):**

| System | Approach | Accuracy |
|--------|----------|----------|
| Hindsight | LLM fact extraction into semantic graph | 86.6% |
| hybrid-search | 512-token chunking, dense+sparse embeddings | 84.4% |
| Cognee | Chunking + graph entity extraction | 81.8% |
| **MemoryHub** | **Hybrid search, no extraction, no chunking in benchmark path** | **81.2%** |

Result files: `amb-outputs/personamem/_archive/memoryhub-pro-unchunked-20260712/`, `amb-outputs/personamem/_archive/memoryhub-flash-lite-unchunked-20260712/`, `amb-outputs/personamem/bm25/`

#### Run: 2026-07-16 (v0.3, Granite embeddings + reranker, Gemini 3.1 Pro Preview)

**Pipeline state:** Fresh ingest with Granite embeddings (granite-embedding-english on L40S GPU) and granite-reranker-english-r2 (L40S GPU, 8192-token max). Hybrid search with RRF blend. No chunking, no fact extraction in this run. Documents ingested into `amb-granite-pro` project.

**Answer LLM:** Gemini 3.1 Pro Preview (leaderboard-comparable).

| Provider | Model | Queries | Correct | Accuracy |
|----------|-------|---------|---------|----------|
| **MemoryHub (Granite)** | **Gemini 3.1 Pro Preview** | **589** | **500** | **84.9%** |

**AMB Leaderboard comparison (all using Gemini 3.1 Pro Preview):**

| System | Approach | Accuracy |
|--------|----------|----------|
| Hindsight | LLM fact extraction into semantic graph | 86.6% |
| **MemoryHub (Granite)** | **Granite embed + reranker, hybrid search, no extraction** | **84.9%** |
| hybrid-search | 512-token chunking, dense+sparse embeddings | 84.4% |
| Cognee | Chunking + graph entity extraction | 81.8% |
| MemoryHub (MiniLM) | MiniLM embed, no reranker on PersonaMem | 81.2% |

**Delta from v0.2:** +3.7pp (84.9% vs 81.2%). The gain comes from Granite embeddings and the Granite reranker now being able to score PersonaMem's long transcripts (8192-token max vs old 512-token limit that fell back to cosine-only).

Result file: `outputs/personamem/granite-pro/rag/32k.json`

#### Run: 2026-07-19 (v0.3, Combined library + dreaming, Gemini 3.1 Pro Preview)

**Pipeline state:** Combined ingestion mode: library ingest (195 sessions as memory nodes with chunks) then dreaming extraction (985 facts extracted via gemini-3.1-flash-lite from conversation threads). Both coexist in a single project (`amb-combined-pro`): 3,468 agent-written memories (`source=agent`) + 985 extracted facts (`source=dreaming`). Search uses the full pool with Granite embeddings, reranker, and hybrid RRF blend.

**Answer LLM:** Gemini 3.1 Pro Preview (leaderboard-comparable).

| Provider | Model | Queries | Correct | Accuracy |
|----------|-------|---------|---------|----------|
| **MemoryHub (Combined)** | **Gemini 3.1 Pro Preview** | **589** | **500** | **84.9%** |

**AMB Leaderboard comparison (all using Gemini 3.1 Pro Preview):**

| System | Approach | Accuracy |
|--------|----------|----------|
| Hindsight | LLM fact extraction into semantic graph | 86.6% |
| **MemoryHub (Combined)** | **Granite embed + reranker, hybrid search + dreaming extraction** | **84.9%** |
| MemoryHub (Granite) | Granite embed + reranker, hybrid search, no extraction | 84.9% |
| hybrid-search | 512-token chunking, dense+sparse embeddings | 84.4% |
| Cognee | Chunking + graph entity extraction | 81.8% |

**Per-category comparison (library-only vs combined):**

| Category | Library | Combined | Delta |
|----------|---------|----------|-------|
| recall_user_shared_facts | 104/129 (80.6%) | 109/129 (84.5%) | +3.9pp |
| track_full_preference_evolution | 131/139 (94.2%) | 128/139 (92.1%) | -2.2pp |
| recalling_the_reasons_behind_previous_updates | 91/99 (91.9%) | 91/99 (91.9%) | 0.0pp |
| generalizing_to_new_scenarios | 53/57 (93.0%) | 52/57 (91.2%) | -1.8pp |
| provide_preference_aligned_recommendations | 50/55 (90.9%) | 50/55 (90.9%) | 0.0pp |
| recalling_facts_mentioned_by_the_user | 15/17 (88.2%) | 15/17 (88.2%) | 0.0pp |
| suggest_new_ideas | 56/93 (60.2%) | 55/93 (59.1%) | -1.1pp |
| **Overall** | **500/589 (84.9%)** | **500/589 (84.9%)** | **0.0pp** |

**Key finding: identical retrieval, answering noise.** Comparing the retrieved context for all 589 queries reveals that the library-only and combined runs return byte-identical context. The dreaming facts (985 short extracted statements) never rank high enough to appear in the top-k retrieval results alongside the 3,468 longer session memories. The 12 queries that flipped between runs (6 gained, 6 lost) are pure Gemini Pro answering non-determinism, not retrieval signal.

**Flipped query breakdown:**
- **Gained** (library wrong, combined right): 5 in `recall_user_shared_facts`, 1 in `suggest_new_ideas`
- **Lost** (library right, combined wrong): 3 in `track_full_preference_evolution`, 1 in `generalizing_to_new_scenarios`, 2 in `suggest_new_ideas`

**Interpretation:** The registered prediction that dreaming's synthesis signature would lift generalization and reasons categories is not supported. The per-category deltas are LLM noise, not retrieval signal. Dreaming extraction is confirmed non-destructive (identical retrieval), but the extracted facts are too short and too numerous (985 facts competing against 3,468 longer documents) to surface in the top-k ranking. This points to a retrieval-side improvement opportunity: boosting short, high-signal extracted facts in the ranking function, or using a dedicated fact retrieval channel separate from the session memory search.

**Source tagging validated:** The `source` column (migration 026) correctly tags library memories as `agent` and extracted facts as `dreaming`. The `exclude_source` search filter enables ablation testing without re-ingestion.

Result file: `outputs/personamem/combined-pro/rag/32k.json`

#### Run: 2026-07-12 (v0.2, SDK provider with chunking, Flash Lite)

**Pipeline state:** Same hybrid search pipeline, but ingestion now goes through the MemoryHub SDK (`client.write()`) which triggers server-side `semantic_chunk()`. Documents are stored as parent nodes with chunk children. Search uses `weight_threshold=0.0` and `mode="full_only"` to return parent documents only.

**Answer LLM:** Gemini 3.1 Flash Lite (not leaderboard-comparable).

| Run | Model | Queries | Correct | Accuracy | Avg Context Tokens | Avg Retrieve ms |
|-----|-------|---------|---------|----------|--------------------|-----------------|
| unchunked | Flash Lite | 589 | 417 | 70.8% | 26,695 | 3,168 |
| **chunked (SDK)** | **Flash Lite** | **589** | **304** | **51.6%** | **1,193** | **1,053** |

Result file: `amb-outputs/personamem/memoryhub-chunked/rag/32k.json`

**Finding: chunking caused a -19.2 point accuracy regression.** The root cause is clear from avg context tokens: the chunked run returns 22x less context per query (1,193 vs 26,695 tokens). The `mode="full_only"` filter excludes chunks from results, but parent document retrieval is also degraded, likely because:

1. Parent documents are now competing with their own chunks in the vector index, diluting retrieval scores.
2. The `weight=0.0` assigned to chunks may be interfering with RRF score aggregation even with `weight_threshold=0.0`.
3. Semantic chunking changes the embedding landscape; parent embeddings are computed from the full document but ranked against chunk-level embeddings.

This confirms that naive chunking without tuning hurts retrieval quality. Tuning work (#343) should investigate: disabling chunk embedding (store chunks for display but don't embed), adjusting chunk weights, or switching to a retrieve-chunk-then-expand-to-parent strategy.

#### Analysis

MemoryHub achieves 81.2% without document chunking or LLM extraction, competitive with Cognee (81.8%) which uses both. The 5.4-point gap to Hindsight (86.6%) is attributable to two factors:

1. **No reranker on PersonaMem transcripts.** The cross-encoder (ms-marco-MiniLM-L12-v2, 512-token max) returns 413 on every query, falling back to cosine-only ranking. Upgrading to bge-reranker-v2-m3 (8192-token max, GPU) should recover 3-5 points.

2. **No fact extraction.** MemoryHub stores raw conversation transcripts; facts buried thousands of tokens deep are invisible to the 1000-char embedding prefix. Top performers (Hindsight, Mem0) extract structured facts before storage. The dreaming pipeline (#336) addresses this.

**LLM model impact:** Gemini Pro adds +10.4 points over Flash Lite on MemoryHub (81.2% vs 70.8%), and the BM25 baseline also improves with better models (Flash Lite 67.7% vs Haiku 62.6%). Model quality is a significant factor alongside retrieval quality.

**MemoryHub retrieval delta:** MemoryHub adds +3.1 points over BM25 with the same model (Flash Lite: 70.8% vs 67.7%). The delta is modest because the reranker is disabled on PersonaMem; with the reranker active (shorter documents), the delta is larger per the cluster retrieval benchmark results.

**Chunking regression:** The -19.2 point drop from chunking (70.8% -> 51.6%) shows that chunking must be carefully tuned before it helps. The dominant signal is context volume: unchunked returns ~27K tokens of context, chunked returns ~1.2K. The retrieval pipeline needs either chunk-to-parent expansion or separate treatment of chunk vs parent embeddings.

### 2. LongMemEval (ICLR 2025) -- Session-Level Retrieval

**What it measures:** Whether the retrieval layer finds the right evidence sessions given a natural-language question about past conversations.

**Dataset:** 500 questions across 6 types (single-session-user, single-session-assistant, single-session-preference, temporal-reasoning, knowledge-update, multi-session). Oracle variant uses only the evidence sessions as the haystack.

**MemoryHub adapter:** Each chat session is ingested as a memory node (content truncated to 10K chars, embedding from first 500 chars). Questions are used as search queries. A hit = the relevant evidence session's memory node appears in top-k results.

#### Run: 2026-07-10 (v0.2, post-hybrid-search)

**Pipeline state:** pgvector cosine recall -> cross-encoder rerank (ms-marco-MiniLM-L12-v2) -> RRF blend (query + focus + keyword signals). Keyword boost weight = 0.15.

**Embedding:** all-MiniLM-L6-v2 (384-dim), deployed on OpenShift via vLLM.

| Question Type | Count | R@5 | R@10 | MRR | Avg Latency |
|---------------|-------|-----|------|-----|-------------|
| knowledge-update | 78 | 1.000 | 1.000 | 1.000 | -- |
| multi-session | 133 | 1.000 | 1.000 | 1.000 | -- |
| single-session-assistant | 56 | 1.000 | 1.000 | 1.000 | -- |
| single-session-preference | 30 | 1.000 | 1.000 | 1.000 | -- |
| single-session-user | 70 | 1.000 | 1.000 | 1.000 | -- |
| temporal-reasoning | 133 | 0.996 | 1.000 | 1.000 | -- |
| **Overall** | **500** | **0.999** | **1.000** | **1.000** | **372.7ms** |

Result file: `longmemeval-oracle-20260710T144331Z.json`

#### Limitations and next steps

- **Oracle variant only.** The oracle variant pre-filters to evidence sessions, so the haystack is small (3-10 sessions per question). Running LongMemEval_S (40+ sessions, ~115K tokens) tests retrieval in a larger haystack and is the fairer comparison to MemPalace.
- **No answer-quality evaluation.** We measure retrieval (did we find the right session?) but not answer generation (did we produce the right answer?). The LongMemEval evaluation script uses an LLM judge for answer quality. Adding this would give us the full pipeline score.
- **Embedding truncation.** Sessions are embedded from the first 500 chars only (embedding service 413s on longer inputs). Chunking sessions into multiple memory nodes would improve embedding coverage.

### 3. Cluster Retrieval -- Production Memory Quality

**What it measures:** Whether hybrid search (keyword + vector + reranker) surfaces different and better results than vector-only search on real MemoryHub data.

**Dataset:** 733 production memories across multiple tenants. 16 test queries: 8 exact-match keyword queries (CLI commands, config keys, acronyms) and 8 semantic queries.

#### Run: 2026-07-10 (v0.2, post-hybrid-search)

| Metric | Vector-only | Hybrid (keyword + vector + reranker) |
|--------|------------|--------------------------------------|
| Avg latency | 313ms | 2,521ms |
| Queries with keyword hits | 0/16 | 7/16 (44%) |
| Queries surfacing new results | 0/16 | 15/16 (94%) |
| Avg new results per query | 0 | 2.8 |

Per-query breakdown:

| Query | Vec ms | Hyb ms | KW hits | New results |
|-------|--------|--------|---------|-------------|
| parmesan cheese | 821 | 1,410 | 6 | 0 |
| CORS_ALLOWED_ORIGINS | 243 | 2,634 | 0 | 3 |
| kubectl apply deployment.yaml | 290 | 2,660 | 0 | 3 |
| register_session api_key | 295 | 2,754 | 2 | 2 |
| content_type experiential behavioral | 248 | 2,546 | 0 | 4 |
| pgvector cosine_distance | 304 | 2,245 | 0 | 2 |
| alembic migration upgrade | 297 | 2,545 | 1 | 4 |
| FIPS compliance | 287 | 2,540 | 2 | 1 |
| how does authentication work | 259 | 2,554 | 0 | 2 |
| what decisions were made about the database | 296 | 2,735 | 0 | 3 |
| user preferences and settings | 297 | 1,891 | 0 | 2 |
| deployment architecture for the MCP server | 286 | 2,639 | 0 | 3 |
| how to search for memories | 304 | 2,976 | 9 | 4 |
| conversation thread persistence | 242 | 2,865 | 3 | 4 |
| agent memory governance and compliance | 296 | 2,771 | 1 | 3 |
| integration with external systems | 242 | 2,567 | 0 | 5 |

Result file: `cluster-retrieval-20260710T130710Z.json`

**Key finding:** Hybrid search surfaces materially different results on 94% of queries (avg 2.8 new results per query), but at ~8x latency cost. The latency is dominated by the cross-encoder reranker (~2.2s per call), not the keyword recall (~10-20ms).

### 4. Retrieval at Scale -- Latency Profiling

**What it measures:** pgvector cosine search latency as corpus size grows.

**Dataset:** Synthetic corpora at 100/1K/10K scale, 8 topics, deterministic mock embeddings. 16 labeled queries with ground-truth topic assignments.

#### Run: 2026-07-10 (v0.2, local PostgreSQL+pgvector)

| Scale | p50 ms | p95 ms | p99 ms | R@10 (vec) | MRR (vec) | MRR (hybrid) |
|-------|--------|--------|--------|-----------|-----------|-------------|
| 100 | 4.1 | 4.9 | 4.9 | 0.095 | 0.270 | 0.241 |
| 1,000 | 13.7 | 15.1 | 15.1 | 0.012 | 0.191 | 0.335 |
| 10,000 | 93.9 | 107.2 | 107.2 | 0.001 | 0.188 | 0.135 |

Result files: `retrieval-scale-20260710T125826Z.json`, `retrieval-scale-20260710T125902Z.json`

**Note:** These use mock (hash-based) embeddings, not semantic embeddings. The relevance numbers are not meaningful in absolute terms -- only the latency scaling and relative vector-vs-hybrid comparison matter. At 1K scale, hybrid search improves MRR by 75% (0.191 to 0.335).

### 5. Cross-Encoder Pool Size Sweep -- Latency vs Quality Tradeoff

**What it measures:** How many candidates to send through the cross-encoder reranker before diminishing returns set in. Larger pools produce better rankings but cost proportionally more reranker time.

**Dataset:** 733 production memories. 10 diverse queries (factual, semantic, code/config, vague). Baseline = pool size 64 (largest tested).

**Method:** Decouple the recall pool size (`RERANK_POOL_SIZE`) from the TEI API batch limit (`RERANK_API_BATCH=32`). Pool sizes above 32 use batched reranking (split into 32-item chunks, merge by cross-encoder score). Measure avg/p50/p95 latency and top-5/top-10 result set overlap with the pool=64 baseline.

#### Run: 2026-07-10 (v0.2, 733 production memories)

| Pool Size | Avg Latency | p50 | p95 | Top-5 Overlap | Top-10 Overlap |
|-----------|------------|-----|-----|---------------|----------------|
| 16 | 1,588ms | 1,630ms | 2,293ms | 94.0% | 90.0% |
| 24 | 2,088ms | 2,172ms | 2,422ms | 94.0% | 93.0% |
| **32 (prev default)** | **2,679ms** | **2,833ms** | **3,134ms** | **98.0%** | **96.0%** |
| 48 | 3,848ms | 3,960ms | 4,383ms | 98.0% | 99.0% |
| 64 | 5,143ms | 5,204ms | 5,696ms | 100% | 100% |

Result file: `pool-sweep-20260710T154357Z.json`

**Decision: Set default pool size to 24.** The 32->24 reduction cuts avg latency by 22% (2,679ms -> 2,088ms) with 94% top-5 overlap and 93% top-10 overlap. The 6-7% miss rate represents candidates ranked 25th-32nd by cosine that the cross-encoder would have promoted -- rare enough at this corpus size that the latency savings justify the tradeoff. The pool size is configurable via `MEMORYHUB_RERANK_POOL_SIZE` env var for deployments that prefer accuracy over speed.

## Retrieval Pipeline Changelog

Track what changed between measurement points so deltas are attributable.

| Date | Change | Issues | Expected Impact |
|------|--------|--------|-----------------|
| 2026-07-10 | Cross-encoder pool size tuned to 24 (was 32) | #274 | -22% hybrid latency (2.7s->2.1s), 94% top-5 overlap |
| 2026-07-10 | Hybrid keyword+vector search with RRF blend | #305 | +recall on exact-match queries (CLI commands, config keys) |
| 2026-07-10 | Alembic 024: tsvector generated column + GIN index | #305 | Zero-cost keyword index, auto-populates on existing data |
| -- | Time-decay recency bias (not yet shipped) | #306 | Better ranking of recent memories over stale ones |
| -- | Entity extraction cascade (not yet shipped) | #272 | Enables graph-traversal retrieval (#273) |
| -- | Graph-traversal retrieval (not yet shipped) | #273 | +recall on entity-linked memories not found by text similarity |
| -- | Conversation message semantic search (not yet shipped) | #270 | Search over thread content, not just memory nodes |

## Open Improvement Issues

| Issue | Description | Expected Benchmark Impact |
|-------|-------------|--------------------------|
| #306 | Time-decay recency bias | Improves ranking freshness; measurable via temporal-reasoning queries |
| #272 | Entity extraction pipeline | Prerequisite for #273; spaCy/GLiNER/LLM cascade |
| #273 | Graph vs flat retrieval | +recall on entity-linked memories; needs labeled graph-query dataset |
| #274 | Cross-encoder cost/benefit | Find optimal reranker candidate pool size to cut hybrid latency |
| #270 | Conversation message search | Extends retrieval to thread content |
| #308 | Offline embedding fallback | Air-gapped deployment support |

## Future Benchmarks to Consider

### Higher priority (strengthens arXiv paper)

- **LongMemEval_S (full haystack):** Run against the 40-session/115K-token variant. This is the fair comparison to MemPalace and other systems that report LongMemEval numbers. Oracle variant isolates retrieval quality; S variant tests retrieval in noise.
- **LongMemEval answer quality:** Use the LongMemEval evaluation script with an LLM judge to measure end-to-end answer accuracy, not just retrieval recall. This is what the paper reports.
- **AMB (Agent Memory Benchmark) harness:** Vectorize's open-source harness wraps LoCoMo, LongMemEval, LifeBench, PersonaMem, MemBench, MemSim, BEAM, and AMA-Bench under one pipeline. Running MemoryHub through AMB produces directly comparable numbers against Cognee, Hindsight, BM25, and others on their leaderboard.
- **Ablation study:** Measure the contribution of each RRF signal independently (vector-only, +reranker, +keyword, +focus, +domain, +graph). This is the most publishable result format.

### Medium priority (validates enterprise value)

- **AMA-Bench / MemoryAgentBench:** Both target capabilities where flat vector systems fail (multi-hop reasoning, update handling). Good discriminators for MemoryHub's versioning and graph features.
- **Poisoning resistance:** PoisonedRAG showed 5 malicious docs in millions cause 90% attack success. Design a benchmark that measures how MemoryHub's curation pipeline resists adversarial writes.
- **Staleness detection:** Measure how well time-decay (#306) and `relevant_until` prevent stale memories from ranking above fresh ones.

### Lower priority (operational)

- **Concurrent query throughput:** Measure latency degradation under 1/5/10/25 parallel queries at each scale tier.
- **Cost per query:** Token cost breakdown (embedding + reranker + LLM judge) per search call.
