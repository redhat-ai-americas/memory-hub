# Session Summary -- 2026-07-28 - personal-edition - Phase 4: Extraction pipeline

**Plan:** NEXT_SESSION-local.md Phase 4   **Commits:** fc485a6..dd72a17 (feat/personal-edition)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: MCP sampling extraction, on-connect dreaming, `memoryhub dream` CLI, deferred queue fallback. Shipped: all four. Slipped: none.
Scope: stayed in scope. No scope creep.

## Shipped
- `fc485a6` Extraction service with LLM-agnostic pipeline: per-turn windowing, similarity-based reconciliation, cursor management, provenance, failure tracking, HTTP LLM factory. 11 tests.
- `34f14c4` Thread extract action wired with MCP sampling via `ctx.sample()` and ExtractionResult Pydantic model.
- `d9382a5` On-connect dreaming in register_session: auto-drains up to 3 pending threads via sampling on session start.
- `df60f21` Shared startup helper (`startup.py`) for DB+embedding init reuse across MCP server and CLI.
- `a925eca` `memoryhub dream` CLI command with Ollama-default URL, `--model`, `--url`, `--api-key`, `--dry-run`.
- `dd72a17` Lint fix in startup.py.

## Verification & confidence
- 41 tests pass (30 existing + 11 new extraction tests) covering windowing, memory creation, cursor advancement, dedup, failure recording, provenance, pending discovery.
- `memoryhub dream --dry-run` verified end-to-end (init backend, query pending threads).
- Confidence: **medium** -- unit tests prove the pipeline mechanics; the MCP sampling round-trip (live Claude Code session writing a thread then extracting) and Ollama round-trip need manual verification with running services.

## Judgment calls & deviations
- Inlined the extraction prompt as a Python constant rather than loading from the shared `prompts/` YAML. The personal edition is a standalone pip package; cross-package file references are fragile. The prompt can diverge if needed.
- Simple reconciliation (similarity thresholds only, no LLM tiebreaker) instead of full cluster-edition reconciliation. Appropriate for local edition where LLM calls are expensive.
- `create_memory()` commits within itself (existing design), so `extract_window` doesn't fully control transaction boundaries. Dedup handles any re-extraction on crash recovery.

## Backlog delta
Filed: none. Closed: none. Deferred: version bump to 0.2.0 (when landing to main).

## Drift & forward-collisions
- Backward: none -- extraction is a new capability, doesn't change existing issue landscape.
- Forward: Phase 5 (onboarding + docs) can now document extraction and `memoryhub dream`. The dreaming epic's cluster-edition extraction (PRs #407, #412) shares the prompt and output schema -- if the prompt changes upstream, the inlined constant here needs syncing.

## For the reviewer
- Sanity-check: the reconciliation thresholds (0.98 skip, 0.85 update) are reasonable for local edition but untested with real extraction output.
- Thin verification: MCP sampling round-trip not tested (requires live agent session). Ollama round-trip not tested (requires running Ollama).
- Wants guidance: none.

## Risks / watch-fors
- `ctx.sample()` behavior may differ across FastMCP versions. Pinned to `>=2.11.3` but sampling API could change.
- Ollama's `/v1/chat/completions` endpoint may not support `response_format: {"type": "json_object"}` on all models. Tested with llama3.2 which does.
