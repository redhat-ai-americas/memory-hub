## MemoryHub Benchmarking Progress -- Meeting Summary (2026-07-16)

### Where we are

MemoryHub's PersonaMem accuracy is **83.7%** (submitted) with Granite embeddings, Granite reranker, and Gemini Pro as the answer model. An earlier internal run scored 84.9%; the submitted result uses the upstream adapter. Both scores exceed Cognee (81.8%) among published AMB leaderboard entries. We are behind Hindsight (86.6%) and hybrid-search (84.4%) -- the gap to close with fact extraction and reconciliation. Leaderboard placement is pending maintainer review of [PR #34](https://github.com/vectorize-io/agent-memory-benchmark/pull/34).

On LongMemEval (retrieval benchmark, 500 queries), MemoryHub scores **R@10 = 1.000** and **MRR = 1.000** -- perfect retrieval.

### Granite pipeline upgrade (+3.7pp)

The single biggest improvement this cycle was replacing MiniLM embeddings and the failing CPU reranker with Granite models on GPU:

| Component | Before | After |
|---|---|---|
| Embeddings | all-MiniLM-L6-v2 (384-dim, CPU) | granite-embedding-english (GPU, L40S) |
| Reranker | ms-marco-MiniLM (512-token max, CPU, 413 on PersonaMem) | granite-reranker-english-r2 (8192-token max, GPU) |
| PersonaMem accuracy | 81.2% | 84.9% |

The old reranker couldn't score PersonaMem's long transcripts at all (returned HTTP 413 on every query, falling back to cosine-only). The Granite reranker handles them natively, which accounts for most of the +3.7pp gain.

### Key findings from the last week

**1. Content delivery was the bottleneck, not retrieval.** An S3 truncation bug was silently clipping 27K-char documents to 1K chars. This single bug accounted for the entire 21pp gap between our MCP path and BM25. Fixed July 15.

**2. Chunk size doesn't matter for PersonaMem.** A 21-config sweep (32-2048 tokens, 0-25% overlap) showed a flat accuracy curve: 62.0-62.6% across all configs. The retrieval unit granularity matters, not the chunk parameters.

**3. Fact extraction is the right retrieval unit.** Mem0-style fact extraction hit **63.3%** at only **1,256 context tokens** -- best budgeted mode, 22x fewer tokens than full-context. Facts dominate the synthesis categories that matter most for "know me" use cases.

**4. Cheapest extraction model wins.** Flash Lite extraction (63.3%) beat Flash extraction (57.7%). Good news for cost.

### Production pipeline shipped

- Write-time fact extraction via MCP sampling (zero server GPU cost)
- `retrieval_unit` search parameter (facts/chunks/parents/auto)
- Full opt-in/opt-out control via `extract_facts` parameter
- Reconciliation service with decision log (#347, PR #414) -- search-before-write with guardrailed thresholds and LLM tiebreaker

### Efficiency story

MemoryHub's value proposition is not just accuracy -- it's accuracy per dollar:

| Mode | Accuracy | Context tokens/query | Relative cost |
|---|---|---|---|
| Full-context (Pro) | 84.9% | ~28,000 | 1x |
| Facts mode (Flash Lite) | 63.3% | 1,256 | ~0.002x |
| Facts mode (Pro, projected) | ~75-80% | ~1,256 | ~0.09x |

The facts mode delivers 75% of the accuracy at 0.2% of the token cost. For high-volume deployments where cost matters more than peak accuracy, this is the operating point.

### Path to 85%+ (the epic's definition of done)

| Gap | Fix | Expected lift |
|---|---|---|
| No reconciliation active in benchmark | Phase 5: #347 reconciliation (PR ready) | improves fact quality over time |
| Facts not yet used in full-context mode | Combine parent + extracted facts in retrieval | +1-2pp |
| Weak on suggest_new_ideas category | Broader context for creative queries | +1-2pp |

The 85% target is within reach. Reconciliation and fact-augmented retrieval are the levers.

### Competitive landscape (PersonaMem 32k, all Gemini 3.1 Pro Preview)

Published AMB leaderboard entries shown for context; MemoryHub's results are internal measurements, not published leaderboard positions. The submitted score (83.7%, August 2026) is pending review.

| System | Accuracy | Approach | Source |
|---|---|---|---|
| Hindsight | 86.6% | LLM fact extraction into semantic graph | AMB leaderboard |
| hybrid-search | 84.4% | 512-token chunking, dense+sparse embeddings | AMB leaderboard |
| MemoryHub (Granite, internal) | 84.9% | Granite embed + reranker, hybrid search, no extraction | Internal run, 2026-07-16 |
| **MemoryHub (submitted)** | **83.7%** | **Granite embed + reranker, upstream adapter** | **PR #34, 2026-08-21** |
| Cognee | 81.8% | Chunking + graph entity extraction | AMB leaderboard |
| MemoryHub (MiniLM, July 12) | 81.2% | MiniLM embed, no working reranker | Internal run |

The remaining gap to Hindsight is attributable to fact extraction (which Hindsight uses and we have built but not yet activated in the benchmark path). The reconciliation pipeline (#347) is the next step toward closing it.
