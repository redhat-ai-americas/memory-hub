# Retrospective: Phase 2 — Memory Learns

**Date:** 2026-04-04
**Effort:** Graph relationships, curation pipeline, inline dedup detection, 5 new MCP tools
**Issues:** #4, #6, #16 (closed); #18 (filed)
**Commits:** 3fe428c..d39466b (6 commits)

## What We Set Out To Do

Phase 2 ("the memory learns"): make MemoryHub's memories self-maintaining through graph relationships (#4), a curator agent (#6), and synthetic test data (#16). The open issues at session start were #4 (graph relationships), #6 (curator architecture), and #16 (synthetic data).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Curator: separate service → inline pipeline with sampling → fully deterministic pipeline | Good pivot (x2) | First pivot: curation at write time is simpler than a background service. Second pivot: MCP spec requires HITL approval for sampling, which is unacceptable friction on write operations. Similarity feedback (return a count, let the agent decide) achieves the same goal. |
| Phase 2b (sampling integration) eliminated | Good pivot | No use case requires sampling now that write_memory returns similar_count and get_similar_memories provides drill-down. Llama 4 Scout credentials preserved for Phase 3 background curator. |
| Sub-agent-created tools → fips-agents scaffolded tools | Rework | Sub-agents can't run slash commands and skipped the scaffold step. Tools lacked template test structure and registration patterns. Redone properly via /plan-tools → /create-tools → /exercise-tools. |
| asyncio.run() rule seeding → removed (manual seeding) | Forced fix | Pre-startup asyncio.run() created a separate event loop that poisoned SQLAlchemy's connection pool. Every DB operation failed. Filed #18 for a proper solution. |
| Added imagePullPolicy: Always to Deployment manifest | Fix | Stale image problem: new builds completed but pods kept using cached images. Recurring issue now permanently fixed in the manifest. |

## What Went Well

- **Three-iteration curator design landed well.** Starting with sampling, discovering the HITL constraint, and arriving at similarity feedback was productive — each iteration was informed by real constraints, not just preferences. The final design is simpler, cheaper, and more predictable than any of the intermediate designs.
- **The curation pipeline works end-to-end.** Secrets blocking, PII flagging, exact duplicate rejection (0.97 blocked), near-duplicate detection (0.87 flagged with similar_count), and user rule tuning all verified against the live deployment with real pgvector embeddings.
- **Implement → review pattern caught real bugs.** The review sub-agent found 7 issues across the graph and curation implementations, including a semantic bug in trace_provenance direction and a critical silent-failure coupling between the scanner and rule names.
- **fips-agents tool workflow produced better tools.** After redoing the 5 tools via the proper scaffold process, the tools had consistent test patterns, proper annotations, and cleaner structure. The exercise-tools step against the live deployment caught the event loop bug that unit tests couldn't surface.
- **Test coverage growth.** 77 → 165 tests. Every new feature has both unit tests (SQLite) and was exercised against the live deployment (PostgreSQL + pgvector).
- **Synthetic data demonstrates real value.** Multi-scope memories with branches, graph relationships, version history, contradiction tracking, and dedup detection — all working together.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Curation rule seeding has no automated path — manual oc exec required after fresh deploy | Follow-up | Filed #18 with four options (alembic data migration, FastMCP lifecycle hook, lazy seeding, init container) |
| Still pushing directly to main (flagged in Phase 1 retro too) | Accept for now | Acceptable during rapid single-developer Phase 2. Will protect main and use feature branches starting Phase 4. |
| #4 (graph relationships) not closed on GitHub despite being complete | Fix now | Needs to be closed |
| write_memory MCP test doesn't test the curation response shape | Minor | Tests only check parameter signatures, not the new tuple return with curation feedback. Covered by core library tests and live exercise. |

## Action Items

- [x] Add CLAUDE.md rule about MCP tool creation workflow (must use fips-agents, never sub-agents)
- [x] Clean up _subagent_tools_backup folder
- [ ] Close #4 on GitHub
- [ ] Protect main branch after Phase 4 (tracked informally, not as an issue)

## Patterns

**Start:**
- Running slash command workflows (/plan-tools, /create-tools, /exercise-tools) in the main conversation context, not delegated to sub-agents. Sub-agents can't execute slash commands and produce tools that need rework.
- Deleting the existing OpenShift deployment before redeploying to avoid stale image/tool caching issues.

**Stop:**
- Using sub-agents to create MCP tools. The fips-agents scaffold produces materially better results and the slash command workflow can't be delegated.
- Using asyncio.run() before FastMCP's event loop starts. It poisons the connection pool.

**Continue:**
- The implement → review sub-agent pattern. Caught 7+ real issues this session.
- Iterating on design docs before implementation. The three-pass curator design avoided building the wrong thing.
- Exercising tools against the live deployment. Found the event loop bug, verified real pgvector similarity scores, caught stale image issues.
- Filing backlog issues immediately when deferring work (#18 for rule seeding).
