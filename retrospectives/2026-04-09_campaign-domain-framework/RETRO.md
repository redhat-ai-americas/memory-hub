# Retrospective: Campaign & Domain Framework MVP

**Date:** 2026-04-09
**Effort:** Phases 1-2 of the campaign & domain framework — cross-project knowledge sharing via campaign scope and domain-tagged retrieval boosting
**Issues:** #154 (umbrella), #155, #156, #157, #158, #159, #160, #161
**Commits:** `753d3d3`..`da5fcea` (8 commits, 19 files, +1,049 lines)

## What We Set Out To Do

Implement the MVP from `planning/campaign-domain-framework.md`: campaign as a new scope between project and organizational (with enrollment-based RBAC), and domains as crosscutting knowledge tags on memories (with retrieval boosting). The session plan defined a 6-step land order across schema, RBAC, tool layer, search, and CLI — all 7 sub-issues under umbrella #154.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Migration head was 008, not 007 as session notes stated | Corrected early | issue-sanity-check caught it; no wasted work |
| `_to_stub` was missing `domains` field | Bug caught during #158 | Would have caused domain info loss on stub degradation |
| `or_()` with no args deprecation warning | Fixed during #157 | Empty scope_conditions (campaign-only caller with no IDs) now returns None cleanly |
| Constraint name mismatch between migration 009 and campaign model | Caught in review | Would have caused Alembic autogenerate drift |
| `Campaign.status` used `default=` instead of `server_default=` | Caught in review | Would have caused Alembic autogenerate drift |
| Session-fallback test needed "campaign" in full tier list | Expected breakage | `ALL_TIERS` expansion is a known ripple; fixed in same PR |

No scope deferrals, no missed requirements, no architectural pivots.

## What Went Well

- **Linear execution of the land order.** 7 issues, 6 steps, zero blocked items. The dependency graph from the session plan was accurate.
- **issue-sanity-check used consistently.** Every issue got checked before work. Caught the migration head discrepancy early. This addresses the "stale issue state" gap identified in 4 of the last 5 retros.
- **Review workers caught real bugs.** The constraint name mismatch and `server_default` issue would have caused persistent Alembic drift. Sub-agent review is paying for itself.
- **Backward compatibility by design.** Every new parameter defaults to `None`; existing callers didn't change. All 458 pre-existing tests passed throughout.
- **Clean deploy.** Migrations 009+010 ran on startup, 15/15 tools verified via mcp-test-mcp, no manual intervention.
- **Test count grew 30 across the session** (227→236 core, 206→222 MCP, 27→32 CLI = 490 total).

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| No integration tests against PostgreSQL — SQLite patches approximate ARRAY and GIN behavior | Medium | Accept for now; tracked informally. The GIN index and `@>` operator are untested. |
| Per-ID tools (read_memory, get_memory_history, etc.) don't resolve campaign_ids — campaign-scoped memories will 403 on direct lookup | Medium | Known; tool-layer wiring for read-path tools deferred. File follow-up issue. |
| Domain boost in non-focus path is post-retrieval (Python); focus path uses RRF (SQL-adjacent). Behavior is consistent but mechanism differs. | Low | Accept — both paths produce correct results; the difference is an optimization detail. |
| No end-to-end test of campaign write → search → read flow across enrolled projects | Medium | Requires running PostgreSQL + the MCP server in test. Integration test infrastructure gap. |

## Action Items

- [x] File follow-up issue: wire `campaign_ids` into read-path tools — #162
- [ ] Update NEXT_SESSION.md with what shipped and what's next

## Patterns

**Continue:** issue-sanity-check before every issue. Sub-agent review after implementation. Linear land-order planning with explicit dependencies. Backward-compatible parameter additions.

**Continue:** Aggressive delegation with worktree isolation for parallel git work. Model-tier selection (Sonnet for implementation, Sonnet for review) keeps costs reasonable.

**Start:** Integration test infrastructure for campaign/domain features. The SQLite patching layer is load-bearing and growing — each new PostgreSQL-specific feature (ARRAY, GIN, Interval) adds another monkey-patch to conftest.
