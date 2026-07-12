# Memory Extraction Pipeline: Dreaming, Reconciliation, and Provenance-Driven Reflection

**Status:** Design (for #336)
**Date:** 2026-07-11
**Revised:** 2026-07-11 (review pass: corrected existing-chunking inventory, added reconciliation guardrails, run-provenance/rollback, Layer 3 churn-trigger fixes)
**Author:** @rdwj (designed with Claude Code Opus 4.6)
**Builds on:** [autonomous-curation-agents.md](autonomous-curation-agents.md) (Dreamer), [conversation-persistence.md](../docs/design/conversation-persistence.md) (#168), [knowledge-compilation.md](../docs/design/knowledge-compilation.md) (#171)
**Validated by:** AMB PersonaMem benchmark results (#332)

---

## 1. Problem Statement

MemoryHub stores conversation traces as raw memory nodes and retrieves them via hybrid search. This works for short, self-contained memories but fails on long conversation transcripts where facts are buried thousands of tokens deep. For oversized content, the parent node's embedding covers only the first `s3_prefix_chars` (1000 chars, ~250 tokens; see `config.py`). Semantic chunk children *are* created at ingestion (`_create_chunk_children` in `services/memory.py`) and independently embedded — so the first open question for Layer 1 is why the 80.0% baseline looks like un-chunked retrieval. Candidate explanations: the AMB benchmark ingestion path bypasses `create_memory`'s chunking, chunking landed after the baseline artifacts were stored, or chunk children aren't surfacing in search results. This must be answered before any new chunking work is scoped.

AMB PersonaMem benchmark results confirm the gap:

| System | Approach | PersonaMem 32k Accuracy |
|--------|----------|------------------------|
| Hindsight | LLM fact extraction into semantic graph | 86.6% |
| hybrid-search | 512-token chunking, dense+sparse embeddings | 84.4% |
| Cognee | Chunking + graph entity extraction | 81.8% |
| **MemoryHub v0.2** | **Raw storage, 500-char embedding** | **80.0%** |
| BM25 baseline | Keyword-only | 62.6% |

Top performers extract structured facts from conversations rather than storing raw text. MemoryHub's governance substrate (versioning, provenance, scope isolation) is designed to support this, but the extraction pipeline isn't wired up for production use.

### What exists today

Significant extraction infrastructure is already implemented:

| Component | File | Status |
|-----------|------|--------|
| Windowed dreaming extraction | `services/dreaming.py` | Functional (442 lines) |
| Extraction cursor + provenance | `models/conversation.py` | Functional |
| Entity extraction cascade (spaCy/GLiNER/LLM) | `services/extraction.py` | Functional (792 lines) |
| Background extraction runner | `services/extraction_runner.py` | Functional (173 lines) |
| Extraction prompt | `prompts/conversation_extraction.yaml` | Functional |
| Curation pipeline (dedup gating) | `services/curation/pipeline.py` | Functional |
| Semantic chunking at ingestion | `storage/chunker.py` + `_create_chunk_children` in `services/memory.py` | Functional (chunk children via `parent_id` + `branch_type="chunk"`, independently embedded) |

The missing pieces are:

1. **Reconciliation**: Extraction creates new memories but doesn't search for existing ones to update. The curation pipeline gates near-duplicates (cosine > 0.90) but returns a recommendation rather than auto-resolving.
2. **Cross-encoder reranking on long documents**: The reranker (ms-marco-MiniLM-L12-v2, CPU, 512-token max) can't score PersonaMem's long transcripts. Falls back to cosine-only.
3. **Version churn detection**: No mechanism to notice "this memory has been updated 5 times in 2 weeks" and trigger higher-order reflection.

## 2. Three Layers

### Layer 1: Retrieval infrastructure (reranker + chunking)

Pure infrastructure improvement. No LLM extraction. Establishes a better baseline before extraction work.

**Reranker upgrade.** The current reranker is ms-marco-MiniLM-L12-v2 running on the TEI CPU image with 2 CPU / 4GB. Problems:
- 512-token max sequence length; PersonaMem transcripts trigger 413s on every query
- CPU inference is slow (~50ms per 512-token pair, quadratic scaling)
- The model itself is mid-tier (NDCG@10 ~0.39 on MSMARCO)

Replace with [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) on L40S GPU:
- 8192-token max sequence length (handles PersonaMem transcripts)
- GPU inference: 10-50x throughput improvement
- Better model quality (NDCG@10 ~0.44)
- Multilingual (relevant for future i18n)

Deployment: TEI GPU image on a shared L40S node (same node pool as the embedding model). The reranker is called once per search (pool of 24 candidates), so GPU utilization will be bursty. Consider sharing the GPU with the embedding service via time-slicing — but note the workload shapes conflict (bursty reranker vs steady embedding traffic), so measure p99 latency for both services under concurrent load before committing to the shared-GPU topology.

**Document chunking — verify, don't rebuild.** Ingestion-time chunking already exists: `create_memory` calls `_create_chunk_children`, which runs `semantic_chunk()` (paragraph/sentence-boundary splitting, `storage/chunker.py`) and creates independently embedded child nodes via `parent_id` + `branch_type="chunk"`. An earlier draft of this doc proposed a new `is_chunk` boolean and `CHUNK_OF` relationship; that would be a second, conflicting mechanism for the same thing and is withdrawn. The existing `branch_type="chunk"` convention is the mechanism of record.

The Layer 1 chunking work is therefore an investigation plus a gap-fix, not a build:

1. **Determine why the 80.0% baseline underperformed despite existing chunking.** Check whether the AMB provider's ingestion path reaches `_create_chunk_children`, whether the benchmark corpus predates the chunking code, and whether chunk children actually appear in search candidate pools.
2. **Fix whichever gap is found** (wire benchmark path through chunking, re-ingest corpus, or fix search surfacing).
3. **Evaluate chunking parameters against PersonaMem transcripts** (target tokens, overlap — `semantic_chunk` currently has no overlap; hybrid-search's 84.4% used 512-token windows with overlap, so overlap may be worth adding to the existing chunker).
4. **Chunk display strategy** (unchanged from original design): by default return chunks but display parent context — see open question 1.

**Validation:** Re-run PersonaMem benchmark after each change. The original 3-5 point reranker / 2-3 point chunking estimates were made before discovering chunking already exists; re-ground both estimates after the investigation in step 1. If chunking was already active in the baseline, the expected gain shifts almost entirely to the reranker and chunker-parameter tuning.

### Layer 2: Single-trace extraction pipeline (2-step)

This is the core capability. The existing `services/dreaming.py` does Step 1. Step 2 (reconciliation) is new.

#### Step 1: Windowed LLM extraction (mostly exists)

The dreaming service already implements:
- Sliding window over thread messages (per_turn / per_session / per_message modes)
- LLM call with structured output (facts, preferences, events, entities)
- Provenance tracking via `conversation_extractions` table
- Cursor-based state to prevent re-extraction
- Retry logic with failure recording

**What needs to change for dreaming:**

The extraction prompt (`prompts/conversation_extraction.yaml`) currently instructs "merge related facts into a single extraction rather than creating near-duplicates." This works within a single window but can't deduplicate across windows or across traces. The prompt should focus purely on what's worth remembering, leaving dedup to Step 2.

For long traces (approaching 128K tokens), the windowing is essential. An 8K-16K window with 1K overlap covers a 128K trace in 8-16 passes. Each pass is cheap (small model, small context). The overlap ensures facts that span window boundaries aren't missed.

**Model choice:** Gemini Flash or Haiku-class. Each window is 8-16K tokens. The extraction task (identify facts worth remembering) is well-suited to smaller models. The prompt is specific enough that model quality matters less than coverage.

#### Step 2: Reconciliation (new)

After extraction produces candidate memories, reconcile each against the existing memory graph. This is a two-phase process:

**Phase A: Similarity search.** For each candidate memory, embed it and search existing memories (same owner, same scope) with cosine similarity. The curation pipeline already does this at write time with thresholds:
- >= 0.98: exact duplicate, reject
- >= 0.90: near duplicate, gate (return recommendation)
- >= 0.80: flag for review

For dreaming, the near-duplicate gate should auto-resolve:
- >= 0.98: skip (exact duplicate, already stored)
- >= 0.90: **update** the existing memory — but only after passing the guardrails below. Call `update()` with new content, preserving version history. Link to source thread turn via provenance.
- 0.80 - 0.90: LLM tiebreaker. Ask a small model: "Are these the same fact? Memory A: '...' Candidate B: '...'" If yes, update. If no, create.
- < 0.80: create new memory

**Guardrails on auto-update (>= 0.90).** The riskiest zone is the one that would run with no LLM check: a wrong auto-update replaces the *current* value of a correct memory ("favorite cheese is mozzarella" vs "favorite pizza topping is mozzarella" can plausibly clear 0.90). Version history softens this but doesn't fix it — retrieval still returns the wrong current value. Two aggravating factors: (a) extraction-produced candidates are all LLM-phrased, which inflates cosine similarity relative to thresholds tuned on human-written memories; (b) the 0.90 threshold was inherited from the interactive curation gate, where a human confirms — here nobody confirms. Therefore:

1. **Run the LLM tiebreaker on the >= 0.90 band too**, at least until thresholds are validated against dreaming-produced candidates. Per the cost model, tiebreaker calls are cheap; a destroyed current value is not.
2. **Require `content_type` and domain match** before auto-update. A behavioral preference should never auto-update a factual memory, regardless of cosine score.
3. **Log every reconciliation decision** (candidate, nearest match, score, action taken, tiebreaker verdict if any) so thresholds can be tuned from data rather than intuition. This log is also the input to the rollback mechanism below.

**Phase B: Provenance linking.** Every created or updated memory gets a `ConversationExtraction` record linking it to the source thread and message range. This already exists in the schema. The new part is linking updates (not just creates) to their source.

**Phase C: Run provenance and rollback (kill-switch).** Dreaming writes memories autonomously with `force=True`, bypassing the curation gates. A bad prompt or model deploy therefore pollutes collections at scale with no human in the loop. Mitigations, all required before dreaming runs against production data:

- **Extraction run ID on every write and update.** Tag each dreaming batch with a run identifier (model, prompt version, timestamp) recorded on the `ConversationExtraction` records it produces. An entire run must be rollback-able as a unit: delete run-created memories, revert run-updated memories to their prior version.
- **Dry-run mode.** Produce the full set of create/update decisions (with reconciliation scores) without committing them, for inspection before enabling a new prompt or model.
- **Circuit breaker.** If a run's create:update ratio or rejection rate deviates wildly from historical norms, halt and flag rather than continue.

This is the same lesson as the 2026-05-19 deploy incident applied to memory writes, and it directly implements the "recovery" metric in the platform benchmark's adversarial-resilience dimension (see `platform-memory-benchmark.md`, Dimension 3).

**Measuring extraction quality directly.** PersonaMem only shows extraction's effect indirectly through end-to-end retrieval; if Step 1 over-extracts noise, the signal is muddy. AMA-Bench (see the benchmark doc's landscape table) separates memory *processing* quality from retrieval — use its processing axis, or a small hand-labeled trace set, to get direct precision/recall on Step 1 before Step 2 compounds its errors.

### Benchmark harness requirements (added 2026-07-13)

PersonaMem prescribes only the dataset, question types, and MCQ scoring; the
harness protocol is AMB's, and the answer LLM is a config parameter. Our own
data shows the answer model moves results ~3x more than retrieval quality
(81.2% Pro vs 70.8% Flash Lite on identical retrieval, vs +3.1 for
MemoryHub-over-BM25 same-model). Two sets of requirements follow.

**Ingestion must be a pluggable mode in the AMB provider** — same adapter,
two configs:

1. *Library mode* (current): raw/chunked `write()` per document. This is the
   Layer 1 instrument (#341/#343/#344) and has a structural ceiling on
   PersonaMem: chunking preserves stale preferences alongside current ones,
   so stale MCQ distractors stay retrievable.
2. *Dreaming mode* (for #349): sessions persist as threads and the extraction
   pipeline produces the searchable memories. Validity requirements:
   - **Chronological ingestion** — reconciliation is order-dependent; no
     batch-parallel writes.
   - **Timestamps preserved** into thread metadata (temporal questions,
     churn windows).
   - **Extraction runs between sessions**, mimicking the async dream cycle,
     not one pass at the end.
   - **Clean attribution** — the search pool contains extracted memories
     only, not the raw threads, or the run measures an unattributable blend.

**Comparability pinning** — every leaderboard-comparable run records in its
results metadata: answer model (`OMB_ANSWER_MODEL`, standard: Gemini 3.1 Pro
Preview), harness mode (`rag`), retrieval k / context budget, dataset variant,
and pipeline commit SHA. Runs off-standard (e.g., Flash matrix rows in the
ablation) are flagged not-leaderboard-comparable. Cross-paper numbers are
never cited as direct comparisons; only same-harness, same-model runs are.
The vendored adapters (`cognee.py`, `hindsight.py`, `mem0.py`) make
self-run competitor comparisons possible — optional Phase 8 stretch, with
ingestion cost reported alongside accuracy.

**The cheese test as acceptance criteria:**

1. Thread 1 contains: "My favorite cheese is mozzarella"
   - Extraction: candidate memory "User's favorite cheese is mozzarella" (content_type: behavioral)
   - Reconciliation: no match -> create memory node, weight 0.8
   
2. Thread 2 contains: "Actually, I had some parmesan today and now that's my favorite"
   - Extraction: candidate "User's favorite cheese is now parmesan"
   - Reconciliation: cosine similarity with existing "mozzarella" memory > 0.90 -> update existing memory
   - Version history: v1 "mozzarella" -> v2 "parmesan"
   - Both versions linked to their source threads

3. Verify: search for "favorite cheese" returns the v2 (parmesan) memory, not both versions

**Integration with existing curation pipeline:** The reconciliation step replaces the interactive gate. Today, the curation pipeline returns `gated=True` with `recommendation="update_existing"` and expects a human or agent to confirm. For dreaming (async, no human in the loop), the reconciliation auto-resolves based on the thresholds above. The `force=True` flag on `create_memory` already bypasses gates; reconciliation uses this after making the create-vs-update decision.

### Layer 3: Provenance-driven pattern detection

The differentiator. Cross-trace insights from metadata, not multi-trace context windows.

#### The insight

When the cheese memory gets updated from mozzarella to parmesan to gruyere to brie, the version chain itself is a signal. No other system captures this because no other system has governed versioning. Hindsight and Mem0 would create four separate memories (or silently overwrite); they can't see the pattern without loading all four source traces into a context window.

MemoryHub's version history makes the pattern visible from metadata alone:
- Memory node X, content_type "behavioral", domain "food preferences"
- Version 1 (2026-07-01): "favorite cheese is mozzarella"
- Version 2 (2026-07-05): "favorite cheese is parmesan"
- Version 3 (2026-07-08): "favorite cheese is gruyere"
- Version 4 (2026-07-11): "favorite cheese is brie"

The reflection prompt only needs this compact version list, not the raw conversation traces.

#### Schema change

Add to `memory_nodes`:

```sql
ALTER TABLE memory_nodes
  ADD COLUMN last_reflection_version integer DEFAULT 0;
```

This tracks the version number at which the last Layer 3 reflection was performed. When `current_version - last_reflection_version >= N` (configurable, default 3), the node is eligible for reflection.

**Churn must be qualified, not just counted.** Two corrections to the raw version-count trigger:

1. **Time window.** Four updates in two weeks is a pattern; four updates in two years is not. The eligibility query needs a timespan term (e.g., only count versions created within a rolling window, default 30 days) or the reflection prompt at minimum receives timestamps so the LLM can discount slow drift.
2. **Semantic delta.** Reconciliation auto-updates in the 0.90-0.98 band can be mere rephrasings of the same fact — version count inflates without meaning change, producing noise insights ("user restates preference often"). Require a minimum embedding distance between consecutive versions (configurable epsilon) for a version bump to count toward churn. The reconciliation decision log (Layer 2, Phase C) already captures the similarity score at update time, so this is a filter, not new computation.

#### Cron-based detection

A background process (the Statistician agent from `autonomous-curation-agents.md`, or a simpler cron) periodically queries:

```sql
SELECT id, current_version, last_reflection_version, content, stub
FROM memory_nodes
WHERE current_version - last_reflection_version >= :threshold
  AND status = 'active'
ORDER BY current_version - last_reflection_version DESC
LIMIT 100;
```

For each eligible node, load its version history (compact: version number, timestamp, stub only) and send to an LLM:

```
This memory has been updated {N} times in {timespan}:

Version history:
- v1 (2026-07-01): "favorite cheese is mozzarella"
- v2 (2026-07-05): "favorite cheese is parmesan"  
- v3 (2026-07-08): "favorite cheese is gruyere"
- v4 (2026-07-11): "favorite cheese is brie"

What pattern or insight does this update history reveal? 
If no meaningful pattern exists, respond with "none".
```

If the LLM produces an insight:
- Create a new memory node with content_type `behavioral` and a new branch_type `insight`
- Link it to the source memory via `parent_id` with `branch_type="insight"`
- Set `last_reflection_version` to the version *read at reflection time*, not `current_version` at completion — a concurrent update landing mid-reflection would otherwise be silently skipped

If no insight: stamp `last_reflection_version` (same read-version semantics) to prevent re-checking until the next N updates.

#### Relationship to contradiction reporting

The existing `report_contradiction` mechanism handles a related but different signal. Contradictions are reported by agents who observe behavior that conflicts with a stored memory. Version churn detection is structural -- it fires based on update frequency alone, regardless of whether any agent noticed a conflict. The two complement each other:

- High churn + no contradictions = preference exploration (the cheese pattern)
- High churn + contradictions = unstable fact that needs investigation
- Low churn + contradiction = one-time correction (the normal case)

## 3. Sequencing and Dependencies

```
#332 (AMB baseline)
  └── Layer 1 (reranker + chunking)
        └── Re-run PersonaMem
              └── Layer 2 Step 1 (extraction - mostly exists)
                    └── Layer 2 Step 2 (reconciliation - new)
                          └── Cheese test validation
                                └── Layer 3 (provenance reflection)
```

Layer 1 is independent and can start as soon as #332 lands. Layers 2 and 3 are sequential.

## 4. Cost Model

**Layer 1:** Infrastructure only. GPU cost for bge-reranker-v2-m3 on shared L40S. No per-query LLM cost.

**Layer 2:** Per-trace extraction cost depends on trace length and window size. For a 32K-token trace with 8K windows: 4 LLM calls at ~8K input tokens each. At Gemini Flash pricing (~$0.075/M input): ~$0.0024 per trace. At Haiku pricing (~$0.25/M input): ~$0.008 per trace. Reconciliation adds one embedding call per candidate (cheap, but not free at scale) plus pgvector cosine search. With the >= 0.90 guardrail tiebreaker enabled, expect an LLM tiebreaker call on most update decisions — each is tiny (two short memory texts + verdict, well under 500 tokens), so this adds pennies per thousand candidates and is worth it until thresholds are validated.

**Layer 3:** Minimal. Reflection prompts are ~500 tokens (version list + instruction). Even at Opus pricing, < $0.01 per reflection. The cron runs infrequently (daily or on-demand).

## 5. Open Questions

0. **Why did the 80.0% baseline underperform despite existing ingestion chunking?** (New; blocks Layer 1 scoping.) See Layer 1 — benchmark path bypass, corpus predating the chunker, or search not surfacing chunk children. Answer empirically before building anything.

1. **Chunk display strategy.** When search returns a chunk, what does the agent see? Options: (a) the chunk text only, (b) the chunk plus surrounding context from the parent, (c) the parent's full content with the chunk highlighted. Option (b) is probably right but needs UX testing.

2. **Reconciliation threshold tuning.** The 0.90 auto-update threshold is inherited from the curation pipeline. It may need adjustment for extraction-produced candidates — and note the asymmetry: LLM-phrased candidates score systematically higher cosine against LLM-phrased memories than the human-written memories the thresholds were tuned on. Tune from the reconciliation decision log, not intuition.

3. **Extraction model selection.** Gemini Flash, Haiku, or a fine-tuned model? The extraction prompt is specific enough that a smaller model may suffice, but quality matters for the "what's worth remembering" judgment. Empirical comparison needed.

4. **Cursor backtracking.** The current extraction cursor only advances forward. If we improve the extraction prompt or model, there's no way to re-extract old threads with the new approach. Should we support cursor reset?

5. **Layer 3 threshold tuning.** How many version updates before triggering reflection? Too low (2) and we generate noise. Too high (10) and we miss patterns. Starting at 3 and adjusting based on the cheese test. Both the time window and the semantic-delta epsilon (see schema section) need tuning alongside N.

6. **Insight memory lifecycle.** Should insight memories be immutable (snapshot of the pattern at the time of reflection) or updated when the source memory continues to change? Immutable is simpler and preserves the historical record.

7. **Extraction quality ground truth.** What labeled set do we measure Step 1 precision/recall against — AMA-Bench's processing axis, a hand-labeled slice of PersonaMem traces, or both? Needed before Layer 2 tuning; end-to-end PersonaMem accuracy alone can't distinguish extraction errors from retrieval errors.
