# Retrospective: Phase 1 — Foundation

**Date:** 2026-04-03
**Effort:** Build MemoryHub from ideation to working MCP server on OpenShift
**Issues:** #1, #2, #3, #8, #12 (Phase 1 core); #13, #14, #15, #16 (filed during)
**Commits:** 167abfb..77cb1ae (12 commits)

## What We Set Out To Do

Phase 1 ("the memory works" phase): get a single agent reading and writing memories through MCP, backed by PostgreSQL + pgvector on OpenShift. Specifically: project structure (#12), memory node schema (#1), PostgreSQL deployment (#3), and MCP tool surface (#8). Memory versioning (#2) was pulled in as a natural extension.

The broader session also included ideation (problem/vision/requirements), design docs for all 8 subsystems, GitHub project setup with issue tracking, and FIPS storage research.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Milvus + Neo4j + MinIO → PostgreSQL-only + MinIO | Good pivot | FIPS research found no validated vector DB. PostgreSQL consolidation is simpler and more compliant |
| Accepted Debian pgvector image, deferred UBI build | Scope deferral | Known RHEL build issues (pgvector #791). Demo cluster, not production. Tracked as #15 |
| FastMCP 2 template → FastMCP 3 entry point | Forced pivot | Template used dynamic loader from v2; tools didn't register over MCP protocol. Created server_v3.py |
| Added API key auth (not originally planned) | Good pivot | Needed user scoping for real multi-user testing. ConfigMap-based, lightweight |
| Deep copy on update + branch retirement + TTL | Good pivot | Exercise-tools found branches orphaned when parent updated. Deep copy is cleaner than reference tracking |
| Embedding dimension 1536 → 384 | Good pivot | User deploying all-MiniLM-L6-v2 instead of OpenAI-compatible model |
| Added mid-conversation memory search to rules | Good pivot | Retro discussion surfaced that initial rule only instructed one-time search at session start |

## What Went Well

- **Ideation → docs → issues → code pipeline.** Having ARCHITECTURE.md and per-subsystem docs before implementation meant we rarely backtracked on design decisions.
- **Exercise-tools against the live cluster.** mcp-test-mcp caught 6 real issues (FastMCP 3 dict requirement, depth expansion missing, branch orphaning, relevance scores null, has_children flags, embedding array truthiness) that unit tests couldn't surface.
- **Implement → review subagent pattern.** Caught the pydantic-settings nesting bug, timezone-naive timestamps, and metadata field naming mismatch before they shipped.
- **Parallel workstreams.** User deployed the embedding model while we built tools. No blocking.
- **77 tests** (56 core library + 21 MCP tool) give solid confidence for iteration.
- **The phased issue structure** (4 phases, prioritized) gave clear direction without over-planning.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| `src.main` vs `src.server_v3` entry point confusion — Containerfile uses one, run_local.py uses the other | Fix now | Consolidate to one entry point; document the decision |
| No integration tests against real PostgreSQL — pgvector cosine similarity only tested manually | Follow-up | Need a test target that runs against a real PG instance |
| CI workflow exists but never ran (pushed directly to main, no PRs) | Accept for now | Will trigger on first PR. Consider adding a push-to-main trigger |
| Deployment not fully IaC — anyuid SCC grant and ConfigMap are manual | Follow-up | Tracked as #14 |
| Old branch data from before retirement fix was still is_current=true | Fixed | Cleared test data. Future: migration scripts for schema-level changes |
| Rule didn't instruct mid-session memory searches | Fixed | Updated rule during retro |

## Action Items

- [x] Update memoryhub-integration rule to instruct mid-session memory searches
- [ ] Consolidate entry points (src.main vs src.server_v3) — decide which is canonical
- [ ] File issue for PostgreSQL integration tests
- [ ] Verify CI runs on next PR

## Patterns

**Start:**
- Exercise tools against the live deployment, not just unit tests. This session proved that real-environment testing catches a class of bugs that mocks miss.
- Update rules/docs during retros when gaps are found — don't defer it.

**Stop:**
- Pushing directly to main for everything. Fine for initial scaffolding, but now that the codebase exists, PRs would catch things the review subagent doesn't.

**Continue:**
- The implement → review subagent pattern for non-trivial code.
- Filing backlog issues immediately when we defer something (UBI build, deployment automation, RBAC). Nothing fell through the cracks.
- The `/imagine` → design docs → phased issues workflow. It produced a clean, well-scoped Phase 1.
