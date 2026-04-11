# Storage Layer

MemoryHub's storage layer uses two systems: PostgreSQL for structured data, vector search, and graph relationships; and MinIO for S3-compatible document storage. This is a deliberate consolidation -- using PostgreSQL for multiple roles reduces operational complexity and keeps the FIPS surface area small.

## PostgreSQL: The Workhorse

PostgreSQL handles three distinct responsibilities within MemoryHub, all on the same database instance managed by the OOTB operator that ships with OpenShift.

### Vector search via pgvector

pgvector adds vector similarity search to PostgreSQL. Memory nodes get embeddings generated at write time, stored in a vector column, and queried using pgvector's distance operators (cosine similarity, L2 distance, inner product). When an agent calls `search_memory`, the query text gets embedded and matched against stored vectors.

pgvector is a good fit here because it keeps vector search collocated with the relational data. We don't need to synchronize between a separate vector database and PostgreSQL -- the embedding lives on the same row as the tree structure, scope metadata, and version history. For our scale target (hundreds of agents, thousands of memories per user), pgvector on a well-indexed PostgreSQL instance should be sufficient.

The FIPS story is clean: pgvector computes vector distances using mathematical operations (L2 norm, dot product, cosine). These are floating-point arithmetic, not cryptographic functions. pgvector doesn't use MD5, SHA, or any crypto primitives, so it works without issues in FIPS mode.

### Graph relationships

Memory nodes form a tree, and the tree structure needs to be queryable. We need to answer questions like "give me all branches of this node," "find the rationale for this memory," and "trace the provenance of this organizational memory back to source user memories."

**Decision: adjacency lists + explicit relationships table for v1.**

Our trees are shallow (3-4 levels), so recursive CTEs (`WITH RECURSIVE`) handle traversal efficiently without additional complexity. This approach requires no new PostgreSQL extensions -- it works with the OOTB operator as-is, which matters because extension support there is less documented than with Crunchy Data's operator. Apache AGE was the alternative (openCypher query support, more expressive graph traversal), but it's an incubator-stage dependency that needs validation we don't need yet. The evolution path to AGE or an in-memory graph remains open.

#### `memory_relationships` table

Beyond the parent/child tree structure (handled by `parent_id` on the node row), we need first-class cross-node relationships: provenance chains, semantic conflicts, supersession across scopes. These live in a dedicated relationships table rather than encoding them as special node types.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | PK |
| `source_id` | UUID FK → memory_nodes | The "from" node |
| `target_id` | UUID FK → memory_nodes | The "to" node |
| `relationship_type` | String | Type of edge |
| `metadata_` | JSON | Relationship-specific context |
| `created_at` | DateTime (tz-aware) | When created |
| `created_by` | String | Who created it |

Initial relationship types:

- `derived_from` -- provenance; this memory was produced from that one
- `supersedes` -- cross-scope replacement; an org memory supersedes a user memory on the same topic
- `conflicts_with` -- semantic conflict; two memories contradict each other
- `related_to` -- general association when no stronger type applies

Indexes on `(source_id, relationship_type)` and `(target_id, relationship_type)` support the common access patterns: "give me all outbound edges of type X from this node" and "give me everything that points at this node."

### Evolution path: in-memory graph

For graph traversals at scale, there's an option we want to keep available: an in-process graph library (like NetworkX in Python or petgraph in Rust) that loads the graph structure from PostgreSQL at startup and runs traversals in memory.

The pattern would be: load the adjacency data from PostgreSQL into an in-memory graph structure, run traversals there (which avoids database round-trips), and write mutations back to PostgreSQL for durability. This could be significantly faster for complex multi-hop traversals.

This isn't needed for v1 -- recursive CTEs against shallow trees should handle our initial graph complexity. If recursive CTEs become a bottleneck as graph depth or query complexity grows, this is the natural next step. Keeping the graph query interface clean means swapping the traversal engine behind it is a contained change.

### Contradiction tracking

Agents report contradictions when they observe behavior that conflicts with a stored memory. Previously these were stored as a JSON list in the memory node's `metadata_` column — convenient but unqueryable across memories and lost on node updates. The `contradiction_reports` table makes contradictions first-class.

#### `contradiction_reports` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | PK, auto-generated |
| `memory_id` | UUID FK → memory_nodes | The memory being contradicted. CASCADE on delete — if the memory is removed, its contradiction history goes with it. |
| `observed_behavior` | Text | What was observed that conflicts. Agents are instructed to be specific ("user ran docker-compose up with 12 services") not vague ("used Docker"). |
| `confidence` | Float (0.0–1.0) | Reporter's confidence that this is a real contradiction, not a temporary exception. |
| `reporter` | String(255) | The `owner_id` of the agent/user that filed the report. Sourced from the authenticated session identity. |
| `created_at` | DateTime (tz-aware) | Auto-timestamped at insert. |
| `resolved` | Boolean, default false | Whether the contradiction has been addressed (memory updated, report dismissed, etc.). |
| `resolved_at` | DateTime (tz-aware), nullable | When resolution occurred. Null until resolved. |

#### Relationship to the curation engine

The `report_contradiction` service function:
1. Verifies the target memory exists (raises `MemoryNotFoundError` if not)
2. Inserts a row into `contradiction_reports`
3. Counts unresolved contradictions for that memory
4. Returns the count to the MCP tool, which compares against a threshold (currently 5)

When the threshold is reached, the MCP tool signals `revision_triggered: true` in its response. The consuming agent is expected to prompt the user for memory review — the system records the signal but doesn't auto-modify the memory.

#### Query patterns

The dashboard's Contradiction Log panel (Panel 5 in the RHOAI demo design) uses these access patterns:

- **Unresolved contradictions for a memory:** `WHERE memory_id = ? AND resolved = false` — used by the curation threshold check and by the dashboard detail view.
- **All unresolved contradictions, newest first:** `WHERE resolved = false ORDER BY created_at DESC` — the main dashboard panel listing.
- **Resolution rate over time:** `GROUP BY date_trunc('day', created_at), resolved` — for the dashboard's trend view.

#### Index strategy

Two composite indexes cover the common queries:

- `ix_contradiction_reports_memory_resolved` on `(memory_id, resolved)` — serves the per-memory threshold count and the detail view. The query planner can use this for either column alone or both.
- `ix_contradiction_reports_resolved_created` on `(resolved, created_at)` — serves the main dashboard listing (unresolved, ordered by date). Also supports the resolution rate query.

No partial index on `resolved = false` for now — the table is append-heavy and most rows will start unresolved, so a partial index wouldn't save much. If the resolved/unresolved ratio shifts heavily toward resolved over time, a partial index becomes worthwhile.

#### Migration path

The move from in-memory (`metadata_["contradictions"]`) to persistent (`contradiction_reports` table) was a clean cut — the service function was rewritten, not dual-pathed. Any contradictions stored in metadata JSON before migration 005 remain there as historical artifacts but are no longer read or written by the service. New contradictions go exclusively to the table.

## MinIO: Document Storage

MinIO provides S3-compatible object storage for memories that are too large for a database row. Full procedure documents, markdown files with embedded examples, comprehensive project context -- these live in MinIO as objects, with a reference (S3 key) stored in the PostgreSQL node row.

MinIO runs on OpenShift via its Red Hat certified operator. For MemoryHub, it's deployed in distributed mode across multiple pods for durability.

The FIPS story: MinIO AIStor supports FIPS 140-3 mode via Go 1.24's validated crypto module, enabled at runtime with `GODEBUG=fips140=on`. In FIPS mode, TLS uses AES-GCM cipher suites only, and object encryption (DARE -- Data At Rest Encryption) uses AES-256-GCM exclusively. MinIO includes a disclaimer that it makes "no statements regarding FIPS certification status," which is an honest position -- they use a validated module but haven't certified the product itself. For our purposes, the technical implementation is sound.

### When content goes to MinIO vs. PostgreSQL

The split is based on size and access pattern:

Content that stays in PostgreSQL: short memories (a few sentences), embeddings, tree structure, metadata, version history, audit logs. These benefit from transactional consistency and relational queries.

Content that goes to MinIO: document-sized memories (multi-paragraph or multi-page), files attached to memories, archived content. These benefit from object storage economics and streaming access.

**Threshold: 4 KB (4096 bytes).** Content at or below 4 KB stays inline in PostgreSQL. Content above 4 KB is stored as an S3 object in MinIO, with the PostgreSQL row holding a reference (`content_ref`) and a truncated prefix for quick access.

The rationale for 4 KB: MiniLM-L6-v2 (our embedding model) has a ~512 token input limit. 4 KB of English text is roughly 600--1000 tokens, well above the embedder's comfort zone. Setting the threshold at 4 KB keeps most memories inline while catching anything that would blow the embedder's context window.

The node row always exists in PostgreSQL regardless -- MinIO stores the body, PostgreSQL stores everything else including a reference to the MinIO object.

### What gets embedded for S3-backed content

For memories stored in MinIO, the PostgreSQL row holds a truncated prefix (~1000 characters, ~250 tokens) in the `content` column. This prefix is what gets embedded for the parent node. The all-MiniLM-L6-v2 embedder has a practical input limit of ~1100 characters of English text; 1000 provides margin. Full content is searchable via **semantic chunk children** -- each chunk is a child node with `branch_type="chunk"`, its own embedding, and `weight=0.0`. Agents find relevant chunks through `search_memory`, then follow `parent_id` to retrieve the full memory.

### Curator participation

The curation engine runs on the full content string but uses the prefix embedding for similarity comparison when checking for near-duplicates. This may reduce dedup sensitivity for content that only differs deep in the body -- two long documents with identical openings but different conclusions could slip past. This is acceptable divergence: the curator is a best-effort dedup aid, not a guarantee. If precision matters, agents can call `get_similar_memories` explicitly after writing large content.

### Read-time behavior

**Lazy hydration.** `read_memory` returns the prefix (the `content` column) by default. When called with `hydrate=True`, the full content is fetched from S3 and returned in place of the prefix. Search results for chunk nodes include a `parent_hint` field guiding the agent to the full memory via its `parent_id`.

This keeps the common read path fast (no S3 round-trip) while giving agents a clear escalation path when they need the full document.

### Version chain in S3

Each version of an S3-backed memory gets its own S3 object, keyed as `{tenant_id}/{memory_id}/{version_id}`. On update, a new S3 object is uploaded and the PostgreSQL row's `content_ref` is updated to point to it. The previous version's S3 object lives until the version expires (TTL-based, governed by the same retention policy as PostgreSQL version rows). On delete, S3 objects for all versions in the chain are removed in a single batch operation.

### Semantic chunking

When content exceeds the 4 KB threshold and lands in S3, the write path also creates **semantic chunks** as child nodes in the memory tree. These chunks enable fine-grained search over large documents without requiring agents to hydrate and scan the full content.

Chunk nodes have:
- `branch_type="chunk"` -- distinguishes them from rationale, provenance, and other branch types
- `weight=0.0` -- chunks are search scaffolding, not memories in their own right; zero weight keeps them out of weight-based rankings
- Their own embedding -- each chunk is independently searchable via `search_memory`
- `parent_id` pointing to the S3-backed parent memory

**Chunking strategy**: `semantic_chunk()` splits content on paragraph boundaries first, then sentence boundaries, targeting ~256 tokens per chunk. This keeps each chunk well within the embedding model's 512-token window while preserving semantic coherence.

**Search behavior**: Default search omits chunks whose parent is already in the result set (consistent with existing branch-collapsing behavior). This prevents a large document from dominating search results with multiple chunk hits when the parent memory already matched.

**Retrieval paths** (cheapest to most expensive):
1. **Read chunk directly** -- if the chunk itself answers the agent's question, no further action needed
2. **Traverse graph** -- follow `parent_id` to get the parent memory's prefix and metadata
3. **Hydrate** -- call `read_memory(memory_id, hydrate=True)` to fetch the full S3 content

## Schema Design

Here are the considerations that drove the schema design.

### Core tables (conceptual)

The memory node table is the center of the schema. It needs columns for: node ID (UUID), parent ID (nullable, for tree structure), scope (enum: user, project, role, org, enterprise), content (text, for short memories), content_ref (S3 key, for document memories), embedding (vector, via pgvector), weight (float), is_current (boolean), version (integer), previous_version_id (UUID, nullable), created_at, updated_at, created_by (agent/user identity), and node_type (enum: memory, rationale, provenance, description, etc.).

The audit log table is append-only. Every memory operation (create, read, update, delete, promote, prune) gets a row with: operation type, target node ID, actor identity, timestamp, and a snapshot of relevant state before and after.

Branch type metadata might warrant its own table, or it might be an enum on the node table. Required vs. optional branches could be enforced by policy rather than schema.

### Indexing strategy

pgvector indexes (IVFFlat or HNSW) on the embedding column for similarity search. B-tree indexes on scope, is_current, parent_id, and created_by for filtered queries. Partial indexes on `is_current = true` to accelerate the common case of "give me current memories only."

### Connection pooling

PgBouncer or a similar connection pooler in front of PostgreSQL. The MCP server will have many concurrent connections from agents; pooling prevents connection exhaustion. The OOTB operator may include PgBouncer -- this needs validation.

## High Availability and Backup

PostgreSQL runs with a primary and at least one synchronous replica, managed by the OOTB operator. Failover is automatic. Backups use the operator's built-in backup mechanism (likely pg_basebackup or a WAL archiving approach -- depends on what OOTB supports).

MinIO runs in distributed mode (minimum 4 pods for erasure coding). Data survives the loss of up to half the pods. Bucket versioning is enabled for document recovery.

Both systems' backup data should be encrypted. PostgreSQL backups inherit OS-level encryption. MinIO backups use DARE with the same KMS configuration as the live data.

## Design Questions

- ~~What's the right content size threshold for PostgreSQL vs. MinIO storage?~~ **Resolved**: 4 KB. See "When content goes to MinIO vs. PostgreSQL" above.
- How do we handle embedding model upgrades? If we switch embedding models, all existing vectors need re-computation. Do we store the model identifier alongside the embedding?
- What's the retention policy for audit logs? Infinite retention is expensive; time-bounded retention loses forensic capability. Tiered storage (hot/warm/cold) for audit data?
- Connection pooling: does the OOTB operator include PgBouncer, or do we deploy it separately?
