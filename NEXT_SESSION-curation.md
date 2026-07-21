# Next Session -- Curation

## Next: Curator scaffold -- AgentPlugin base class + no-op sweep (#350)

Build the runtime infrastructure that all autonomous sweep agents use.
No curation logic yet. The session produces a testable AgentPlugin base
class and a concrete NoOpSweep that discovers candidate memories, logs
skip decisions, and exits cleanly. Code and tests only; deployment is a
follow-up session.

Branch off `feat/dreaming-ablation-results` as
`feat/curation/350-curator-scaffold`.

1. **Read the design doc first**
   `planning/autonomous-curation-agents.md` sections 4 (architecture),
   5.2 (Curator Agent spec), 9 (deployment topology), 12 (phasing).
   Also `planning/memory-extraction-pipeline.md` Layer 3 section for
   the reflection sweep interface contract. The design is detailed;
   don't re-derive decisions it already made.

2. **AgentPlugin base class** (`src/memoryhub_core/agents/base.py`)
   Abstract sweep lifecycle: `discover() -> list[Candidate]`,
   `evaluate(candidate) -> Decision`, `act(decision) -> Result`,
   `report(results) -> SweepReport`. Configuration via dataclass
   (thresholds, batch size, dry-run flag). DB session management
   via existing `get_session()`. Logging structured for CronJob
   pod log inspection.

3. **NoOpSweep implementation** (`src/memoryhub_core/agents/noop_sweep.py`)
   Concrete subclass. `discover()` queries active memory_nodes (limit
   configurable, default 100). `evaluate()` returns `Decision.SKIP` for
   every candidate. `act()` is a no-op. `report()` logs candidate count,
   skip count, elapsed time. This proves the lifecycle works end-to-end
   against a real (or SQLite test) database.

4. **CLI entry point** (`src/memoryhub_core/cli/curator.py`)
   `python -m memoryhub_core.cli.curator --sweep noop --dry-run`
   Same pattern as existing `retention_sweep.py`. This is what the
   CronJob will invoke. Support `--sweep` arg to select sweep type
   (noop for now, dedup/staleness/reflection later).

5. **Tests** (`tests/agents/test_base.py`, `tests/agents/test_noop_sweep.py`)
   - AgentPlugin lifecycle hooks called in order
   - NoOpSweep discovers candidates from test DB
   - NoOpSweep produces correct SweepReport (all skips, correct counts)
   - Dry-run mode prevents `act()` from being called
   - Configuration validation (bad thresholds, missing DB)

6. **K8s manifests (templates only, not applied)**
   CronJob + ServiceAccount + RBAC in `deploy/curator/` or alongside
   existing manifests. `concurrencyPolicy: Forbid`. Schedule placeholder
   (daily 02:00 UTC). These are committed but not deployed this session.

**Sequencing.** Items 1-5 are the session. Item 6 is quick scaffolding
at the end if time permits. The design doc read (item 1) informs
everything else -- don't skip it.

**Constraints for the session:**
- Code only, no cluster deployment. Tests run locally against SQLite.
- Branch from `feat/dreaming-ablation-results`, not main (PR #448 is
  still open).
- Follow existing patterns: `retention_sweep.py` for CLI entry point,
  `services/dreaming.py` for service-layer async patterns.
- `actor_id` column already exists on `memory_nodes` and
  `conversation_messages` -- no migration needed for OBO writes.
- Don't build dedup/staleness/reflection logic. The sweep types are
  Phase 2 work. This session builds the harness they plug into.

**Session start protocol:**
- Premise checks: verify `feat/dreaming-ablation-results` is current
  (`git log -1`); verify `actor_id` column exists in models
  (`grep actor_id src/memoryhub_core/models/memory.py`); read
  `planning/autonomous-curation-agents.md` sections 4, 5.2, 9
- Rules with history: all pushes through PRs; MCP tool creation uses
  fips-agents workflow (but this session is service-layer code, not
  MCP tools)
- Stop-and-ask before: adding new MCP tools (not planned, but if it
  comes up, use `/plan-tools` workflow); changing existing model
  schemas (shouldn't be needed)
- Close ritual: session summary; PR targeting
  `feat/dreaming-ablation-results`

**Exit predicate:**
- `AgentPlugin` base class with abstract lifecycle methods exists and
  has tests
- `NoOpSweep` runs against SQLite test DB, discovers candidates,
  produces a `SweepReport` with all-skip decisions
- CLI entry point works: `python -m memoryhub_core.cli.curator --sweep noop`
- All new tests pass; no regressions in existing suite
- PR opened targeting `feat/dreaming-ablation-results`

## Remaining epic phases

Autonomous curation: a Curator Agent running as a CronJob on the cluster
that periodically deduplicates memories (with measured precision), detects
staleness and cross-scope conflicts, and generates insight memories from
version-churn patterns (Layer 3 reflection). The agent runs unattended and
improves memory quality without user intervention.

Design references: `planning/autonomous-curation-agents.md` (Curator Agent
sections), `planning/memory-extraction-pipeline.md` (Layer 3 reflection).

### Phase 0: Housekeeping (start of first session)

Land `feat/dreaming-ablation-results` branch (tenant fix, source ablation
results, retrieval-unit routing design doc). Close #349 (Layer 2
validation) and #336 (extraction pipeline epic -- Layers 1-2 shipped,
remaining work moves to this epic).

**Work:**
1. Merge current branch via PR
2. Close #349 with final ablation summary
3. Close #336 with note that Curator (#350-353) and reflection (#345) are
   tracked under this epic

**Definition of done:** #349 and #336 closed on GitHub. Current branch
merged to main.

**Dependencies:** None.

**Parallel-ok:** Can bundle with Phase 1 in a single session.

### Phase 1: Curator scaffold (#350)

Build the runtime infrastructure for autonomous sweep agents. No
curation logic yet -- the sweep runs, logs "no-op," and exits cleanly.

**Work:**
1. `AgentPlugin` base class: sweep lifecycle (init, discover candidates,
   evaluate, act, report), configuration from env/ConfigMap
2. Leader election or single-pod CronJob (design doc says either; CronJob
   with `concurrencyPolicy: Forbid` is simpler)
3. K8s manifests: CronJob, ServiceAccount, RBAC (scoped to memory read/write),
   ConfigMap for sweep config
4. No-op sweep implementation: queries memory_nodes, iterates candidates,
   logs skip decisions, exits 0
5. Deploy to cluster, verify CronJob triggers and completes

**Definition of done:** `oc get cronjob curator-agent --context mcp-rhoai -n memory-hub-mcp`
shows a CronJob that has run at least once with status Succeeded. Pod logs
show the no-op sweep discovering candidate memories and completing without
action. AgentPlugin base class has tests covering lifecycle hooks.

**Dependencies:** Phase 0 (clean main branch).

**Parallel-ok:** No (everything else depends on this).

### Phase 2a: Dedup judge (#351)

Build and measure the dedup detection capability before wiring it into
production.

**Work:**
1. Build labeled pair set from real cluster data: ~50-100 pairs of
   (memory_a, memory_b, is_duplicate: bool). Mix of obvious dupes,
   near-dupes, and distinct-but-related memories
2. Implement dedup judge: embedding similarity + LLM tiebreaker (same
   pattern as reconciliation). Configurable thresholds
3. Measure precision/recall against labeled set. Target: >= 90% precision
   (false merges are destructive), >= 70% recall (missed dupes are
   tolerable)
4. Tests covering threshold bands, edge cases (same content different
   owner, same fact different wording)

**Definition of done:** Dedup judge passes precision >= 90% / recall >= 70%
against labeled pair set. Precision/recall numbers committed in a test or
results file. Judge is a callable module, not yet wired into a sweep.

**Dependencies:** Phase 1 (needs AgentPlugin base class for interface contract).

**Parallel-ok:** Yes -- runs in parallel with 2b and 2c. Needs worktree
isolation.

### Phase 2b: Staleness + cross-scope conflict (#353)

Second sweep type. Detects memories that are stale (no reads, old, low
weight) and memories that contradict each other across scopes.

**Work:**
1. Staleness sweep: query memories by last_accessed, age, weight. Flag
   candidates for review (not auto-delete -- destructive actions need
   the dedup judge's precision bar or human review)
2. Cross-scope conflict detection: find memories with high embedding
   similarity but different content across scopes/owners. Surface as
   contradictions via `report_contradiction()`
3. Wire both into AgentPlugin as sweep types in the CronJob
4. Deploy and verify on cluster

**Definition of done:** CronJob runs staleness + conflict sweeps. Pod logs
show candidates discovered and flagged. At least one real staleness
candidate and one real conflict surfaced from cluster data (not synthetic).
`report_contradiction()` called for conflicts.

**Dependencies:** Phase 1 (needs AgentPlugin scaffold + CronJob).

**Parallel-ok:** Yes -- runs in parallel with 2a and 2c. Needs worktree
isolation.

### Phase 2c: Layer 3 reflection (#345)

Third sweep type. Generates insight memories from version-churn patterns
using the version history that Layer 2 reconciliation produces.

**Work:**
1. Schema: add `last_reflection_version` column to `memory_nodes`
   (Alembic migration)
2. Churn detection query: find memories where
   `current_version - last_reflection_version >= threshold` within a
   rolling time window. Apply semantic-delta filter (skip rephrasings
   via embedding distance between consecutive versions)
3. Reflection prompt: compact version list -> LLM -> insight memory.
   Write insight as a new memory with `branch_type="reflection"` and
   `parent_id` pointing to the source memory
4. Wire into AgentPlugin as a sweep type
5. Integration test: the cheese test from the design doc (mozzarella ->
   parmesan -> gruyere -> brie -> "user frequently changes cheese
   preference")

**Definition of done:** Cheese test passes end-to-end: 4+ version updates
to a memory trigger reflection, insight memory created with correct
parent_id and branch_type. Churn detection filters out rephrasings
(semantic-delta < epsilon). Sweep runs in CronJob on cluster.

**Dependencies:** Phase 1 (needs AgentPlugin scaffold + CronJob).

**Parallel-ok:** Yes -- runs in parallel with 2a and 2b. Needs worktree
isolation.

### Phase 3: Deep-dedup sweep (#352)

Wire the measured judge from Phase 2a into production. This is the first
sweep that takes destructive action (merging duplicate memories).

**Work:**
1. Wire dedup judge into a sweep type: discover candidate pairs
   (embedding similarity above threshold), run judge, merge or flag
2. Merge action: soft-delete the duplicate, add provenance link to the
   surviving memory, preserve version history
3. Flag action: for pairs below the precision threshold, surface for
   human review (write a contradiction or admin notification)
4. Deploy and run against real cluster data. Monitor merge decisions
5. Verify merged memories are searchable and duplicates are gone

**Definition of done:** Dedup sweep runs on cluster, merges at least one
real duplicate pair, and the surviving memory has correct provenance.
No false merges (verify manually). Flagged pairs surfaced for pairs
below the auto-merge threshold.

**Dependencies:** Phase 2a (#351 -- needs the measured judge).

**Parallel-ok:** No (terminal phase).

---

## What this covers (and what it doesn't)

**In scope:**
- #350 Curator scaffold (AgentPlugin, CronJob, no-op sweep)
- #351 Labeled dedup pair set + deep-dedup judge
- #352 Deep-dedup sweep (merge/flag actions)
- #353 Staleness + cross-scope conflict detection
- #345 Layer 3 provenance-driven reflection
- #285 Curator Agent tracker (closed when #350-353 are done)
- #336 Extraction pipeline tracker (closed in Phase 0 -- Layers 1-2 done)

**Out of scope (other epics own):**
- #447 Retrieval-unit routing for dreaming facts (post-curation)
- #370 Ablation matrix B (blocked by #349, not this epic)
- #290 Five-stage promotion pipeline (follow-on to Curator, separate epic)
- #291 Per-agent fine-tuning (follow-on, separate epic)
- #289 Statistician agent (separate agent, separate epic)
- #334 Adversarial write / poisoning resistance (needs Curator, separate epic)

## What landed last session (2026-07-21)

Epic bootstrapped from dreaming epic. No code yet. Planning only:
`NEXT_SESSION-curation.md` created, `NEXT_SESSION-dreaming.md` updated
to point here for Phases 6-7.

**Context from dreaming epic:** Layers 1-2 shipped. Source ablation showed
dreaming adds +0.1pp without retrieval-unit routing. Autonomous curation
is the next quality lever. PR #448 (ablation results + tenant fix) is
open on `feat/dreaming-ablation-results`.

## Watch out for

- **OBO ownership model.** Curator writes memories on behalf of users.
  The `owner_id` / `actor_id` dual-field model is designed in
  `planning/autonomous-curation-agents.md` section 3. `actor_id` column
  already exists on `memory_nodes` and `conversation_messages` --
  verified 2026-07-21.
- **Existing `retention_sweep.py` is thread retention, not memory curation.**
  Don't confuse the two. The retention sweep handles conversation thread
  TTL; the Curator Agent handles memory quality. Different concerns,
  different code paths. But the CLI entry point pattern is worth copying.
- **Destructive actions need precision guarantees.** Merge (dedup) and
  delete (staleness) are irreversible for the user even if soft-deleted
  in the DB. The labeled pair set in Phase 2a is the quality gate.
  Phase 1 (scaffold) has NO destructive actions -- the no-op sweep
  only reads.
- **Parallel phases need worktree isolation.** Phases 2a/2b/2c modify
  different subsystems but share the same repo. Use
  `isolation: "worktree"` when running parallel sub-agents.
- **CronJob vs Deployment.** The design doc discusses both. CronJob with
  `concurrencyPolicy: Forbid` is the simpler starting point. Move to a
  long-running Deployment with leader election only if sweep duration
  exceeds the cron interval.
- **Branch topology.** This epic branches from
  `feat/dreaming-ablation-results` (not main) until PR #448 merges.
  Sub-branches target the parent feature branch per project convention.

## If blocked

- If PR #448 hasn't merged and you need main: the scaffold code is
  independent of the ablation work. You could branch from main instead,
  but the epic file assumes the feature branch. Check with the user.
- If the design doc is unclear on a specific sweep interface: the
  no-op sweep is intentionally minimal. Don't over-design the base
  class for sweep types that don't exist yet. Keep the interface thin
  and extend when Phase 2 work starts.
- If cluster is unavailable: Phase 1 is entirely local (SQLite tests).
  No cluster needed until deployment in a follow-up session.
