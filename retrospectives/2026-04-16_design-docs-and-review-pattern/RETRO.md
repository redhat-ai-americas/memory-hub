# Retrospective: Design Docs & Review Pattern Restoration

**Date:** 2026-04-16
**Effort:** Draft 6 needs-design design docs + agent ergonomics consult + RHOAI tile investigation + review pass + fixes
**Issues:** #166, #109, #168, #169, #170, #171, #102
**Commits:** 8bc7856, c8fc3c6

## What We Set Out To Do

Per yesterday's NEXT_SESSION.md: review and flesh out the six design docs tagged `needs-design` or `type:design` — #166 (project governance), #109 (UI design), #168 (conversation persistence), #169 (context compaction), #170 (graph-enhanced memory), #171 (knowledge compilation). Close #102 (already fixed by #63).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Added unplanned agent-ergonomics consult for a sibling Claude Code session building the demo-chat-agent | Scope addition | Time-sensitive demo prep; the integration pattern (register_session as a tool call, not HTTP header) wasn't documented anywhere and the other agent was stuck on it |
| Added unplanned Red Hat managed indicator investigation | Scope addition | User context: presenting to the Red Hat managed app gatekeepers; current CR claims a category we haven't earned. Investigation revealed Self-managed enablement requires per-app validators hardcoded in odh-dashboard source — not fixable via CR alone |
| Skipped implement-then-review pattern on the initial design doc drafts | Process gap | Shipped 6 design docs (~3,000 lines) in commit 8bc7856 without review sub-agents. Caught in the retro; review pass ran and found 2 critical + ~15 minor issues. Fixed in c8fc3c6 |
| Red Hat managed experiment ran before reading odh-dashboard source | Process gap | Jumped to live cluster experimentation to see what broke. Reverted cleanly because backups were in place, but we could have known the answer without disturbing the live tile |

## What Went Well

- **Parallel drafting with dependency-aware sequencing.** #166/#109 solo, then #168/#170/#169 in parallel (independent), then #171 after those landed (because it composes them). Four-wave structure kept context small per sub-agent.
- **Sub-agent drafts were well-grounded in codebase state.** Each doc referenced real model names, file paths, existing relationship types, curation patterns. The review pass confirmed most factual claims held up — the issues found were narrow (wrong function suffix, panel order swap, type mismatch) rather than structural.
- **#166 correctly built on shipped state.** The projects table already exists via migration 012; the doc built on that rather than re-designing from the issue body's pre-012 starting point.
- **Red Hat managed experiment had a clean revert path.** Backed up state before changing anything, reverted within seconds when the tile disabled. Zero demo impact.
- **Agent ergonomics consult was precise.** Caught the `register_session`-as-tool-call vs HTTP-header nuance and proposed a reusable `auth.type: register_session` abstraction for future MCP servers with similar shim auth.
- **Review-pass discipline restored.** After catching the "no review sub-agents on the 6 design docs" gap in the retro itself, ran the review and found real issues before they propagated into implementation. The two critical items (#170 constraint migration, #169 content_ref collision) would have caused runtime failures or design ambiguity during implementation.
- **Critical design fixes resolved in-session, not deferred.** Both implementation-blocking issues were resolved directly in the docs (partial unique index for #170; archive key on compaction_events for #169) rather than filed as follow-up issues.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| 6 design docs (~3,000 lines) landed without review sub-agents | Medium | Fixed in-session via review pass + c8fc3c6. Pattern regression noted. |
| RHOAI dashboard source not read before live cluster experiment | Low | Backup saved us. Next session: read odh-dashboard source first, then decide on strategy |
| "Validation is hardcoded per-app in dashboard source" asserted without reading source | Medium | Captured in NEXT_SESSION.md as "confirm by reading odh-dashboard source." Whole Path 1 vs Path 2 recommendation for Red Hat managed rests on this theory being correct |
| CLAUDE.md modified pre-session, still untracked | Low | Same as past two retros. Worth running `git diff CLAUDE.md` at the start of the next session and committing or reverting |
| No tests run this session | Accept | Docs-only + cluster config + reverted experiment. Not applicable. |

## Action Items

- [ ] Read odh-dashboard source (github.com/opendatahub-io/odh-dashboard) next session to confirm the "validation is hardcoded per-app" theory before committing to Path 1 (submit upstream PR) or Path 2 (bundle into RHOAI operator)
- [ ] Resolve the pre-session CLAUDE.md modification (commit or revert) at the start of the next session
- [ ] Consider updating `/retro` or a session-start checklist to include "did the work this session include sub-agent-drafted output that hasn't been reviewed?" — this pattern has now regressed twice

## Patterns

**Start:**
- Read authoritative source (e.g., upstream dashboard source code, operator CRD schemas) before running live experiments that affect shared state. Fast, safe, and gives more confident conclusions than experimentation.
- When a review reveals critical design issues, resolve them in the design doc itself rather than filing follow-up issues. Filing "resolve the content_ref collision before implementation" as an issue just defers the work; the doc is the artifact the implementer reads.

**Stop:**
- Shipping sub-agent-drafted output without a review pass. This is the fifth consecutive retro to confirm "review sub-agents catch real issues." It regressed this session and was caught only because the retro surfaced it explicitly. Next session: add a review pass as part of the design-doc drafting workflow, not as a retro afterthought.

**Continue:**
- Review sub-agents after implementation — restored this session after skipping initially; caught 2 critical + ~15 minor issues
- Parallel sub-agent drafting with dependency-aware sequencing (solo → parallel wave → serial final)
- Clean revert paths for live cluster experiments (backup first, apply, verify, revert if needed)
- Resolving design issues in-session rather than deferring to follow-up work
- Close stale issues proactively (#102 reconfirmed closed this session, previously-flagged pattern applied)
