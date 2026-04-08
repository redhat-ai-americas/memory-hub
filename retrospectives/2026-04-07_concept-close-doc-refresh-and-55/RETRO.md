# Retrospective: Agent-memory-ergonomics close-out + repo doc refresh + #55 rename

**Date:** 2026-04-07 (evening — seventh retro of the day)
**Effort:** Close out the agent-memory-ergonomics concept (Layer 3 ship), refresh repo-level documentation, rename the server-side `memoryhub` package to `memoryhub_core` to resolve the #55 collision, and deploy everything.
**Issues closed:** #59, #60, #73, #55. Issues filed: #83.
**Commits:** `5edc821` · `420bdb5` · `46328d3` · `31fb079` · `b89b7eb` · `f315bd5`
**Production state changes:** memory-hub-mcp pod `69f7789c9-tc2th` → `86d9447675-85wsb`; memoryhub-ui pod `68ddb64c84-5c4gt` → `7cbbf9b4d6-mn2bc`.

## What We Set Out To Do

The NEXT_SESSION brief scoped this session to **Layer 3 of the agent-memory-ergonomics concept**:

1. **#73** (prep): surface `mode`/`max_response_tokens`/`include_branches` on the SDK's `MemoryHubClient.search()`.
2. **#59**: define the `.memoryhub.yaml` Pydantic schema in `sdk/src/memoryhub/config.py`, wire the loader into `MemoryHubClient`, auto-apply `retrieval_defaults` on outbound calls.
3. **#60**: add `memoryhub config init` and `memoryhub config regenerate` to `memoryhub-cli`, with per-pattern (eager / lazy / lazy_with_rebias / jit) rule-file templates.

The brief pre-identified four open design forks to pause on: focus inference home, migration path for the existing rule file, Pattern E knobs in the #59 schema, and which package hosts the new CLI command. Everything else was in-scope for announce-and-proceed.

The brief explicitly did NOT include the full doc refresh, #55, CONTRIBUTING, or the kagenti accuracy work. Those all surfaced mid-session.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| The brief said "Layer 3 + close the concept." I took it at face value — landed #59/#60/#73, then the user asked "are SYSTEMS.md and ARCHITECTURE.md up to date with what we've done?" The answer was no. Scope expanded to a full repo doc refresh. | **Good pivot** — the docs were genuinely stale (no mention of SDK, CLI, UI, auth, OAuth, RBAC, agent-memory-ergonomics). They were misrepresenting the project to anyone landing on the repo. Fixing them at the natural boundary (after a concept closes) was the right time. |
| #55 (the memoryhub package naming collision) was explicitly punted in the brief as "still parked." User asked about it after the doc refresh — "do we have exactly one SDK and one CLI now?" Answer: one CLI, one SDK, but two packages both named `memoryhub` (server-side vs SDK). User then queued #55 for this session after the docs. | **Good pivot** — scope creep, but the right kind. The rename was well-understood (docs/package-layout.md was the design doc), the mechanical work was clear, and bundling it into the "concept done" narrative was cleaner than pushing it to yet another session. |
| CONTRIBUTING.md, NOTICE, LICENSE copyright line, and the kagenti accuracy audit were all unplanned mid-session additions. User asked "are kagenti references accurate" and "should we add a contributing guide" and "put 2026 Wes Jackson wherever we add copyright info" as part of the doc review. | **Good pivot** — same reason. The brief asked for "close out the concept." The user's implicit bar was "close out the concept and leave the repo in a state someone else could walk into." CONTRIBUTING + NOTICE + kagenti accuracy are part of that. |
| Found the `memoryhub-ui/deploy/deploy.sh` build pipeline drift during the #55 prep: the Containerfile was reading from `memoryhub/` while the build script staged to `memoryhub-core/`. Folded the fix into the #55 commit. | **Good pivot** — the mismatch would have been a silent build failure the next time someone triggered a UI rebuild. Fixing it while already touching those files was near-zero marginal cost. |
| Two deploy gotchas surfaced during the #55 UI deploy: `memoryhub-ui/deploy/deploy.sh` has no `oc rollout restart` step, and the Deployment spec pins an image digest rather than using the imagestream tag. Neither is a #55 regression — both were pre-existing latent issues exposed because this was the first content change to the UI image in a while. | **Scope deferral** — filed as #83, not fixed in this session. Fixing it would mean editing the deploy script, re-running the UI deploy from the fixed script to verify, and committing. That's a focused follow-up, not an in-session patch. |
| Pre-existing `.claude/skills/issue-tracker.md` modification in the working tree never got resolved. I left it alone every commit per the "don't bundle unrelated pre-existing changes" rule, and it's still dirty. | **Missed understanding** — I should have asked what changed in that file and either staged it with permission or understood why it keeps showing as modified. Instead it stayed in the "not mine" bucket all session. See Gaps. |

## What Went Well

- **The fork-then-announce-and-proceed pattern held across every scope expansion.** Every real design decision surfaced as a fork, got locked in one pass, then I executed without re-confirming. Zero wasted back-and-forth. The user's "announce-and-proceed for unambiguous next steps in agreed scope" rule (from `feedback_pause_for_forks_not_for_permission.md`) was load-bearing all session.

- **Layer 3 landed in the order the brief predicted.** #73 → #59 → #60 with no mid-session deferrals. The three issues closed cleanly with commit pointers. Test counts went from 38 → 41 → 59 on the SDK and 0 → 27 on memoryhub-cli (new suite), both matching predictions.

- **The doc refresh caught four missing subsystems in SYSTEMS.md.** `sdk`, `memoryhub-cli`, `memoryhub-ui`, and `memoryhub-auth` were all deployed and running but nowhere in the subsystem inventory. ARCHITECTURE.md was pre-OAuth, pre-dashboard, pre-SDK, pre-ergonomics. Both documents now reflect reality. The diagrams are honest about the three-namespace topology and the cross-encoder reranker.

- **The #55 rename was a pure refactor.** All five test suites stayed at identical baselines before and after the rename: mcp-server 134, root services + models 117, BFF 39, SDK 66, memoryhub-cli 27. Zero test drift, zero behavior change. The sanity check via `make test`, `make install`, and running both `build-context.sh` scripts confirmed the end-to-end pipeline was coherent before we touched production.

- **Same-commit consumer audit ran on every shape change.** For #73/#59/#60, for #55, for the kagenti accuracy fixes. The audit habit is now muscle memory — it runs without being prompted. Consumer priority tier list (memory `cf907154`, v3) was updated mid-session by the #58 retro agent and I trusted it throughout.

- **mcp-test-mcp post-deploy verification caught the memoryhub-ui deploy gotcha.** Without the discipline (forced on me by the #58 retro's hard rule), I would have declared success when the build succeeded and never noticed that the running pod was on the 23-hour-old image. The `oc get deploy ... -o jsonpath='{.spec.template.spec.containers[0].image}'` check is the specific assertion that caught it — comparing the digest against the baseline revealed the pin.

- **The focus-path smoke test on the deployed mcp-server actually exercised the rename.** I didn't just list tools and stop; I registered a session, ran a real `search_memory` with `focus="package layout"`, got 5 results with valid float scores, `pivot_suggested: true` (as expected for an off-focus query), and no `focus_fallback_reason` (cross-encoder reachable). The #58 numpy regression would have surfaced here if it had been re-introduced; it wasn't.

- **The kagenti accuracy verification used WebSearch against the live sources.** Rather than trusting what was in the kagenti-integration docs, I cross-referenced github.com/kagenti/kagenti and the Red Hat Emerging Technologies blog. Found two real inaccuracies (README "kagenti LangGraph agents" phrasing; stale namespace topology in both kagenti-integration/architecture.md and llamastack-integration/architecture.md) and one "likely drift" (specific version pin + AutoGen/Marvin frameworks not in current sources). The user's decision to "drop the version pin and trim the framework list" was the right honest call.

- **Recursive retro saved for later**. Six retros today means the next `/retro --review-patterns` run will be long but valuable. Today's retros alone cover: mcp fixes wave 1-4, cleanup pivot, RBAC enforcement, demo scenarios, BFF walker tests, session focus vector #58, and this one. Strong signal that the project's retro cadence is working.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| **MemoryHub embedding service 413 errors on long memory content.** Hit twice in this session when trying to save durable learning memories — had to trim content significantly both times. Probably a hard limit on the vLLM embedding service (all-MiniLM-L6-v2 has a max sequence length around 256-512 tokens, and long memories exceed it). Not THIS session's bug, but a recurring pattern across recent sessions. | **Watch** — Worth investigating. Either (a) the MCP server's `write_memory` tool should chunk long content before embedding and store the first chunk's vector, (b) the embedding service should truncate server-side with a warning, or (c) memory content length should be enforced at write time with a clear error. Right now it's a silent 413 that the caller has to recover from by trimming. Not filing as an issue yet — defer until it has a clear design. |
| **`memoryhub-ui/deploy/deploy.sh` pipeline drift went unnoticed for days.** The Containerfile read from `memoryhub/` while the build script staged to `memoryhub-core/`. The dashboard pod that was running was from a build that succeeded under different conditions; any rebuild would have failed silently. Caught during #55 only because it was the first UI content change in a while. | **Fixed in commit `b89b7eb`** (build pipeline fix folded into the #55 rename). |
| **memoryhub-ui deploy lacks `oc rollout restart` + pins digest in Deployment spec.** Two gotchas that required manual intervention to take effect. Not a #55 regression, pre-existing. | **Filed as #83** with labels `type:bug` + `subsystem:ui`, in Backlog. Includes reference to the working `memory-hub-mcp/deploy/deploy.sh` pattern and two implementation options (imagestream tag + `imagePullPolicy: Always` recommended). |
| **`.claude/skills/issue-tracker.md` has a pre-existing uncommitted edit (adding `subsystem:auth` label) that I never resolved.** It showed as `M` in git status throughout the session across multiple commits. I left it alone per the "don't bundle unrelated changes" rule but never asked what it was. | **Process gap** — should have asked the user once and either committed with permission or understood why it was dirty (possibly a hook that modifies the file on each run but never commits, which would be a minor settings cleanup). Not filing as an issue; this is a "ask once next session" item. |
| **Three pre-existing untracked docs directories** (`docs/auth/`, `docs/identity-model/`, `demos/scenarios/`) have been in git status since session start and stayed untracked the whole session. They're presumably work-in-progress from other sessions. Clutter every `git status` output. | **Process gap** — should have asked what they are. Either they need to be tracked (they're real work) or gitignored (they're local drafts). Living in the untracked limbo is noise. Not filing as an issue; defer to next session. |
| **No integration test coverage for `search_memories_with_focus`** — the #58 retro action item. Would have caught the numpy.float32 regression and would catch any future focus-path regressions against real pgvector. Not touched this session. | **Carry-forward from #58 retro** — still opportunistic, not blocking. Will land when someone next touches `services/memory.py` focus code. |
| **Retro directory name is long.** `2026-04-07_concept-close-doc-refresh-and-55` is 48 chars. Prior retros are shorter (`2026-04-07_session-focus-vector-58`, `2026-04-07_rbac-enforcement`). Mine is closer to three-concepts-in-one because the session genuinely covered three concepts. Not a real gap; just noting the length for future retros. | **Accept** — the session was big enough to warrant the long name. If it had been only Layer 3, the retro would be `2026-04-07_layer-3-ergonomics`. The scope creep naturally forces the longer name. |

## Action Items

Immediate (this session):
- [x] #83 filed for memoryhub-ui deploy script (done, in Backlog).
- [x] #55 deployed and verified (done — both pods on new images, mcp-test-mcp focus path confirmed, BFF healthz confirmed).
- [ ] Update `NEXT_SESSION.md` for Valkey + #61/#62 kickoff (next step after this retro).

Carry-forward (next session or later):
- [ ] Ask about `.claude/skills/issue-tracker.md` modification.
- [ ] Decide what to do with `docs/auth/`, `docs/identity-model/`, `demos/scenarios/` (track or gitignore).
- [ ] Add `search_memories_with_focus` integration tests to `tests/integration/test_pgvector.py` (carry-forward from #58 retro).
- [ ] Re-benchmark NEW-1 on real production memories once corpus volume is meaningful (carry-forward from #58 retro).
- [ ] `/retro --review-patterns` run soon — 17 prior retros is enough signal to consolidate.
- [ ] Investigate the MemoryHub embedding service 413 limit pattern; decide whether to fix server-side truncation or enforce write-time length limits.

## Patterns

**New pattern — Scope expansion within a session is OK when the work is ready and the user explicitly pre-authorizes.** This session started as "land Layer 3" and grew to "land Layer 3 + full doc refresh + #55 + CONTRIBUTING + kagenti accuracy + template cruft + two production deploys + #83 filed." Every expansion was user-initiated ("are the docs up to date?" "what about Makefile + pyproject?" "is kagenti accurate?") and every one landed cleanly. The pattern works because: (1) the user is engaged and pre-authorizes each expansion, (2) the work is genuinely ready (design exists, mechanical execution is clear), (3) the session has a natural "wrap up" point that forces closure. Contrast this with open-ended scope creep (no user check-in, unclear design, no natural stopping point) which is the thing to avoid.

**New pattern — Post-deploy mcp-test-mcp verification is the ONLY thing that caught the memoryhub-ui deploy regression.** The build succeeded. The deploy script exited 0. The pod was running. Healthz returned 200. Everything LOOKED green. But the running pod was on the 23-hour-old image because the deploy script silently doesn't trigger a rollout. The only way I noticed was `oc get deploy ... -o jsonpath='{.spec.template.spec.containers[0].image}'` and comparing the digest against the baseline. This is the #58 retro's "verify-on-every-deploy via mcp-test-mcp" lesson generalized: **a clean exit from the deploy script is not proof that the new code is running**. Always diff the image digest post-deploy.

**New pattern — Build pipeline drift is the silent killer.** The memoryhub-ui Containerfile vs build-context.sh mismatch had been there for days (possibly longer). Git blame would show they drifted at different times. The current running pod was from a build that succeeded before the drift happened. Any rebuild after would fail. The lesson: when two files reference the same artifact by name (`memoryhub/` vs `memoryhub-core/`), grep across the build pipeline to confirm they agree, not just compile-or-deploy to confirm they work.

**Confirmed pattern — Same-commit consumer audit catches structural facts, not just bugs.** Ran it multiple times this session for the Layer 3 changes, the #55 rename, and the kagenti accuracy fixes. Zero bugs found (the audit was negative each time), but the audit habit produced structural knowledge: confirmed that memoryhub-auth is fully self-contained and doesn't import the server-side library (relevant to #55 scope — it was the reason auth didn't need a rebuild). The habit is paying dividends beyond its original purpose.

**Confirmed pattern — "Save memories before deploy" held again.** The MCP session in this conversation was already invalidated from the #58 session's deploy at the start of this conversation (`register_session` returned `Session not found`). I had to use mcp-test-mcp to open a fresh connection to write the post-deploy learning memory. Pattern works but the failure mode is subtle — the in-conversation MCP tools keep returning `Session not found` even after a fresh deploy because the old session context is still attached to the old conversation. Working around it via mcp-test-mcp is fine but adds friction. Long-term fix is probably in FastMCP's session lifecycle, not memory-hub.

**Confirmed pattern — Use the project-local `/deploy-mcp` slash command, not the template default.** Per `feedback_mcp_deploy_customizations.md`. Followed exactly this session: read `memory-hub-mcp/.claude/commands/deploy-mcp.md` first, captured the baseline pod name, delegated the build to `terminal-worker` with the exact prompt from the slash command, verified the new pod differed from baseline, ran mcp-test-mcp end-to-end verification. Zero drift from the documented flow.

**Start:**
- Asking once about pre-existing modified-but-not-mine files in git status at session open. Either commit them with permission or understand why they're dirty. Don't just leave them in limbo.
- Running `/retro --review-patterns` periodically — 17 prior retros is enough signal that recurring themes deserve consolidation.
- Filing follow-up issues at the moment the gotcha is discovered, not at the end of the session. I did file #83 this session but the timing was "after the deploy succeeded" rather than "the moment the gotcha became clear." Earlier filing means the issue body has fresher context.

**Stop:**
- Treating "the UI deploy script exits 0" as sufficient evidence of a successful UI deploy. The script's definition of success (build completed) is not the same as the user's definition (new code is running). Always diff the image digest against the baseline post-deploy for ANY deploy, not just the MCP server.

**Continue:**
- Announce-and-proceed within agreed scope; pause only on genuine forks.
- Pre-authorizing scope expansions explicitly before executing them.
- mcp-test-mcp post-deploy verification on EVERY deploy, not just ones where I expect problems.
- Same-commit consumer audit on every shape change, even when the change is "just a rename."
- Using WebSearch to verify external claims (kagenti accuracy) rather than trusting what's in the existing docs.
- Writing retros at session close — even for long sessions that cover multiple concepts. The retro is the place where patterns become visible.
