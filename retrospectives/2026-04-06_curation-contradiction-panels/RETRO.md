# Retrospective: Curation Rules & Contradiction Log Panels

**Date:** 2026-04-06
**Effort:** Add Panel 4 (Curation Rules) and Panel 5 (Contradiction Log) to MemoryHub dashboard
**Issues:** #19 (dashboard), #40 (rule versioning — filed), #41 (event logging — filed), #42 (memory deletion — filed)
**Commits:** f8348fc, bb96009
**Builds:** 24–31 (8 deployments)

## What We Set Out To Do

Session scope doc defined 5 implementation steps: BFF Pydantic schemas, BFF routes (8 endpoints), frontend types + API client, two React panel components (CurationRules, ContradictionLog), wire into App.tsx, deploy and verify. This completes 6 of 7 planned dashboard panels.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Rule detail modal with click-to-view | Good pivot | Table truncates useful fields; user requested detail view |
| Auto-generated rule summaries (`describeRule()`) | Good pivot | Rules are opaque without plain-English explanation of trigger+tier+action |
| Config explanations for pattern sets (`describeConfig()`) | Good pivot | `{"pattern_set": "secrets"}` is meaningless without listing what patterns it scans for |
| Panel descriptions on all pages | Good pivot | User noticed titles were insufficient context |
| Masthead dark background fix | Good pivot | White-on-grey text invisible in PF6 light mode |
| 4 deploy cycles on responsive layout (builds 28–31) | Scope creep | Tried to fix PF6 sidebar overlay at narrow widths; turned out to be framework-level breakpoint behavior |
| Rule editing deferred | Scope deferral | Needs version/previous_version_id/edited_by columns first — filed as #40 |

## What Went Well

- Parallel sub-agent pattern: backend + frontend types built simultaneously, then two panel components in parallel, then review agent in parallel with TypeScript build check
- All 8 BFF endpoints verified with real data (`oc exec curl`) before declaring done
- `describeRule()` and `describeConfig()` are pure string template lookups — no LLM, fully deterministic, easy to extend
- 3 follow-up issues filed inline during session (#40, #41, #42) — backlog stays current
- Build context preparation is now muscle memory: temp dir, physical copies, strip .venv/node_modules, `oc start-build --from-dir`

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| No tests for 8 new BFF routes | Follow-up | Backend route tests needed; #36 covers frontend |
| 4 wasted deploys on responsive layout | Process | Should have checked PF6 Page docs before iterating; sidebar overlay at `xl` breakpoint is by-design |
| PF6 CSS variable `--pf-v6-global--BackgroundColor--dark-100` doesn't exist | Fixed | Used hardcoded `#1b1d21`; lesson: verify PF6 CSS vars exist before using them |
| `handleNavigateToMemory` doesn't highlight the target node in the graph | Accept | Navigates to graph panel but no node selection; noted in code comment |
| No frontend component tests (recurring from dashboard retro) | Follow-up | #36 still open |

## Action Items

- [ ] Backend route tests for `/api/rules/*` and `/api/contradictions/*` endpoints
- [ ] #40 — Curation rule versioning and edit tracking
- [ ] #41 — Structured event logging and memory usage tracking
- [ ] #42 — Memory deletion (MCP tool + dashboard UI)
- [ ] #36 — Frontend component tests

## Patterns

**Recurring (2nd occurrence):** No frontend tests. Dashboard retro flagged this; still not addressed. #36 remains open.

**Recurring (2nd occurrence):** Multiple deploy cycles for UI polish. Dashboard retro had similar iteration count for graph layout. Root cause: iterating on visual changes without local preview is expensive (~3 min per build cycle). A local dev server with hot reload would eliminate this.

**Start:** Check PatternFly documentation before attempting CSS/layout workarounds. PF6 has intentional responsive breakpoints that shouldn't be fought.

**Stop:** Guessing PF6 CSS variable names. Verify they exist in `node_modules/@patternfly` before using them.

**Continue:** Parallel sub-agent pattern for independent work streams. Filing issues immediately when scope items are deferred. Verifying endpoints with `oc exec curl` before declaring done. Auto-generating human-readable descriptions from structured data (describeRule pattern).
