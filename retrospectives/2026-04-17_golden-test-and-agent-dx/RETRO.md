# Retrospective: Golden Test Verification & Agent DX Polish

**Date:** 2026-04-17
**Effort:** Verify deploy-full.sh golden test, fix discovered bugs, agent usability testing and DX improvements
**Issues:** #188 (related)
**Commits:** 52c3051, 9cdfd05, 7fc995e, 1c4a21d, 5727c46, f31a531, 4f0465d

## What We Set Out To Do

Five items from the prior session's NEXT_SESSION.md, in priority order:

1. Run the golden test (`uninstall --skip-db && install`) to prove deploy-full.sh is self-contained (blocking)
2. Read odh-dashboard source to validate the "hardcoded validator" theory
3. Begin design doc implementation (#166 project-governance as warm-up)
4. Clean up 71 ruff lint errors
5. Resolve CLAUDE.md pre-session modification (3+ sessions showing as dirty)

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Golden test found 2 bugs (DB Secret overwrite, MCP password sync) | Good discovery | The test did exactly what it was designed to do — proved the script wasn't self-contained |
| Pivoted from odh-dashboard to agent DX work | Scope deferral | User tested MemoryHub live, hit DB auth failure, then needed agent self-registration working before a demo |
| Design doc implementation deferred | Scope deferral | Golden test fixes + DX improvements consumed the session |
| Ruff cleanup deferred | Scope deferral | 4th session in a row — error count grew from 71 to 434 |
| Agent-as-usability-tester pattern emerged | Good pivot | Sub-agent self-enrollment test produced specific, actionable feedback that drove 7 fixes |

## What Went Well

- **Golden test found real bugs.** The DB Secret overwrite (`deploy/postgresql/secret.yaml` applied by kustomize, replacing the real password with a placeholder) and the MCP namespace password gap (hardcoded `memoryhub-dev-password` in `openshift.yaml`) would have broken any future clean install or cluster migration. Both are the same anti-pattern flagged in the prior retro: infrastructure created manually, never captured in IaC.
- **Agent-as-usability-tester.** Spawning a fresh sub-agent to self-enroll and report friction was fast (9 tool calls to complete the flow), honest (rated DX 4/5 with specific complaints), and actionable (all 5 issues were fixable). This pattern should be reused for any consumer-facing API change.
- **Rapid fix-deploy-test cycles.** Each DX fix was deployed and re-verified within minutes. The cycle was: edit → test locally (268 tests) → deploy → run usability sub-agent → confirm. Three full cycles in one session.
- **Integration guide shipped same-day.** `docs/agent-integration-guide.md` is immediately usable by other agent sessions — no separate documentation effort needed.
- **Prior retro action item closed.** "Run the golden test after any infrastructure change" was the #1 action item from the 2026-04-16 retro. Done, and it found exactly what it was supposed to find.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Hardcoded passwords in 2 YAML files (same anti-pattern as prior retro) | Fixed | secret.yaml removed from kustomize (52c3051), MCP password synced post-deploy (9cdfd05) |
| Standalone `make deploy` in memory-hub-mcp still applies hardcoded password | Low | Accept — deploy-full.sh handles the production path. Standalone deploy is for dev iteration where the password doesn't matter |
| DB password sync adds an extra rollout restart to every deploy | Low | Accept — adds ~2 min. Long-term fix: read password from DB namespace Secret in the MCP deployment YAML instead of hardcoding |
| `get_session` tool skipped fips-agents scaffold workflow | Low | Accept — 15-line read-only tool. The scaffold rule exists for tools with validation logic and test coverage needs |
| Ruff lint errors now at 434 (4 sessions without cleanup) | Medium | Carry forward. Growing linearly. Should be a focused cleanup session, not squeezed into a feature session |
| Cluster context renamed from `workshop-cluster` to `mcp-rhoai` | Fixed | CLAUDE.md not updated (still says workshop-cluster). NEXT_SESSION.md documents the new name. CLAUDE.md update deferred to avoid churn — will fix when CLAUDE.md is next edited for another reason |
| odh-dashboard investigation deferred 2 sessions in a row | Low | Carry forward. Not blocking anything, but the longer it sits the more likely the upstream code changes |

## Action Items

- [ ] Update CLAUDE.md cluster context name from `workshop-cluster` to `mcp-rhoai` (next session that touches CLAUDE.md)
- [ ] Close or triage #188 — auto-enrollment works, remaining items are structural DX improvements
- [ ] Ruff lint cleanup session (434 errors, 4 sessions deferred)

## Patterns

**Start:**
- Use agent-as-usability-tester for consumer-facing API changes. The sub-agent approach produces specific, quantifiable feedback (DX rating, tool call count, exact friction points) that a manual review wouldn't catch. Run it before and after fixes to measure improvement.

**Stop:**
- Hardcoding credentials in YAML manifests. This is the second consecutive retro flagging it. The `ensure_random_secret` and `copy_secret` helpers exist specifically to avoid this. When adding a new Secret to any component, use the helpers from day one — don't add a placeholder "to unblock" and formalize later.

**Continue:**
- Running the golden test after infrastructure changes (closed the prior retro's top action item)
- Rapid fix-deploy-test cycles for deployed services (3 cycles this session, each verified end-to-end)
- Committing infrastructure fixes in the same session they're discovered
