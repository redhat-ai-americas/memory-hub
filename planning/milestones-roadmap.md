# MemoryHub Milestones Roadmap

*Updated 2026-08-12*

## Overview

MemoryHub's work is organized into six milestones that sequence the path from reliable retrieval through platform maturity. Each milestone gates on the one before it: you can't curate what you can't retrieve, and you can't integrate what you haven't curated. Sixty-two issues are open across the backlog; 30 have been closed across milestones.

| Milestone | Progress | Status |
|-----------|----------|--------|
| v0.2 - Retrieval Quality | 5/8 (63%) | In progress |
| v0.3 - Multi-Harness & Onboarding | 1/6 (17%) | In progress |
| v0.4 - Curation & Governance | 10/16 (63%) | In progress |
| v0.5 - Platform Integrations | 8/9 (89%) | Nearly complete |
| v0.6 - UI & Dashboard | 6/6 (100%) | Complete |
| Unassigned | 47 open | Needs triage |

---

## v0.2 - Retrieval Quality (5/8 complete)

What this delivers: The foundation -- search results that are accurate, fast, and trustworthy enough to build agent workflows on.

### Completed

- #311 -- Default content_type for memory writes
- #305 -- Keyword and hybrid search
- #304 -- Benchmark retrieval accuracy
- #271 -- Retrieval latency at scale
- #41 -- Structured event logging

### Remaining

| Issue | Title | Blocker? |
|-------|-------|----------|
| #272 | Measure entity extraction throughput | No -- independent measurement work |
| #273 | Graph-traversal vs flat vector search comparison | No -- but answers "why not just pgvector?" for marketing |
| #306 | Time-decay recency bias in search scoring | No -- scoring refinement |

### What blocks completion

Nothing blocks the remaining three issues from each other. They are independent work items that require benchmark infrastructure and scoring changes. #273 has marketing implications (the "why not just pgvector?" question) but is technically straightforward.

---

## v0.3 - Multi-Harness & Onboarding (1/6 complete)

What this delivers: MemoryHub works beyond Claude Code -- framework-agnostic onboarding, turn-level hooks, and at least two additional agent harness integrations.

### Completed

- #307 -- IDE auto-save hooks

### Remaining

| Issue | Title | Blocker? |
|-------|-------|----------|
| #310 | Framework-agnostic agent onboarding | Yes -- gates all harness integrations; needs-design |
| #312 | Multi-harness support (tracking) | Depends on #310 |
| #313 | Turn-level hooks (automatic rebias and extraction) | Independent |
| #489 | OpenClaw integration | Depends on #310 |
| #509 | OpenCode integration | Depends on #310 |

### What blocks completion

#310 is the critical path. It requires a design document (flagged needs-design) before implementation can start. Every harness integration (#489, #509) and the tracking system (#312) depend on the framework-agnostic onboarding pattern it defines. #313 (turn-level hooks) is independent and could land in parallel.

Note: OpenClaw has three open bugs (#494, #495, #496) that are unassigned but will need fixing alongside the v0.3 integration work.

---

## v0.4 - Curation & Governance (10/16 complete)

What this delivers: Memory doesn't just accumulate -- it gets curated, promoted, audited, and governed. This is the milestone that separates MemoryHub from a dumb vector store.

### Completed

- #291 -- Training data collection
- #285 -- Curator Agent
- #281 -- Epic tracker
- #277 -- Audit trail schema
- #171 -- Knowledge compilation design
- #169 -- Context compaction design
- #92 -- Emergency-response patterns
- #91 -- Agriculture patterns
- #90 -- Public-safety patterns
- #89 -- Cybersecurity patterns

### Remaining

| Issue | Title | Blocker? |
|-------|-------|----------|
| #40 | Curation rule versioning and edit tracking | No |
| #68 | HIPAA/PHI detection in curation pipeline | No -- but hard gate for healthcare customers |
| #70 | Persist audit log to durable store | Yes -- blocks #71 (intersection auth); table stakes for regulated customers |
| #239 | Convergent learning (consolidate duplicates across users) | No -- future |
| #289 | Statistician Agent (population-level patterns) | No |
| #290 | Five-stage promotion pipeline | No |

### What blocks completion

#70 (durable audit log) is the most critical: it's table stakes for regulated customers and blocks intersection authorization (#71). #68 (HIPAA/PHI detection) is a hard gate for healthcare verticals. The remaining items are independent features that can land in any order.

---

## v0.5 - Platform Integrations (8/9 complete)

What this delivers: MemoryHub integrates with external agent platforms (LlamaStack, Kagenti, fips-agents).

### Completed

- #309 -- fips-agents OGX demo
- #33 -- LlamaStack Phase 3
- #32 -- LlamaStack Phase 2
- #31 -- LlamaStack Phase 1
- #30 -- Kagenti Phase 3
- #29 -- Kagenti Phase 2
- #28 -- Kagenti Phase 1
- #27 -- LlamaStack integration

### Remaining

| Issue | Title | Blocker? |
|-------|-------|----------|
| #82 | LibreChat integration | No -- standalone integration work |

### What blocks completion

Only #82 remains. LibreChat integration is self-contained and doesn't depend on other milestones.

---

## v0.6 - UI & Dashboard (COMPLETE)

All 6 issues closed. The UI and dashboard milestone is fully delivered.

---

## Proposed: Unassigned Issue Triage

47 open issues have no milestone. Grouped by theme with triage recommendations:

### Retrieval and search improvements (7 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #389 | S3 hydration for large-content tail | v0.2 -- retrieval quality |
| #397 | Hard-stop mode (truncate vs stubs) | v0.2 -- retrieval quality |
| #404 | Effective-k observability (**Bug**) | v0.2 -- retrieval quality |
| #453 | Reimplement disabled_signals | Defer -- future |
| #454 | Reimplement entity-aware search | Defer -- future |
| #511 | embedding_max_tokens config mismatch (**Bug**) | Unblocked -- fix independently |
| #270 | Semantic search over conversation threads | Defer -- future |

### Curation and memory hygiene (7 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #350 | Curator scaffold | v0.4 -- blocks #352, #353 |
| #351 | Labeled dedup pair set | v0.4 -- blocks #352 |
| #352 | Deep-dedup sweep | v0.4 -- depends on #350, #351 |
| #353 | Staleness sweep | v0.4 -- depends on #350 |
| #345 | Provenance-driven reflection (Layer 3) | v0.4 -- curation |
| #346 | Domain ontology refinement | v0.4 -- curation |
| #512 | Chunk/fact node creation fails (**Bug**) | Unblocked -- fix independently |

### Agent resilience and sessions (4 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #491 | Memory rewind/rollback | Needs design first |
| #104 | Persist session state across pod restarts | v0.3 -- onboarding quality |
| #431 | Session-close memory capture | v0.3 -- hooks |
| #87 | Typed SDK push notifications | Defer -- future |

### CLI, SDK, and developer tooling (5 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #492 | Per-project identity selection | v0.3 -- developer experience |
| #493 | delete-agent command | v0.3 -- depends on #492 |
| #497 | Surface last_updated_by | v0.3 -- depends on #492 |
| #458 | create-agent table output omits api_key (**Bug**) | Unblocked -- fix independently |
| #459 | Add rotate-api-key subcommand | v0.3 -- developer experience |

### Benchmarks and evaluation (6 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #330 | LongMemEval_S full-haystack | v0.2 -- validates retrieval |
| #331 | Answer-quality with LLM judge | v0.2 -- depends on #330 |
| #370 | Ablation Matrix B | Post-v0.2 |
| #400 | Evaluate AutoRAG | Post-v0.2 |
| #334 | Adversarial write resistance | v0.4 -- governance |
| #337 | Platform-level benchmark design | v0.4 -- depends on #334 |

### Security and authorization (3 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #514 | Validate project membership in list/search (**Bug**) | Unblocked -- security fix, high priority |
| #71 | Intersection authorization | Defer -- depends on #70 (v0.4) |
| #72 | driver_id redaction | Defer -- future |

### Compliance (Trust Bricks) (2 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #516 | PTC-aligned provenance and taint metadata | v0.4 -- governance |
| #517 | GAL-aligned memory trust lifecycle | v0.4 -- governance |

### Competitive analysis (2 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #505 | Create test deployment of Hindsight | Stay unassigned -- research/spike |
| #506 | Create test deployment of GBrain | Stay unassigned -- research/spike |

### Marketing and design (2 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #507 | Demo: quantitative benefits of memory sharing | Stay unassigned until design exists |
| #508 | "Building the case for agent memory" design doc | Stay unassigned -- planning |

### Infrastructure and bugs (4 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #375 | Full local test suite hang (**Bug**) | Unblocked -- fix independently |
| #395 | MinIO content doesn't survive uninstall (**Bug**) | Unblocked -- fix independently |
| #383 | Capability-claim sweep | Post-milestone -- meta-task |
| #241 | Evaluate pluggable storage backend | Defer -- future |

### Client bugs (OpenClaw) (3 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #494 | OpenClaw: scope/project_id placement (**Bug**) | v0.3 -- client bugs |
| #495 | OpenClaw: connection leak (**Bug**) | v0.3 -- client bugs |
| #496 | OpenClaw: remove as-never casts (**Bug**) | v0.3 -- client bugs |

### Other (2 issues)

| Issue | Title | Recommended milestone |
|-------|-------|----------------------|
| #426 | EvalHub sidecar result-drain retry | Stay unassigned -- infra improvement |
| #518 | UI deploy script hard-fails without RHOAI (**Bug**) | Unblocked -- fix independently |

### Highest-priority unassigned items

1. **#514** -- Authorization bug allowing cross-project memory access. Security issue, should be fixed immediately.
2. **#511** -- Embedding config mismatch blocks writes. Breaks basic functionality on CPU deployments.
3. **#512** -- Chunk/fact node creation completely non-functional. Foundational storage bug.
4. **#404** -- Effective-k silent capping. Agent silently gets fewer results than requested.
5. **#395** -- MinIO data loss on reinstall. Data integrity risk.

---

## Critical Path

### Dependency chains that span milestones

```
v0.2                              v0.4
#330 LongMemEval full-haystack ──► #331 answer-quality with judge

v0.4 (internal chain)
#350 Curator scaffold ──► #352 Deep-dedup sweep
#351 Labeled dedup set ──► #352
#350 ──────────────────► #353 Staleness sweep

v0.4 → future
#334 Adversarial resistance ──► #337 Platform benchmark
#70 Durable audit log ──────► #71 Intersection authorization

Developer tooling (unassigned chain)
#492 Identity selection ──► #493 delete-agent
                       └──► #497 last_updated_by
```

### Sequencing priorities

1. **Fix security and storage bugs first** (#514, #511, #512) -- these undermine trust in the deployed system regardless of milestone work.

2. **Close v0.5** -- only #82 (LibreChat) remains. Getting a milestone to 100% is a marketing win and removes tracking overhead.

3. **Close v0.2** -- three independent issues remain (#272, #273, #306). All are scoped and unblocked. Add #330/#331 (LongMemEval) and #404 (effective-k bug) for a stronger completion story.

4. **Design-gate v0.3** -- #310 (framework-agnostic onboarding) needs a design document before implementation. Start design work now so v0.3 implementation can begin once v0.2 wraps.

5. **Advance v0.4 curation chain** -- #350 (Curator scaffold) blocks two high-leverage features (#352 dedup, #353 staleness). This is the longest dependency chain in the backlog.

### Key blockers across milestones

| Blocker | What it blocks | Impact |
|---------|---------------|--------|
| #310 needs-design | All v0.3 harness integrations | Can't onboard OpenClaw, OpenCode, or any new harness |
| #350 Curator scaffold | #352 dedup, #353 staleness | Memory quality degrades as store grows |
| #330 LongMemEval run | #331 answer-quality eval | No provable retrieval quality claims |
| #334 Adversarial resistance | #337 Platform benchmark | No security benchmark story |
| #70 Durable audit log | #71 Intersection auth | No audit trail for regulated customers |

---

## Bug Triage

11 open bugs across the backlog, ordered by severity:

### Critical (security or data integrity)

| Issue | Title | Milestone | Assessment |
|-------|-------|-----------|------------|
| #514 | Project membership not validated in list/search | Unassigned | **Security** -- callers can see memories in projects they don't belong to. Fix immediately. |
| #395 | MinIO content lost on uninstall --skip-db | Unassigned | **Data loss** -- object storage silently lost during what should be a safe reinstall. |
| #512 | Chunk/fact node creation fails (logical_id NOT NULL) | Unassigned | **Feature non-functional** -- chunk and fact nodes have never worked. Zero rows exist. |
| #511 | embedding_max_tokens config mismatch | Unassigned | **Write failures** -- memories over ~1000 chars fail with HTTP 413 on CPU embedding model. |

### High (degrades developer or agent experience)

| Issue | Title | Milestone | Assessment |
|-------|-------|-----------|------------|
| #404 | Effective-k silent capping | Unassigned | Agent silently gets fewer results than requested. Hard to diagnose. |
| #375 | Full local test suite hang | Unassigned | Developers stop running tests. Corrosive to code quality. |
| #518 | UI deploy script fails without RHOAI | Unassigned | Blocks UI deployment on clusters without RHOAI installed. |

### Medium (papercuts and client bugs)

| Issue | Title | Milestone | Assessment |
|-------|-------|-----------|------------|
| #494 | OpenClaw: scope/project_id placement | Unassigned | Client-side bug; blocks correct OpenClaw usage. |
| #495 | OpenClaw: connection leak in resetSession | Unassigned | Resource leak; may cause issues under load. |
| #496 | OpenClaw: remove as-never casts | Unassigned | Code quality; TypeScript type safety gap. |
| #458 | create-agent output omits api_key | Unassigned | Papercut; user can't see the key they just created. |

### Bugs that block milestone completion

None of the 11 bugs are assigned to milestones, so none technically block milestone completion. However, #514 (authorization bypass) and #511/#512 (storage bugs) should be fixed before claiming any milestone is production-ready, since they undermine the system's reliability and security regardless of feature completeness.
