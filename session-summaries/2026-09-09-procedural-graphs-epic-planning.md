# Session Summary -- 2026-09-09 -- procedural-graphs -- Epic planning from arXiv paper

**Plan:** Ad-hoc (paper review + issue filing + epic creation)   **Commits:** 57e59ba (`epic/procedural-graphs-planning`)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: read arXiv 2609.09153, discuss applicability to MemoryHub. Shipped: read paper, filed 4 issues, created new epic with full arc and first session plan, reconciled 2 stale epics, opened PR #556. Scope expanded from "discuss" to "file + plan + reconcile" at user's direction.

## Shipped
- Read and analyzed arXiv 2609.09153 "Procedural Graphs: Self-Evolving Execution Structures for LLM Agents" -- identified 4 directly applicable ideas for MemoryHub
- Filed #552 (procedural graph memory type), #553 (localized 2-hop retrieval), #554 (dreaming extraction for procedural graphs), #555 (rejection memory) -- all in Backlog on project board
- Created `NEXT_SESSION-procedural-graphs.md` with 4-phase epic arc and detailed first session plan (design doc + schema extension)
- Reconciled retrieval-polish epic: #389 (S3 hydration) was already closed, updated Phase 2, added reconciliation note
- Reconciled curation epic: parent branch `feat/dreaming-ablation-results` merged 2 months ago (PR #449), fixed 6 stale branch references to target main, marked Phase 0 done
- Ran `/plan-epics` portfolio review across all 4 active epics + the new one
- PR #556 opened, Ray Carroll tagged for review

## Verification & confidence
- All changes are planning/documentation files -- no code to verify
- CI green (Tests + Secret Scanning) on the branch
- Gitleaks clean
- Confidence: high -- purely additive planning files, no risk of regression

## Judgment calls & deviations
- Named the epic `procedural-graphs` rather than `procedural-memory` -- the paper's contribution is the graph structure specifically, not just procedural knowledge in general
- Placed #552/#553 under `subsystem:memory-tree` (no `subsystem:retrieval` label exists) and #554/#555 under `subsystem:curator` (no `subsystem:dreaming` label exists)
- Did not create a tracking issue for the epic -- the 4 component issues + the NEXT_SESSION file are sufficient for now
- Decided Phase 1 (schema) should include a design doc as the primary deliverable, not just code -- the graph structure mapping needs to be right before implementation

## Backlog delta
Filed #552, #553, #554, #555. Opened PR #556. No issues closed. No issues re-scoped. No memories written.

## Drift & forward-collisions
- Backward: #454 (entity-aware search) and #273 (graph-traversal benchmark) are still valid but now have a related epic that will produce procedural-specific graph retrieval. Neither is stale -- they cover different concerns.
- Backward: #345 (Layer 3 reflection) still valid. #554 extends toward it but does not replace it -- reflection generates insight memories from churn; #554 generates procedural graphs from trajectories.
- Forward: none -- all 4 issues are new; no existing issue is partly satisfied.

## For the reviewer
- Sanity-check: the decision to add `procedural` as a new ContentType rather than a subtype of `behavioral`. The research doc maps behavioral to procedural memory, but the paper's graph-structured procedures are different enough from flat behavioral text to warrant separation. Worth a second opinion.
- Thin verification: the paper's results are strong (21/24 settings) but the benchmarks tested (HotpotQA, ALFWorld, etc.) are quite different from MemoryHub's use case (long-running agent memory across sessions). The transfer may not be direct.
- Wants guidance: none

## Risks / watch-fors
- The curation epic (#350 scaffold) has been stalled 50 days. Phase 3 of procedural-graphs (#554) benefits from that scaffold. If curation stays parked, #554 will need a standalone extraction approach.
- Three new relationship types (precedes, requires, alternative_to) could pollute existing graph-boosted search if not filtered. Phase 1 design doc needs to address this.
