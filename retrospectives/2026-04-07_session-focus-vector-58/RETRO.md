# Retrospective: Session focus vector / two-vector retrieval (#58)

**Date:** 2026-04-07 (evening — sixth retro of the day)
**Effort:** Land Layer 2 of the agent-memory-ergonomics concept. Embed a session focus string per call, bias `search_memory` retrieval toward it, surface a server-side pivot signal, and ship the cross-encoder reranker that was deployed mid-session.
**Issues closed:** #58 (resolves open-questions Q1 ranking math, Q2 pivot detection)
**Commits:** `754adfe` (main implementation), `0f3b9bc` (numpy.float32 fix)

## What We Set Out To Do

Per the session brief: a five-phase plan to ship #58 in one sitting.

1. Build a benchmark harness with a 200-memory × 4-topic synthetic dataset and 40 queries × 3 levels.
2. Run the benchmark, pick the winning ranking math empirically, and document the decision.
3. Implement server-side: `search_memories_with_focus`, MCP tool wiring, server-side pivot detection.
4. SDK surface (`MemoryHubClient.search()` forwarding) plus a same-commit consumer audit on BFF and CLI.
5. Docs (research file, design.md, open-questions.md), close #58, save durable learning memories before any deploy.

The brief explicitly anticipated five open forks at session start (focus statefulness, which ranking options to test, dataset shape, results location, embedding service choice). It expected the benchmark to test the original three cosine-blend options A/B/C from the research file.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| User dropped a deployed cross-encoder reranker (`ms-marco-MiniLM-L12-v2`) into the session via pasted endpoint info. The original Options A/B/C all assumed cosine-only blending; the design space collapsed. | **Good pivot** — required re-evaluating the design space mid-session. Surfaced as a sixth fork ("the reranker changes everything; here are three new variants NEW-1/2/3 + baseline"). User locked in the new design space in one pass. The new sweep was tighter (4 pipelines vs 3 × 5 weight sweep) which made the benchmark faster and the analysis cleaner. |
| `numpy.float32` leaked into the production response and shipped on the first deploy. | **Real bug, caught post-deploy** — see Gaps. |
| Cross-encoder alone (NEW-3) was empirically neutral on the synthetic corpus, sometimes worse than baseline cosine. Production code added a "skip rerank when no focus / weight=0" short-circuit. | **Good pivot** — discovered during analysis. The architecture still ships the reranker because (a) the user explicitly deployed it for this work and (b) production data may be longer/noisier than the synthetic dataset. The short-circuit avoids the regression on the no-focus path. |
| The brief expected the benchmark to test the original Options A/B/C; the new design space dropped them all. | **Scope replacement, not deferral** — the original options were strictly worse than NEW-1 in both expressiveness (cross-encoder >> blended cosine) and code simplicity. No follow-up work owed. |
| `register_session` was NOT extended to take a focus string. Focus is per-call on `search_memory` instead. | **Good pivot** — Fork 1 from the brief. Stateless avoids every coordination question and lets #62's eventual stored session vector live in Valkey. |

## What Went Well

- **The five-phase plan ran in order with no mid-session deferrals.** Phase 1 (harness + dataset) and Phase 2 (run + analyze) took the longest as planned. The empirical answer was unambiguous enough that no follow-up tuning was needed.

- **Forking pattern worked cleanly.** Five-then-six forks surfaced upfront, locked in one pass, then announce-and-proceed through the agreed scope. Zero re-confirmations needed for in-scope work; the only mid-session interaction was the deploy/commit/close decision at the end.

- **Same-commit consumer audit took ~30 seconds and confirmed both BFF and CLI clean.** The habit is now muscle memory. The audit also surfaced a useful structural finding: BFF talks to the database via raw SQL at `/api/graph/search`, NOT through the SDK — so search-shape changes don't ripple to the BFF at all. Worth recording in the consumer-priority memory (already done).

- **All five learning memories saved BEFORE the first deploy.** The saved `feedback_deploy_invalidates_mcp_session.md` rule worked exactly as designed. When the deploy invalidated my MCP session, no memories were lost. The discipline of "save before risky operations" paid off.

- **Test deltas tracked cleanly.** mcp-server 127→134 (+7), root services+models 108→117 (+9 including the numpy regression), SDK 59→66 (+7). Every delta was a real new test, not baseline drift.

- **The benchmark methodology was honest about uncertainty.** The provisional recommendation in the research file was Option B (rerank-after-recall with cosine blend). The actual benchmark winner (NEW-1, RRF blend over cross-encoder rerank) was a different shape entirely because the design space changed mid-session. The research file was updated to mark the original analysis as historical and document the new decision with empirical numbers. The temptation to massage the original recommendation into looking like a successful prediction was resisted.

- **`/deploy-mcp` ran the project-canonical script, not the template default.** The saved `feedback_mcp_deploy_customizations.md` rule was honored: I read the project-local `.claude/commands/deploy-mcp.md` first, captured the baseline pod name, used the exact delegation prompt, verified the new pod differed from baseline, and ran end-to-end verification via mcp-test-mcp before declaring success.

- **Bolder-recommendation pattern held.** Per the prior retro's "recommendations should be bolder" rule, I recommended a single bundled commit (option B) when presenting the commit/deploy/close decision, not five split commits. User confirmed. Worked out cleanly.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| **`numpy.float32` leaked into production response shipping the first deploy.** Mock embedding service returns Python lists; pgvector returns numpy arrays. `_cosine_distance` propagated `numpy.float32` to `relevance_score`, which `pydantic_core.to_jsonable_python` rejects. FastMCP silently dropped `structured_content`, surfacing as the confusing "outputSchema defined but no structured output returned" on every focus call. Caught by mcp-test-mcp post-deploy verification. | **Real bug, fix shipped same session** | Fixed in `0f3b9bc` (one-line `float()` cast at the function exit). Regression test added in `tests/test_services/test_memory_service.py::test_cosine_distance_returns_python_float_for_numpy_inputs` that explicitly uses `numpy.float32` and asserts the response payload round-trips through `pydantic_core.to_jsonable_python`. **Follow-up action item: add `tests/integration/test_pgvector.py` cases for `search_memories_with_focus` so this class of bug is caught against real pgvector before deploy.** The integration suite already runs via podman-compose; no infrastructure work needed, just test cases. |
| **Synthetic benchmark may not generalize to real production memories.** The cross-encoder was neutral-to-negative on memory-hub's short, topic-coherent corpus. Real production memories may be longer and noisier where the cross-encoder genuinely helps. | Watch | Re-benchmark on real memories once we have enough corpus volume. Tracked via the saved memory `599007a6` (cross-encoder behavior) and the design.md note. Not a tracking issue — the re-benchmark is opportunistic, not blocking. |
| **Verify-on-every-deploy via mcp-test-mcp is now a hard discipline, not a "should."** The numpy bug surfaced because I ran mcp-test-mcp against the deployed server. Without that step, the bug would have shipped silently and only surfaced when an SDK consumer hit the focus path — much worse blast radius. | Process improvement | The project-local `/deploy-mcp` slash command already requires this. The discipline now needs to apply EVEN when the test suite is fully green. The numpy bug had 100% line coverage in unit tests; that wasn't enough. |
| **Unit-test mock services are fundamentally insufficient for catching numpy/pgvector boundary bugs.** The audit (see Patterns below) found 5 mock-vs-real boundaries in the codebase. The integration suite covers #1 (pgvector storage) and `memoryhub-auth/tests/` covers #3 (real OAuth). Categories #4 (HTTP transport) and #5 (OpenShift container) are still verify-on-deploy only. | Systemic | Documented in Patterns. No immediate action — the integration suite is the right pattern, the discipline is "use it for any new code that touches the boundaries." |
| **Two `make deploy` runs ate ~6 minutes each plus pre-flight verification.** Acceptable cost for catching a real bug. Not a process gap; observation. | Accept | Re-deploy is the cost of the verify-on-deploy discipline. Cheaper than shipping bugs. |

## Action Items

- [x] #58 closed; auto-closed by "Closes #58" in the main commit. Standalone summary comment posted to the issue with commit pointers.
- [x] `numpy.float32` regression fix shipped (`0f3b9bc`) + regression test added.
- [x] Five durable learning memories saved before deploy: `35718bd4` (Layer 2 ship note), `443e3ee4` (NEW-2 dead), `599007a6` (cross-encoder neutral on short corpora), `7c1bfcb5` (session_focus_weight tuning), `a8c3718e` (#61/#62 forward pointers). Consumer priority memory updated to v3 (`cf907154`).
- [x] Deploy manifest updated with `MEMORYHUB_RERANKER_URL` secret key and shipped.
- [ ] **Add `search_memories_with_focus` integration tests at `tests/integration/test_pgvector.py`.** This is the only test-time mitigation that would have caught the numpy bug. Should cover: focus-path returns serializable response with real pgvector embeddings; relevance_score is Python float not numpy; pivot signal computed correctly. Not blocking on a tracking issue — just file when picking up #61 or #62 and add the tests opportunistically.
- [ ] **Re-benchmark NEW-1 on real production memories** once memory-hub has enough corpus to be representative. The synthetic benchmark says the cross-encoder is neutral; production may differ. Not blocking; watch.
- [ ] **#61 (session focus history) and #62 (Pattern E push)** are now unblocked. Both will need a Valkey-backed store for session focus vectors so #62's broadcast paths can filter without per-call re-embedding. See the saved memory `a8c3718e` for the forward pointer rationale.

## Patterns

**New pattern — Mock-vs-real type mismatch is a systemic test gap, not a one-off bug.** This session's `numpy.float32` leak was the second time a "production-only" bug shipped because the test environment differs from production at an infrastructure boundary. The first was the chmod 644 file permissions issue (developer UID vs container non-root UID). Both are mock-vs-real mismatches. The audit conducted during this retro identified **5 such boundaries** in the codebase:

1. **Embeddings**: SQLite `_JsonEncodedVector` + Mock service returning Python lists vs pgvector `Vector` column returning numpy arrays. **The bug landed here.** Mitigation: integration tests at `tests/integration/test_pgvector.py`. Already exists for non-focus paths; needs focus-path cases.
2. **JSONB server defaults**: Tests patch `'{}'::jsonb` to `None`; production inserts the empty dict. Currently safe but trap is set if any code reads metadata fields without a Pydantic default.
3. **JWT auth context**: Tests set `_current_session` directly; production runs JWT verification + scope normalization. Mitigation: `memoryhub-auth/tests/` runs against the real auth service. The MCP server's JWT integration is end-to-end-only.
4. **HTTP transport**: Tests use STDIO + in-memory mocks; production uses streamable-http over the cluster network. Mitigation: `mcp-test-mcp` verify-on-every-deploy. **No test-time coverage.**
5. **OpenShift container constraints**: Developer UID vs arbitrary non-root container UID, env vars, service discovery. Mitigation: deploy scripts and CLAUDE.md conventions. **No test-time coverage.**

The systemic answer is **categories #1 and #3 should ship integration tests when new code touches the boundary**, and **categories #4 and #5 are caught only by deploy verification, which is now a hard discipline**.

**New pattern — `/deploy-mcp` verification via `mcp-test-mcp` is now mandatory, not optional.** The numpy bug had 100% line coverage in the unit test suite and shipped to production anyway. The bug was caught only because I ran a focus-path call against the deployed server via `mcp-test-mcp`. Without that step, the bug would have surfaced at SDK consumer time with much worse blast radius. Going forward: any deploy of `memory-hub-mcp` MUST include a post-deploy `mcp-test-mcp` verification of the changed code paths, not just a tools/list smoke test.

**Confirmed pattern — Save durable memories BEFORE any risky operation.** The saved `feedback_deploy_invalidates_mcp_session.md` rule did its job. All five learning memories were saved before the first `/deploy-mcp` invocation, so when the deploy invalidated my MemoryHub MCP session, no memories were lost. The discipline of "memories first, then risky action" is generalizable to other session-invalidating events.

**Confirmed pattern — Same-commit consumer audit is muscle memory and catches structural facts, not just bugs.** The audit took ~30 seconds (grep BFF + grep CLI) and confirmed both unaffected. As a side effect, I noticed the BFF talks to the database via raw SQL at `/api/graph/search`, not through the SDK. Updated the consumer-priority memory (`cf907154`, version 3) to record this so future tier-1 audits can skip the BFF for search-tool changes specifically. The audit habit produces structural knowledge as well as bug-catching.

**Confirmed pattern — Bolder recommendations on closed-scope decisions.** Per the prior retro's "recommendations should be bolder" rule, I recommended a single bundled commit when presenting the commit/deploy/close decision (instead of five split commits). User confirmed. The bundled commit was 27 files / 29031 insertions, which sounds intimidating but the diff was coherent because the pieces are interdependent. Splitting would have meant five commits each with a partial story.

**New pattern — When a user-shipped resource changes the design space mid-session, treat it as a fork and re-confirm.** The cross-encoder reranker dropped into the conversation via pasted info around fork-resolution time. The original three options (A/B/C) all assumed cosine-only blending, so the reranker collapsed two of them and required a fundamentally different approach. Surfacing this as a sixth fork ("the reranker changes everything; here are three new variants NEW-1/2/3 + baseline; here's my pick; confirm or correct") was the right call. The alternative — silently incorporating the reranker into Option B without surfacing the design implications — would have produced a worse benchmark and a less defensible decision.

**Continue:**
- Aggressive verification on deploy via `mcp-test-mcp`, even when the test suite is green.
- Saving durable learning memories before any risky operation that could invalidate the MemoryHub session.
- Surfacing genuine forks for confirmation; announce-and-proceed for in-scope work.
- Same-commit consumer audit on every search/write/delete tool shape change.
- Bolder recommendations on closed-scope decisions.
- Reading project-local slash commands (`memory-hub-mcp/.claude/commands/deploy-mcp.md`) before invoking the generic skill.

**Start:**
- Adding pgvector-backed integration tests for any new code path that touches embeddings, before declaring "tests green = ready to deploy."
- Auditing the mock-vs-real boundary explicitly when introducing new server-layer code; the 5-category list above is the audit checklist.

**Stop:**
- Treating "all unit tests green" as sufficient evidence that a server-side change is deploy-ready. The numpy bug had 100% line coverage and still shipped. Unit tests cover logic; deploy verification covers infrastructure boundaries.
