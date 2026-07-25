# Next Session: Execute Backlog Loops

**Context:** Backlog refinement completed 2026-06-30. All 9 sections reviewed, design sessions done. 47 open issues reduced to 30 (closed #100, #276, #99; deferred #275, #71, #72, #87 to priority:future). Plan at `planning/backlog-refinement-2026-06.md`, benchmark design at `planning/system-benchmarks.md`.

## What happened

Full backlog refinement pass over all 50 open issues. Every issue categorized as loop-ready, blocked, deferred, or needing design. All design sessions completed except #45 (admin content moderation -- missing design doc). Key structural changes:

- #292 (pattern surfacing) promoted out of curation agents epic as standalone
- #286 (shared agent framework) promoted from "needs design session" to loop-ready -- design doc already resolves all open questions
- #104 (session persistence) same -- Fork C recommendation confirmed
- #100 folded into #274; #276 closed (children cover it)
- Demo curation patterns (#89-92) blocked on fips-agents team capability + demo script freshness audit

## Loop-ready issues (no prerequisites, pick any)

These can run as autonomous loops right now. Sorted by estimated bang-for-buck:

| # | Issue | Exit predicate | Est. size |
|---|-------|---------------|-----------|
| #67 | Audit logging stub | `audit.py` created, all tools call `record_event`, JSON log lines verified | Small |
| #274 | Cross-encoder cost/benefit benchmark | Optimal candidate set size identified, recommendation in results JSON | Medium |
| #66 | actor_id/driver_id plumbing | All tools propagate actor_id/driver_id, tests pass | Medium |
| #282 | relevant_until schema + temporal classifier | Migration applied, classifier tags at write time, tests pass | Medium |
| #271 | Retrieval at scale benchmark | All 3 scale tiers benchmarked, latency stable across 3 runs | Medium |
| #105 | Tenant-scope admin API | Admin API enforces tenant_id filter, cross-tenant returns 404, tests pass | Medium |
| #292 | Within-user pattern surfacing | Search annotates with pattern_signals when cluster detected, tests pass | Medium |
| #283 | Deploy Valkey to memoryhub-agents | Valkey pod running, queue keys accessible, manifests committed | Medium |
| #286 | Shared agent framework | Package installable, lifecycle works e2e with test agent, leader election tested | Large |
| #82 | LibreChat integration | OAuth client registered, librechat.yaml configured, 8-step verification passes | Medium |
| #104 | Session persistence (Phase 1) | Pod restart doesn't require re-register, push subscribers re-spawn lazily | Large |
| #45 | Admin content moderation | Status column migrated, 4 admin ops implemented, MCP tools exposed, tests pass | Large |

## Loop-ready after prerequisites

| # | Issue | Blocked on |
|---|-------|-----------|
| #284 | OBO authorization | #66 (actor_id/driver_id) |
| #64 | Project-scope membership | Not urgent, but loop-ready |
| #272 | Entity extraction benchmark | Manual: label 50-100 memories with ground-truth entities |
| #273 | Graph vs flat benchmark | Manual: design and label 50+ queries with expected results |

## Suggested first loop batch

Start with issues that are small, have clear exit predicates, and unblock other work:

1. **#67** (audit stub) -- Smallest, self-contained, no dependencies. Good warmup loop.
2. **#66** (actor_id/driver_id) -- Unblocks #284 (OBO auth), which unblocks curation agents.
3. **#274** (cross-encoder benchmark) -- Extends existing infrastructure, produces real data.

These three can run in parallel (independent). Together they'd clear the smallest issues and unblock the #284 dependency chain.

## Design docs to reference

- `planning/backlog-refinement-2026-06.md` -- Master plan with all decisions and progress log
- `planning/system-benchmarks.md` -- Benchmark framework design (section 1)
- `planning/autonomous-curation-agents.md` -- Curation agents epic design (section 4, esp. Section 13 for #286)
- `planning/session-persistence.md` -- Session persistence forks (section 8, #104)
- `docs/admin/content-moderation.md` -- Admin content moderation design (section 8, #45)
- `docs/identity-model/data-model.md` -- actor_id/driver_id design reference (section 2, #66)

## Still blocked

- Demo curation patterns (#89-92): waiting on fips-agents team capability + demo script freshness audit
- Agent implementations (#285, #287-289): waiting on #283 (Valkey) + #286 (framework) + #284 (OBO)
- UI work (#44, #106, #109, #125): all deferred, no active UI push planned
- ~~#45 (admin content moderation)~~: promoted to loop-ready (design doc found, open questions resolved)
- #69 (agent generation CLI): blocked on demos + #64
