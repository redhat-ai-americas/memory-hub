# Retrospective: Dreaming Arc (Extraction Pipeline + Benchmarking)

**Date:** 2026-07-13
**Effort:** Multi-session epic spanning July 10-13, 2026. Retrieval benchmarking, AMB harness integration, EvalHub deployment, RRF signal toggles, and ablation matrix infrastructure. Foundational benchmarking work (LongMemEval, hybrid search, cross-encoder tuning) dates to late June.
**Issues:** #332, #333, #336, #338, #341, #354, #357, #358, #359, #360, #363, #364, #365, #366, #367, #368, #369, #370, #371, #372
**PRs merged:** #294, #329, #335, #340, #356, #358, #361, #362, #363, #368
**Commits:** ~123 across the arc

## What We Set Out To Do

Close the quality gap between MemoryHub (81.2% on PersonaMem with raw storage) and competitors using LLM extraction (Hindsight 86.6%, Cognee 81.8%). The plan had 8 phases:

1. AMB baseline (PersonaMem + LongMemEval)
2. Naming sweep (align codebase on "dreaming" terminology)
3. Layer 1 (reranker upgrade + chunking fix)
4. Layer 2 (extraction pipeline with reconciliation)
5. RRF ablation study
6. Curator Agent (dedup, staleness, conflict detection)
7. Layer 3 (provenance-driven reflection)
8. Final validation (PersonaMem >= 85%)

Design reference: `planning/memory-extraction-pipeline.md`, `planning/system-benchmarks.md`, `planning/evalhub-integration.md`.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| EvalHub integration expanded from 1 session to 3+ (spike, deploy, hardening) | Scope expansion | TrustyAI operator on OpenShift had unforeseen operational friction: sidecar forwarding, PVC limitations, Gemini model deprecation, provider ID instability |
| Phases 3-8 not started | Scope deferral | Infrastructure work (EvalHub, cluster capacity, deploy scripts, signal toggles) consumed all capacity |
| 48.4% baseline discrepancy surfaced as P0 blocker | Good discovery | Ablation matrix ran but returned 7 identical results. Deployed search path is vector-only; keyword/BM25 not active. Correctly prioritized as must-fix before further runs |
| Cluster capacity freed via LlamaStack/LibreChat cleanup | Good pivot | ~2000m CPU freed without provisioning new nodes |
| Per-request tenant_id selection (#368) | Good pivot | Required for ablation matrix to target benchmark tenant correctly |
| Chunking regression identified (#341) | Good discovery | 51.6% with chunking vs 70.8% without. Investigation stayed read-only and produced clear root cause |

**Phases completed:** 1 (AMB baseline), 2 (naming sweep), 5 partial (toggle flags + EvalHub infra, but matrix results not yet meaningful).
**Phases remaining:** 3 (Layer 1), 4 (Layer 2), 5 remainder (matrix re-run), 6 (Curator), 7 (Layer 3), 8 (validation).

## What Went Well

- **AMB baseline is competitive.** 81.2% on PersonaMem with no extraction pipeline, within 0.6% of Cognee (which uses entity extraction). Proves the governance substrate is not a tax on retrieval quality.
- **LongMemEval numbers are benchmark-leading.** R@5=0.999, R@10=1.000, MRR=1.000 with 8x smaller embeddings (384-dim vs MemPalace's 3072-dim). Publishable result.
- **Investigation discipline held.** #341 (chunking investigation) stayed read-only and produced a clear finding without drifting into a fix session. Same discipline correctly applied to #369.
- **EvalHub is end-to-end functional.** Despite operational friction, the platform works: adapter builds, MLflow persists results, deploy script is idempotent. Reusable for all future benchmark runs.
- **Cross-encoder pool tuning was data-driven.** Pool-size sweep produced a clear 22% latency reduction (2.7s to 2.1s) with 94% top-5 result overlap. Configurable default, committed results.
- **Issue decomposition improved.** Tracker issues (#336, #333, #285) broken into session-sized sub-issues with explicit exit predicates. Better than earlier monolithic issues.
- **Hybrid search surfaces materially different results.** 94% of queries got new results (avg 2.8 per query) that vector-only missed.

## Gaps Identified

### The recurring pattern: unverified capability claims

Three instances of the same error class in one epic. From reviewer feedback:

> Capability claims -- about our own codebase, deployed infrastructure, or third-party software -- get verified against code, docs, or live state before they propagate into issues, plans, or reviews. A 10-minute doc read beats a feature request, and a grep beats a rebuild.

| Incident | What was assumed | What was true | Cost |
|----------|-----------------|---------------|------|
| Chunking discovery (#341) | "Chunking isn't active in the benchmark path" | `_create_chunk_children` in `services/memory.py` was functional; AMB provider bypassed it | Investigation session; #343 re-scoped |
| PVC claim (#365) | "PVC can persist EvalHub SQLite" (then, after the patch failed: "PVC not possible with the operator") | TrustyAI operator reconciles away *manual volume patches* but SUPPORTS PVC via `outputs.pvcManaged`/`pvcName` on the eval job CR (found by /issue-gate doc read, 2026-07-14) | Attempted fix, wrong conclusion propagated to plan/review/reconciliation, corrected next day. Refines the lesson: verifying by attempt against the wrong mechanism still produces a false claim -- verify against the documented interface |
| EvalHub sidecar (#364) | Sidecar should forward results (implied by docs) | `DefaultCallbacks.from_adapter()` required but undocumented; duplicate COMPLETED status was a second undocumented constraint | Debugging session for root cause |

### Other gaps

| Gap | Severity | Resolution |
|-----|----------|------------|
| 48.4% vs 70.8% baseline discrepancy unexplained | High | #369 filed, top of NEXT_SESSION |
| Keyword/BM25 not active in deployed MCP search path | High | #372 filed |
| No preflight manifest for benchmark runs | Medium | #371 filed |
| EvalHub SQLite persistence is a workaround | Medium | #365 re-scoped 2026-07-14 to a config fix (`outputs.pvcManaged`/`pvcName`); hard gate for Matrix A, no longer "accepted risk" |
| CI CLI tests failing (pre-existing memoryhub_core import) | Low | #374 filed |
| Full local test suite hangs | Low | #375 filed |

## Action Items

- [x] Write institutional lesson into CLAUDE.md (this retro)
- [ ] #369 -- Investigate 48.4% vs 70.8% discrepancy (next session)
- [ ] #371 -- Benchmark preflight manifest
- [ ] #372 -- Activate keyword/BM25 in deployed MCP search path
- [ ] #370 -- Ablation Matrix B (post-dreaming signals)
- [ ] #374 -- Fix CI CLI test failure (pre-existing memoryhub_core import)
- [ ] #375 -- Investigate local test suite hang

## Patterns

Scanning 44 prior retros for recurring themes relevant to this arc:

**Start:**
- **Verify capability claims before propagating them.** Three citations in one epic (see table above). A 10-minute doc read, a grep, or a port-forwarded SQL query beats a feature request or a rebuild. This is the primary lesson of the dreaming arc.
- **Require a preflight manifest for benchmark runs.** Corpus state, pipeline config, provider registration, and model availability should be checked before submitting 589-query runs. #371 tracks this.

**Stop:**
- **Assuming infrastructure work is a fixed-time investment.** EvalHub was scoped as "1 session" and consumed 3+. Operator-managed platforms on OpenShift have a base tax that planning consistently underestimates.

**Continue:**
- **Read-only investigation sessions.** #341 worked because it stayed disciplined. The same approach is correctly being applied to #369. This pattern prevents investigation sessions from drifting into fix sessions that lose the diagnostic thread.
- **Session-sized sub-issues with exit predicates.** The #336 decomposition (tracker with ~15 sub-issues) is the best issue structure this project has used. Each sub-issue is one session, each has a clear "done" definition.
- **Data-driven retrieval decisions.** Pool-size sweep, hybrid search benchmark, PersonaMem competitive comparison. Every retrieval change has committed result data behind it.
