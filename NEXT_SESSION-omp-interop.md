# Next Session -- OMP Interop

## Next: <to be planned via /plan-next-session>

(No next-session focus selected yet. Run `/plan-next-session omp-interop`
to pick the first slice from the phases below.)

## Remaining epic phases

OMP-informed improvements to MemoryHub, grounded in the prior art survey
and standards sketching session (2026-09-09). The end-state: MemoryHub
carries upstream trust provenance through extraction, assembles context
through an ordered security pipeline, exports in the emerging MOF
standard format, and aligns its MCP tool surface with the MAP sketch.
Phases 1-2 are internal hardening that ship value regardless of OMP
direction. Phases 3-4 depend on working group feedback and should be
scheduled after the OMP convening produces signal.

Design doc: `planning/omp-informed-improvements.md`
OMP PRs: [#3 prior art](https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol/pull/3),
[#4 standards sketch](https://github.com/The-AI-Disclosures-Project/Open-Memory-Protocol/pull/4)

### Phase 1: Trust provenance and dreaming gates

Internal hardening. Both improvements are pure product quality and
security, independent of OMP direction.

**Work:**
1. Add `upstream_trust_level` field to MemoryNode (`trusted`,
   `untrusted`, `mixed`). Alembic migration, default `'trusted'` for
   existing rows. (#559)
2. Dreaming extraction pipeline carries the trust level of the source
   conversation content through to the extracted memory.
3. Add configurable deterministic threshold gates (`min_recall_count`,
   `min_unique_queries`, `min_score`) before the LLM consolidation step
   in the dreaming pipeline. Candidates below threshold deferred, not
   discarded. (#562)
4. Tests for both: extraction from conversations with trusted/untrusted/
   mixed content; gate behavior with candidates above and below
   thresholds.

**Definition of done:** Extracted memories carry the trust level of their
source content. The dreaming pipeline skips LLM consolidation for
candidates that have not been recalled enough times. Both fields appear
on API response models. Tests pass.

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of all other epics.

### Phase 2: Context assembly pipeline and generating_model

Security hardening of the injection path, plus a small schema addition.

**Work:**
1. Refactor the injection path (SessionStart hook, search_memory
   context injection) into an explicit ordered pipeline: authenticate
   source, validate schema, enforce scope, check freshness, deduplicate,
   apply budget, screen content (optional), stamp provenance, emit to
   context. (#561)
2. Each stage logs what it filtered and why (machine codes, not free
   text from excluded content).
3. Add `generating_model` column to MemoryNode. Extraction pipeline
   populates with the model identifier. Nullable for user-stated
   memories. Alembic migration. (#566)
4. Tests: pipeline ordering invariants (scope before dedup, budget
   before screening); generating_model populated on extraction,
   null on user-stated.

**Definition of done:** Context assembly follows a documented, ordered
pipeline. Each filtering decision is logged. `generating_model` appears
on API response models. Existing injection behavior is preserved (no
user-visible regression). Tests pass.

**Dependencies:** Benefits from Phase 1 (upstream trust level feeds
pipeline step 7), but can be implemented without it.

**Parallel-ok:** Yes -- independent of other epics. Can run concurrently
with Phase 1 if session availability allows.

### Phase 3: Portability and taint reporting (after OMP feedback)

OMP-aligned work. Schedule after working group feedback on the MOF and
MAP sketches.

**Work:**
1. MOF serialization module shared between server and SDK. Field mapping
   from MemoryNode to MOF (see mapping table in design doc). (#560)
2. MCP export tool supports `format=mof_markdown` (YAML frontmatter)
   and `format=mof_json`. Exchange bundle format with manifest.
3. Round-trip test: export as MOF, parse back, verify lossless for
   required fields.
4. search_memory and read_memory responses include taint metadata when
   `upstream_trust_level` is `untrusted`. Response carries
   `taint: {tainted: bool, sources: list[str]}`. (#563)
5. SDK export method supports MOF formats. SDK Memory model includes
   taint metadata.

**Definition of done:** Memories can be exported in MOF markdown and MOF
JSON. The export round-trips losslessly for all required MOF fields.
Taint metadata is present in search/read responses for untrusted
memories. SDK supports both.

**Dependencies:** Phase 1 (#559 -- upstream trust level must exist for
taint reporting). MOF field names may shift based on OMP working group
feedback; the serialization module should be easy to update.

**Parallel-ok:** No -- depends on Phase 1. Can run concurrently with
Phase 2.

### Phase 4: Standard alignment (after OMP feedback)

Lighter items that align MemoryHub's interface with whatever OMP
standardizes. Scope may shift based on working group direction.

**Work:**
1. Per-scope consent signals: `memory_enabled` state per scope,
   queryable and settable through MCP tools. Writes rejected when scope
   is disabled. (#564)
2. Contradiction signaling: review `report_contradiction` tool interface
   against MAP sketch, align schema, update documentation. (#565)
3. Memory source admission: design pattern for admitting new memory
   sources with human ceremony. Design-only unless channel connectors
   are added. (#567)

**Definition of done:** Users can toggle memory on/off per scope through
MCP tools. Contradiction signaling interface aligns with MAP sketch.
Source admission pattern is documented. Tests cover consent enforcement
(writes rejected when disabled, reads still work).

**Dependencies:** None hard. Benefits from Phases 1-3 being complete
(the full trust/pipeline/export story is in place). Consent signals and
contradiction alignment are independent of each other.

**Parallel-ok:** Yes -- independent of other epics. Items within this
phase are independent and could split across sessions if needed.

---

## What this covers (and what it doesn't)

**In scope:**
- #559 Upstream trust level tracking through dreaming extraction
- #560 MOF export format for memory portability
- #561 Context assembly ordered security pipeline
- #562 Deterministic threshold gates before dreaming consolidation
- #563 PTC taint metadata reporting at read time
- #564 Per-scope memory consent signals
- #565 Contradiction signaling alignment with OMP MAP sketch
- #566 generating_model field on MemoryNode
- #567 Memory source admission pattern design
- #516 PTC-aligned provenance (closed, superseded by #559 + #563)

**Out of scope (other epics own):**
- Procedural graph memory type (NEXT_SESSION-procedural-graphs.md)
- Curator scaffold and sweeps (NEXT_SESSION-curation.md)
- Retrieval quality improvements (NEXT_SESSION-retrieval-polish.md)
- SOC demo (NEXT_SESSION-soc-demo.md)

**Cross-epic notes:**
- Phase 1's dreaming gates (#562) complement the curation epic's
  AgentPlugin framework (#350). The gates can use a simpler integration
  initially and migrate to AgentPlugin when the scaffold ships.
- Phase 2's context assembly pipeline (#561) may surface retrieval
  quality concerns that belong in the retrieval-polish epic.

## What landed last session

(No sessions yet for this epic. Created 2026-09-09 from OMP prior art
survey and standards sketching.)

## Watch out for

- **OMP working group direction.** Phases 3-4 depend on working group
  feedback from the first convening (2026-09-09). If MOF field names or
  MAP tool schemas change substantially, the serialization module (Phase
  3) should be easy to update. Avoid over-investing in format details
  before the standard stabilizes.
- **#516 supersession.** Closed #516 as superseded by #559 + #563. If
  someone references #516, point them to the new issues.
- **PTC adoption.** The taint hook (#563) is valuable as advisory
  metadata even without PTC integration. But the full enforcement path
  (tainted turn escalates external writes) only fires in a PTC-
  integrated harness. Don't block on PTC adoption for the metadata.

## If blocked

- If OMP working group diverges from our sketches: Phases 1-2 are pure
  internal improvements and unaffected. For Phases 3-4, assess the
  divergence and pivot if we agree with the new direction. The design
  doc captures our rationale; update it if the rationale changes.
- If dreaming pipeline changes are complex: Phase 1 (#559 trust level)
  is a new field + write-path change. Phase 1 (#562 gates) is a
  pre-existing pipeline step with threshold logic. Both are additive,
  not refactors.
- If context assembly refactor (#561) risks regressions: the pipeline
  is a recomposition of existing checks, not new logic. Test against
  the existing injection behavior as the regression baseline.
