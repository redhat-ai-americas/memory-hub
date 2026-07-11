# Memory Extraction Pipeline: Dreaming, Reconciliation, and Provenance-Driven Reflection

**Status:** Design (for #336)
**Date:** 2026-07-11
**Author:** @rdwj (designed with Claude Code Opus 4.6)
**Builds on:** [autonomous-curation-agents.md](autonomous-curation-agents.md) (Trace Reviewer), [conversation-persistence.md](../docs/design/conversation-persistence.md) (#168), [knowledge-compilation.md](../docs/design/knowledge-compilation.md) (#171)
**Validated by:** AMB PersonaMem benchmark results (#332)

---

## 1. Problem Statement

MemoryHub stores conversation traces as raw memory nodes and retrieves them via hybrid search. This works for short, self-contained memories but fails on long conversation transcripts where facts are buried thousands of tokens deep. The embedding covers only the first 500 characters; everything else is invisible to vector search.

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
| Windowed conversation extraction | `services/conversation_extraction.py` | Functional (442 lines) |
| Extraction cursor + provenance | `models/conversation.py` | Functional |
| Entity extraction cascade (spaCy/GLiNER/LLM) | `services/extraction.py` | Functional (792 lines) |
| Background extraction runner | `services/extraction_runner.py` | Functional (173 lines) |
| Extraction prompt | `prompts/conversation_extraction.yaml` | Functional |
| Curation pipeline (dedup gating) | `services/memory.py` | Functional |

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

Deployment: TEI GPU image on a shared L40S node (same node pool as the embedding model). The reranker is called once per search (pool of 24 candidates), so GPU utilization will be bursty. Consider sharing the GPU with the embedding service via time-slicing.

**Document chunking.** Add a chunking step at ingestion time. When a memory node's content exceeds a threshold (e.g., 1024 tokens), split into overlapping windows (512 tokens, 64-token overlap). Each chunk becomes a child memory node linked to the parent via a `chunk_of` relationship. The parent retains full content for audit; chunks are what gets embedded and searched.

This is the same approach hybrid-search (84.4%) uses. It solves the 500-char embedding truncation problem without needing LLM extraction.

**Schema changes:**
- `memory_nodes.is_chunk` boolean (default false) to distinguish chunks from source nodes
- `memory_relationships` edge type `CHUNK_OF` linking chunk -> parent
- Search filters: by default, return chunks but display the parent's content (or the chunk with surrounding context)

**Validation:** Re-run PersonaMem benchmark after each change. Expected improvement: 3-5 points from reranker alone, 2-3 more from chunking, putting us at 85-88%.

### Layer 2: Single-trace extraction pipeline (2-step)

This is the core capability. The existing `conversation_extraction.py` does Step 1. Step 2 (reconciliation) is new.

#### Step 1: Windowed LLM extraction (mostly exists)

The conversation extraction service already implements:
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
- >= 0.90: **update** the existing memory. Call `update()` with new content, preserving version history. Link to source thread turn via provenance.
- 0.80 - 0.90: LLM tiebreaker (optional). Ask a small model: "Are these the same fact? Memory A: '...' Candidate B: '...'" If yes, update. If no, create.
- < 0.80: create new memory

**Phase B: Provenance linking.** Every created or updated memory gets a `ConversationExtraction` record linking it to the source thread and message range. This already exists in the schema. The new part is linking updates (not just creates) to their source.

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
- Set `last_reflection_version = current_version` on the source memory

If no insight: stamp `last_reflection_version` anyway to prevent re-checking until the next N updates.

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

**Layer 2:** Per-trace extraction cost depends on trace length and window size. For a 32K-token trace with 8K windows: 4 LLM calls at ~8K input tokens each. At Gemini Flash pricing (~$0.075/M input): ~$0.0024 per trace. At Haiku pricing (~$0.25/M input): ~$0.008 per trace. Reconciliation similarity search is free (pgvector cosine); LLM tiebreaker calls are rare.

**Layer 3:** Minimal. Reflection prompts are ~500 tokens (version list + instruction). Even at Opus pricing, < $0.01 per reflection. The cron runs infrequently (daily or on-demand).

## 5. Open Questions

1. **Chunk display strategy.** When search returns a chunk, what does the agent see? Options: (a) the chunk text only, (b) the chunk plus surrounding context from the parent, (c) the parent's full content with the chunk highlighted. Option (b) is probably right but needs UX testing.

2. **Reconciliation threshold tuning.** The 0.90 auto-update threshold is inherited from the curation pipeline. It may need adjustment for extraction-produced candidates, which tend to be more concise than raw user-written memories.

3. **Extraction model selection.** Gemini Flash, Haiku, or a fine-tuned model? The extraction prompt is specific enough that a smaller model may suffice, but quality matters for the "what's worth remembering" judgment. Empirical comparison needed.

4. **Cursor backtracking.** The current extraction cursor only advances forward. If we improve the extraction prompt or model, there's no way to re-extract old threads with the new approach. Should we support cursor reset?

5. **Layer 3 threshold tuning.** How many version updates before triggering reflection? Too low (2) and we generate noise. Too high (10) and we miss patterns. Starting at 3 and adjusting based on the cheese test.

6. **Insight memory lifecycle.** Should insight memories be immutable (snapshot of the pattern at the time of reflection) or updated when the source memory continues to change? Immutable is simpler and preserves the historical record.
