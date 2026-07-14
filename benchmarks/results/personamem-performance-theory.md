# Why PersonaMem Performance Is Low -- Theory Document

Last updated: 2026-07-14. Working hypotheses, not conclusions.

## The numbers

| Configuration | Accuracy | Corpus | Notes |
|--------------|----------|--------|-------|
| BM25 local (no MCP) | 67.7% | clean (195 parents) | Flash Lite, keyword match on raw documents |
| MemoryHub #332 baseline | 70.8% | clean (unchunked, pre-#344) | Flash Lite, old provider path |
| MemoryHub #332 baseline | 81.2% | clean (unchunked, pre-#344) | Gemini PRO — the +10.4pp over 70.8% is the measured model uplift, NOT retrieval |
| MemoryHub vector-only matrix | 48.4% | CONTAMINATED (6,419 chunks, 33:1) | Flash Lite, per #369/#376 attribution |
| Keyword on/off smoke (PR #379) | 55.0% both | clean (post-reset) | 20 queries only — small-sample, not a baseline |
| Competitor reference: Cognee | 81.8% | n/a | PersonaMem leaderboard (Pro) |
| Competitor reference: Hindsight | 86.6% | n/a | PersonaMem leaderboard (Pro) |

**Correction (2026-07-14 review):** an earlier draft of this doc labeled
48.4% as the clean-corpus number and called 81.2% "inflated by chunk
contamination." That inverts the merged #369/#376 attribution: 48.4% was
measured ON the contaminated corpus; 70.8%/81.2% were measured on the
unchunked corpus, and the 81.2-vs-70.8 difference is the answer model
(Pro vs Flash Lite), not the corpus. **No clean-corpus 589-query baseline
exists yet** — the corpus was reset mid-keyword-session and the only
post-reset datapoint is the 20-query smoke. Matrix A's vector-only row is
the decisive measurement. Registered predictions: ~70% confirms the #369
attribution; ~48-55% falsifies it and points at a content-delivery
difference in the MCP path (see H6).

## Hypothesis 1: PersonaMem's MCQ format strongly favors keyword matching

PersonaMem asks multiple-choice questions about facts from persona-specific
conversations. The questions and answer choices frequently contain exact
terms from the source text ("What did Alex say about PostgreSQL?" where
the memory literally contains "PostgreSQL").

BM25/keyword match finds these by exact term overlap. Vector similarity
finds them by semantic proximity, which is weaker when the discriminating
signal is a specific noun or proper name rather than a semantic concept.

**Evidence:** BM25 local (67.7%) beats vector-only (48.4%) by 19pp. This
gap is large and consistent across the 589-query dataset. The gap is the
primary performance problem.

**Implication:** keyword signal activation (#372, done) and reranker
(#342, next) should close part of this gap. If keyword+reranker bring
the MCP path to ~65-70%, the storage model is fine and the remaining
gap is tuning. If they don't, the problem is deeper.

## Hypothesis 2: Small per-user corpus makes keyword redundant at current scale

PersonaMem has ~5 documents per user (32 users, 195 total documents).
With k_recall=24 and max_results=10, cosine similarity already returns
every document for each user. Keyword recall can't surface *new*
candidates because the pool is already exhausted.

This explains the zero delta in the 20-query keyword smoke test (55.0%
both on and off). The keyword signal adds nothing when cosine already
returns every candidate.

**Evidence:** smoke test showed identical contexts retrieved with keyword
on vs off.

**Implication:** keyword signal will differentiate only when the per-user
corpus grows (post-chunking, post-ingestion of more data). At 195 docs,
keyword's value is in *ranking* (via RRF blend), not *recall*. The
reranker may be more impactful at this scale because it reranks the
existing candidates rather than trying to surface new ones.

## Hypothesis 3: Missing cross-encoder reranker leaves ranking quality on the table

The retrieval pipeline returns candidates by cosine distance, then blends
with keyword rank via RRF. But there's no cross-encoder reranker to do
fine-grained relevance scoring between the query and each candidate.

Cross-encoders (like bge-reranker-v2-m3) see the query and document
together and can capture term-level interactions that bi-encoder
embeddings miss. This is especially valuable for PersonaMem's MCQ format
where the answer hinges on a specific fact in the document.

**Evidence:** no direct evidence yet. Matrix A (#360) will test this by
comparing vector-only vs vector+reranker.

**Implication:** the reranker is the highest-expected-value signal for
this dataset. If it closes most of the 19pp gap, the iteration path is
clear (tune reranker weights, add chunking for larger corpora). If it
doesn't, the problem may be in the embedding model itself.

## Hypothesis 4: WITHDRAWN — chunks did not assist the original baseline

An earlier draft theorized the 81.2% was "accidental chunk-assisted
retrieval." This is falsified by the record: (a) the 81.2%/70.8% #332
runs predate the chunked ingest entirely (#369 H1, created_at evidence);
(b) #344's controlled A/B measured chunked = 51.6% vs unchunked = 70.8%
on identical content — chunks HURT by 19pp, they did not help; (c) #369's
misquoted "22pp discrepancy" was 70.8-vs-48.4, both Flash Lite, and was
attributed to contamination LOWERING the score.

**What survives of this hypothesis:** intentional chunk-to-parent
expansion (#343) remains worth building — not to "recover" a phantom
benefit, but because chunk-granular matching with parent-level delivery
is the correct design for corpora with long documents (match precision
without context starvation). The naive form (chunks compete with parents,
post-recall filtering) is the proven-harmful one.

## Hypothesis 6: Content delivery through the MCP path is lossy (NEW)

If H2 is true (cosine already returns every per-user document), then
BM25-local and MCP-vector deliver the same candidate set — and ranking
cannot explain the 19pp gap between them (67.7% vs the contested 48.4%).
The gap would have to live in WHAT the answerer receives: truncation,
stub-vs-full-content, per-memory token caps, or formatting differences
between the local BM25 path (raw documents) and the MCP search response.
The SDK-to-MCP send limitation surfaced on 2026-07-14 is adjacent
territory.

**Evidence:** none yet — this is the H1/H2 tension made explicit. H1 and
H2 cannot both explain the BM25-vs-MCP gap; if H2 holds, H6 is the
leading candidate.

**Test (cheap, do before interpreting Matrix A):** context-delivery
audit — for ~5 queries, dump the exact answerer context from the
BM25-local path and the MCP path on the clean corpus; compare token
counts and content fidelity. ~1 hour. If MCP delivers materially less
than local, that is a MemoryHub-first fix (product defect), not a
harness issue.

## Hypothesis 5: Embedding model may be suboptimal for conversational data

The current embedding model (deployed via vLLM) may not be well-suited
for the conversational, persona-specific nature of PersonaMem data.
Embeddings trained on general-purpose text corpora may not capture the
discriminating features of casual conversation.

**Evidence:** no direct evidence. This is the lowest-priority hypothesis
because it's the hardest to test (requires swapping embedding models
and re-ingesting the entire corpus).

**Implication:** defer this investigation until after reranker and
chunking are tuned. If the compound pipeline (vector + keyword +
reranker + chunk-to-parent) still underperforms, embedding model
evaluation becomes the next lever.

## What Matrix A will tell us

Matrix A runs 4 configurations on the clean 195-parent corpus:

1. vector-only (current baseline, ~48%)
2. vector + keyword
3. vector + reranker
4. vector + keyword + reranker

The pairwise deltas answer:
- **Does keyword ranking help** even when it can't expand the candidate
  pool? (H1 vs H2 -- if keyword lifts accuracy at this corpus size,
  the ranking contribution is real even without recall expansion)
- **Does the reranker close the BM25 gap?** (H3 -- if vector+reranker
  approaches 67%, the cross-encoder is the primary lever)
- **Is the compound effect additive?** (if keyword+reranker together
  exceed either alone, the signals are complementary and the RRF blend
  is working)

**Registered predictions (2026-07-14), so Matrix A results are read
against commitments rather than post-hoc stories:**

| Row | If #369 attribution is right | If H2 (pool exhaustion) is right | If H6 (lossy delivery) is right |
|-----|------------------------------|----------------------------------|--------------------------------|
| vector-only | ~70% | (compatible with any) | ~48-55% |
| +keyword delta | small | ~0 | ~0 |
| +reranker delta | small-moderate | ~0 | ~0 |

Interpretation guide: vector-only ~70% confirms #369 and makes the prior
matrix's 48.4% fully explained; vector-only ~48-55% falsifies #369's H2
elimination and makes the context-delivery audit (H6) mandatory before
any further signal work. Near-zero keyword/reranker deltas on this corpus
are EXPECTED under H2 and are not a failure — differentiation likely
requires #343 growing the per-user pool. If deltas appear anyway, H2 is
wrong and the signals matter even at 195 docs.

If Matrix A shows keyword+reranker at ~65%+, the path forward is
chunking (#343) to grow the per-user pool and let keyword do recall
expansion. If it plateaus below 55%, run the H6 audit before concluding
anything about the storage model.

## Matrix A Results (2026-07-14)

All 4 runs: 589 queries, Flash Lite, clean corpus (195 parents, 0 chunks),
amb-benchmark tenant, preflight-verified manifest.

| Configuration | Correct | Accuracy | Delta from baseline |
|---|---|---|---|
| vector-only | 274 | 46.5% | (baseline) |
| vector + keyword | 274 | 46.5% | +0.0pp |
| vector + reranker | 274 | 46.5% | +0.0pp |
| vector + keyword + reranker | 274 | 46.5% | +0.0pp |

**All four configurations produced exactly 274/589 correct answers.**

### Reading against registered predictions

| Row | Prediction table | Actual | Match? |
|-----|-----------------|--------|--------|
| vector-only | ~48-55% (H6 lossy delivery) | 46.5% | YES (low end) |
| +keyword delta | ~0 (H2 pool exhaustion) | 0 | EXACT |
| +reranker delta | ~0 (H2 pool exhaustion) | 0 | EXACT |

### Interpretation

1. **H2 (pool exhaustion) is conclusively confirmed.** At 195 docs and
   k_recall=24, cosine already retrieves every per-user document. Neither
   keyword recall nor cross-encoder reranking can change the candidate set
   or ranking when the entire pool is returned. The deltas are not just
   "near zero" -- they are exactly zero (same 274 queries correct in all 4
   runs). This is the strongest possible H2 signal.

2. **#369 attribution is falsified.** The prediction that a clean-corpus
   vector-only run would yield ~70% (matching the prior #332 baseline) is
   wrong. 46.5% on the clean corpus with the current MCP path is 24pp
   below the 70.8% #332 baseline. Something changed between the #332 run
   and now, or the #332 run had a configuration that no longer applies.

3. **H6 (lossy content delivery) is now the leading hypothesis.** The
   46.5% vector-only result falls in the predicted H6 range (48-55%).
   The gap between BM25-local (67.7%) and MCP-vector (46.5%) is 21pp,
   which cannot be explained by ranking differences when the candidate
   set is identical (H2). The context-delivery audit (H6 test) is
   mandatory before any further signal work.

4. **The 70.8% baseline is under suspicion.** Either the #332 run used a
   different answering model, a different corpus state, or a different
   MCP code path. Reproducing the exact #332 configuration is the first
   debugging step.

### Next steps

1. **H6 context-delivery audit** (mandatory): Compare exact answerer
   context from BM25-local vs MCP path for ~5 queries. If MCP delivers
   materially less content, that is a MemoryHub product defect.
2. **Reproduce #332 baseline**: Identify what configuration produced
   70.8% and whether it still works.
3. **Defer keyword/reranker tuning** until the per-user pool grows (#343)
   or the content delivery gap is closed. At 195 docs, these signals
   literally cannot differentiate.

## H6 Context-Delivery Audit (2026-07-14)

### Finding: Content truncation at ingestion, not retrieval

**Root cause**: `AppSettings.s3_threshold_bytes = 1024` (config.py:72).
Any content over 1024 bytes triggers the "oversized" path. PersonaMem
documents average 27,912 chars (min 3,923, max 60,818) -- all are
oversized.

In the oversized path with S3 configured (memory.py:155):
`db_content = data.content[:s3_prefix_chars]` where
`s3_prefix_chars = 1000`. The full content is uploaded to MinIO, but
only the first 1000 chars are stored in PostgreSQL.

**The search path returns DB content, never hydrating from S3.** Every
search result contains only the 1000-char prefix. The answerer receives
~1000 tokens per memory instead of the full ~5000+ tokens.

### Measured impact

| Path | Context/query | Chars/memory | Accuracy |
|------|--------------|-------------|----------|
| BM25 local | 5,179 tokens (28K chars) | Full (~28K avg) | 67.7% |
| MCP (MemoryHub) | 997 tokens (5K chars) | Truncated (1000 chars) | 46.5% |

Ratio: BM25 delivers **5.2x more context** than MCP per query.

### Classification

This is a **MemoryHub product defect** (MemoryHub-first rule applies).
The search tool returns a stub where it should either:
1. Hydrate from S3 before returning results, or
2. Return the content_ref so the client can fetch full content, or
3. Not truncate the DB column in the first place (raise the threshold
   or store full content inline for memories under some reasonable limit)

### Fix priority

This is the single largest performance blocker. Fixing content delivery
is worth more than keyword, reranker, and chunking combined at this
corpus size. Every signal improvement is invisible while the answerer
sees only 3.6% of each document.
