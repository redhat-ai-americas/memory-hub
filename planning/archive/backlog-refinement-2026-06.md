# Backlog Refinement -- June 2026

**Date:** 2026-06-30
**Purpose:** Categorize all 50 open issues into loop-ready work vs design/judgment sessions, track progress through each.

---

## How to use this file

Each section below represents a work batch. Within each batch, issues are grouped by the design/judgment session needed to unblock them, followed by the loop-ready execution work. Work through the design sessions in order, then execute the loops.

**Status key:** `[ ]` not started, `[d]` design session done, `[x]` loop executed and complete

---

## 1. Benchmarking Suite

Design doc: `planning/system-benchmarks.md`

#275 (agent performance evaluation) decoupled and deferred to `priority:future` -- it's a research track, not a system benchmark. The four system benchmarks follow `tests/perf/` conventions (no shared base class, just shared metric functions and result file format).

### Design session -- DONE (2026-06-30)

Decisions made:
- Follow existing `tests/perf/` pattern, not a new framework
- Extract shared metrics (recall, precision, MRR, NDCG) to `tests/perf/metrics.py`
- Each benchmark: engine module + test file + standalone script + JSON results
- #100 folded into #274 (cross-encoder superset)
- #275 deferred as separate research track

### Manual prep (before loops)

- [ ] Label 50-100 memories with ground-truth entities (for #272)
- [ ] Design and label 50+ queries with expected results (for #273)

### Loop targets (in execution order)

- [ ] **#272** -- Entity extraction throughput and accuracy
  - Prereq: labeled entity set exists
  - Exit predicate: per-stage latency breakdown + accuracy metrics committed to `benchmarks/`
- [ ] **#274** -- Cross-encoder re-ranking cost/benefit (subsumes #100)
  - Prereq: none (extends existing benchmark)
  - Exit predicate: optimal candidate set size identified, recommendation in results JSON
- [ ] **#271** -- Retrieval latency and relevance at scale (100/1K/10K memories)
  - Prereq: none (corpus generated programmatically)
  - Exit predicate: all three scale tiers benchmarked, latency stable across 3 runs
- [ ] **#273** -- Graph-traversal vs flat vector search
  - Prereq: labeled query set exists
  - Exit predicate: comparison report committed, pursue/skip/hybrid recommendation documented

---

## 2. MCP Server Plumbing

### Design session -- DONE (2026-06-30)

Decisions made:
- #66 and #64 are independent, both loop-ready as-is (detailed acceptance criteria in issues)
- #71 and #72 deferred to `priority:future` (both self-described as future work, depend on unshipped prerequisites)
- #64 is not urgent (healthcare demo reference is stale)
- Schema columns and Pydantic schemas for actor_id/driver_id already exist; #66 is purely MCP tool wiring

### Loop targets (independent, either order)

- [ ] **#66** -- Plumb actor_id and driver_id through tools and register_session
  - Exit predicate: all tools accept and propagate actor_id/driver_id, tests pass
- [ ] **#64** -- Implement project-scope membership enforcement
  - Exit predicate: non-members rejected, members allowed, tests pass
  - Not urgent; pick up when project isolation becomes a real need

### Deferred (priority:future)

- **#71** -- Intersection authorization (depends on #66 + #70)
- **#72** -- driver_id redaction on read (depends on #71)

---

## 3. Domain Curation Patterns

Structurally identical work across four domains, but blocked on demo script readiness.

### Design session -- DONE (2026-06-30)

Decisions made:
- Demo goals are still solid, but scripts may need rework to reflect MemoryHub capabilities added since April
- fips-agents team capability (in progress) may materially change how demos run -- wait for that to land before building demos
- Curation patterns use demo scripts as their spec; can't loop until scripts are current
- #93 (SME validation) stays open as a parallel human gate
- The curation infrastructure (CuratorRule model, regex pipeline, layered rules) is ready -- no framework work needed

### Prerequisite: demo script review

- [ ] **Demo script freshness audit** -- Review all five demo scripts against current MemoryHub capabilities (entity extraction, curation pipeline, identity model, memory tree, threads). Flag sections that assume features we didn't have in April or miss features we've added since.
  - Blocked on: fips-agents team capability landing (in progress)
  - Output: per-script delta list, then update the scripts before building curation patterns

### Loop targets (parallel, independent -- after demo scripts are current)

- [ ] **#89** -- Cybersecurity domain curation patterns (credentials, exec ID redaction)
  - Exit predicate: patterns defined, test fixtures pass, integrated with curation pipeline
- [ ] **#90** -- Public-safety domain curation patterns (third-party PII, CI handling)
  - Exit predicate: same as #89
- [ ] **#91** -- Agriculture domain curation patterns (yield data, lease boundaries)
  - Exit predicate: same as #89
- [ ] **#92** -- Emergency-response domain curation patterns (resident PII, political dynamics)
  - Exit predicate: same as #89

### Related

- [ ] **#93** -- SME validation outreach for 5 demo scenarios (tracking)
  - Human-only gate, runs in parallel with implementation

---

## 4. Autonomous Curation Agents Epic (#281)

Large epic with strict sequential phases. Design doc at `planning/autonomous-curation-agents.md`.

### Design session -- DONE (2026-06-30)

Decisions made:
- #282 and #283 are independent prerequisites, both loop-ready now
- #284 (OBO auth) is loop-ready but depends on #66 (actor_id/driver_id plumbing) landing first
- #286 (shared framework) needs its own design session before agent implementations start
- #292 (pattern surfacing) promoted out of epic -- independent read-path enhancement, no agent dependency
- #290 and #291 deferred until agents are running and collecting data

### Phase 0: Prerequisites (parallel loops, no design session needed)

- [ ] **#282** -- Add relevant_until column and temporal classification
  - Exit predicate: migration applied, temporal classifier tags memories at write time, tests pass
- [ ] **#283** -- Deploy Valkey to memoryhub-agents namespace
  - Exit predicate: Valkey pod running, queue keys accessible, kustomize manifests committed

### Phase 0.5: OBO Auth (sequential, after section 2 loop)

- [ ] **#284** -- Implement OBO authorization for service agents
  - Depends on: #66 (actor_id/driver_id plumbing)
  - Exit predicate: service agents can write with any owner_id in their scope, metadata_.actor_id auto-set, tests pass

### Phase 1: Shared Framework (loop-ready -- design doc resolves open questions)

- [ ] **#286** -- Build shared agent framework
  - Design doc Section 13 answers all 8 open questions; recommendations confirmed 2026-06-30
  - Single `memoryhub-agent` package, plugin modules per agent, single container image with AGENT_TYPE env var
  - Exit predicate: package installable, lifecycle (auth/dequeue/process/report) works end-to-end with a test agent, leader election helper tested
  - Blocks: all four agent implementations

### Phase 2: Agent Implementations (after framework, loops)

- [ ] **#285** -- Curator Agent (deep dedup, staleness, conflict detection)
  - Exit predicate: CronJob runs on schedule, processes queue, dedup/staleness results verified
- [ ] **#287** -- Fact Checker Agent (temporal expiry, verification plugins)
  - Exit predicate: verifies facts, updates relevant_until, CalendarPlugin works, tests pass
  - Can parallelize with #285 (most independent pair)
- [ ] **#288** -- Dreamer Agent (post-session memory extraction)
  - Exit predicate: extracts memories from completed threads, OBO writes succeed
  - Note: full mode needs conversation persistence (#168); basic mode works without
- [ ] **#289** -- Statistician Agent (population-level pattern aggregation)
  - Exit predicate: produces summary memories with convergence provenance

### Phase 3+: Deferred (after agents are running)

- **#290** -- Integrate Curator with five-stage promotion pipeline
- **#291** -- Training data collection and per-agent fine-tuning

### Promoted out of epic (standalone loop target)

- [ ] **#292** -- Within-user pattern surfacing via search-time signals
  - No agent dependency; read-path enhancement to existing search
  - Exit predicate: search annotates results with pattern_signals when cluster detected, tests pass

---

## 5. Governance

### Design session -- DONE (2026-06-30)

Decisions made:
- #67 (audit stub) is a clean standalone loop target -- fully specified, no design needed
- #70 (LlamaStack telemetry) is a research/evaluation task, not blocking anything; keep as-is
- #276 (access control design) -- concrete children already tracked (#64, #71, #72); recommend defer to `priority:future`
- #277 already `priority:future`

### Loop target

- [ ] **#67** -- Add audit logging stub interface
  - Exit predicate: `audit.py` created, all tools call `record_event` after auth decisions, structured JSON log lines verified

### Research (not loop-shaped, not urgent)

- [ ] **#70** -- Evaluate LlamaStack telemetry as audit persistence backend
  - Replaces the stub from #67 when ready; evaluation criteria listed in issue

### Deferred (priority:future)

- ~~**#276**~~ -- Closed; concrete children tracked as #64, #71, #72
- **#277** -- Design immutable audit trail schema

---

## 6. Auth

### Design session -- DONE (2026-06-30)

Decisions made:
- #105 is fully specified (acceptance criteria, data model already tenant-aware). Loop-ready as-is.
- #236 stays `priority:future`

### Loop target

- [ ] **#105** -- Tenant-scope memoryhub-auth admin API endpoints
  - Exit predicate: admin API enforces tenant_id filter, BFF forwards tenant, cross-tenant returns 404, tests pass

### Deferred (priority:future)

- **#236** -- Design team agent identity model with delegated user access

---

## 7. UI

### Design session -- DONE (2026-06-30)

Decisions made:
- No UI work is on the near-term horizon; all four issues deferred
- #44 (local dev server) is the only loop-ready item but pointless without active UI work
- #106 (Option B multi-tenant) has open design questions and Option A already works
- #125 (welcome flow) explicitly not urgent until >10 contributors
- Revisit this section when a UI development push is planned

### Deferred (all -- revisit when UI work resumes)

- **#109** -- Write UI design doc (writing task, not code)
- **#106** -- Per-request BFF operator identity (design questions unresolved, Option A works)
- **#125** -- Automate contributor welcome flow (not urgent at current contributor count)
- **#44** -- Set up local dev server (loop-ready but no active UI work to justify it)

---

## 8. Remaining Individual Issues

### Design session -- DONE (2026-06-30)

Decisions made:
- #100 already folded into #274 (section 1)
- #99 closed (LlamaStack integration no longer active)
- #87 deferred to `priority:future` (no active consumer for full-content push)
- #82 kept (blocker #74 is closed; loop-ready as config + validation)
- #45 kept (incident response, distinct from background curation agents)
- #69 tied to demo fleet; blocked on same items as section 3 (fips-agents team capability)
- #104 needs its own design session when session persistence becomes a priority

### Loop targets

- [ ] **#82** -- Integrate MemoryHub with LibreChat as second MCP client
  - Blocker #74 (OAuth broker) is closed; no MemoryHub code changes needed
  - Exit predicate: OAuth client registered, librechat.yaml configured, 8-step verification passes

### Loop-ready (design doc resolves forks)

- [ ] **#104** -- Persist session state across pod restarts
  - Design doc at `planning/session-persistence.md` recommends Fork C (Valkey + no-op register_session under JWT + SDK retry); confirmed 2026-06-30
  - Phase 1: Valkey persistence for app session map
  - Phase 2: SDK transparent retry on "Session not found"
  - Phase 3: Upstream FastMCP investigation (separate, non-blocking)
  - Exit predicate: pod restart doesn't require SDK clients to re-register; push subscribers re-spawn lazily

### Loop-ready (design doc found and open questions resolved)

- [ ] **#45** -- Admin agent for content moderation and bulk deletion
  - Design doc at `docs/admin/content-moderation.md` (issue had wrong path); 7 open questions resolved 2026-06-30
  - Exit predicate: status column migration applied, four admin operations implemented, MCP tools exposed, authorization enforced (memory:admin + sub-scopes), audit trail works in normal + sanitized modes, tests pass

### Blocked on demo work (section 3)

- [ ] **#69** -- Agent generation CLI for demo fleet provisioning
  - Also depends on #64 (project membership)

### Deferred (priority:future)

- **#87** -- Push notifications full-content delivery (no active consumer)
- **#239** -- Convergent learning to consolidate duplicate memories
- **#241** -- Evaluate pluggable storage backend adapter pattern
- **#254** -- Multi-modal memory with text-stub + artifact retrieval
- **#270** -- Semantic search over conversation message content

---

## 9. Large Design Documents (no near-term implementation)

### Design session -- DONE (2026-06-30)

Confirmed parked. Both are ambitious multi-subsystem designs with unshipped prerequisites. Not loop targets. Revisit when their dependencies (#168 conversation persistence, #170 graph-enhanced memory) start landing.

- **#169** -- Context compaction services (ACE) -- needs design doc authored; builds on existing curator
- **#171** -- Knowledge compilation -- builds on #168, #169, #170; "crown jewel" capability, furthest out

---

## Progress Log

Track design sessions and loop executions here as they complete.

| Date | Item | Type | Notes |
|------|------|------|-------|
| 2026-06-30 | Benchmarking suite design | Design session | #275 deferred as research; #100 folded into #274; design doc at planning/system-benchmarks.md |
| 2026-06-30 | MCP server plumbing | Design session | #71, #72 deferred to future; #66, #64 are independent loop targets; #64 not urgent |
| 2026-06-30 | Domain curation patterns | Design session | Blocked on demo script freshness audit + fips-agents team capability; curation infra is ready |
| 2026-06-30 | Curation agents epic | Design session | Prerequisites loop-ready; #284 depends on #66; #286 needs own design session; #292 promoted out of epic; #290/#291 deferred |
| 2026-06-30 | Governance | Design session | #67 is standalone loop target; #70 is research; #276 closed (children cover it); #277 stays future |
| 2026-06-30 | Auth | Design session | #105 loop-ready as-is; #236 stays future |
| 2026-06-30 | UI | Design session | All four deferred; no active UI work planned |
| 2026-06-30 | Remaining issues | Design session | #99 closed; #87 deferred; #82 loop-ready; #104 loop-ready (design doc resolves forks); #45 needs design doc; #69 blocked on demos |
| 2026-06-30 | Large design docs | Design session | #169, #171 confirmed parked; prerequisites unshipped |
| 2026-06-30 | #286 shared framework | Promotion | Design doc resolves all 8 open questions; promoted from "needs design" to loop-ready |
| 2026-06-30 | #104 session persistence | Promotion | Fork C confirmed; promoted from "needs design" to loop-ready |
| 2026-06-30 | #45 content moderation | Promotion | Design doc found at docs/admin/content-moderation.md (issue had wrong path); 7 open questions resolved; promoted to loop-ready |
| 2026-06-30 | Refinement complete | Milestone | 50 issues -> 47 open (3 closed), 14 loop-ready, next session doc written |
