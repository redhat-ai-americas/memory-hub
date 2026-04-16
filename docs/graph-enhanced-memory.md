# Graph-Enhanced Memory

**Issue**: #170
**Date**: April 2026
**Status**: Design

## Summary

This document specifies a three-phase evolution of MemoryHub's graph layer: temporal validity on relationships (Phase 1), automatic entity extraction at write time (Phase 2), and a deferred decision point on a dedicated graph computation backend (Phase 3). Phases 1 and 2 run entirely on the existing PostgreSQL + pgvector stack. The goal is to close the key accuracy gaps identified in the research survey — specifically multi-hop reasoning and temporal consistency — without introducing new infrastructure dependencies.

## Strategic Context

The 2026 research consensus is that hybrid vector+graph retrieval outperforms either approach alone. Hindsight achieves 91.4% on LongMemEval with a four-network architecture; vector-only Mem0 scores 49.0% on the same benchmark. The accuracy gap widens specifically on multi-session, temporal, and knowledge-update questions — exactly the classes of queries a long-running agent memory system must handle well.

MemoryHub already has structural advantages most competing systems lack: typed directed edges (`memory_relationships`), a versioned tree with provenance tracking, contradiction reporting, multi-scope RBAC, and an RRF blend already wired into `search_memories_with_focus`. The gaps are narrower than the benchmark gap suggests: we lack temporal validity on edges, graph-assisted retrieval in the search path, and automatic entity extraction.

PostgreSQL-first is the right default. The survey's analysis of MemoryHub's scale profile (hundreds of agents, thousands of memories per user, 3–4 hop depth) confirms recursive CTEs are sufficient for Phase 1 traversal. AGE remains deferred — it is still in the Apache Incubator as of April 2026, does not auto-create indexes, and has a performance ceiling below dedicated graph databases for the workloads we will eventually need. The honest path is: extend PostgreSQL for Phases 1 and 2, then make a clean, informed decision about a graph computation layer in Phase 3 when actual query patterns are observable.

**Relationship to RetrievalHub**: MemoryHub is the experiential/episodic layer — what this agent knows from its own interactions. Any future RetrievalHub is the factual/document layer — what can be retrieved from a corpus. The entity graph built here is intentionally agent-scoped and conversation-derived. Do not conflate it with a document knowledge graph.

## Phase 1: Temporal Relationships and Graph-Enhanced Retrieval

### Temporal Validity

#### Schema Changes

Add two nullable columns to `memory_relationships`:

```sql
valid_from   TIMESTAMPTZ  NOT NULL DEFAULT now()
valid_until  TIMESTAMPTZ  NULL     DEFAULT NULL
```

A row with `valid_until IS NULL` is active. Invalidation sets `valid_until = now()`, never deletes the row.

The existing `created_at` column tracks when the system recorded the relationship; `valid_from` tracks when the relationship became semantically valid. For most cases these will be equal. The distinction matters when an agent back-dates a relationship (e.g., "this policy superseded the old one as of last month").

The Alembic migration (`013_add_relationship_validity.py`) must:
1. Add `valid_from` with `server_default=func.now()`, backfilled from `created_at`.
2. Add `valid_until` as nullable.
3. Add a partial index: `CREATE INDEX ON memory_relationships (valid_until) WHERE valid_until IS NOT NULL;`
4. Add a composite index: `CREATE INDEX ON memory_relationships (source_id, relationship_type, valid_until);`

#### Invalidation Semantics

Invalidation is not deletion. When a relationship becomes no longer valid:

```python
async def invalidate_relationship(
    rel_id: uuid.UUID,
    session: AsyncSession,
    *,
    valid_until: datetime | None = None,
) -> None:
    now = valid_until or datetime.now(tz=timezone.utc)
    stmt = (
        update(MemoryRelationship)
        .where(MemoryRelationship.id == rel_id)
        .where(MemoryRelationship.valid_until.is_(None))  # idempotent
        .values(valid_until=now)
    )
    await session.execute(stmt)
```

The `uq_memory_relationships_edge` unique constraint (source, target, type) prevents re-creating the same active edge while an active one exists. When a relationship is invalidated, a new one with the same endpoints can be created, giving a full audit trail of edge lifecycles.

The existing `MemoryRelationship` model comment ("immutable — create or delete, never update") is partially superseded: `valid_until` is the sole mutable field, settable only to the current time or a past time. All other columns remain immutable.

#### "What Was True at Time T?" Queries

```python
def active_at(t: datetime) -> BinaryExpression:
    """SQLAlchemy filter for relationships active at time t."""
    return and_(
        MemoryRelationship.valid_from <= t,
        or_(
            MemoryRelationship.valid_until.is_(None),
            MemoryRelationship.valid_until > t,
        ),
    )
```

All relationship queries in `services/graph.py` (`get_relationships`, `trace_provenance`) gain an optional `as_of: datetime | None = None` parameter. When `None`, the default filter is `valid_until IS NULL` (current active edges only), preserving backward compatibility.

### Graph-Enhanced Retrieval

#### Algorithm

After `search_memory` returns top-N results by vector similarity, follow outgoing and incoming relationships from each result to collect connected nodes. Combine the original set with the neighbor set, then apply RRF to re-rank.

```
vector search → top_k candidates
    ↓
hop traversal → neighbor nodes (filtered by tenant, scope, RBAC)
    ↓
union of candidates + neighbors (deduped)
    ↓
RRF blend (vector rank + graph proximity rank)
    ↓
top max_results
```

Graph proximity rank: nodes surfaced by graph traversal receive a rank based on hop distance (1-hop neighbors rank higher than 2-hop). Direct vector candidates that are also graph neighbors receive a bonus from the graph rank signal.

This is a fourth RRF signal alongside the existing query, focus, and domain signals in `search_memories_with_focus`. When `graph_depth=0` (the default for backward compatibility), the traversal step is skipped entirely.

#### Implementation in the Search Service Layer

Add to `services/memory.py`:

```python
async def collect_graph_neighbors(
    seed_ids: list[uuid.UUID],
    session: AsyncSession,
    *,
    tenant_id: str,
    max_depth: int = 1,
    relationship_types: list[str] | None = None,
    as_of: datetime | None = None,
) -> dict[uuid.UUID, int]:
    """Return {node_id: min_hop_distance} for all neighbors reachable from seed_ids."""
```

The function uses a recursive CTE bounded by `max_depth`. It filters on tenant, excludes soft-deleted nodes, and respects the `as_of` time filter. Return value is a dict so the hop distance is available for rank construction. Cap at `max_depth=3` hard maximum; deeper traversal on a PostgreSQL recursive CTE is expensive and rarely meaningful for agent memory.

Update `search_memories_with_focus` signature:

```python
async def search_memories_with_focus(
    query: str,
    session: AsyncSession,
    embedding_service: EmbeddingService,
    *,
    tenant_id: str,
    focus_string: str,
    graph_depth: int = 0,
    graph_relationship_types: list[str] | None = None,
    ...
) -> FocusedSearchResult:
```

The `FocusedSearchResult` dataclass gains a `graph_neighbors_added: int` field for observability.

#### Performance Considerations

- `max_depth=1` is the recommended default. Depth 2 multiplies the neighbor candidate count significantly; depth 3 should require explicit opt-in.
- The recursive CTE terminates early when the hop frontier is empty; it does not enumerate the entire graph.
- Add a `LIMIT` inside the CTE to cap the neighbor candidate set at `k_recall * max_depth * 4` rows before the RBAC filter step.
- Relationship type filtering (`graph_relationship_types`) reduces traversal fan-out substantially. For most retrieval use cases, only `derived_from` and `related_to` are useful neighbors; `conflicts_with` and `supersedes` are better used for contradiction detection, not retrieval augmentation.
- Monitor with `EXPLAIN ANALYZE` on the combined query once indexes from migration 013 are in place.

### Search Tool Changes

The `search_memory` MCP tool gains two new optional parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `graph_depth` | `int` | `0` | Hop depth for graph-enhanced retrieval. 0 disables; max 3. |
| `graph_relationship_types` | `list[str]` | `null` | Limit traversal to these relationship types. Null means all. |

Backward compatibility: `graph_depth=0` produces identical results to the current implementation. No existing callers break.

The tool response gains two optional fields when `graph_depth > 0`:
- `graph_neighbors_added`: count of unique nodes surfaced by graph traversal
- `graph_fallback_reason`: if traversal was skipped (e.g., no relationships exist for the seed nodes), a human-readable reason

## Phase 2: Entity Extraction

### Entity Model

Entities are a specialization of the existing node structure, not a separate table. Introduce a new reserved `scope` value `"entity"` for entity nodes, with `branch_type` encoding the POLE+O type.

This avoids a new table and keeps the RBAC machinery, soft-delete, and versioning applicable without modification. The tradeoff is that entity nodes participate in the existing `memory_nodes` indexes (tenant, scope, owner) — acceptable given their expected count.

Alternative considered: a separate `entity_nodes` table. Rejected because it would require duplicating RBAC filters, soft-delete, and Alembic migration discipline across a parallel structure. The existing node model is expressive enough.

#### POLE+O Entity Types

Store in `branch_type`:

| Value | Meaning |
|---|---|
| `entity:person` | People, personas, user references |
| `entity:object` | Tools, products, systems, files |
| `entity:location` | Physical or logical locations |
| `entity:event` | Discrete occurrences, meetings, incidents |
| `entity:organization` | Teams, companies, projects |

The `content` field holds a canonical name. The `metadata_` JSON field holds aliases, confidence score, and extractor provenance.

Entity node example:
```python
MemoryNode(
    scope="entity",
    branch_type="entity:organization",
    content="MemoryHub",
    owner_id=owner_id,
    tenant_id=tenant_id,
    weight=0.6,  # lower than knowledge memories; entities are infrastructure
    metadata_={
        "aliases": ["memory-hub", "memoryhub"],
        "extraction_confidence": 0.92,
        "extracted_by": "spacy",
    },
)
```

#### Entity Deduplication Strategy

At write time, before creating a new entity node, query for existing entity nodes with similar names. Use two signals:

1. Exact match on canonical name (lowercased, stripped) — O(1) with a functional index.
2. Vector similarity on the entity name embedding — same pgvector index already used for memory search.

If a candidate with cosine similarity > 0.92 exists, return the existing entity node rather than creating a new one. Log the deduplication event with the confidence score.

Aliases are merged into `metadata_["aliases"]` on the existing node via `update_memory`. Do not create duplicate entity nodes for "PostgreSQL", "Postgres", and "PG" — canonicalize to the first-seen form with aliases.

Add a partial GIN index on `content` for entity nodes:

```sql
CREATE INDEX ix_entity_nodes_content ON memory_nodes
    USING gin(to_tsvector('english', content))
    WHERE scope = 'entity';
```

### Extraction Pipeline

Entity extraction runs asynchronously after `write_memory` commits, to avoid adding latency to the write path. The write returns immediately; extraction is a background task.

#### Multi-Stage Cascade

```
write_memory commits
    ↓
background: extract_entities_from_memory(memory_id)
    ├─ Stage 1: spaCy (~5ms)
    │   └─ Standard NER for person, location, organization
    ├─ Stage 2: GLiNER2 (~50ms) [if Stage 1 confidence < threshold]
    │   └─ Zero-shot for object, event types + domain-specific terms
    └─ Stage 3: LLM fallback (~500ms) [if total confidence < threshold]
        └─ Structured extraction prompt for complex cases
    ↓
dedup: match against existing entity nodes
    ↓
create or update entity nodes
    ↓
create MENTIONS relationships
```

Stage selection logic: run Stage 1 always. If Stage 1 identifies fewer than 2 entities with confidence > 0.8, continue to Stage 2. If Stage 2 coverage is still low, run Stage 3. For most agent memory content (short factual statements), Stage 1 alone will handle the majority of cases.

The LLM fallback uses a structured prompt targeting `gpt-4o-mini` (or the configured local SLM) with a JSON schema response. It extracts both entities and relationships between them — the only stage that extracts inter-entity relationships rather than entity-to-memory relationships.

#### Integration with write_memory

The extraction is triggered in the service layer after the transaction commits, using `asyncio.create_task`. The memory node exists in the database before extraction runs. If extraction fails, the memory write succeeds and the failure is logged — extraction is best-effort.

Add a `extraction_status` field to `metadata_` on the memory node: `"pending"` immediately after write, `"complete"` after extraction succeeds, `"failed"` with reason if extraction fails.

Expose `ENTITY_EXTRACTION_ENABLED` as an environment variable (default `false` until Phase 2 is fully deployed). This allows the feature to be toggled without a code change.

#### Performance Budget

| Stage | Latency | Triggered when |
|---|---|---|
| spaCy | ~5ms | Always |
| GLiNER2 | ~50ms | spaCy coverage low |
| LLM fallback | ~500ms | GLiNER2 coverage low |

The background task fires after commit; the calling agent sees no added latency. The concern is memory node volume: if 1,000 writes/hour arrive and 30% trigger GLiNER2, that's ~300 concurrent 50ms tasks. Bound the extraction task pool with a semaphore (configurable, default 10 concurrent extraction tasks) to prevent resource exhaustion.

### Entity-Aware Search

`search_memory` gains an optional `entities` parameter:

```python
entities: list[str] | None = None  # Filter to memories mentioning these entity names
```

When `entities` is provided, the SQL WHERE clause adds:

```sql
AND id IN (
    SELECT source_id FROM memory_relationships mr
    JOIN memory_nodes en ON en.id = mr.target_id
    WHERE mr.relationship_type = 'mentions'
      AND en.scope = 'entity'
      AND en.content = ANY(:entity_names)
      AND mr.valid_until IS NULL
)
```

The filter runs before vector similarity, as a pre-filter on the candidate set. This is a SQL predicate, not a post-filter — it uses the index on `relationship_type` and the entity content index added above.

Entity filtering composes with all existing filters (scope, owner, project, domain). An agent can ask "find memories related to MemoryHub that mention PostgreSQL" using both domain tags and entity filters.

### MENTIONS Relationship

Add `mentions` to the `RelationshipType` enum:

```python
class RelationshipType(StrEnum):
    derived_from = "derived_from"
    supersedes = "supersedes"
    conflicts_with = "conflicts_with"
    related_to = "related_to"
    mentions = "mentions"  # Phase 2: memory → entity
```

`MENTIONS` edges are automatically created by the extraction pipeline; they cannot be created manually via `create_relationship` (validate and reject). This keeps the vocabulary clean — agents link memories to memories; the system links memories to entities.

Alembic migration `014_add_entity_scope.py`:
1. Add `mentions` to the `relationship_type` CHECK constraint (if one exists) or document the VARCHAR approach.
2. Add the GIN index on entity content.
3. Add the partial index on `valid_until` for MENTIONS edges: `WHERE relationship_type = 'mentions'`.

The `create_relationship` tool's docstring updates to list `mentions` in the type vocabulary and explain it is system-managed.

## Phase 3: Strategic Decision Point (Deferred)

Phase 3 is not an implementation plan. It is a set of evaluation criteria for when to re-examine the graph compute backend. Revisit when any of the following is true:

- Graph traversal depth requirements exceed 3 hops regularly in production query logs.
- Community detection (grouping semantically related memories into clusters) becomes a required feature.
- Graph algorithm needs arise (centrality, path similarity, PageRank-style importance weighting).
- p95 latency of graph-enhanced retrieval exceeds 200ms after PostgreSQL tuning.

### Graph Computation Options

**NetworkX in-memory projection**: Load the entity and relationship graph from PostgreSQL at startup (or on a refresh schedule) into a NetworkX DiGraph. Run graph algorithms (connected components, community detection, centrality) in Python. Writes still go to PostgreSQL. This is the lowest-friction option: no new infrastructure, algorithms immediately available, FIPS inherited from Python. Limitation: the full graph must fit in memory; does not handle concurrent writes to the in-memory projection without synchronization.

**Apache AGE**: openCypher queries on existing PostgreSQL. Deferred — still in Apache Incubator as of April 2026. Re-evaluate when it graduates. AGE provides Cypher ergonomics and avoids a new database, but requires explicit index management and cannot match a native graph database's traversal performance.

**Neo4j**: The richest ecosystem (Neo4j Agent Memory library, Graphiti, Mem0 integration). Enterprise Edition required for graph-native access control (label and relationship-type permissions). Separate operational footprint — a new stateful service in OpenShift alongside PostgreSQL. Appropriate if community detection and deep traversal become core requirements and the operational overhead is acceptable.

The correct answer depends on observed production behavior in Phases 1 and 2. Do not choose a backend based on benchmarks from other systems; choose based on MemoryHub's actual query patterns.

### Reasoning Memory (Sketch)

Neo4j Agent Memory's reasoning tier — recording agent thought chains, tool calls, and decision sequences — is the one Phase 3 capability with no clean PostgreSQL-only equivalent. Reasoning traces are naturally graph-structured (thought → tool call → observation → conclusion) and benefit from trace similarity search. This is deferred because it requires agent-side instrumentation changes (the MCP server must capture trace metadata) as well as storage design. File a separate design issue when the reasoning memory requirement is concrete.

## Migration

### Phase 1

`013_add_relationship_validity.py`:
- Adds `valid_from TIMESTAMPTZ NOT NULL DEFAULT now()` to `memory_relationships`, backfilled from `created_at`.
- Adds `valid_until TIMESTAMPTZ NULL DEFAULT NULL`.
- Adds partial index on `valid_until WHERE valid_until IS NOT NULL`.
- Adds composite index on `(source_id, relationship_type, valid_until)`.
- No data loss; all existing relationships are treated as active (`valid_until = NULL`).

### Phase 2

`014_add_entity_extraction.py`:
- Adds GIN index on `memory_nodes.content WHERE scope = 'entity'`.
- Adds partial index on `memory_relationships` for MENTIONS type.
- No schema changes to `memory_nodes` itself — entity nodes use existing columns.
- Updates the `relationship_type` vocabulary (if constrained at DB level).

Both migrations run as non-destructive `ALTER TABLE ... ADD COLUMN` operations with no table locks on active rows (PostgreSQL 11+ instant ADD COLUMN for nullable columns; `valid_from` uses `DEFAULT` but is backfilled after the fact to avoid a table rewrite).

Deployment order: migrate first, deploy new code second. Phase 1 search enhancements must be guarded by `graph_depth=0` default so old callers observe no behavior change before code is deployed.

## Dependencies

**What this depends on**:
- PostgreSQL with pgvector (existing)
- `search_memories_with_focus` and its existing RRF infrastructure (existing)
- `memory_relationships` table and `services/graph.py` (existing)
- asyncio task infrastructure in the FastAPI app (existing)
- spaCy, GLiNER2 Python packages (new dependencies, Phase 2)
- A configured LLM endpoint for the fallback stage (Phase 2; reuse the embedding service infrastructure or configure separately)

**What depends on this**:
- `search_memory` MCP tool: gains `graph_depth` and `entities` parameters; backward compatible.
- `create_relationship` MCP tool: gains `mentions` in the type vocabulary (system-managed only).
- `get_relationships` MCP tool: gains `as_of` parameter for temporal queries.
- Any consumer that calls `search_memories_with_focus` directly — no interface break.
- Phase 3 backend decision: depends on observability data from Phase 1 and 2 production runs.

## Open Questions

1. **Extraction trigger for existing memories**: Phase 2 extraction runs at write time going forward. Do we backfill entity extraction for the existing memory corpus? Backfill could be done as a background migration task, but it will make a large number of LLM calls. Define scope and cost estimate before enabling `ENTITY_EXTRACTION_ENABLED=true` in production.

2. **Entity ownership and scope**: An entity node extracted from a user-scoped memory — who owns it? Options: (a) same owner as the source memory, (b) tenant-wide shared entity pool. Shared entity pool is more useful (deduplication across users) but requires careful RBAC design — a user should not be able to discover that another user mentioned an entity. Leaning toward option (a) with cross-user dedup deferred until the RBAC implications are fully designed.

3. **MENTIONS relationship directionality**: Currently `source_id → target_id` is `memory → entity`. Confirm this is the right direction for graph traversal semantics before migration 014 runs. (Alternative: entity → memory, to query "all memories mentioning this entity" as outgoing edges from the entity node.)

4. **GLiNER2 and FIPS**: GLiNER2 uses transformer model weights loaded at runtime. Verify this is compatible with the FIPS-mode Python environment (no MD5/SHA1 in the crypto path; model loading uses standard file I/O, not cryptographic operations). Likely fine, but requires explicit verification in the FIPS environment.

5. **Invalidation API surface**: Should `invalidate_relationship` be exposed as an MCP tool, or only callable internally (e.g., when `supersedes` is created automatically)? Explicit invalidation by agents could be useful for temporal modeling but creates a footgun if misused. Start internal-only; promote to a tool in a follow-on issue.

6. **Conflict between temporal filter and existing `get_relationships` behavior**: The current `get_relationships` tool returns all edges regardless of validity (since `valid_until` does not yet exist). After migration 013, the default must change to return only active edges. Callers relying on historical edges must use `as_of`. Document this as a behavior change in the Phase 1 migration notes.
