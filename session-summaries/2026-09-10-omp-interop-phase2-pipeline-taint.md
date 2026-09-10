# Session Summary -- 2026-09-10 -- omp-interop -- Phase 2: pipeline, generating_model, taint

**Plan:** NEXT_SESSION-omp-interop.md (Phase 2)   **Commits:** c7c3c5f..de7491f (`feat/omp-interop/trust-and-gates`)
**Deployed:** none   **Model:** Claude Code (Opus 4.6)

## Plan vs. actual
Planned: #566 generating_model + #561 context assembly pipeline. Shipped: both, plus #563 taint metadata (user added mid-session) and pre-existing test fixes. Scope expanded by one issue at user request.

## Shipped
- `c7c3c5f` schema: generating_model column, Alembic 029, all model layers (#566)
- `edb12c4` extraction: wire generating_model through SDK pipeline, SDK client.write, MCP write_memory, server dreaming/reconciliation paths (#566)
- `e51c7ef` tests: 13 generating_model tests (6 pipeline, 7 schema) (#566)
- `4c1d5af` search: context assembly pipeline with 9 named stages, structured logging, ordering invariants (#561)
- `6b54100` tests: 23 pipeline tests (stage behavior, ordering, logging) (#561)
- `92b50bf` tests: fix pre-existing failures -- embedding mock max_tokens, conftest _session_id cleanup
- `4675912` fix: upstream_trust_level and generating_model never propagated through node_to_read/MemoryNodeStub -- silently defaulted
- `b89a08a` search: taint metadata on search/read responses for untrusted/mixed memories (#563)
- `bb72c6b` tests: 11 taint tests + fix None propagation in node_to_read (#563)
- `de7491f` style: ruff lint fixes, SDK import guard

## Verification & confidence
- All new code tested: 47 new tests across 4 test files
- SDK: 379 passed, MCP: 625 passed (from respective venvs)
- No deployment -- all changes are on the feature branch, 10 commits ahead of remote
- Confidence: **high** for #566 and #563 (schema + wiring, straightforward pattern). **Medium** for #561 (pipeline refactor touches a critical path; defense-in-depth stages don't filter under normal conditions, so their value is auditable ordering + logging, not runtime filtering)

## Judgment calls & deviations
- Added `upstream_trust_level` to `_WRITE_OPTS` whitelist while wiring `generating_model` -- it was missing from Phase 1, same pattern
- Fixed `node_to_read()` and all MemoryNodeStub constructors to propagate trust/model fields -- found during #563 investigation, would have made taint metadata useless without the fix
- Used `or` fallback instead of `getattr` default for ORM fields that exist as None (SQLAlchemy attribute semantics)
- Taint `sources` list uses the memory's `source` field (agent/dreaming/import) -- detailed per-tool provenance tracking deferred

## Backlog delta
Closed (pending PR merge): #566, #561, #563. No new issues filed. No memories updated.

## Drift & forward-collisions
- Backward: #560 (MOF export) -- not affected by this session, still waiting on OMP
- Forward: none

## For the reviewer
- Sanity-check: the `node_to_read()` propagation fix (`4675912`) -- was this gap real? Every search and read response has been returning `upstream_trust_level="trusted"` since Phase 1 landed. The ORM column was set correctly, the schema field existed, but the service-layer constructor skipped it
- Thin verification: context assembly pipeline (#561) runs in production but its filtering stages are defense-in-depth -- they'll only trigger on service-layer bugs (scope leak, tenant mismatch). Normal operation = passthrough with logging
- Wants guidance: none

## Risks / watch-fors
- PR #570 carries Phase 1 + Phase 2 + #563 on one branch (10 commits). May want to push and expand the PR description
- MCP server tests pass in MCP venv but 2 manage_session focus tests fail from project root venv (pytest-asyncio version mismatch: 1.3.0 vs 0.24.0). Pre-existing environment gap, not introduced here
