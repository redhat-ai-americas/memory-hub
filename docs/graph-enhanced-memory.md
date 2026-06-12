# Graph-Enhanced Memory

**Issue**: #170
**Date**: April 2026
**Status**: Phase 2 shipped (June 2026). Phases 1 and 3 deferred to Graph-Enhanced Retrieval epic.

## Epic Boundary

This design originally covered three phases as a single effort. During implementation, the work was split into two epics:

- **Entity Extraction epic** (closed, June 2026): Phase 2 -- extraction pipeline, entity model, entity management actions, backfill. All shipped.
- **Graph-Enhanced Retrieval epic** (future epic, not yet bootstrapped): Phase 1 -- temporal relationships, graph-enhanced search, entity-aware search filtering, `graph_depth`/`entities` search parameters. Not started.
- **Phase 3** (graph computation backend decision): Deferred until Phase 1 production data exists. Owned by the Graph-Enhanced Retrieval epic.

Sections below are annotated with **[Shipped]**, **[Deferred -- Graph-Enhanced Retrieval epic]**, or **[Deferred -- Phase 3]** to indicate status.

## Summary

This document specifies a three-phase evolution of MemoryHub's graph layer: temporal validity on relationships (Phase 1), automatic entity extraction at write time (Phase 2), and a deferred decision point on a dedicated graph computation backend (Phase 3). Phases 1 and 2 run entirely on the existing PostgreSQL + pgvector stack. The goal is to close the key accuracy gaps identified in the research survey -- specifically multi-hop reasoning and temporal consistency -- without introducing new infrastructure dependencies.

## Strategic Context

The 2026 research consensus is that hybrid vector+graph retrieval outperforms either approach alone. Hindsight achieves 91.4% on LongMemEval with a four-network architecture; vector-only Mem0 scores 49.0% on the same benchmark. The accuracy gap widens specifically on multi-session, temporal, and knowledge-update questions — exactly the classes of queries a long-running agent memory system must handle well.

MemoryHub already has structural advantages most competing systems lack: typed directed edges (`memory_relationships`), a versioned tree with provenance tracking, contradiction reporting, multi-scope RBAC, and an RRF blend already wired into `search_memories_with_focus`. The gaps are narrower than the benchmark gap suggests: we lack temporal validity on edges, graph-assisted retrieval in the search path, and automatic entity extraction.

PostgreSQL-first is the right default. The survey's analysis of MemoryHub's scale profile (hundreds of agents, thousands of memories per user, 3–4 hop depth) confirms recursive CTEs are sufficient for Phase 1 traversal. AGE remains deferred — it is still in the Apache Incubator as of April 2026, does not auto-create indexes, and has a performance ceiling below dedicated graph databases for the workloads we will eventually need. The honest path is: extend PostgreSQL for Phases 1 and 2, then make a clean, informed decision about a graph computation layer in Phase 3 when actual query patterns are observable.

**Relationship to RetrievalHub**: MemoryHub is the experiential/episodic layer — what this agent knows from its own interactions. Any future RetrievalHub is the factual/document layer — what can be retrieved from a corpus. The entity graph built here is intentionally agent-scoped and conversation-derived. Do not conflate it with a document knowledge graph.

## Phase 1: Temporal Relationships and Graph-Enhanced Retrieval [Deferred -- Graph-Enhanced Retrieval epic]

> **Implementation note (June 2026):** The temporal validity *schema* (migration `013_add_relationship_validity`) shipped as part of the entity extraction epic because MENTIONS edges use `valid_from`/`valid_until`. The `invalidate_relationship` internal function also shipped (Open Question #5). What remains deferred is everything that *consumes* the temporal data: graph-enhanced retrieval (`collect_graph_neighbors`, `graph_depth` on search), temporal queries via `as_of` parameter, entity-aware search filtering (`entities` parameter on `search_memory`), and the RRF graph proximity signal. The MCP tool accepts `graph_depth`, `graph_relationship_types`, `graph_boost_weight`, and `entities` parameters but does not yet wire them into the core search service.

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
3. Drop the existing unique constraint and replace it with a partial unique index:
   ```sql
   ALTER TABLE memory_relationships DROP CONSTRAINT uq_memory_relationships_edge;
   CREATE UNIQUE INDEX uq_memory_relationships_active_edge
     ON memory_relationships (source_id, target_id, relationship_type)
     WHERE valid_until IS NULL;
   ```
   The original constraint rejects any second row with the same `(source_id, target_id, relationship_type)` regardless of `valid_until`, so the invalidate-and-recreate pattern would raise `IntegrityError` at runtime without this change.
4. Add a partial index: `CREATE INDEX ON memory_relationships (valid_until) WHERE valid_until IS NOT NULL;`
5. Add a composite index: `CREATE INDEX ON memory_relationships (source_id, relationship_type, valid_until);`

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

The partial unique index `uq_memory_relationships_active_edge` enforces that only one active edge per (source, target, type) can exist. Invalidated edges (`valid_until IS NOT NULL`) are excluded from the uniqueness check, allowing the full audit trail of edge lifecycles.

The existing `MemoryRelationship` model comment ("immutable — create or delete, never update") is partially superseded: `valid_until` is the sole mutable field, settable only to the current time or a past time. All other columns remain immutable.

Note on column naming: the `MemoryRelationship` ORM model uses `metadata_` (trailing underscore) as both the Python attribute name and the actual PostgreSQL column name. This differs from `MemoryNode.metadata_`, which maps to the column named `metadata`. Any raw SQL written against `memory_relationships` must use `metadata_` as the column name.

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

Add to `services/graph.py` alongside the existing `find_related` and `trace_provenance` functions:

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

### Search Tool Changes [Deferred -- Graph-Enhanced Retrieval epic]

The `search_memory` MCP tool gains two new optional parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `graph_depth` | `int` | `0` | Hop depth for graph-enhanced retrieval. 0 disables; max 3. |
| `graph_relationship_types` | `list[str]` | `null` | Limit traversal to these relationship types. Null means all. |

Backward compatibility: `graph_depth=0` produces identical results to the current implementation. No existing callers break.

The tool response gains two optional fields when `graph_depth > 0`:
- `graph_neighbors_added`: count of unique nodes surfaced by graph traversal
- `graph_fallback_reason`: if traversal was skipped (e.g., no relationships exist for the seed nodes), a human-readable reason

## Phase 2: Entity Extraction [Shipped]

> The extraction pipeline, entity model, MENTIONS relationships, entity management actions, and backfill are all shipped. The **Entity-Aware Search** subsection below (filtering `search_memory` results by entity names) is deferred to the Graph-Enhanced Retrieval epic, since it requires the same search service integration as `graph_depth`.

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

1. Exact match on canonical name (lowercased, stripped) -- O(1) with a functional index.
2. Vector similarity on the entity name embedding -- same pgvector index already used for memory search.

If a candidate with cosine similarity > 0.92 exists, return the existing entity node rather than creating a new one. Log the deduplication event with the confidence score.

Aliases are merged into `metadata_["aliases"]` on the existing node via `update_memory`. Do not create duplicate entity nodes for "PostgreSQL", "Postgres", and "PG" -- canonicalize to the first-seen form with aliases.

Add a partial GIN index on `content` for entity nodes:

```sql
CREATE INDEX ix_entity_nodes_content ON memory_nodes
    USING gin(to_tsvector('english', content))
    WHERE scope = 'entity';
```

> **Implementation note (June 2026, #247):** The design's "exact match on canonical name via functional index" was replaced with **content-addressed hashing**. Entity deduplication uses a SHA-256 hash of `tenant_id:owner_id:normalized_name:entity_type` stored in the existing `content_hash` column on `memory_nodes`. Step 1 is a hash lookup (indexed, O(1)); Step 2 falls back to vector similarity if no hash match. This avoids a new functional index and reuses the `content_hash` column already present on the memory model. Race conditions on concurrent creation are handled by catching `IntegrityError` and retrying the hash lookup.

### Extraction Pipeline

Entity extraction runs asynchronously after `write_memory` commits, to avoid adding latency to the write path. The write returns immediately; extraction is a background task.

#### Multi-Stage Cascade

```
write_memory commits
    ↓
background: extract_entities_from_memory(memory_id)
    ├─ Stage 1: spaCy (~5ms)
    │   └─ Standard NER for person, location, organization
    ├─ Stage 2: GLiNER2 (~50ms) [always alongside Stage 1]
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

Stage selection logic: Stages 1 (spaCy) and 2 (GLiNER2) run always in parallel. If combined results produce fewer than 2 entities with confidence > 0.7, continue to Stage 3 (LLM fallback). For most agent memory content (short factual statements), Stages 1 and 2 combined will handle the majority of cases.

The LLM fallback uses a structured prompt targeting `gpt-4o-mini` (or the configured local SLM) with a JSON schema response. It extracts both entities and relationships between them -- the only stage that extracts inter-entity relationships rather than entity-to-memory relationships.

> **Implementation note (June 2026, #267):** The original design had GLiNER2 running *conditionally* (only when spaCy coverage was low). Live testing revealed that spaCy's `en_core_web_sm` aggressively tags technical terms and acronyms as ORG or GPE, inflating the "high-confidence entity count" and preventing the cascade from reaching Stage 2 even when spaCy's entity types were wrong. The fix: GLiNER now runs **unconditionally** alongside spaCy, and acronym-pattern entities from spaCy (matching `^[A-Z]{2,}$`) receive a confidence discount from 1.0 to 0.5. The old `_should_run_stage2` function is retained but deprecated. See "Stage 3 Implementation Notes" section below for live testing details.
>
> **Implementation note (June 2026, #249):** The LLM fallback targets `RedHatAI/gpt-oss-20b` via cluster-internal vLLM, not `gpt-4o-mini` as originally designed. Configuration is via `MEMORYHUB_LLM_EXTRACTION_URL` and `MEMORYHUB_LLM_EXTRACTION_MODEL` environment variables. When URL is empty, Stage 3 is disabled entirely.

#### Integration with write_memory

The extraction is triggered in the service layer after the transaction commits, using `asyncio.create_task`. The memory node exists in the database before extraction runs. If extraction fails, the memory write succeeds and the failure is logged — extraction is best-effort.

Add a `extraction_status` field to `metadata_` on the memory node: `"pending"` immediately after write, `"complete"` after extraction succeeds, `"failed"` with reason if extraction fails.

Expose `MEMORYHUB_ENTITY_EXTRACTION_ENABLED` as an environment variable (default `false` until Phase 2 is fully deployed). This allows the feature to be toggled without a code change.

#### Performance Budget

| Stage | Latency | Triggered when |
|---|---|---|
| spaCy | ~5ms | Always |
| GLiNER2 | ~50ms | Always (changed from conditional, #267) |
| LLM fallback | ~500ms | Stages 1+2 combined < 2 high-confidence entities |

The background task fires after commit; the calling agent sees no added latency. The concern is memory node volume: if 1,000 writes/hour arrive, all trigger both spaCy and GLiNER2 concurrently. Bound the extraction task pool with a semaphore (configurable via `entity_extraction_concurrency`, default 10 concurrent extraction tasks) to prevent resource exhaustion.

### Entity-Aware Search [Deferred -- Graph-Enhanced Retrieval epic]

`search_memory` gains an optional `entities` parameter:

```python
entities: list[str] | None = None  # Filter to memories mentioning these entity names
```

When `entities` is provided, the SQL WHERE clause adds:

```sql
AND id IN (
    SELECT mr.source_id FROM memory_relationships mr
    JOIN memory_nodes en ON en.id = mr.target_id
    JOIN memory_nodes src ON src.id = mr.source_id
    WHERE mr.relationship_type = 'mentions'
      AND en.scope = 'entity'
      AND en.content = ANY(:entity_names)
      AND mr.valid_until IS NULL
      AND src.owner_id = ANY(:authorized_owner_ids)
)
```

The join through `memory_nodes src` and the `owner_id` filter mirrors the `_build_search_filters` pattern used elsewhere in the search path, preventing entity names from leaking membership across tenants or users.

The filter runs before vector similarity, as a pre-filter on the candidate set. This is a SQL predicate, not a post-filter — it uses the index on `relationship_type` and the entity content index added above.

Entity filtering composes with all existing filters (scope, owner, project, domain). An agent can ask "find memories related to MemoryHub that mention PostgreSQL" using both domain tags and entity filters.

> **Implementation note (June 2026):** Entity-aware search filtering is not yet implemented in the core search service. The MCP tool accepts the `entities` parameter but it is not wired through to query filtering. The `find_entities_by_names` service function exists (`services/entity.py`) and provides the entity-ID lookup needed for the pre-filter join above, but the integration with `search_memories_with_focus` is deferred to the Graph-Enhanced Retrieval epic.

### MENTIONS Relationship [Shipped]

Add `mentions` to the `RelationshipType` enum:

```python
class RelationshipType(StrEnum):
    derived_from = "derived_from"
    supersedes = "supersedes"
    conflicts_with = "conflicts_with"
    related_to = "related_to"
    mentions = "mentions"  # Phase 2: memory → entity
```

`MENTIONS` edges are automatically created by the extraction pipeline; they cannot be created manually via `manage_graph(action="create_relationship", ...)` (validate and reject). This keeps the vocabulary clean — agents link memories to memories; the system links memories to entities.

Alembic migration `015_add_entity_extraction.py`:
1. Add the GIN index on entity content.
2. Add the partial index for MENTIONS edges: `(source_id, target_id) WHERE relationship_type = 'mentions' AND valid_until IS NULL`.

> **Implementation note:** No CHECK constraint on `relationship_type` -- the column is VARCHAR with no DB-level constraint. The `mentions` type is enforced at the application level. Migration number is `015`, not `014` as originally planned (see Migration section).

The `manage_graph(action="create_relationship", ...)` tool's docstring updates to list `mentions` in the type vocabulary and explain it is system-managed.

### Entity Management Actions [Shipped]

> **Implementation note (June 2026, #251):** The original design did not specify entity management actions. The following were added during implementation and shipped across MCP server, SDK, and CLI:
>
> - `list_entities` -- enumerate entities with MENTIONS counts, ordered by mention frequency, filterable by entity type. Paginated.
> - `merge_entities` -- merge source entity into target. Reassigns MENTIONS edges (skipping duplicates), adds source name to target aliases, soft-deletes source.
> - `rename_entity` -- rename canonical name, preserve old name as alias, recalculate content hash and embedding. Rejects if new name collides (directs user to merge instead).
> - `backfill_entities` -- MCP admin action that runs the 3-stage cascade on memories without `extraction_status`. Also available as K8s Job (`scripts/backfill-job.yaml`, `scripts/backfill-entities.py`).
>
> These actions use the unified `memory(action=...)` dispatch pattern. Entity management is scoped per-owner (same as entity deduplication).

## Phase 3: Strategic Decision Point (Deferred) [Deferred -- Phase 3]

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

### Phase 1 [Shipped]

`013_add_relationship_validity.py` (deployed April 2026):
- Adds `valid_from TIMESTAMPTZ NOT NULL DEFAULT now()` to `memory_relationships`, backfilled from `created_at`.
- Adds `valid_until TIMESTAMPTZ NULL DEFAULT NULL`.
- Drops `uq_memory_relationships_edge` and replaces it with partial unique index `uq_memory_relationships_active_edge` on `(source_id, target_id, relationship_type) WHERE valid_until IS NULL`.
- Adds partial index on `valid_until WHERE valid_until IS NOT NULL`.
- Adds composite index on `(source_id, relationship_type, valid_until)`.
- No data loss; all existing relationships are treated as active (`valid_until = NULL`).

### Phase 2 [Shipped]

`015_add_entity_extraction.py` (deployed May 2026):
- Adds GIN index on `memory_nodes.content WHERE scope = 'entity'`.
- Adds partial index on `memory_relationships` for MENTIONS type: `(source_id, target_id) WHERE relationship_type = 'mentions' AND valid_until IS NULL`.
- No schema changes to `memory_nodes` itself -- entity nodes use existing columns.

> **Implementation note:** The migration number is `015`, not `014` as originally planned. Migration `014` was used for contradiction resolution (`014_add_contradiction_resolution`). The `relationship_type` vocabulary is not constrained at DB level (VARCHAR column, no CHECK constraint), so no vocabulary migration was needed.

Both migrations run as non-destructive `ALTER TABLE ... ADD COLUMN` operations with no table locks on active rows (PostgreSQL 11+ instant ADD COLUMN for nullable columns; `valid_from` uses `DEFAULT` but is backfilled after the fact to avoid a table rewrite).

Deployment order: migrate first, deploy new code second. Phase 1 search enhancements must be guarded by `graph_depth=0` default so old callers observe no behavior change before code is deployed.

## Dependencies

**What this depends on**:
- PostgreSQL with pgvector (existing, shipped)
- `search_memories_with_focus` and its existing RRF infrastructure (existing, shipped)
- `memory_relationships` table and `services/graph.py` (existing, shipped)
- asyncio task infrastructure in the FastAPI app (existing, shipped)
- spaCy `en_core_web_sm`, GLiNER2 (`urchade/gliner_medium-v2.1`) Python packages (shipped, Phase 2)
- vLLM endpoint for Stage 3 fallback -- `RedHatAI/gpt-oss-20b` via cluster-internal DNS (shipped, Phase 2)

**What depends on this (shipped)**:
- Entity management actions (`list_entities`, `merge_entities`, `rename_entity`, `backfill_entities`) on MCP, SDK, CLI.
- `memory(action="write")` triggers background entity extraction when `MEMORYHUB_ENTITY_EXTRACTION_ENABLED=true`.
- MENTIONS edges are system-managed; `manage_graph(action="create_relationship")` rejects manual MENTIONS creation.

**What depends on this (deferred -- Graph-Enhanced Retrieval epic)**:
- `search_memory` MCP tool: `graph_depth` and `entities` parameters are accepted but not wired through.
- `manage_graph(action="get_relationships")`: `as_of` parameter for temporal queries.
- `search_memories_with_focus`: graph proximity RRF signal, `collect_graph_neighbors`.
- Phase 3 backend decision: depends on observability data from Phase 1 production runs.

## Stage 3 Implementation Notes (PR #266, 2026-06-09)

### What shipped

Stage 3 adds an LLM-based fallback extractor to the cascade. When Stages 1 (spaCy) and 2 (GLiNER2) combined produce fewer than 2 high-confidence entities, Stage 3 calls a configured vLLM endpoint with a structured extraction prompt. It is the only stage that extracts inter-entity relationships (not just memory-to-entity MENTIONS edges).

Configuration: `MEMORYHUB_LLM_EXTRACTION_URL` and `MEMORYHUB_LLM_EXTRACTION_MODEL`. When URL is empty, Stage 3 is disabled. Currently pointed at GPT-OSS 20B (`RedHatAI/gpt-oss-20b`) via cluster-internal service DNS.

Inter-entity relationships use the existing `related_to` edge type. The LLM's specific label (e.g., `uses`, `part_of`, `created_by`) is stored in `metadata["llm_relationship_type"]`. This avoids schema changes while preserving the LLM's richer relationship vocabulary.

### Resilience

Adapted from the CDC data-acceptance-testing pipeline (which made GPT-OSS 20B work reliably in batch):

- **Best-effort JSON parsing**: direct parse, strip code fences, regex extraction. Handles the model occasionally wrapping JSON in markdown fences or embedding it in prose.
- **Pydantic schema validation** via `_ExtractionResult` model. Validates entity types against POLE+O vocabulary and confidence ranges. Invalid entity types are silently dropped (not rejected), so one bad entity doesn't invalidate the whole response.
- **Retry with correction**: on format or validation failure, the bad response is injected back into the conversation with a correction message explaining what went wrong. GPT-OSS 20B responds well to seeing its own mistake. Up to 3 retries with exponential backoff (1s, 2s, 4s).
- **Service error retry**: transient HTTP errors (429, 502, 503, 504) get separate exponential backoff (2s, 4s, max 2 retries). Non-retryable errors (400) fail immediately.

KFP pipelines were considered but rejected for the per-write path. The extraction runner's existing semaphore-bounded concurrency pool is sufficient. KFP is appropriate for the corpus backfill scenario (open question #1) if that gets filed.

### Live testing observations

Tested 2026-06-09 on the mcp-rhoai cluster with three memories of varying entity density:

1. **"Alice Johnson presented the Q3 roadmap at the all-hands meeting in Austin"** -- spaCy extracted Alice Johnson (person) and Austin (location). Stage 1 sufficient, no cascade.

2. **"Deployed PostgreSQL 16 with pgvector extension on OpenShift..."** -- spaCy found 4 entities but with poor type accuracy: "Deployed PostgreSQL" tagged as PERSON, "ORM" as ORG. Stage 1 met the threshold (2+ entities), so Stages 2 and 3 never fired.

3. **"Wes Jackson at Red Hat built MemoryHub..."** (entity-rich) -- spaCy found 11 entities including Wes Jackson (correct), Red Hat (correct), but also PostgreSQL as GPE (location), NER/LLM/GPT as ORG. Again, Stage 1 met threshold.

**Key finding**: spaCy's `en_core_web_sm` aggressively tags technical terms and acronyms as ORG or GPE. This inflates the "high-confidence entity count" and prevents the cascade from reaching Stage 2 (GLiNER) or Stage 3 (LLM), even when spaCy's entity types are wrong. The cascade trigger counts entities but not type accuracy.

**Resolution (#267, 2026-06-09):** GLiNER now runs unconditionally alongside spaCy, eliminating the flawed conditional gate. Acronym-pattern entities from spaCy (matching `^[A-Z]{2,}$`) receive a confidence discount from 1.0 to 0.5, improving Stage 3 triggering accuracy.

## Open Questions

1. ~~**Extraction trigger for existing memories**~~: **Resolved (#250, 2026-06-09).** Backfill ran as a K8s Job (`scripts/backfill-job.yaml`) with the full 3-stage cascade at concurrency 2 against GPT-OSS 20B. 140 memories processed, 837 entities extracted, 0 failures, 12 minutes wall time. Script at `scripts/backfill-entities.py`; also available as `memory(action="backfill_entities")` MCP admin action for future use.

2. ~~**Entity ownership and scope**~~: **Resolved (PR #244).** Option (a): per-owner deduplication. Entity nodes inherit `owner_id` from the source memory. `find_or_create_entity` scopes its exact-match and vector-similarity queries by `(tenant_id, owner_id)`. Cross-user deduplication deferred until RBAC implications are fully designed.

3. ~~**MENTIONS relationship directionality**~~: **Resolved (PR #244).** Confirmed as `source=memory, target=entity` (memory mentions entity). The entity-aware search subquery joins `memory_relationships.source_id` to find memories mentioning an entity, which aligns with this direction.

4. ~~**GLiNER2 and FIPS**~~: **Resolved (#268, 2026-06-11).** Static analysis (#265, 2026-06-09) found the inference hot path uses no cryptographic functions. Runtime verification confirmed on FIPS-enabled OpenShift cluster (`memory-hub-fips` context, `memoryhub-fips-verify` namespace): all three checks passed (hashlib wrapper, model load in 2.6s, inference in 0.4s). Job logs: `RESULT: FIPS-VERIFIED -- all checks passed`. GLiNER2 `gliner_medium-v2.1` is FIPS-compatible for production use on FIPS-enabled RHEL nodes.

5. ~~**Invalidation API surface**~~: **Resolved (PR #243).** `invalidate_relationship` is internal-only. Not exposed as an MCP tool. Agents cannot call it directly; it is invoked by the system when temporal edges are superseded. Promotion to a tool deferred to a follow-on issue if demand emerges.

6. ~~**Conflict between temporal filter and existing `manage_graph(action="get_relationships", ...)` behavior**~~: **Resolved (PR #243).** `get_relationships` now defaults to returning only active edges (`valid_until IS NULL`). The `as_of` parameter is exposed on the `manage_graph` tool for temporal queries. Callers requesting historical edges pass `as_of` explicitly.
