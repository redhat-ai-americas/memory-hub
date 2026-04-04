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

## MinIO: Document Storage

MinIO provides S3-compatible object storage for memories that are too large for a database row. Full procedure documents, markdown files with embedded examples, comprehensive project context -- these live in MinIO as objects, with a reference (S3 key) stored in the PostgreSQL node row.

MinIO runs on OpenShift via its Red Hat certified operator. For MemoryHub, it's deployed in distributed mode across multiple pods for durability.

The FIPS story: MinIO AIStor supports FIPS 140-3 mode via Go 1.24's validated crypto module, enabled at runtime with `GODEBUG=fips140=on`. In FIPS mode, TLS uses AES-GCM cipher suites only, and object encryption (DARE -- Data At Rest Encryption) uses AES-256-GCM exclusively. MinIO includes a disclaimer that it makes "no statements regarding FIPS certification status," which is an honest position -- they use a validated module but haven't certified the product itself. For our purposes, the technical implementation is sound.

### When content goes to MinIO vs. PostgreSQL

The split is based on size and access pattern:

Content that stays in PostgreSQL: short memories (a few sentences), embeddings, tree structure, metadata, version history, audit logs. These benefit from transactional consistency and relational queries.

Content that goes to MinIO: document-sized memories (multi-paragraph or multi-page), files attached to memories, archived content. These benefit from object storage economics and streaming access.

The threshold is TBD but probably in the range of 4-8 KB. Below that, PostgreSQL is fine. Above that, MinIO is more appropriate. The node row always exists in PostgreSQL regardless -- MinIO stores the body, PostgreSQL stores everything else including a reference to the MinIO object.

## Schema Design

**Status: TBD.** Schema design is one of the first implementation tasks. Here are the considerations driving it.

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

- What's the right content size threshold for PostgreSQL vs. MinIO storage?
- How do we handle embedding model upgrades? If we switch embedding models, all existing vectors need re-computation. Do we store the model identifier alongside the embedding?
- What's the retention policy for audit logs? Infinite retention is expensive; time-bounded retention loses forensic capability. Tiered storage (hot/warm/cold) for audit data?
- Connection pooling: does the OOTB operator include PgBouncer, or do we deploy it separately?
