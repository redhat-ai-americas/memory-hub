# Retrospective: Embedding Errors & S3 Decoupling

**Date:** 2026-04-15
**Effort:** Bug-fix session targeting 3 NEXT_SESSION.md items + MinIO deployment
**Issues:** #119, #84, #102
**Commits:** efe1df9, 9ad20ba, 6951058, b322060

## What We Set Out To Do

Fix 3 priority bugs from NEXT_SESSION.md:
1. **#119** — Translate upstream embedder errors (connection failures, timeouts, 413s) into structured ToolError responses so agents can distinguish failure modes
2. **#102** — Add forward-walking to BFF `/api/memory/{id}/history` so any version ID resolves the full chain
3. **#84** — Handle embedding service 413 on long content with graceful truncation or chunking

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| #102 was already fixed by #63 | Scope removal | Confirmed via code + git history — the BFF delegates to the service-layer's bidirectional walker since 2026-04-07 |
| #84 expanded to include MinIO deployment | Scope addition | Natural next step after decoupling chunking from S3 — verify the full S3 offloading path works end-to-end |
| #84 approach: chose Option 2 (chunk without S3) over Option 1 (truncate-only) | Good pivot | User chose the more complete solution; existing chunking infrastructure made it a small diff |

## What Went Well

- **Layered fixes:** #119 (structured errors) became defense-in-depth for #84 (preventing the 413). The two issues complemented each other rather than overlapping.
- **Review sub-agents caught real issues:** missing `from exc` chains in search_memory and update_memory, wrong docstring threshold (4 KB vs 1 KB), dead `use_s3` variable in content-unchanged path.
- **Small diff for #84:** Decoupling chunking from S3 was a 3-file, +180/-25 change because the chunking infrastructure already existed — just gated behind the wrong condition.
- **Same-session deploy verification:** MinIO deployed, MCP server configured, and full roundtrip tested (write → S3 offload → hydrated read → delete) before closing the session.
- **Zero regressions:** 570 tests (302 root + 268 MCP) all passing throughout.
- **Clean commit history:** 4 focused commits — #119, #84 code, manifest, docs — each independently reviewable.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Live MCP deployment uses literal S3 credentials via `oc set env`, not secretKeyRef from manifest | Low | Accept for dev. Manifest has correct secretKeyRef pattern; next full deploy via deploy.sh will pick it up. |
| MCP server version not bumped (still 0.5.1) despite new error handling | Low | Follow-up — bump to 0.6.0 when next deploying |
| #102 still open on GitHub despite being fixed since 2026-04-07 | Low | Close with comment referencing #63 |
| 307 pre-existing ruff lint errors in root project | Low | Pre-existing, not from this session. Not blocking. |

## Action Items

- [ ] Close #102 with comment explaining it was resolved by #63 (commit 035031a)
- [ ] Bump MCP server version to 0.6.0 on next deploy session

## Patterns

**Continue:**
- Review sub-agents after implementation — they consistently catch real issues (4th consecutive retro confirming this)
- Same-session deploy verification — catching deploy issues immediately rather than deferring
- Plan mode for non-trivial changes (#84 design discussion before implementation)
- Aggressive delegation with focused sub-agent scopes

**Start:**
- Close stale issues proactively — #102 sat open for 8 days after its fix shipped

**Stop:**
- Nothing new to stop this session. Clean execution.
