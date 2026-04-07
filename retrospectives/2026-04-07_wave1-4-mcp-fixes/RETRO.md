# Retrospective: Wave 1-4 mcp-server fixes

**Date:** 2026-04-07
**Effort:** Land all 8 mcp-server issues filed during the 2026-04-06 `/exercise-tools` session
**Issues closed:** #47, #48, #49, #50, #51, #52, #53, #54
**Commits:** `f990762`, `be5e8b9`, `72710a4`, `b51f229`, `c871da8`, `2a10ad0`, `dcecd72`, `67241ab`, `7f69806`, `3c4bbd6`

## What We Set Out To Do

Execute four waves of fixes against the 8 issues planned by the previous session's `NEXT_SESSION.md`:

- **Wave 1** (mcp-server only): #47 (broken `get_similar_memories` RBAC filter), #48 (orphan branches), #53 (`search_memory` `has_more`)
- **Wave 2** (`read_memory` schema redesign): #50 (drop `depth`, add `branch_count`), #52 (auto-resolved by #50)
- **Wave 3** (parent `memoryhub` package + service layer): #49 (bidirectional version walker), #51 (`current_version_id` pointer), version bump to 0.2.0
- **Wave 4**: #54 (TOOLS_PLAN.md sync)

Two deploys planned: one after Wave 2, one after Wave 3, both verified end-to-end with `mcp-test-mcp`.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #47 fix added a pre-fetch caller-vs-source authorization check rather than just deleting the broken post-fetch filter | Good pivot | The issue body said "remove the post-fetch RBAC block." Doing only that would have created a security gap: any authenticated user could probe similar memories of any source UUID. Replaced the broken filter with `read_memory` service + `authorize_read`, matching the pattern in `read_memory` tool. |
| #50 commit was split into two: server-side (root memoryhub + mcp-server tool) and consumer-side (SDK + CLI) | Good pivot | Single commit would have touched 8 files across 3 packages with a mix of concerns. Split keeps the schema change reviewable and the consumer catch-up cleanly attributed. |
| Consumer audit for #50 also caught that #53 was shipped without updating the SDK/CLI in Wave 1 | Recovery of missed audit | The previous session's plan said "consumer audit for #50" but `total_accessible` from #53 had already been removed from the server when #53 committed. The CLI was silently displaying "5 of 0 accessible" until I caught it during the #50 audit. Folded both into the #50 consumer commit. |
| #52 surfaced a pre-existing bug during deploy verification | Discovery | Removing the `depth == 0` gate exposed `for v in history` iterating dict keys (the service returns a dict, not a list). The bug had been hidden because nobody had ever exercised `include_versions` against this server. Filed as commit `2a10ad0` with a test that mocks the real shape. |
| Wave 3 used a single shared `_walk_version_chain` helper for both `delete_memory` and `get_memory_history` (and #51) | Good pivot | The two callers previously had divergent walkers; #49 was an opportunity to unify rather than just patch `get_memory_history`. The same helper now backs `read_memory`'s historical-version pointer in #51. |
| BFF has a parallel backward-only walker that wasn't fixed | Scope deferral | `memoryhub-ui/backend/src/routes.py:337` has its own duplicate of the buggy walker for `/api/memory/{id}/history`. It doesn't call into the memoryhub service, so it wasn't touched by #49. Filed in this retro's action items. |

## What Went Well

- **All 8 planned issues landed in one session** with no scope cuts. Each issue got its own commit, the version bump is its own commit, the consumer catch-up is its own commit. 10 commits total, all clean and reviewable.
- **Two deploys verified end-to-end** with `mcp-test-mcp` against the live cluster. Wave 2 verification spot-checked `write_memory` orphan rejection, `search_memory` `has_more`, `read_memory` `branch_count`, `read_memory` `include_versions`, and `get_similar_memories` non-empty results. Wave 3 verification built a real 3-version chain, tested `get_memory_history` with the oldest ID, and tested `read_memory` of both old and middle versions for `current_version_id`.
- **Mode switch back to delegation worked.** The previous session ran first-party because the foundation was a mess. This session defaulted to delegation (terminal-worker for the two builds, main context for everything else) and moved much faster. Per the previous retro's pattern.
- **Discovery during planning paid off again.** Reading the `_walk_version_chain` helper from `delete_memory` before writing #49 meant the refactor was a 1-helper extraction instead of a duplicate-walker copy.
- **Tests were fixed at the right level.** When the `_compute_branch_flags` signature changed, two service tests broke and were updated to assert `branch_count` directly. When the include_versions bug was caught, I rewrote the test to mock the real dict shape so the contract drift can't recur silently.
- **Cleanup B (#55) deferral held.** The temptation to "just rename `memoryhub` while we're touching it" was real and was correctly resisted. The package layout doc (`docs/package-layout.md`) was the single touchpoint we needed.
- **Commit-per-issue discipline held even when commits were tightly coupled.** #50 and #52 share a commit because #52 was auto-resolved by the same code change; the commit message attributes both. #50/#53 consumer updates share a commit because the SDK/CLI changes were impossible to split cleanly. Everything else is one issue per commit.
- **TOOLS_PLAN.md sync (#54) included rationale, not just text changes.** The `delete_memory` "not found collapses three causes" section explicitly preserves the security reasoning so the next person doesn't try to "fix" it back to a 409. Same for the `read_memory` historical version note.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Wave 2 deploy hit a digest-resolution race: build pushed new image, but `oc rollout restart` happened before the `:latest` ImageStream tag updated, so the new pod ran an *older* digest (`7be0c3ae` instead of the just-pushed `7529c4d8`). Required a manual `oc apply -f openshift.yaml` after the build to force re-resolution, then a second rollout. | **Recurring (4th occurrence)** | Filed below. The deploy script needs to re-apply the manifest *after* the build, not just before. |
| Pre-existing bug in `read_memory` `include_versions` was caught only during deploy verification, not local tests | Test mock vs reality drift | Fixed in `2a10ad0`. Test now mocks the real dict shape. Pattern: test mocks should match the real return shape, not a convenient simplification. |
| BFF `/api/memory/{id}/history` has a duplicate of the same backward-only walker bug fixed by #49 | Follow-up | Filed below as a new issue. Same fix recipe applies. |
| **#36 — Frontend component tests for dashboard. 4th retro this is open.** | Recurring (4th occurrence) | Action: next session, either commit to it or close it with "we are not testing the frontend." |
| **#43 — Backend route tests for new BFF endpoints. 3rd retro this is open.** | Recurring (3rd occurrence) | Same — commit or close. |
| Wave 1 commit for #53 missed updating SDK/CLI consumers | Process | Caught and fixed via the #50 consumer audit. **The pattern: when ANY commit changes a server response shape, the consumer audit must run *as part of that commit*, not be deferred.** |

## Action Items

- [x] All 8 planned issues fixed and verified end-to-end
- [ ] **Fix the deploy script's image-resolution race.** Add `oc apply -f deploy/openshift.yaml -n memory-hub-mcp` *after* `oc start-build --follow` completes, before the final rollout-restart. The `alpha.image.policy.openshift.io/resolve-names` annotation re-resolves `:latest` to the current digest at apply time, so a second apply after the push is the cheapest fix. **Do this next session, before any further deploys.** This is the 4th retro to flag a deploy/image-cache failure family. The previous fixes (`noCache: true`, ImageChange trigger discussion) were partial.
- [ ] File a follow-up issue for the BFF `/api/memory/{id}/history` backward-only walker (parallel to the #49 fix in the service layer).
- [ ] **#36 (frontend tests) and #43 (backend route tests) — make a decision next session.** Both have now survived 3+ retros. Either commit to it or close them.
- [ ] Carry forward to NEXT_SESSION.md: deploy-script fix is the highest-priority foundation work for next session.

## Patterns

**Recurring (4th occurrence): Deploy/image-cache failures.** Past instances:
- 2026-04-07 RBAC retro: BuildConfig lacked `noCache: true`, Deployment lacked ImageChange trigger
- 2026-04-06 dashboard-memory-graph: 3+ redeploys with stale code (3rd occurrence noted at the time)
- 2026-04-07 cleanup-pivot: rebuilt deploy script entirely, added Step 0 preflight, but didn't address the image-resolution race
- **2026-04-07 this session**: pushed image succeeds, but resolve-names race makes the rollout pick up the *previous* digest

This is a systemic failure mode with a known recipe: builds and rollouts must always be paired with a manifest re-apply (or an ImageChange trigger). **The fix has been "filed" four times and not durably applied.** Next session must do this *first*, before anything else.

**New pattern: Test mocks must match real return shapes, or contract drift hides bugs until production.** The `read_memory` `include_versions` bug was hidden because the unit test mocked `get_memory_history` as a list, while the real service returns a dict. The test passed; production failed. The fix-up included a test that mocks the real dict shape. Going forward: when mocking a service function, copy the real return type from the source, not what would be convenient for the test.

**New pattern: Server response shape changes require a same-commit consumer audit.** The #53 commit shipped with `total_accessible` removed from the server, but the SDK SearchResult model and CLI display still referenced it. Pydantic `extra="allow"` masked the failure mode (no crash, just silent zero). I caught it during the #50 audit, but it would have been better caught at commit time. Going forward: any commit that changes a tool's response shape must grep the SDK and CLI for the old field name before committing.

**Confirmed pattern (3rd time): Recurring action items survive retros unless explicitly addressed.** #36 has been open since 4 retros ago. #43 has been open since 3 retros ago. The deploy/image-cache family has been open since 4 retros ago. **A recurring item that survives 2+ retros is no longer an "action item" — it's a decision the project hasn't made yet.** Force the decision next session.

**Start:** Re-applying the deployment manifest *after* every successful build, not just before. This is the cheapest fix to the recurring deploy race.

**Start:** When mocking a service function in a tool test, copy the real return shape from the source. Don't simplify to "what's convenient for the test" — that hides bugs.

**Start:** Running a grep-the-consumers check as part of any commit that changes a tool's response shape. SDK + CLI + BFF + dashboard. One-line `grep -rn 'old_field_name' sdk/ memoryhub-cli/ memoryhub-ui/`.

**Stop:** Filing the same recurring action item across retros without escalating it to a decision. After 2 retros, it's a decision, not a TODO.

**Continue:** Aggressive delegation as the default mode, with first-party reserved for foundation cleanup sessions. Worked well this session — main agent stayed focused on coordination, terminal-worker handled the two builds, sub-agents weren't needed for any of the file edits because the scope was clear and well-bounded.

**Continue:** Discovery-first planning. Reading `_walk_version_chain` from `delete_memory` before writing #49 made the refactor a one-helper extraction.

**Continue:** Commit-per-issue discipline, with deliberate exceptions when issues are tightly coupled and well-attributed in the message. The two #50-related commits are a good model.
