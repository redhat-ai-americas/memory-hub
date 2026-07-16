# Session Summary -- 2026-07-16 - Dreaming - extract_facts wiring + prompt audit

**Plan:** NEXT_SESSION-dreaming.md   **Commits:** b5f509f (fix/extract-facts-wiring)
**Deployed:** dev (build #19, memory-hub-mcp)   **Model:** Opus 4.6

## Plan vs. actual

Planned: extraction model comparison (Part 1) + permanent write-time extraction pipeline (Part 2).
Shipped: neither -- both were already done by an earlier session today (PR #407, session summary at 2026-07-16-dreaming-extraction-pipeline.md). Pivoted to closing the gaps that session identified: extract_facts parameter wiring, prompt infrastructure audit, integration test, deployment, sweep cleanup.
Scope: stayed within the extraction pipeline scope; the pivot was a natural follow-on.

## Shipped

- b5f509f `extract_facts` parameter wired through `write_memory()` with input validation, branch guard, and mode dispatch (eager/off/background). Closes #406.
- Prompt versioning: `version: "1.0"` added to `entity_extraction.yaml` and `conversation_extraction.yaml`.
- MCP server deployed (build #19) with extract_facts support and prompt files confirmed in container.
- Integration test: all three modes verified live (off suppresses, eager defers gracefully without sampling client, invalid values rejected with ToolError).
- Sweep project cleanup: 15 benchmark projects (130k+ rows) deleted from database. 7 still deleting via pod-side SQL at session end.

## Verification & confidence

- Unit tests: 567 passed (561 existing + 6 new), 0 failed
- Lint: clean on modified files (35 pre-existing lint issues in other files)
- Integration test: live MCP tool calls via mcp-test-mcp confirmed all three extract_facts modes
- Deployment: build #19 verified -- digest match, 14 tools registered, prompts in container
- Confidence: **high** -- end-to-end verified on deployed server. Sampling itself was not tested (mcp-test-mcp doesn't support sampling callbacks), but the graceful deferral path works.

## Judgment calls & deviations

- Pivoted from re-running the extraction model comparison (already done) to closing the gaps from the earlier session. No time wasted -- the redundant background agent was stopped after ~120/195 docs.
- Prompt infrastructure audit concluded: no shared loader refactor needed. The three consumers each resolve paths correctly in both local and container environments (different `parents[N]` depths, but the nesting works out). Documenting the fragility is sufficient.
- Decided against registering prompts as MCP prompt resources (`@mcp.prompt`). The three current prompts are internal to extraction pipelines, not agent-facing. Future agent-facing prompts should use the decorator.

## Backlog delta

Closed #406 (extract_facts gap). No new issues filed. #405 and #404 are pre-existing and unrelated to this session.

## Drift & forward-collisions

- Backward -- #347 (reconciliation): more urgent now. Facts are being created in production (via eager extraction on oversized writes). Cross-write fact dedup is explicitly deferred to #347 per the design doc. Still valid.
- Backward -- #348 (run provenance): `extraction_run_id` metadata is carried on every fact. #348 may find this pattern partly satisfies its requirements.
- Forward -- none identified.

## For the reviewer

- Sanity-check: `extract_facts="eager"` on non-oversized content forces extraction. This is intentional per the plan (lets SDK callers explicitly request extraction), but the utility is questionable for small writes that are already fact-sized. Worth monitoring.
- Thin verification: live MCP sampling (ctx.sample()) has never been exercised end-to-end. The server issues the request correctly, but no client has completed the round-trip. First real test will be when an MCP client with sampling support (e.g., Claude Desktop, a custom FastMCP client) writes oversized content.
- Wants guidance: should we prioritize getting a sampling-capable client test before proceeding with Phase 5 (#347 reconciliation)?

## Risks / watch-fors

- Sweep cleanup: DELETE of ~102k rows still running on memoryhub-pg-0 at session end. Will complete autonomously. Verify with `SELECT COUNT(*) FROM memory_nodes WHERE scope_id LIKE 'amb-c%';` next session.
- CI: CLI lint and integration tests failing (pre-existing, not caused by this session). MCP server tests pass.
- GPU machineset still at 3 nodes. Scale back to 2 when confirmed both models fit.
