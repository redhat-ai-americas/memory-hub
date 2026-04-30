# Retrospective: kagenti-ci cleanup and provisioning

**Date:** 2026-04-30
**Effort:** Land the #207 cleanup decision for kagenti-adk's E2E test memories. Discovered the underlying user wasn't even provisioned, so scope expanded from "decide" to "decide + provision + scope-with-invite_only + verify + coordinate with @JanPokorny on PR #231."
**Issues:** #207 (closed), #219 (filed for `list_memories` enumeration API)
**Commits:** `4f4bad0` (planning doc skeleton → decided)

## What We Set Out To Do

Decide a cleanup strategy for kagenti-ci's E2E test memories per #207. The
planning doc had three options (A/B/C); Option A (test-side cleanup) plus a
scoped project was the recommendation. @JanPokorny had already commented
agreeing with the project-scoping approach. Expectation going in was a
small session: pick the option, comment, close.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| Discovered `kagenti-ci` user wasn't provisioned at all on the live cluster. | Missed precondition | Issue body framed the work as "decide cleanup strategy" — assumed provisioning was already done. NEXT_SESSION cluster-state line claimed it was. Both wrong. Forced a 4-hour scope expansion. One-off issue-quality gap, not a process gap (per session retro discussion). |
| Verified `invite_only=true` enforcement before promising the boundary on #207 (B1). | Good pivot | Spawned an Explore agent to read `ensure_project_membership` before drafting the issue comment. Found default `invite_only=false` silently auto-enrolls writers — the flag is load-bearing. The decision comment would have been wrong without B1. |
| Swapped my freshly-generated `kagenti-ci` API key for the value Wes had already emailed @JanPokorny. | Good pivot | Caught by Wes asking "is this a different value?" before the PR comment posted. Avoided forcing @JanPokorny to rotate a working secret. |
| Recommended scope switch to `scope="project"` in the kagenti-adk example, not just acknowledged that user-scope works. | Good pivot | After reading the actual E2E test, realized the example writes `scope="user"` — the new `kagenti-tests` project would sit unused. Reframed the PR comment to actually close #207's intent. |
| First draft of the PR comment recommended `store.search("")` for cleanup enumeration. | Bug caught pre-publish | SDK check showed the server rejects empty queries (`search_memory.py:650-653`). Replaced with a capture-and-delete pattern. |
| Filed #219 for `memory(action="list")` enumeration API. | Scope deferral | Crashed-test orphan sweep has no clean idiom today. Worth its own issue, not bolted onto #207. |
| Direct commit to main with admin override (intentional). | Process choice | Doc-only commit; multi-dev prep is the long-term reason to keep main protected, not this change in particular. |

## What Went Well

- **"Pause for real forks" worked three times** — provisioning vs decision-only scope, scope choice for the kagenti-ci user, user-scope vs project-scope recommendation to @JanPokorny. Each pause caught a wrong-or-suboptimal default.
- **B1 verification before promising blast-radius bounding on #207.** The Explore agent's finding (`invite_only=true` is the only enforceable membership boundary today) drove the design and is now persisted in memory for any future "scoped CI/test/agent user" pattern.
- **Caught the API-key drift before the PR comment went out.** Asking "did you previously email Jan something?" was load-bearing — saved a pointless rotation request.
- **Drafted-then-revised PR comments before posting.** Both the (b) framing reveal and the SDK-rejects-empty-query catch happened during the draft phase, not after the comment was public.
- **Smoke-tested both rejection and happy paths on the live cluster.** Negative path (`dev-test` rejected) is what makes the "blast radius bounded" claim defensible.
- **Verify-render check on the PR comment** caught a HEREDOC-with-backticks markdown corruption before anyone saw the broken comment.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| Issue body buried the load-bearing problem (provision was a precondition, not a step). Burned ~30 min of session before realizing it. | Fix now (one-off) | Acknowledged as one-off issue-quality gap. No process change. |
| HEREDOC + triple-backticks ate the markdown on the first PR comment post. | Fix now | Patched live via `gh api -X PATCH`. Lesson: write the body to a file and use `gh ... -F body=@file` for anything with code fences. |
| `cluster-health-check.sh` verifies pod/route/image but not ConfigMap user list. NEXT_SESSION's "users currently provisioned" line drifted from reality and wasn't caught at session start. | Follow-up | Either extend `cluster-health-check.sh` to verify the ConfigMap user list against an expected set, OR drop that line from NEXT_SESSION entirely and treat user list as live-only state. |
| Runbook step 6 (`docs/runbooks/add-mcp-api-user.md`) says wrong key returns 401 on MCP `initialize`; smoke testing showed `initialize` doesn't gate on the key (auth happens at `register_session`). | Follow-up | Filed as separate issue. ~5 min doc-only fix. |
| `users-configmap.example.yaml` ships only 2 users; live cluster has 5. Fresh-deploy install template would silently drop kagenti-ci, rdwj-agent-1/2. The drift that caused #207's framing problem will recur on next install. | Follow-up | Filed as separate issue. Fails the IaC-reproducibility rule in CLAUDE.md. Three options proposed; pick one. |

## Action Items

- [x] Close #207 (done in `4f4bad0`)
- [x] File `list_memories` follow-up (#219)
- [x] Persist `invite_only=true` enforcement learning to MemoryHub (memory written 2026-04-30)
- [x] File runbook step 6 fix issue
- [x] File ConfigMap drift issue
- [ ] Pick approach for cluster-health-check ConfigMap-user check vs NEXT_SESSION trim — decide next session
- [ ] Watch PR kagenti/adk#231 for @JanPokorny's response to the recommended scope switch
