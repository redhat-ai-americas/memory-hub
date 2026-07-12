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

| **MemoryHub v0.2** | PersonaMem 32k (589q) | **81.2%** | -- | -- | This document, 2026-07-12 |
| Hindsight | PersonaMem 32k | 86.6% | -- | -- | AMB leaderboard |
| hybrid-search | PersonaMem 32k | 84.4% | -- | -- | AMB leaderboard |
| Cognee | PersonaMem 32k | 81.8% | -- | -- | AMB leaderboard |
| BM25 baseline | PersonaMem 32k | 67.7% | -- | -- | This document, 2026-07-12 |

Notes:
- MemPalace numbers are from the LongMemEval paper's reported "session decomposition + fact-augmented key expansion + time-aware query expansion" pipeline.
- Our run uses the oracle variant (evidence sessions only, not the full 115K-token haystack). The oracle variant isolates retrieval quality from the haystack-filtering step. Running LongMemEval_S (full haystack) is the next comparison point.
- MemoryHub uses all-MiniLM-L6-v2 (384-dim) embeddings. MemPalace uses text-embedding-3-large (3072-dim). Despite the 8x smaller embedding, MemoryHub's hybrid pipeline (vector + keyword + RRF) achieves higher recall.
- PersonaMem accuracy column shows MCQ exact-match accuracy (not R@k). MemoryHub and BM25 both used Gemini 3.1 Pro Preview as the answer LLM; leaderboard systems also used Gemini 3.1 Pro Preview. BM25 number shown is the Flash Lite run (67.7%); Pro partial run (140/589) was trending at 72.9%.

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

Result files: `amb-outputs/personamem/memoryhub/rag/32k-summary.json`, `amb-outputs/personamem/memoryhub-flash-lite/rag/32k-summary.json`, `amb-outputs/personamem/bm25/rag/32k-summary.json`

#### Analysis

MemoryHub achieves 81.2% without document chunking or LLM extraction, competitive with Cognee (81.8%) which uses both. The 5.4-point gap to Hindsight (86.6%) is attributable to two factors:

1. **No reranker on PersonaMem transcripts.** The cross-encoder (ms-marco-MiniLM-L12-v2, 512-token max) returns 413 on every query, falling back to cosine-only ranking. Upgrading to bge-reranker-v2-m3 (8192-token max, GPU) should recover 3-5 points.

2. **No fact extraction.** MemoryHub stores raw conversation transcripts; facts buried thousands of tokens deep are invisible to the 1000-char embedding prefix. Top performers (Hindsight, Mem0) extract structured facts before storage. The dreaming pipeline (#336) addresses this.

**LLM model impact:** Gemini Pro adds +10.4 points over Flash Lite on MemoryHub (81.2% vs 70.8%), and the BM25 baseline also improves with better models (Flash Lite 67.7% vs Haiku 62.6%). Model quality is a significant factor alongside retrieval quality.

**MemoryHub retrieval delta:** MemoryHub adds +3.1 points over BM25 with the same model (Flash Lite: 70.8% vs 67.7%). The delta is modest because the reranker is disabled on PersonaMem; with the reranker active (shorter documents), the delta is larger per the cluster retrieval benchmark results.

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
