# Next Session -- Curation Agents

## Next: Implement Curator Agent (#285)

The Curator is the most complex curation agent and the load-bearing one in the epic -- it owns deep dedup, staleness processing, and cross-scope conflict detection. All prerequisites are shipped: framework (#286), Valkey (#283), OBO auth (#284), admin moderation (#45). Completing #285 unblocks #290 (promotion pipeline integration).

This is LLM-heavy work. The deep dedup sweep (0.70-0.80 similarity range) requires an LLM judge to decide whether near-duplicates are genuinely redundant. Prompt engineering and evaluation need interactive iteration, not autonomous loops.

1. **#285 -- Curator Agent** (LLM-heavy, singleton, leader election)
   - Design at `planning/autonomous-curation-agents.md` Section 5.2
   - Subclass `AgentPlugin` from `memoryhub-agents/src/memoryhub_agents/lifecycle.py`
   - Leader election via `memoryhub-agents/src/memoryhub_agents/leader.py` (already tested)
   - CronJob manifest (daily 02:00 UTC, `concurrencyPolicy: Forbid`)
   - Service identity `curator-agent` already in `users-configmap.example.yaml` with RBAC scopes
   - Key challenge: LLM judge for deep dedup in 0.70-0.80 similarity range. Needs prompt design, evaluation against real memories, and a decision threshold for merge vs flag.

**Sequencing.** Start with the structural pieces (plugin class, CronJob manifest, leader election wiring) then move to the LLM judge. Test the dedup sweep against production memories via the MCP search tool before wiring in automated merge decisions.

**Constraints for the session:**
- Need cluster access (login before starting)
- Need an LLM endpoint for the judge prompts -- check what's available on the cluster via RHOAI
- The Curator writes to organizational/role/campaign scope with `memory:knowledge_curator` -- verify this scope exists in the RBAC layer

## What landed last session (2026-06-30)

Massive backlog execution session. 13 issues closed across 11 PRs, consuming nearly the entire `NEXT_SESSION-backlog-loops.md` plan. memoryhub-core bumped to 0.10.0.

**Closed:**
- #66 -- actor_id/driver_id plumbing (three-tier resolution in all tools)
- #67 -- Audit logging stub (15 call sites, JSON events)
- #274 -- Cross-encoder cost/benefit benchmark (4 candidate sizes, NDCG/MRR)
- #282 -- relevant_until + temporal classifier (heuristic, 5 categories)
- #105 -- Tenant-scope admin API (auth service + BFF forwarding)
- #292 -- Within-user pattern surfacing (search-time cluster detection)
- #64 -- Project-scope membership enforcement (claims pipeline wiring)
- #284 -- OBO authorization for service agents
- #45 -- Admin content moderation (status model, quarantine, hard delete)
- #283 -- Valkey verified (already deployed, queue keys tested)
- #286 -- Shared agent framework (lifecycle, queue, leader election, MCP client)
- #287 -- Fact Checker agent (calendar verification plugin)
- #288 -- Trace Reviewer agent (heuristic extraction, degraded mode)

Also shipped: `docs/design/two-vector-retrieval.md` explainer, SYSTEMS.md and ARCHITECTURE.md updates.

## Watch out for

- `memoryhub-agents/pyproject.toml` had a duplicate `[project.scripts]` section from parallel agents -- fixed in session-close commit, but watch for similar merge artifacts if running parallel agent PRs again
- The `memory:knowledge_curator` scope referenced in the design doc may not exist in the RBAC layer yet -- grep for it before assuming it works
- Curator writes cross-owner memories (organizational scope) -- verify OBO auth covers organizational scope (it was implemented for user + project in #284, but organizational already had service-agent support pre-#284)

## If blocked

- **#289 (Statistician)** -- independent of Curator, could start in parallel if Curator is blocked on LLM availability. SDC logic is code-heavy but doesn't need an LLM for the core k-anonymity implementation.
- **Full backlog loop suitability review** -- triage remaining 49 open issues for loop-readiness, similar to the `planning/backlog-refinement-2026-06.md` exercise. Different epic file (`NEXT_SESSION-backlog-loops.md`).
