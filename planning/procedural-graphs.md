# Procedural Graphs: Design Doc (#552)

**Status:** Design (for #552, phase 1 of the procedural-graphs epic; #553/#554/#555 out of scope)
**Date:** 2026-09-17

## Problem

MemoryHub's `content_type` classification has three values: `experiential`, `knowledge`,
`behavioral`. `behavioral` is meant to carry "how to do things" — demonstrated patterns and
successful approaches, surfaced today through the `reconstruct` MCP action
(`memory-hub-mcp/src/tools/memory.py`), which is a thin alias for
`search(content_type="behavioral")` with weight-based ordering. The content itself is stored
and returned as flat text.

"Procedural Graphs: Self-Evolving Execution Structures for LLM Agents" (arXiv 2609.09153)
reports that representing procedural knowledge as a directed attributed graph — nodes as
action/reasoning steps, edges as transitions carrying conditions, guidance, and pitfalls — and
retrieving a localized subgraph around the agent's current step outperforms flat-text and
episodic-memory baselines: first or tied-first place in 21/24 model×benchmark combinations
across 6 benchmarks and 4 LLM families, ahead of MemoryBank, RAP, ExpeL, AutoGuide, AWM, and
KnowAgent.

This doc is Phase 1 of the epic tracked across #552–#555 (see
`NEXT_SESSION-procedural-graphs.md`): schema and design only. No retrieval changes (#553), no
extraction from the dreaming pipeline (#554), no rejection tracking (#555).

## The paper's formalism, mapped onto MemoryHub

The paper defines a procedural graph as 𝒢 = (𝒱, ℛ, ℰ, Φ):

- 𝒱 — nodes, each an action (tool call) or reasoning step
- ℛ — a relation vocabulary
- ℰ ⊆ 𝒱 × ℛ × 𝒱 — directed, typed edges (transitions)
- Φ — attributes on nodes and edges (preconditions, guidance text, known pitfalls)

MemoryHub already has two structures that, combined, cover this without new tables:

| Paper concept | MemoryHub mechanism |
|---|---|
| Procedure (the graph as an addressable whole) | A `MemoryNode` with `content_type=procedural` — the thing search/list/read returns |
| Step node 𝒱 | A `MemoryNode` with `parent_id` pointing at the procedure node, `branch_type="procedure_step"` |
| Node attributes Φ(v) | `MemoryNode.metadata_` (JSON) on each step node |
| Transition (procedure, relation, procedure) ⊆ ℰ | A `MemoryRelationship` row between two step nodes |
| Edge attributes Φ(e) | `MemoryRelationship.metadata_` (JSON) on that edge |
| Relation vocabulary ℛ | Three new `RelationshipType` values: `precedes`, `requires`, `alternative_to` |

This is two independent structures doing two independent jobs, which is why it maps cleanly:
`parent_id` gives *membership* ("these N nodes are the steps of procedure X"), and
`memory_relationships` gives *topology* ("step 3 precedes step 4, unless condition C, in
which case see step 6"). `get_subtree(procedure_id)` already returns membership;
`find_related()` / `collect_graph_neighbors()`, filtered to the three new relationship types,
already return topology. Nothing about procedural graphs required inventing a graph layer —
MemoryHub already separated "what belongs together" from "what connects to what," and this
feature is the first consumer to need both on the same object.

## Decision 1: new top-level `ContentType.PROCEDURAL`, not a `behavioral` subtype

**Recommendation: new top-level enum value.**

The alternative — a `behavioral_subtype` field distinguishing flat behavioral text from
graph-structured procedures — looks cheaper at first glance but isn't, once you look at how
`content_type` is actually used:

- `reconstruct` (`memory-hub-mcp/src/tools/memory.py:405-408`) hard-filters on
  `content_type="behavioral"` and returns results as a flat, weight-sorted list for "pattern
  replay." A procedural graph's step nodes are not independently meaningful text to inject this
  way — returning them through `reconstruct` would silently interleave graph fragments into a
  flat list a caller has no way to reassemble. A subtype field pushes the job of filtering them
  back out onto every current and future caller of `content_type="behavioral"`; a distinct
  top-level value means `reconstruct` simply never sees them, by construction.
- `services/reconciliation.py` uses `content_type` equality as one signal for "is this
  candidate the same memory as an existing one." A subtype would need to be folded into that
  match logic too, or dedup would start comparing flat behavioral text against procedure-step
  text as if they were the same kind of thing.
- `search_memory` and `list_memory` already expose `content_type` as an equality filter
  end-to-end (MCP tool parameter → service layer → SQL `WHERE`). A subtype requires threading a
  *second* filter parameter through the same path to get the same selectivity a new enum value
  gives for free.
- The only place a fourth `content_type` value costs anything is the DB `CHECK` constraint (see
  Decision 3) — one migration, not a chain of call-site changes.

`ContentType.PROCEDURAL = "procedural"` (9 chars, well under the `String(20)` column width).

## Decision 2: reuse the existing adjacency structure — it already handles non-tree graphs

The open question was whether `memory_relationships` is a general graph or assumes strict-tree
shape, since the paper's procedural graphs are not necessarily DAGs (retry loops back to an
earlier step are a normal pattern in agent execution traces).

Checked against `src/memoryhub_core/models/memory.py`: `MemoryRelationship` has exactly one
structural constraint, `CheckConstraint("source_id != target_id", name="ck_memory_relationships_no_self_ref")`
— it forbids a self-loop, nothing else. There is no acyclicity constraint and no fan-in limit;
a node can have multiple incoming and outgoing edges of different types, and a 3+ node cycle is
permitted (A `precedes` B, B `precedes` C, C `precedes` A is a valid set of rows). The recursive
CTE in `collect_graph_neighbors()` bounds traversal by hop count, not by DAG-ness, so a cycle
doesn't loop forever — it just gets visited once via the `GROUP BY node_id` min-depth
aggregation.

Concretely, this means `memory_relationships` was already built as a general directed
multigraph over `memory_nodes`, separate from the `parent_id` tree. It does not need to be
extended, generalized, or bypassed for procedural graphs — it needs three new
`RelationshipType` values and, per edge, an attribute payload.

`parent_id` tree membership stays shallow and simple (procedure → its steps, one level), which
matches the existing "trees are 3-4 levels" assumption noted in
`research/surveys/knowledge-and-graph-memory.md` §6. All the graph complexity — branching,
loops, multiple predecessors — lives in `memory_relationships`, where it was already designed
to live.

## Decision 3: schema changes

### 3a. `ContentType` (application enum + DB constraint)

`src/memoryhub_core/models/schemas.py`:

```python
class ContentType(StrEnum):
    """Content classification for behavioral memory (#237)."""

    EXPERIENTIAL = "experiential"
    KNOWLEDGE = "knowledge"
    BEHAVIORAL = "behavioral"
    PROCEDURAL = "procedural"
```

**Correction to `NEXT_SESSION-procedural-graphs.md`'s assumption:** that doc speculates content
types are "application-level (StrEnum), not DB-level constraints" and that the migration "may
only need to widen the String column if needed." That's true for `RelationshipType` (see 3b)
but not for `ContentType`. Migration `017_add_content_type.py` added a real
`CHECK` constraint:

```python
op.create_check_constraint(
    "ck_memory_nodes_content_type",
    "memory_nodes",
    "content_type IN ('experiential', 'knowledge', 'behavioral')",
)
```

So a new Alembic migration is required — not to widen a column, but to drop and recreate this
constraint:

```python
def upgrade() -> None:
    op.drop_constraint("ck_memory_nodes_content_type", "memory_nodes")
    op.create_check_constraint(
        "ck_memory_nodes_content_type",
        "memory_nodes",
        "content_type IN ('experiential', 'knowledge', 'behavioral', 'procedural')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memory_nodes_content_type", "memory_nodes")
    op.create_check_constraint(
        "ck_memory_nodes_content_type",
        "memory_nodes",
        "content_type IN ('experiential', 'knowledge', 'behavioral')",
    )
```

`String(20)` already fits `"procedural"`; no column-width change needed. The composite indexes
`ix_memory_nodes_content_type` and `ix_memory_nodes_content_type_scope` need no changes — they
index the column, not its allowed values.

### 3b. `RelationshipType` (application enum only — no DB constraint exists)

`memory_relationships.relationship_type` is `String(50)` with **no** `CHECK` constraint
(confirmed against `alembic/versions/003_add_memory_relationships.py` and every later migration
that touches the table). Validation is enforced entirely at the Pydantic/API layer via the
`RelationshipType` StrEnum, referenced directly by `RelationshipCreate.relationship_type` and
`RelationshipRead.relationship_type`. Adding values here needs **no Alembic migration**:

```python
class RelationshipType(StrEnum):
    """Controlled vocabulary for graph edge types between memory nodes."""

    derived_from = "derived_from"
    supersedes = "supersedes"
    conflicts_with = "conflicts_with"
    related_to = "related_to"
    mentions = "mentions"  # Phase 2: memory -> entity (system-managed)
    precedes = "precedes"          # step ordering
    requires = "requires"          # precondition
    alternative_to = "alternative_to"  # branching path
```

`memory-hub-mcp/src/tools/manage_graph.py` derives its runtime allowlist from the enum
(`_VALID_TYPES = [t.value for t in RelationshipType]`), so validation there updates for free.
Two things in that file are *not* derived and need a manual edit:

1. The `relationship_type` `Field(description=...)` on `manage_graph()` hardcodes prose —
   `"Must be one of: derived_from, supersedes, conflicts_with, related_to."` — that will now be
   wrong. Update it to list the three new types (and note that `mentions` stays excluded from
   this list, as it already is, since it's system-managed).
2. `mentions` is special-cased and rejected from manual creation
   (`if relationship_type == "mentions": raise ToolError(...)`) because it's written only by the
   entity-extraction pipeline. `precedes`/`requires`/`alternative_to` should **not** get the same
   treatment in Phase 1 — until #554 (graph extraction from dreaming) exists, manual creation via
   `relate` is the only way anyone builds a procedural graph at all. Revisit this exclusion when
   #554 ships an automated writer.

Also update the `content_type` `Field(description=...)` in `memory-hub-mcp/src/tools/write_memory.py`
to mention `procedural`. Note in passing: that docstring already says `"Use 'declarative' for
facts and preferences"`, but the actual enum value is `knowledge` — a pre-existing doc/enum
drift unrelated to this issue, worth a one-line fix while the docstring is being touched anyway.

### 3c. Node attributes Φ(v) — `MemoryNode.metadata_`, no new columns

Per-step attributes go in the existing JSON `metadata_` column, following
`NEXT_SESSION-procedural-graphs.md`'s recommendation to start with JSON and add dedicated
columns only if query patterns demand indexing them. `MemoryNodeCreate.metadata` /
`RelationshipCreate.metadata` are typed `dict[str, Any] | None`, so Pydantic only confirms the
value is a JSON object -- it does not enforce the internal shape below (which keys exist, their
types, or that they're present at all). Nothing validates the `procedure` shape at write time,
at the DB layer, or anywhere else in Phase 1; a malformed or missing `action`/`tool_ref`/etc.
is accepted silently. Suggested shape, by convention only:

```json
{
  "procedure": {
    "action": "Run the pre-deploy smoke test suite",
    "tool_ref": "run_tests.sh --suite=smoke",
    "preconditions": ["staging environment is healthy"],
    "postconditions": ["all smoke tests green"],
    "pitfalls": ["flaky test test_cache_warmup fails ~5% of the time; retry once before escalating"],
    "guidance": "If this step fails twice, do not proceed to deploy — check #incidents first."
  }
}
```

The root procedure node's own `content` field carries the human-readable summary of the whole
procedure (what today's flat `behavioral` text would have said); `metadata_.procedure` on the
root can optionally hold graph-level attributes (e.g. an `entry_step_id`, since a procedure
graph needs a defined start).

### 3d. Edge attributes Φ(e) — `MemoryRelationship.metadata_`, no new columns

Already JSON with a `{}` default; no migration needed. Shape:

```json
{
  "condition": "smoke tests failed",
  "guidance": "Roll back the last deploy before retrying.",
  "pitfalls": ["rollback script requires the previous image tag, not 'latest'"]
}
```

## Retrieval and traversal — explicitly deferred to #553, but already partly reusable

The issue (and the survey doc's phase framing) asks how an agent queries and walks the graph at
runtime. That's #553's job, not this doc's — but it's worth recording what Phase 1's schema
choice gets for free, so #553 doesn't reinvent it:

- "Give me all the steps of procedure X" is `get_subtree(procedure_node_id)` — already exists,
  no changes.
- "Give me the 2-hop neighborhood around the step the agent is currently on" is
  `find_related(current_step_id, relationship_types=["precedes", "requires", "alternative_to"])`
  — already exists, no changes. Its default `max_hops=2` matches the paper's own best-performing
  neighborhood size, per `research/surveys/knowledge-and-graph-memory.md`'s "Watch out for"
  note in `NEXT_SESSION-procedural-graphs.md`.
- What's genuinely missing (and belongs in #553): a way to *enter* the graph — resolve "how do I
  deploy X" to a procedure node and its entry step — and a way to turn a localized subgraph into
  natural-language guidance for the agent. `reconstruct` should almost certainly stay
  `behavioral`-only rather than absorbing `procedural`; a separate action (the `get_procedure`
  name floated in `NEXT_SESSION-procedural-graphs.md` is reasonable) keeps the two retrieval
  shapes — flat weight-sorted list vs. localized subgraph — from being forced through one
  parameter surface.
- One thing #553 will need to decide that Phase 1 should not preempt: whether
  `collect_graph_neighbors()`'s default (no relationship-type filter) should keep including
  procedural edges in general graph-boosted search re-ranking, or whether procedural edges
  should be excluded from that path by default and only surfaced through the dedicated
  procedural-retrieval entry point. Flagged here since it's the one place the new edge types
  could silently affect existing (non-procedural) search behavior if `relationship_types` is
  left unset somewhere in the reranking path — worth an explicit check in #553, not a Phase 1
  concern since Phase 1 adds no reranking-path callers.

## Scope

No changes needed. `MemoryScope` already covers `user`/`project`/campaign/etc.; a procedure is
scoped exactly like any other memory node (its root node's `scope`/`scope_id` govern it, and its
step children inherit visibility the same way any parent/child pair in the tree already does).

## Migrating existing `behavioral` records

Out of scope for Phase 1, and there's no forced migration: existing `behavioral` memories stay
exactly as they are, flat text, queryable by `reconstruct` as today. `procedural` is opt-in for
new writes only. If a maintainer later wants to promote a specific `behavioral` memory into a
`procedural` graph (i.e., decompose its flat text into step nodes), that's a curation job worth
scoping separately once #554's extraction pipeline exists to do this automatically — doing it by
hand for existing records isn't blocking anything in this epic.

## Tests (Phase 1 exit criteria, from `NEXT_SESSION-procedural-graphs.md`)

- `ContentType` validation accepts `procedural` (Pydantic layer) and the DB `CHECK` constraint
  accepts an insert with `content_type='procedural'` (catches the migration-forgotten case,
  since this is exactly the kind of failure Decision 3a's correction would have produced if the
  DB constraint had been missed).
- `RelationshipType` validation accepts `precedes`, `requires`, `alternative_to` at both the
  Pydantic layer and through `manage_graph`'s `_VALID_TYPES` allowlist.
- A procedural graph can be created end-to-end: root node with `content_type=procedural`, 3+
  step nodes with `parent_id` set to the root and `branch_type="procedure_step"`, linked by a
  mix of `precedes`/`requires`/`alternative_to` edges (including one edge that creates a 3-node
  cycle, to confirm the "no acyclicity constraint" claim in Decision 2 holds in practice, not
  just in the schema).
- `get_subtree(root_id)` returns all step nodes.
- `find_related(step_id, relationship_types=["precedes", "requires", "alternative_to"])` returns
  the correct neighbors and excludes edges of other types (e.g. a `related_to` edge coincidentally
  touching one of the same nodes).
- `collect_graph_neighbors()` traverses procedural edges correctly when explicitly filtered, and
  — per the open question above — a test asserting current default (unfiltered) behavior doesn't
  change for non-procedural callers, so #553 has a baseline to compare against.
- Existing `reconciliation.py` content-type-match tests still pass unmodified (confirms adding a
  4th enum value doesn't perturb the equality-based dedup signal for the other three).

## Out of scope (owned by later phases)

- #553 — localized graph retrieval, subgraph-to-guidance generation, MCP surface (`get_procedure`
  or equivalent).
- #554 — automatic procedural graph extraction/refinement from the dreaming pipeline.
- #555 — rejection tracking for failed extraction/edit proposals.
- Benchmarking the schema against one of the paper's benchmarks (or an internal task set) to
  confirm the structure earns its complexity in MemoryHub's own retrieval context, not just in
  the paper — worth doing once #553 makes the graph queryable, since Phase 1 alone (schema with
  no retrieval path) has nothing to benchmark yet.

## Open questions carried forward

1. Should `precedes`/`requires`/`alternative_to` remain manually creatable indefinitely, or
   should they become system-managed (like `mentions`) once #554 ships automated extraction?
   Leaning toward: keep manual creation available even after #554, since hand-authored
   procedures (a human writing down a known-good runbook) are a legitimate first-class use case,
   not just a bootstrapping measure.
2. Should a procedure's entry point be a convention (e.g. "the step with no incoming `precedes`
   edge") or an explicit field (`metadata_.procedure.entry_step_id` on the root, as sketched in
   3c)? The explicit field is more robust against graphs with multiple valid entry points
   depending on context, and costs nothing since it's already inside the JSON blob — recommend
   deciding this in #553 once there's an actual reader that needs to resolve it, rather than
   guessing the shape now.
