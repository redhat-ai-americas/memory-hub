# Retrospective: DX Backlog Close & Temporal Validity Prep

**Date:** 2026-04-17
**Effort:** Close DX backlog (#190, #166), prep #170 Phase 1 temporal validity, migration 013, exercise-tools verification
**Issues:** #190 (closed), #166 (closed), #170 (in progress)
**Commits:** 0c2aa8b, d8de465, 6948988, c117a01, 2498c86, 7c539eb

## What We Set Out To Do

Three priorities from NEXT_SESSION.md:
1. Redeploy MCP server (progressive discovery from last session)
2. Close DX backlog: #190 (session TTL) + #166 (project governance tools)
3. Start #170 Phase 1 (graph-enhanced retrieval)

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| 3 proposed tools consolidated into 1 `manage_project` | Good pivot | User read Anthropic's tool design article and asked "do we need 3 tools or 1?" — consolidation follows their guidance directly |
| Auto-extend on activity chosen over explicit renewal for TTL | Good design | Matches web session semantics, avoids agents needing renewal logic |
| #170 scoped to prep-only (temporal validity) this session | Scope deferral | Correct — graph-enhanced retrieval (collect_graph_neighbors + RRF) is 2-3 sessions of work |
| DB credential drift discovered during exercise-tools | Found gap | openshift.yaml had a stale password from a previous golden test; patched cluster Secret and reverted to REPLACE-ME placeholder |

## What Went Well

- **Verify-before-deploy discipline.** User asked "verify first" before redeploying — confirmed the progressive discovery build was not yet live, avoiding an unnecessary redeploy.
- **Review-then-fix cycle caught real bugs.** Sub-agent reviews found: (a) stale user data returned on expired sessions (#190), (b) no authorization on remove_member (#166). Both would have been exploitable in production.
- **Anthropic article drove a better design.** Reading the tool design guidance before implementing led to a fundamentally different (better) approach — one tool instead of six.
- **Exercise-tools caught the credential drift.** Running manage_project against the live server surfaced the DB password mismatch that unit tests couldn't detect.
- **Clean session close.** All tests passing (628), lint clean, docs updated, version bumped, everything pushed.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| DB credential drift (3rd retro flagging this family) | Fix now | Patched in 7c539eb — openshift.yaml now uses REPLACE-ME placeholder. deploy.sh preflight catches it. |
| openshift.yaml still stores DB password in a tracked file | Follow-up | deploy.sh should copy the Secret from memoryhub-db namespace like deploy-full.sh does, not rely on the manifest. |
| `add_project_member` returns `False` on duplicate but never raises — tool message says "already a member" but no way to distinguish from success programmatically | Accept | Good enough for agent UX; a dedicated status code would over-engineer it. |
| Migration 013 was committed without being applied for several commits | Accept | Explicitly tracked in NEXT_SESSION.md as step 0. Applied later in the same session before exercise-tools. |

## Action Items

- [ ] File issue for deploy.sh to copy DB Secret from memoryhub-db namespace instead of hardcoding in openshift.yaml (this is the 3rd retro flagging credential drift)

## Patterns

**Start:**
- Read relevant external design guidance (Anthropic article, RFCs) before implementing new tool surfaces. The tool consolidation decision this session produced a materially better design than the plan entering the session.

**Stop:**
- Storing real or stale DB passwords in tracked YAML manifests. This is the **third consecutive retro** flagging this family. The deploy.sh `copy_secret` pattern exists in deploy-full.sh but is not used in the per-component deploy scripts. Close this for real: file the issue (action item above), land it next session.

**Continue:**
- Sub-agent review after implementation — caught 2 security bugs this session.
- Exercise-tools against the live deployment as a final verification gate — caught credential drift that tests couldn't.
- Verify-before-deploy when picking up deferred work from a previous session.
