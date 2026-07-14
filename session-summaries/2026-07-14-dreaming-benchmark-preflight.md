# Session Summary -- 2026-07-14 - dreaming - Benchmark system map + enforced preflight

**Plan:** NEXT_SESSION-dreaming.md / #371   **Commits:** 643fdfc..717d125 (feat/benchmark-preflight)
**Deployed:** none   **Model:** Opus 4.6 (1M)

## Plan vs. actual
Planned: system map doc + preflight module + adapter integration + expected_manifest on all configs. Shipped: all four, plus live verification against mcp-rhoai and a CLI import fix discovered during verification. Slipped: none.
Scope: stayed in scope. No MCP server or memoryhub_core changes.

## Shipped
- `643fdfc` docs: benchmark system map with stack diagram, signal activation matrix (6 signals), corpus provenance
- `866aaa7` bench: preflight module (check_signal_* probes, enforce_manifest recursive subset match, CLI entry point); 14 unit tests
- `b5b7abd` bench: adapter integration (preflight before every run, RuntimeError on mismatch, manifest in MLflow metadata)
- `0430510` bench: expected_manifest on all 9 matrix configs (vector+keyword active, reranker/focus/domain/graph inactive, 0 chunks)
- `717d125` bench: CLI import fix (bypass adapter __init__.py to avoid EvalHub SDK chain)
- Live verification: standalone preflight, config enforcement pass, deliberate mismatch fail with readable diff

## Verification & confidence
- 14 unit tests pass (enforce_manifest 9 cases, check_signal_focus, check_signal_reranker 3 cases, get_version_shas)
- Live preflight against mcp-rhoai: manifest matches expected deployment (195 parents, 0 chunks, vector+keyword active)
- Deliberate mismatch test: exit 1 with diff showing `signals.reranker.active: expected True, got False` and `corpus.chunk_nodes: expected 500, got 0`
- Confidence: **high** on preflight correctness (live-verified against real cluster), **high** on adapter integration (compile-checked, path-tested)

## Judgment calls & deviations
- Used `importlib.util.spec_from_file_location` for CLI wrapper to bypass `__init__.py` SDK chain (same pattern as tests). Discovered during live verification.
- Placed preflight module inside adapter package (`memoryhub_evalhub/preflight.py`) for clean container imports, with thin CLI wrapper at `benchmarks/preflight.py` per issue spec.
- Used asyncpg directly (not SQLAlchemy) for lightweight DB probes. Matches the provider's existing pattern for corpus reset.

## Backlog delta
Filed: none. Closes: #371 (via PR #380). Memory: none new. Deferred: adapter lint pre-existing issues (import sort L56, unused get_llm L57).

## Drift & forward-collisions
- Backward: #360 (Matrix A) now has one fewer blocker (#371 done). Remaining: #372 (PR #379), #342 (reranker), #365 (EvalHub PVC).
- Backward: #372 (keyword) unaffected; PR #379 still pending review.
- Forward: #342 (reranker) -- when TEI is deployed, the reranker signal check in preflight will automatically detect it (probes /info endpoint). Config expected_manifest will need updating from `reranker: {active: false}` to `true`. No comment needed; this is by design.

## For the reviewer
- Sanity-check: the expected_manifest is identical across all 9 configs because they share the same deployment. When signals activate (#342 reranker, #343 chunking), each config's expected_manifest will diverge -- is that manageable at 9 configs?
- Thin verification: adapter integration not tested end-to-end through EvalHub (would require submitting a real job). The preflight call itself is proven; the integration path from adapter to MLflow metadata is compile-checked only.
- Wants guidance: none.

## Risks / watch-fors
- Pre-existing CI failure: Secret Scanning (gitleaks) fails on both feat/benchmark-preflight pushes. Tests workflow passes.
- Pre-existing test failures: 8 failures in test_conversation_extraction.py on main (dreaming.py TypeError). Not from this session.
- Pre-existing lint: adapter.py has 2 pre-existing ruff findings (import sort, unused import). Not from this session; noted for future cleanup.
