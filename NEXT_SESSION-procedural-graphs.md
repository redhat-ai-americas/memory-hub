# Next Session -- Procedural Graphs

## Next: Design doc and schema for procedural graph memory type (#552)

Write a design document and implement the schema extension for storing
procedural knowledge as directed graphs in the memory tree. This session
produces a design doc, a ContentType extension, new relationship types,
and an Alembic migration. No retrieval or extraction logic yet.

Reference: arXiv 2609.09153 "Procedural Graphs: Self-Evolving Execution
Structures for LLM Agents" -- the paper that motivated this epic.

Branch off `main` as `feat/procedural-graphs/552-schema`.

1. **Read existing architecture first**
   - `research/surveys/knowledge-and-graph-memory.md` -- our survey of
     graph memory approaches. Section 1 frames the "what things ARE vs
     how things HAPPEN" split. Section 3 notes Mem0 added a procedural
     type. Section 6 discusses PostgreSQL as graph substrate.
   - `src/memoryhub_core/models/memory.py` -- MemoryNode (adjacency list,
     parent_id tree), MemoryRelationship (directed edges with temporal
     validity, 5 relationship types).
   - `src/memoryhub_core/models/schemas.py` -- ContentType enum
     (experiential/knowledge/behavioral), RelationshipType enum,
     MemoryScope enum.
   - `src/memoryhub_core/services/graph.py` -- existing graph traversal:
     `collect_graph_neighbors()` (recursive CTE, 3-hop cap),
     `find_related()` (BFS, 2-hop default), `get_subtree()`,
     `trace_provenance()`.

2. **Write design doc** (`planning/procedural-graphs.md`)
   Cover:
   - How procedural graphs map onto the existing memory tree. The paper's
     formalism is G = (V, R, E, Phi): nodes are action/reasoning steps,
     edges are transitions, attributes are conditions/guidance/pitfalls.
   - Whether `procedural` should be a new ContentType value or a
     subclassification of `behavioral`. The research doc notes behavioral
     covers "patterns, habits, learned routines" -- procedural graphs are
     more structured than that. Recommend a new ContentType value.
   - New relationship types needed: `precedes` (step ordering),
     `requires` (precondition), `alternative_to` (branching paths).
     These extend the existing RelationshipType enum.
   - Node attribute schema for procedural nodes: action description,
     preconditions (list), postconditions (list), pitfalls (list),
     guidance text. These can live in the existing JSON `metadata_`
     column or as new columns.
   - How procedural graph nodes relate to regular memories: a procedural
     graph is rooted at a regular memory node with `content_type=procedural`,
     and its steps are child nodes linked by the new relationship types.
   - Scope considerations: procedural graphs are typically project-scoped
     (how to deploy X) or user-scoped (how I debug Y).

3. **Extend ContentType enum** (`src/memoryhub_core/models/schemas.py`)
   Add `PROCEDURAL = "procedural"` to ContentType. Update the String(20)
   column width if needed (it fits). Update any validation that
   enumerates content types.

4. **Extend RelationshipType enum** (`src/memoryhub_core/models/schemas.py`)
   Add `precedes`, `requires`, `alternative_to`. These are the minimum
   set for encoding procedural graph structure.

5. **Alembic migration**
   Migration to add the new content type and relationship type values.
   Since these are application-level enums (StrEnum checked at the API
   layer, not DB-level CHECK constraints), the migration may only need
   to widen the String column if needed. Verify by checking how the
   existing enum values are enforced.

6. **Tests**
   - ContentType validation accepts `procedural`
   - RelationshipType validation accepts new edge types
   - A procedural graph can be created: root node with
     `content_type=procedural`, child step nodes linked by `precedes`
     edges
   - `collect_graph_neighbors()` traverses procedural edges correctly
   - `find_related()` returns step nodes from a procedural root

**Sequencing.** Items 1-2 are the foundation (read, then design). Items
3-5 are the implementation. Item 6 validates. Don't skip the design doc.

**Constraints for the session:**
- Schema and design only. No retrieval changes (#553), no extraction
  logic (#554), no rejection tracking (#555).
- The design doc informs all subsequent phases. Spend time getting the
  graph structure right.
- Check whether the `metadata_` JSON column is sufficient for step
  attributes or whether dedicated columns are warranted. The paper's
  node attributes (preconditions, postconditions, pitfalls, guidance)
  are structured enough to merit their own fields, but JSON avoids a
  migration for every attribute addition.

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  - Cluster health: `oc get pods --context mcp-rhoai -n memory-hub-mcp`
  - Current ContentType values: `grep -A5 "class ContentType" src/memoryhub_core/models/schemas.py`
  - Current RelationshipType values: `grep -A10 "class RelationshipType" src/memoryhub_core/models/schemas.py`
  - Verify String column widths in memory.py model
- Rules with history:
  - All pushes through PRs (no direct main pushes)
  - Schema changes require Alembic migration (CLAUDE.md)
  - Commit incrementally, not batched at end
- Stop-and-ask before:
  - Adding new columns to MemoryNode (use metadata_ JSON first)
  - Changing existing relationship type behavior

**Exit predicate:**
- Design doc `planning/procedural-graphs.md` exists and covers the
  mapping from paper formalism to MemoryHub schema
- ContentType enum includes `procedural`
- RelationshipType enum includes `precedes`, `requires`, `alternative_to`
- Alembic migration committed
- Tests pass: procedural graph creation, traversal, validation
- PR opened targeting `main`

## Remaining epic phases

Procedural graphs as a first-class memory structure in MemoryHub. The
paper (arXiv 2609.09153) showed that storing procedures as directed
attributed graphs and retrieving localized subgraphs materially improves
agent task completion. This epic adds the schema, retrieval mode,
extraction pipeline, and rejection tracking to support procedural
knowledge.

### Phase 1: Schema and design (#552)

Add the `procedural` content type and procedural relationship types to
the memory tree. Write the design doc that maps the paper's formalism
onto MemoryHub's existing graph infrastructure.

**Work:**
1. Design doc covering graph structure, node attributes, relationship
   types, and scope model
2. Extend ContentType and RelationshipType enums
3. Alembic migration
4. Tests for creation and traversal of procedural graphs

**Definition of done:** A procedural graph can be created, stored, and
traversed using existing graph service functions. Design doc reviewed
and committed.

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of all other epics.

### Phase 2: Localized graph retrieval (#553)

Implement graph-aware retrieval that returns a bounded 2-hop neighborhood
around the agent's current step, then generates natural-language guidance
from the subgraph.

**Work:**
1. Search mode that detects procedural-graph queries (by content_type
   or explicit parameter)
2. Subgraph extraction: given a current-step node ID, retrieve 2-hop
   neighborhood using existing `find_related()` / `collect_graph_neighbors()`
3. Guidance generation: convert the localized subgraph (step descriptions,
   conditions, pitfalls) into natural-language guidance. This may use an
   LLM call or a template-based approach.
4. MCP tool surface: expose procedural retrieval through the search tool
   or a dedicated `get_procedure` tool
5. Tests and benchmarks comparing localized vs full-graph injection

**Definition of done:** An agent can query "how do I do X" and receive
localized procedural guidance from the relevant subgraph. Token overhead
is measurably lower than full-graph injection.

**Dependencies:** Phase 1 (#552 -- schema must exist).

**Parallel-ok:** Yes -- independent of Phases 3-4.

### Phase 3: Procedural graph extraction from dreaming (#554)

Extend the dreaming pipeline to detect procedural patterns in session
transcripts and build/refine procedural graphs automatically.

**Work:**
1. Trajectory analysis: identify action sequences in conversation
   messages (tool calls, reasoning steps, decision points, outcomes)
2. Graph construction: build procedural graphs from detected patterns
3. Iterative refinement: compare new sessions against existing procedural
   graphs and propose structural edits (add/remove nodes and edges)
4. Wire into dreaming pipeline as a post-extraction step or a separate
   curation sweep (using the AgentPlugin framework from #350)

**Definition of done:** The dreaming system can detect a multi-step
procedure in a session transcript and create a procedural graph from it.
Subsequent sessions covering the same procedure refine the graph rather
than creating duplicates.

**Dependencies:** Phase 1 (#552 -- schema). Benefits from curation epic
#350 (AgentPlugin framework) but can use a simpler integration initially.

**Parallel-ok:** Yes -- independent of Phase 2.

### Phase 4: Rejection memory (#555)

Add rejection tracking to dreaming and curation so failed extraction or
edit proposals are cached and used as negative signals.

**Work:**
1. Rejection log schema (table or metadata on existing nodes)
2. Integration with dreaming extraction (track rejected candidates)
3. Integration with curation rules (connect to `reject_with_pointer`)
4. Observability: rejection analytics and dashboard

**Definition of done:** Failed extraction proposals are logged. The
dreaming system checks the rejection log before re-proposing known-bad
extractions. Rejection counts are visible in observability.

**Dependencies:** None (can be done independently). Most valuable after
Phase 3 (#554) where graph refinement generates the most rejections.

**Parallel-ok:** Yes -- independent of all other phases.

---

## What this covers (and what it doesn't)

**In scope:**
- #552 Procedural graph memory type (schema, design)
- #553 Localized graph retrieval (2-hop neighborhood)
- #554 Procedural graph extraction from dreaming
- #555 Rejection memory for failed proposals

**Out of scope (other epics own):**
- #350-353 Curator scaffold and sweeps (curation epic)
- #404, #306, #397, #453, #454, #370 Retrieval polish (retrieval-polish epic)
- #345 Layer 3 reflection (curation epic, but #554 builds toward it)

**Cross-epic dependencies:**
- Phase 3 (#554) benefits from curation #350 (AgentPlugin base class)
  but is not hard-blocked on it. Can use a simpler standalone sweep
  initially and migrate to AgentPlugin when the scaffold ships.
- Phase 2 (#553) relates to retrieval-polish #454 (entity-aware search)
  and #273 (graph traversal benchmark). Both would benefit from the
  procedural retrieval mode.

## What landed last session

(No sessions yet for this epic. Created 2026-09-09 from arXiv 2609.09153
analysis.)

## Watch out for

- **ContentType column width.** The `content_type` column is `String(20)`.
  "procedural" is 10 chars, fits fine. But verify no hard-coded
  validation lists exist beyond the StrEnum.
- **Relationship type proliferation.** Adding 3 new types (precedes,
  requires, alternative_to) to the existing 5. The graph service's
  `collect_graph_neighbors()` CTE doesn't filter by relationship type
  by default -- verify that procedural edges don't pollute regular
  graph-boosted search results. May need a `procedural_only` flag or
  relationship-type filtering on the search path.
- **Metadata vs columns for step attributes.** The paper's nodes have
  structured attributes (preconditions, postconditions, pitfalls,
  guidance). Using the JSON `metadata_` column is flexible but
  un-indexable. Start with JSON; migrate to columns only if query
  patterns demand it.
- **Existing graph traversal limits.** `collect_graph_neighbors()` caps
  at 3 hops, `find_related()` defaults to 2. The paper's best results
  used 2-hop neighborhoods, so existing defaults align well.

## If blocked

- If the design doc reveals that procedural graphs don't map cleanly
  onto the adjacency-list tree model: consider a separate table for
  procedural graph structure while keeping the root node in memory_nodes.
  The MemoryRelationship table is already a general-purpose edge table
  and should handle this.
- If schema changes are contentious: the ContentType and RelationshipType
  enums are application-level (StrEnum), not DB-level constraints. Adding
  new values is backwards-compatible.
- If cluster is unavailable: all Phase 1 work is local (SQLite tests,
  design doc writing). No cluster needed until deployment.
