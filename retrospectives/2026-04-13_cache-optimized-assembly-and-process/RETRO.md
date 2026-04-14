# Retrospective: Cache-Optimized Assembly, Value Proposition, Process Hardening

**Date:** 2026-04-13
**Effort:** Implement #175 (cache-optimized memory assembly), rewrite README value proposition (#182), backfill integration tests (#177), enhance session preflight (#178), file SDK compat issue (#184) and API key auth issue (#183)
**Issues:** #175, #182, #177, #178, #95 (closed); #183, #184 (filed)
**Commits:** `a86feb2`, `054ad4a`, `283239b`, `45eaee6`

## What We Set Out To Do

Implement cache-optimized memory assembly (#175) with compilation epochs, consolidating all memory optimization thinking with compaction in mind. Add a value proposition section to the README. The session expanded to also close #177 (integration test convention), #178 (session preflight), and file two new issues from real user feedback.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| README value proposition went through two iterations | Good pivot | First version was cache-cost-centric; Wes caught the framing error — governance and shared memory are the lead story, cache is third |
| #177 and #178 turned out mostly done | Scope reduction | Infrastructure (compose.yaml, PR template, FREEZE NOTICE, cluster-health-check.sh) already existed. Only gap-filling needed. |
| #176 deprioritized | Strategic decision | User recruitment timeline pushed out ~1 week. Stored in MemoryHub so future sessions stop surfacing it. |
| API key auth discussion → #183 | Good pivot | Emerged from real user feedback. Formalized what's already an unnamed dev shim — no code changes needed, just docs and positioning. |
| SDK backward-compat issue → #184 | New finding | External project hit the OAuth migration breaking change. Captured with option analysis (shim + template update). |
| `should_recompile` threshold semantics | Design deviation | Sub-agent implemented ratio check gated on `compiled_count < min_appendix` to make test cases consistent. Semantics need review. |

## What Went Well

- **compilation.py as pure logic with zero I/O** — 14 unit tests, fully deterministic, clean separation from Valkey state. Good pattern to replicate.
- **Parallel sub-agent work was effective** — tasks 1+2 and 4+5 ran concurrently without git conflicts (worktree isolation).
- **"Most of #177 is already done" discovery** saved significant time. The infrastructure we built in earlier sessions paid off.
- **Real user feedback driving issues** — #184 came from an actual downstream consumer hitting a real problem. This is exactly the signal the project needs.
- **Session flow** — feature (#175) → positioning (#182) → process (#177, #178) → issue triage (#183, #184) was a natural progression that covered multiple value layers.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Integration tests for compilation/campaign can't run without compose stack | Medium | Need to run `make test-integration` in a future session. Tests parse and follow patterns but are unexecuted. |
| `should_recompile` threshold has subtle semantics | Low | Review below. The ratio check gating on `compiled_count < min_appendix` is defensible but non-obvious. |
| 26 pre-existing MCP test failures (3 distinct root causes) | High | See test debt analysis below. These have survived multiple sessions. |
| No benchmark proving cache optimization impact | Medium | Accepted from prior retro. Benchmark when deployed to cluster with real workload. |
| Sub-agent created conftest.py with autouse fixture | Low | The `_disable_scope_isolation` fixture patches only `search_memory` module. Other tool tests are unaffected but the pattern should be reviewed. |

## Test Debt Analysis (26 failures, 3 root causes)

**Root cause 1: Mock signature drift (16 failures — test_tenant_isolation.py)**
`create_memory` mock doesn't accept the `s3_adapter` kwarg that was added to the real function. The mock's `_fake()` signature is stale. Fix: update the mock factory to accept `**kwargs` or add the `s3_adapter` parameter.

**Root cause 2: Async mock not awaited (2 failures — test_get_relationships.py)**
`get_projects_for_user` mock returns a coroutine that `result.all()` tries to iterate synchronously. The mock needs to return a proper awaitable result. Fix: use `AsyncMock` with correct return value wrapping.

**Root cause 3: Module renamed/consolidated (8 failures — test_campaign_read_path.py)**
`src.tools.get_memory_history` no longer exists — the tool was consolidated in #173/#174 (`suggest_merge` and `get_memory_history` merged). Tests import the old module name. Fix: update imports to the new module path, or delete tests for removed tools.

## Action Items

- [ ] Run `make test-integration` against the compose stack to validate new tests
- [ ] Fix 26 MCP test failures (3 root causes above)
- [ ] Review `should_recompile` threshold semantics

## Patterns

**Continue:** Pure-logic modules with no I/O (compilation.py). Parallel sub-agent work with worktree isolation. Two-iteration approach to positioning/docs (write fast, review, fix framing).

**Start:** Running `make test-integration` as part of session verification when compose-dependent tests are added. Checking MCP test suite health at session start (the 26 failures have been invisible because they're in a different test directory).

**Stop:** Letting mock signature drift accumulate across sessions. The s3_adapter and module-rename failures are the exact pattern #177 was filed to prevent.
