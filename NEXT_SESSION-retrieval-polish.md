# Next Session -- Retrieval Polish

## Next: <to be planned via /plan-next-session>

(No next-session focus selected yet. Run `/plan-next-session retrieval-polish` to
pick the first slice from the phases below.)

## Remaining epic phases

Quality-of-life improvements to the search pipeline. Every issue is
independent -- no shared infrastructure, no sequencing constraints. The
tiers reflect priority, not dependency. The search pipeline works; this
epic makes it more observable, more flexible, and more complete.

### Phase 1: Quick wins (#404, #306)

Fix the effective-k observability bug and add time-decay recency bias.
Both are small, self-contained changes to the search service.

**Work:**
1. Surface the k-chain in search response metadata so callers can see
   when their requested k was reduced and by which stage (#404). Four
   capping points (harness default, provider env, SDK config, server cap)
   currently operate silently.
2. Add recency bias to search scoring -- a time-decay factor so recent
   memories rank higher, all else being equal (#306). Complementary to
   the existing `temporal_status` binary filtering. Design notes in
   `research/agent-memory-ergonomics/`.

**Definition of done:** Search response includes `effective_k` and
per-stage cap decisions in metadata. Recency bias is active with a
configurable decay rate, and a test shows recent memories ranking above
older ones with equal similarity scores.

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of all other phases.

### Phase 2: Search assembly (#397, #389)

Two improvements to how results are assembled and delivered: hard-stop
mode for small-context models, and S3 hydration for the large-content
tail.

**Work:**
1. Hard-stop mode (#397): a search mode that returns top-k with full
   content but stops (rather than degrading to stubs) when total tokens
   hit a caller-specified limit. Serves 64K-window models that need
   guaranteed full content.
2. S3 hydration (#389): complete the read-half of the S3 spill design.
   For content >100KB, rank on the DB prefix, then hydrate the final
   top-k from S3 via parallel GETs before returning in `full` mode.
   Valkey cache is a candidate for hot content. Design reference:
   `benchmarks/results/h6-content-delivery-audit.md`.

**Definition of done:** Hard-stop mode returns full-content results up to
a token budget and cleanly stops (no stubs). S3 hydration returns full
content for oversized memories in `full` mode with parallel fetches.
Both have tests covering edge cases (zero results, budget exhausted on
first result, S3 unavailable fallback).

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of all other phases. #397 and #389
can also be done independently of each other within this phase.

### Phase 3: Reimplementation + benchmark (#453, #454, #370)

Bring back two features that were stripped during the action-dispatch
compaction, then run the ablation matrix that depends on them.

**Work:**
1. Reimplement `disabled_signals` for per-search RRF signal toggling
   (#453). Enables A/B testing and ablation without server config
   changes. Prior implementation existed on a deleted branch.
2. Reimplement entity-aware search and entity service (#454). Entity
   scope for memory nodes, MENTIONS relationship type, entity_names
   filter on search, find-or-create entity service. Prior implementation
   existed on two deleted branches.
3. Run Ablation Matrix B (#370) -- focus, domain, and graph signal
   configs against a dreaming-mode corpus with preflight enforcing that
   tags and edges exist.

**Definition of done:** `disabled_signals` parameter accepted on search
and toggles RRF signals. Entity-aware search filters by entity_names.
Ablation Matrix B results documented in `benchmarks/RESULTS.md` with
per-signal contribution analysis.

**Dependencies:** Benefits from dreaming-followon #447 (retrieval-unit
routing) being complete, but not gated on it.

**Parallel-ok:** Yes -- independent of Phases 1-2. #453 and #454 can
also be done independently of each other.

---

## What this covers (and what it doesn't)

**In scope:**
- #306 Add time-decay recency bias to search scoring
- #370 Ablation Matrix B -- focus/domain/graph (post-dreaming)
- #389 S3 hydration for large-content tail
- #397 Hard-stop mode (truncate vs stubs)
- #404 Effective-k observability
- #453 Reimplement disabled_signals for RRF signal toggling
- #454 Reimplement entity-aware search and entity service

**Out of scope (other epics own):**
- #447 Retrieval-unit routing (`NEXT_SESSION-dreaming-followon.md`)
- #350-353 Curator scaffold and sweeps (`NEXT_SESSION-curation.md`)
- #272, #273 System benchmarks (backlog)

## What landed last session

(No sessions yet for this epic.)

## Watch out for

- **Deleted branches.** #453 and #454 had prior implementations on
  branches that were pruned. The code is gone; reimplement against the
  current architecture rather than trying to recover.
- **RRF signal ordering.** Changes to the search scoring pipeline
  (#306 recency, #453 disabled_signals) need to be tested against the
  PersonaMem baseline to confirm no regression.
- **S3 hydration latency.** Parallel S3 GETs add latency to the search
  hot path. Measure before/after and consider Valkey caching for hot
  content.

## If blocked

- All phases run locally against SQLite for development. Cluster is
  only needed for benchmark runs (#370) and S3 hydration testing (#389).
- If Gemini API is down: #370 ablation runs need an answer LLM. Develop
  code changes locally and defer the benchmark run.
