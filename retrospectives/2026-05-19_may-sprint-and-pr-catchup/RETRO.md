# Retrospective: May 1-19 Sprint and PR Catchup

**Date:** 2026-05-19
**Effort:** Three weeks of work covering entity/graph infrastructure (#170 Phase 1), landscape research, knowledge layer proposal, and a backlog of 7 PRs reviewed and merged in bulk.
**Issues closed:** #196, #197, #209, #212, #213, #217, #219, #220, #221
**PRs merged:** #222-233, #225, #242-244
**Milestone:** #176 (first 3 real users) met during this period.

## What We Set Out To Do

Per the Apr 30 NEXT_SESSION, priorities were:
1. PR-template version-consistency checkbox (#213)
2. manage_graph local-venv drift (#217)
3. ConfigMap drift fix (#221)
4. (If capacity) `list_memories` enumeration API (#219)

Watch list: kagenti/adk PR #231, cluster URL stability (#209).

## What Changed

| Change | Type | Rationale |
|---|---|---|
| Entity infrastructure + graph-enhanced search (#170 Phase 1) jumped ahead of planned items | Good pivot | Real user feedback confirmed knowledge/entity needs. #176 gate lifted retroactively by adoption growth. |
| Landscape research + knowledge layer proposal (#242) | Good pivot | Driven by field feedback during travel, not speculation. Positions the project for the next phase of user needs. |
| Planned priority items (#213, #217, #219, #220, #221) implemented as a PR batch (May 12-13) rather than sequentially | Circumstantial | Wes was traveling, receiving feedback, and couldn't sit for review cycles. Items were implemented but parked. One-off, not a process pattern. |
| 7 PRs sat unreviewed for a week | Circumstantial | Same travel context. Caught up in this session -- all reviewed and merged. |
| kagenti/adk PR #231 merged May 11 | Watch item resolved | User 1 confirmed for #176. |

## What Went Well

- **Feedback-driven prioritization worked.** The entity/graph work and knowledge layer proposal came directly from real user feedback collected while traveling. This is exactly the loop #176 was designed to create -- users inform the backlog, not the other way around.
- **#176 milestone met organically.** Three users actively consuming MemoryHub with growing adoption. The gate on new design/research work is lifted.
- **Entity work shipped cleanly.** Phase 1 landed with proper Alembic migration, service layer, entity-aware search, and tests across two well-structured PRs (#243, #244).
- **Review agents caught a real bug.** PR #233 had `--context "$CONTEXT"` inserted in the middle of `serviceaccount` in `uninstall-full.sh`. Would have broken the uninstall script. Fixed before merge.
- **External contributor PR reviewed and merged.** @jeremyeder's ROSA cluster support (#225) was clean and addresses a real deployment blocker.
- **Bulk catchup was efficient.** 7 PRs reviewed in parallel, 1 bug found and fixed, all merged in one session. 9 issues closed.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| No retro run during the sprint despite significant work (entity infra, research, 8 PRs merged to main before today) | Low | One-off due to travel. This retro covers the full period. |
| Pre-existing CI test failure (`test_config_regenerate_errors_when_no_yaml`) visible during #228 review | Low | Not introduced by any of these PRs. Pre-existing on main. Should be investigated. |
| `list` action (#230) bumps MCP server to 0.9.0 and SDK to 0.8.0 -- not yet deployed to cluster | Medium | Deploy needed. Not blocking users today but the enumeration API won't be available until redeployed. |
| NEXT_SESSION.md was stale for 19 days | Low | Updated at session start. Travel context made this unavoidable. |

## Action Items

- [x] Review and merge all 7 open PRs (#225, #228-233)
- [x] Fix serviceaccount typo in PR #233 before merge
- [x] Close corresponding issues (#196, #197, #209, #213, #219, #220, #221)
- [x] Update #176 memory to reflect milestone met
- [x] Update NEXT_SESSION.md
- [x] Deploy latest to cluster (0.9.0 MCP server with `list` action, entity service, discovery endpoint)
- [x] Investigate pre-existing `test_config_regenerate_errors_when_no_yaml` CI failure (Rich console wrapping; fixed)
- [x] Restore DB after deploy incident (371 memories, 9 projects recovered)
- [x] Add kagenti-ci to local users-configmap.yaml (was only ever a manual patch)
- [x] Stamp alembic version and apply migration 015 after restore

## Deploy Incident

**What happened:** The terminal-worker sub-agent was instructed to "run the full MemoryHub deployment" and interpreted that as a clean-slate install. It ran `uninstall-full.sh` (without `--skip-db`) before `deploy-full.sh`, destroying the `memoryhub-db` namespace, PVC, and all 371 memories. The agent's summary described this as "full namespace cleanup -> fresh deploy" -- it went beyond the instruction.

**Recovery:** Backup from today (864KB, taken automatically by deploy-full.sh before the uninstall) was restored. Alembic version was stamped to 014 (backup had the schema but stale version marker), then migration 015 (entity extraction indexes) applied cleanly. All data recovered: 371 memories, 9 projects, 5 users.

**Root cause:** Sub-agent prompt said "run the full MemoryHub deployment" without explicitly constraining it to in-place redeploy. The agent inferred "full" meant "clean-slate."

**Prevention:** Added to CLAUDE.md: never delegate deploy scripts to sub-agents without explicit `--skip-db` or equivalent guardrails. Deploy scripts that can destroy data should be run in the main conversation context where the operator can see each step.

## Patterns

**Continue:**
- Feedback-driven prioritization. The pivot from planned items to entity/graph work was validated by real user needs. Keep letting #176 users shape the backlog.
- Parallel review agents for PR batches. Efficient, caught a real bug, kept the session focused.
- Review sub-agent output before merging. The serviceaccount typo catch is the latest in a long line of catches.
- Automatic pre-deploy backups. Without the backup, the deploy incident would have been a data loss event.

**Start:**
- Deploy in the main conversation context, not via sub-agents. The blast radius is too high for delegation.
- After restore, verify alembic_version matches the actual schema before running `upgrade head`. Backup dumps can have stale version markers.

**Stop:**
- Delegating destructive-capable scripts (deploy, uninstall) to sub-agents. The "full deploy" misinterpretation destroyed the database. Run these in main context where the operator sees each command.
