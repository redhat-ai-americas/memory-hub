# Retrospective: Contradiction Reports Table + Backlog Grooming

**Date:** 2026-04-05
**Effort:** Persistent contradiction tracking, issue housekeeping, cluster deployment
**Issues:** #20 (closed), #23 (closed), #9 (closed — descoped), #25 (created), #26 (created), #27 (created)
**Commits:** bd25940, b12c2be

## What We Set Out To Do

Three things: implement #20 (move contradiction tracking from metadata JSON to a dedicated table), create tracking issues for future agent integration work (CLI, SDK, LlamaStack), and descope #9 (operator CRD — replaced by RHOAI dashboard integration).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Clean cut instead of dual-write for contradiction migration | Good decision | The metadata JSON approach was a prototype. Dual-writing adds complexity for no benefit — no consumer reads the old format. |
| Added Python-side `default` values to model alongside `server_default` | Bug fix | `server_default=text("uuid_generate_v4()")` and `server_default=text("false")` are PostgreSQL-only. SQLite tests failed without Python-side defaults. |
| Added `reporter` parameter to service function | Scope addition | The issue spec included a `reporter` column but the original service function didn't accept one. Natural addition — sourced from authenticated session identity. |
| Redeployment prompted by user, not planned | Missed step | Implementation was committed but not deployed. User caught this. |

## What Went Well

- **Plan-then-implement pattern.** The schema and approach were discussed and approved before any code was written. No wasted work, no rework.
- **Sub-agent delegation worked cleanly.** Model + migration, service update, MCP tool update, and test updates were parallelized across sub-agents. Review sub-agent confirmed consistency.
- **End-to-end cluster verification.** Used mcp-test-mcp to register a session, write a memory, report a contradiction, then queried the database directly to confirm the row landed with correct `reporter` and `resolved` values.
- **Issue housekeeping was efficient.** Three future-phase issues (#25, #26, #27) created with proper design doc references and project board placement in one batch. New `subsystem:client` label groups them.
- **Storage design doc updated in the same session.** #23 closed alongside #20 — the implementation and its documentation shipped together.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Forgot to deploy after committing | Minor | User caught it. Added to patterns below. |
| No `resolve_contradiction` service function yet | Accept for now | The `resolved` and `resolved_at` columns exist but there's no service function to set them. The dashboard will need this — can be added when building Panel 5. |
| Old metadata contradictions not migrated | Accept | Any contradictions stored in `metadata_["contradictions"]` before this change remain as orphaned JSON. No production data exists yet so this is academic. |
| #7 and #13 still overlap | Minor | Both are governance/RBAC design issues. Should be merged before starting design work. |

## Action Items

- [x] Close #20 and #23
- [x] Descope #9
- [x] Create #25, #26, #27 for agent integration work
- [ ] Merge #7 and #13 before starting RBAC design
- [ ] Add `resolve_contradiction` service function when building dashboard Panel 5

## Patterns

**Start:**
- Deploying and verifying on the cluster as part of the implementation workflow, not as an afterthought. This session, the user had to remind us. Make it a standard step: implement → test locally → deploy → verify on cluster.

**Stop:**
- Nothing new this session.

**Continue:**
- Discussing the plan before implementing. The clean-cut vs. dual-write decision was made upfront.
- Review sub-agents after implementation.
- Live-verifying against the cluster with mcp-test-mcp + direct database queries.
- Closing design doc issues alongside implementation issues — ship code and docs together.
