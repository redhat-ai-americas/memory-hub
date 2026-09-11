# Session Summary -- 2026-09-11 -- omp-interop -- Debundle PR #570 and create scratchpad repo

**Plan:** NEXT_SESSION-omp-interop.md   **Commits:** 23 across 6 branches (no commits on main)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: implement trust provenance (#559) and dreaming gates (#562). Shipped: debundled the already-implemented work from PR #570 into 5 focused PRs, created the scratchpad repo, and forked AMB. Scope changed because Sanjeev's review feedback (design doc request + PR size) was the higher-priority problem.

## Shipped
- `83372dc..f3e5b1e` (feat/trust-provenance) -- PR #574: upstream_trust_level + taint metadata, design doc, 17 files
- `6c12664..8b0b6a7` (feat/dreaming-gates) -- PR #575: threshold gates before LLM consolidation, design doc, 6 files
- `f11257d..c50f5e3` (feat/context-assembly-pipeline) -- PR #576: 9-stage injection pipeline + generating_model, design doc, 22 files
- `66bde72` (feat/memory-object-format-design) -- PR #577: MOF portability design ideation, 1 file
- `20bd1b7` (docs/contributing-guide-update) -- PR #578: labeling, design doc rules, workflow reference, 1 file
- `b719db8` (chore/move-research-to-scratchpad) -- PR #579: move research/planning/demos to scratchpad, 339 files removed
- Created `redhat-ai-americas/memory-hub-scratchpad` (private) with README + promotion path
- Forked `vectorize-io/agent-memory-benchmark` to `redhat-ai-americas/agent-memory-benchmark`
- Commented on PR #570 announcing the split

## Verification & confidence
- Cherry-picks resolved cleanly (conflicts were generating_model/upstream_trust_level cross-contamination, resolved correctly by keeping only the relevant feature per PR)
- Design docs verified against actual implementation (corrected taint object structure in trust-provenance doc)
- Confirmed zero file overlap between PRs #574-578 and PR #579 (no merge conflict risk)
- Confidence: **high** for the split itself (mechanical cherry-pick + doc writing); **medium** for whether the cherry-picked code compiles/tests clean on each branch in isolation (no CI results yet since PRs just opened)

## Judgment calls & deviations
- Deviated from the NEXT_SESSION plan (which called for implementing #559/#562) to address the PR review feedback first. The code was already written; the problem was presentation, not implementation.
- Stripped all OMP references from design docs per Wes's direction. The improvements are framed as internal hardening.
- Combined #559 (trust level) and #563 (taint metadata) in one PR since taint is the read-time surface of the trust field.
- Included generating_model (#566) with context assembly (#561) since they share the "injection path provenance" theme and the generating_model field feeds the pipeline's provenance stamp stage.

## Backlog delta
Filed: none. Closed: none (PRs are open, awaiting review). Memory: `feedback-tight-prs` (PR discipline rule).
Deferred: closing PR #570 (wait for replacement PRs to land). Deferred: cleaning up untracked orphans (`demos/memory-on-off-demo-scenario.md`, `planning/trajectory-ingestion-format.md`) before #579 merges.

## Drift & forward-collisions
- Backward: none
- Forward: none

## For the reviewer
- Sanity-check: the cherry-pick conflict resolution in PR #576 (context assembly) was the most complex, touching 4 files with interleaved upstream_trust_level/generating_model changes. Worth verifying the `generating_model` lines landed in the right construction sites.
- Thin verification: no CI results yet on any of the 6 PRs. The cherry-picks compile-tested locally via conflict resolution but no pytest run on each branch in isolation.
- Wants guidance: none

## Risks / watch-fors
- PR #570 should be closed after replacements land, not before. It's the audit trail for the split decision.
- The untracked files `demos/memory-on-off-demo-scenario.md` and `planning/trajectory-ingestion-format.md` need to be moved to the scratchpad or deleted before PR #579 merges, since their parent directories are being removed.
- The scratchpad repo needs contributor access granted to the same people who have access to memory-hub.
