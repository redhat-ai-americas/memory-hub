# Session Summary -- 2026-08-21 - public-benchmarks - Adapter, server fix, checkpoint-gated eval

**Plan:** NEXT_SESSION-public-benchmarks.md (Phases 1+2)   **Commits:** c4b3c06..d82e9c3 (feat/soc-demo-openshell + fork main)
**Deployed:** Server fix deployed (build 33, mcp-rhoai)   **Model:** Opus 4.6

## Plan vs. actual
Planned: Fork upstream AMB repo, write clean MemoryHub adapter, reproduce 84.9%, submit PR. Shipped: Fork, adapter, server bug fix, checkpoint-gated evaluation system. Slipped: Reproduction run blocked by Gemini credit exhaustion; PR submission deferred.
Scope: Expanded to include server-side logical_id bug fix and checkpoint-gated batch evaluation (both blockers discovered during execution).

## Shipped

**memory-hub repo:**
- `c4b3c06` fix: Set logical_id on chunk and fact child nodes (server bug, deployed as build 33)

**agent-memory-benchmark fork (rdwj/agent-memory-benchmark):**
- `d82e9c3` feat: Add MemoryHub provider adapter and reproduction tooling (130-line adapter, lab notes, PR draft)
- `fd21357` feat: Checkpoint-gated batch evaluation with smoke test gate (--smoke-test / --batch-size flags)
- `5ec4f11` feat: Add incremental checkpointing to batch mode runner (superseded by fd21357 but still in history)

**Infrastructure:**
- Fork created at rdwj/agent-memory-benchmark
- MemoryHub adapter registered, discoverable via `amb providers`
- 195 PersonaMem documents ingested on cluster (project: amb-upstream-repro)
- Server rebuilt and deployed with logical_id fix

## Verification & confidence
- Provider discovery: verified via `uv run amb providers` and Python import
- Ingestion: 195 docs in 82.8s, confirmed via server logs
- Retrieval + answer: 3/3 correct in smoke test with gemini-3.1-pro-preview
- Checkpoint gating: verified that --batch-size fails without --smoke-test
- Full 589-query run: NOT completed (Gemini credits depleted at ~540 queries)
- Confidence: **medium** -- adapter and infrastructure proven end-to-end on small scale; full reproduction pending credits

## Judgment calls & deviations
- Fixed logical_id server bug in-session rather than filing and deferring (it was a direct blocker for any write that triggers chunking, and the fix was mechanical)
- Built checkpoint-gated evaluation after three runs lost data (escalated from "incremental save" to "structural gate" at user direction)
- Used gemini-3.5-flash-lite as answer LLM initially (75.2% result); switched to gemini-3.1-pro-preview to match original 84.9% but credits ran out

## Backlog delta
Memory `feedback_implement_checkpointing_not_notes` -- benchmark checkpointing must be in code, not conventions. Memory `feedback_keep_upstream_fork_local` -- clone upstream repos on fast connections before sessions.

## Drift & forward-collisions
- Backward -- none identified
- Forward -- none identified

## For the reviewer
- Sanity-check: The 75.2% flash-lite result vs 84.9% pro-preview raises the question of which model to submit with. The retrieval quality is identical; the gap is entirely in the answer LLM. Need to decide: submit with the cheaper model (lower score, reproducible by anyone) or the expensive model (higher score, harder to reproduce)?
- Thin verification: Full 589-query reproduction not completed. The 3-query smoke test is too small to confirm retrieval quality matches the original run.
- Wants guidance: Should we submit the adapter PR without results (let upstream run it themselves), or wait until we have a full verified run?

## Risks / watch-fors
- Gemini credits are depleted across all models. Next session needs credits topped up before any benchmark work.
- The fork's `uv.lock` was modified by dependency resolution and included in the commit. This is expected (adding `memoryhub>=0.15` to pyproject.toml triggers a lockfile update) but the diff is large.
- Context token count doubled (53k vs 26k in original). Root cause not fully investigated. Could affect score comparison even with the same answer model.
