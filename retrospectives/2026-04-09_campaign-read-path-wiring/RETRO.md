# Retrospective: Campaign Read-Path Wiring

**Date:** 2026-04-09
**Effort:** Wire campaign_ids into all read-path MCP tools so campaign-scoped memories don't 403 on direct lookup
**Issues:** #162 (closed), #47 (already closed before session), #164 (filed as follow-up)
**Commits:** `3e3f78c` (code), `8657ea4` (NEXT_SESSION)

## What We Set Out To Do

Close two issues: #162 (wire campaign_ids into 9 read-path tools) and #47 (get_similar_memories returns empty due to broken RBAC filter). The plan described a mechanical pattern — same change in 9 places — using write_memory and update_memory as reference implementations. Additionally, get the MemoryHub deployment into working status.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #47 was already closed (April 7) | Scope reduction | issue-sanity-check.sh caught it immediately; zero time wasted |
| update_memory already correct — 8 tools, not 9 | Scope reduction | Code review showed it already had campaign_ids for authorize_write and doesn't call authorize_read |
| DB stuck at migration 008, not 010 as briefing stated | Unplanned fix | MemoryHub search_memory failed with "column domains does not exist"; port-forwarded and ran alembic upgrade head |
| Migrations don't auto-run on server startup | Corrected assumption | Briefing said they do; no alembic runner in MCP server code. Manual port-forward + alembic required. |
| MCP server redeployment needed | Expected | Both for migration fix and to ship the #162 code changes |
| SDK parameter gap discovered | Filed as #164 | SDK typed wrappers don't expose project_id or domains; campaign features inaccessible to SDK consumers |

## What Went Well

- **Pattern-first execution.** Read the write_memory reference, applied the same block to 8 tools. Zero rework, review sub-agent found only one unused import.
- **issue-sanity-check.sh continues to pay off.** Caught #47 as already closed before any work started. This is the tool's 4th consecutive session of catching stale state.
- **Early detection of DB drift.** The MemoryHub search_memory call at session start surfaced the missing migrations immediately, not during a demo or in the next session.
- **Data-driven test file.** Parametrized signature test covers all 8 tools in one shot; per-tool tests share fixtures. 24 tests, single file, easy to maintain.
- **Clean deploy pipeline.** Preflight check, build, rollout, digest verification, mcp-test-mcp — all green on first attempt. 15/15 tools confirmed with project_id in schemas.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Paste context had 3 factual errors (DB state, #47 status, migration auto-run) | Low | All caught in-session. Recurring pattern — 4th retro flagging stale briefing data. |
| No integration test against real PostgreSQL for campaign read path | Medium | Tests mock `get_campaigns_for_project`; if the SQL is wrong, mocks won't catch it. Tracked informally; #95 covers the broader integration test gap. |
| SDK/CLI can't pass project_id or domains to any tool | Medium | Filed as #164; next session's work |
| get_relationships provenance chain with campaign nodes has no test | Low | Code is correct (reuses same campaign_ids); coverage gap noted in review but not blocking |

## Action Items

- [x] #162 closed and merged
- [x] DB migrations 009+010 applied
- [x] MCP server redeployed and verified
- [ ] #164 — SDK + CLI campaign/domain parameter catch-up (Backlog, next session)
- [ ] #95 — PostgreSQL integration test target (recurring gap, still in Backlog)

## Patterns

**Recurring (4th occurrence):** Paste context / session briefings contain stale state. issue-sanity-check.sh mitigates for issues, but DB migration state, deployment status, and "what auto-runs" assumptions aren't checked. Consider adding a "verify deployment state" step to session startup alongside the issue sanity checks.

**Continue:** Pattern-first mechanical changes with review sub-agent. The workflow (read reference → apply N times → sub-agent review → fix nits → test → deploy) is efficient and reliable for this class of work.

**Continue:** MemoryHub MCP registration at session start as an early smoke test. The search_memory failure at session start was the canary that surfaced the migration drift.
