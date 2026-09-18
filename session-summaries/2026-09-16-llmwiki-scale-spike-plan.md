# Session Summary — 2026-09-16 · LLMWiki Scale Spike Plan

**Plan:** Ad-hoc request from architecture team   **Commits:** ae56a1e (`planning/llmwiki-scale-spike`)
**Deployed:** none   **Model:** Claude Code (Opus 4.6)

## Plan vs. actual
Planned: Write a spike plan proving out LLMWiki/OKF (markdown with YAML frontmatter) vs PostgreSQL at 10M memories / 5k users. Shipped: planning doc + PR. No slippage -- scope was one document.

## Shipped
- `ae56a1e` — Spike plan at `planning/llmwiki-scale-spike.md`: three-tier comparison (pure OKF files, OKF + SQLite/FAISS, PostgreSQL), four workloads (search latency, concurrent writes, storage footprint, cold start), cluster resource estimates (~165Gi PVC, 6 cores, 12Gi), decision criteria
- PR #584 opened against main

## Verification & confidence
- Document reviewed for tone (approvers are the llmwiki/markdown advocates; language adjusted to be collaborative rather than adversarial)
- CI green (secret scan + tests)
- Confidence: high — this is a planning artifact, not code

## Judgment calls & deviations
- Chose three tiers rather than two: added "OKF + search infrastructure" (T2) as the strongest possible file-based argument, so the comparison is fair rather than a straw man against pure grep
- Used synthetic 384-dim vectors rather than real embeddings to isolate index performance from embedding throughput -- real embeddings for 10M memories would take hours and obscure what we're measuring
- Tone pass: replaced "repeatedly asked" with "raised a good question," removed "stop asking the question" from decision criteria, reframed predictions as testable hypotheses

## Backlog delta
Filed: none. Closed: none. PR #584 pending review.

## Drift & forward-collisions
- Backward — none
- Forward — The spike may produce data relevant to #560 (MOF export format) and the git-transport-mode plan in `planning/git-transport-mode.md`. If file-based storage shows strong performance at moderate scale, it strengthens the case for OKF as an interchange format even if not as the primary store.

## For the reviewer
- Sanity-check: Are the resource estimates (80Gi for 10M small files on ext4) credible? The 4KB block-minimum math is well-established but OpenShift PVCs default to XFS, which has different inode allocation -- may affect the number.
- Thin verification: none -- planning doc only
- Wants guidance: none

## Risks / watch-fors
- The spike needs ~165Gi of temporary PVC on the mcp-rhoai cluster. If quota is tight, may need to negotiate with other namespace owners or run on a different cluster.
- 10M-file creation on a PVC could hit inode limits depending on filesystem. The plan calls out XFS (OpenShift default) as a mitigation since it allocates inodes dynamically.
