# Retrospective: Bug Fix Sprint, Infra Hardening, and Retrieval Signal Problem

**Date:** 2026-04-20
**Effort:** Fix #194 (search filter bypass), close #192, implement #191 (backup/restore), fix live UI outage, close #165/#108, file #195
**Issues:** #194 (closed), #192 (closed), #191 (closed), #108 (closed), #165 (closed), #195 (filed)
**Commits:** ff279da, b1e0c95, 3e01405, d9058ff, 918bb9b

## What We Set Out To Do

Work three issues from the backlog in priority order: #194 (search_memory project_id filter bug), #192 (deploy.sh hardcoded DB Secret), #191 (PostgreSQL backup/restore lifecycle). Then quick wins #165 (CLI --version) and #108 (Weight tooltip).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #192 was already done — closed immediately | Scope reduction | Prior session (6b2b52b) already implemented it; the issue just wasn't closed |
| UI 500 outage discovered mid-session | Unplanned | Restarting UI pod to pick up fixed Secret revealed the RHOAI Endpoints fragility and a Secret key name mismatch (POSTGRES_* vs MEMORYHUB_DB_*) |
| Filed #195 (RHOAI Endpoints fragility) | Good discovery | The Endpoints pattern breaks on every pod restart — this is the 2nd time it's caused an outage |
| #165 was already done — closed immediately | Scope reduction | CLI already had --version callback |

## What Went Well

- **Root cause analysis on #194 was precise.** Traced the bug to `_backfill_compiled_entries` bypassing scope filters — the compilation epoch cache was inadvertently acting as a filter bypass. Fix was minimal (pass existing filters to the backfill query) and all 304 MCP tests stayed green.
- **UI outage diagnosed and resolved quickly.** DB connection refused → checked pod logs → traced to Secret key mismatch → fixed Secret on cluster, updated deploy-full.sh, redeployed. Total time from symptom to resolution was fast.
- **deploy-full.sh Secret key mismatch was a systemic bug, not a one-off.** The `copy_secret` helper copies raw keys; the UI's Pydantic config uses `env_prefix="MEMORYHUB_"`. This would have broken every fresh install. Fixed permanently.
- **Backup/restore scripts landed clean.** backup-db.sh, restore-db.sh, integration with uninstall (--no-backup) and deploy (--restore-from). Golden test now has a safety net.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| #195: RHOAI Endpoints break on every pod restart | Follow-up | Filed as #195, Backlog. ExternalName Service is the likely fix. |
| No test for the #194 backfill filter bypass | Accept | The fix reuses `_build_search_filters` which has coverage. An integration test would need pgvector + Valkey + multi-project data — high cost, low incremental value. |
| Fresh install path not tested after deploy-full.sh fix | Follow-up | The MEMORYHUB_DB_* key fix in deploy-full.sh should be verified on next full-fresh golden test. |

## Signal-to-Noise: The Bigger Problem Behind #194

The #194 bug was discovered by asking Claude Code in the `agent-template` project whether MemoryHub was providing value. The answer was mostly no — the agent reported getting a lot of noise and only one useful memory that it could have easily kept in its own local memory.

The project_id filter fix addresses the technical leak (cross-project memories bleeding through), but the underlying problem is deeper: **MemoryHub's retrieval isn't surfacing enough signal relative to the noise, even when filtering works correctly.** This is the critical UX question for the product.

Areas to investigate:
- Are the right memories being written in the first place? (garbage in, garbage out)
- Is cosine similarity alone sufficient, or does the recall pool need better ranking?
- Does the compilation epoch's stable ordering dilute relevance by prioritizing cache efficiency over freshness?
- Would aggressive weight-based stubbing (only full-inject truly high-value memories) reduce noise?

This should inform priorities for #170 (graph-enhanced retrieval) and #171 (knowledge compilation) — both are designed to improve retrieval quality.

## Action Items

- [ ] #195: Fix RHOAI Endpoints fragility (next session)
- [ ] Verify deploy-full.sh MEMORYHUB_DB_* fix on next golden test
- [ ] Investigate retrieval signal-to-noise ratio as a first-class concern — the product question behind #194

## Patterns

**Continue:** Reactive bug-fixing sessions that diagnose root causes rather than applying band-aids. The #194 analysis traced through 4 layers (tool → service → SQL → cache backfill) before identifying the real culprit.

**Continue:** Filing issues for problems discovered incidentally (#195) rather than letting them fade.

**Start:** Soliciting agent feedback on MemoryHub value. The "is this helping you?" question surfaced a critical product signal that no test suite would catch. Do this periodically across consuming projects.

**Stop:** Using `copy_secret` for cross-namespace Secrets where the consumer expects different key names. The helper is convenient but assumes key names are stable across consumers — they aren't.
