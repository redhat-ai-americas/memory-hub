# Knowledge Layer for MemoryHub

**Status:** Proposal -- for discussion before implementation
**Date:** May 2026
**Related issues:** #170, #171, #235, #237, #240

---

## 1. What "Knowledge" Means in MemoryHub

A **memory** is an experiential record -- a decision, preference, observation, or rationale that emerged from agent activity. It may be wrong, outdated, or contradicted. It is one agent's perspective at one point in time.

A **knowledge node** is a governed assertion that has been validated through a defined process and can be trusted as a stable fact within its scope. It graduated from experiential memory, or was curated directly by an authorized actor, and carries provenance back to the evidence that supports it.

Examples of knowledge:
- "Our PostgreSQL clusters use connection pool size 25 in production" (organizational knowledge)
- "The billing module depends on the tax-calculation service" (project knowledge)
- "Wes prefers Podman over Docker" (user knowledge)

What knowledge is NOT in MemoryHub:
- Not an ontology or schema definition (that is RetrievalHub's domain)
- Not a document or corpus chunk (that is retrieval, not memory)
- Not immutable -- knowledge can be versioned, contradicted, and retired like any memory
- Not a separate data store -- it lives in `memory_nodes` with the same governance substrate

The distinction is **epistemic status**, not access level. A piece of knowledge can be user-scoped (personal domain facts) or enterprise-scoped (company-wide standards). Scope remains the access dimension; content type is the confidence dimension.


## 2. Schema Approach: New `content_type` Column

Add `content_type VARCHAR(20) NOT NULL DEFAULT 'experiential'` to `memory_nodes`.

**Values:** `experiential` (default for all existing rows), `knowledge`, `behavioral` (#237).

### Why this approach

**Why not `branch_type`?** `branch_type` classifies the structural role of a node in the memory tree (rationale, provenance, chunk, compiled_article). A compiled article is a structural artifact that could contain either experiential summaries or graduated knowledge assertions. A knowledge node can be a root memory or a branch. These are orthogonal: `content_type` is what it IS; `branch_type` is where it SITS in the tree.

**Why not `metadata_`?** Metadata is extensible JSON for application-specific tags. Making content type a JSON key means it cannot be indexed efficiently, filtered at the SQL level, or enforced with a CHECK constraint. Every search query that needs to distinguish knowledge from memory would require JSON path extraction. Content type is a first-class dimension, not an afterthought.

**Why not a new table?** A separate `knowledge_nodes` table would duplicate the governance substrate (RBAC, tenant isolation, versioning, contradiction detection, embedding, soft-delete). Knowledge nodes need all of these. The column approach reuses everything and adds one indexed filter dimension.

**Why not a new scope?** Scope is about ACCESS (who can see it). Content type is about TRUST LEVEL (how confident are we). These compose: user-scoped knowledge, project-scoped knowledge, enterprise-scoped knowledge. Conflating them into a single dimension forces a false choice.

**Backward compatibility:** `DEFAULT 'experiential'` means existing rows are automatically classified. Existing searches return all content types unless the caller explicitly filters. No existing behavior changes.


## 3. Database Layer Changes

### No change to database product

PostgreSQL + pgvector remains the correct choice. Knowledge nodes have the same access patterns as memories: vector similarity search, scope-filtered queries, shallow graph traversal via recursive CTEs, tenant isolation. Nothing about knowledge requires a graph database, a triple store, or OWL reasoning. Sakhatsky's critique applies: the value is in governed assertions, not graph topology.

### Alembic migration 015

```
1. ADD COLUMN content_type VARCHAR(20) NOT NULL DEFAULT 'experiential'
2. ADD CHECK (content_type IN ('experiential', 'knowledge', 'behavioral'))
3. CREATE INDEX ix_memory_nodes_content_type ON memory_nodes (content_type)
4. CREATE INDEX ix_memory_nodes_content_type_scope ON memory_nodes (content_type, scope)
```

No backfill needed. Non-destructive, reversible.

### Model changes

- `MemoryNode`: add `content_type: Mapped[str]` with `default="experiential"`
- `schemas.py`: add `ContentType(StrEnum)` with values `experiential`, `knowledge`, `behavioral`
- `MemoryNodeCreate`: add optional `content_type` field (default `experiential`)
- `MemoryNodeRead` / `MemoryNodeStub`: include `content_type` in response


## 4. MCP Tool Surface

### Modified actions

**`search`** -- Add optional `content_type` filter to `_SEARCH_OPTS`. When set, SQL filter includes `MemoryNode.content_type == content_type`. When omitted, searches all content types (backward compatible).

**`write`** -- Add optional `content_type` to `_WRITE_OPTS`. Default `experiential`. Direct write of `content_type="knowledge"` is restricted: requires either (a) service identity (compilation service, curator agent), or (b) a `memory:knowledge_curator` role claim. Regular agents write experiential memories; knowledge is produced through graduation.

**`list`** -- Add optional `content_type` filter to `_LIST_OPTS`.

**`read`** -- Response includes `content_type` in the output (no input change needed).

### New action: `graduate`

```
graduate(memory_id, [options: {evidence, reviewer_note}])
```

Graduates an experiential memory to knowledge:

1. Validates the memory exists, is current, is `content_type="experiential"`
2. Checks authorization (curator role or service identity)
3. Creates a new version with `content_type="knowledge"`, `version=N+1`
4. Creates a `derived_from` relationship from knowledge version to experiential version
5. If `evidence` is provided, creates a child branch with `branch_type="evidence"`
6. Records graduation metadata: `metadata_.graduation = {graduated_by, graduated_at, reviewer_note}`

Authorization: requires `memory:knowledge_curator` role or service identity. Graduation is a governed write -- not available to any agent that can write experiential memories.

Graduation does NOT change scope. A user-scoped experiential memory graduates to user-scoped knowledge. Scope promotion (#235) is a separate operation that composes with graduation but is not coupled to it.

### No separate `knowledge_search` action

`search(query=..., options={content_type: "knowledge"})` achieves the same result without action proliferation. Consistent with the single-tool design principle.


## 5. Graduation Pipeline

### Phase 1: Manual graduation (ship with the column)

A curator agent or human operator calls `graduate(memory_id=..., options={evidence: "...", reviewer_note: "..."})`. The action creates a governed knowledge node with provenance. Simple, auditable, manually triggered.

### Phase 2: Automatic candidate detection (after #170)

The curation scanner gains a periodic rule that identifies graduation candidates:

- Memories with 3+ contradiction reports all resolved as `keep_old` (stable under challenge)
- Memories with high weight (>= 0.9) current for > 30 days without contradiction
- Memories that are `derived_from` targets for 3+ other memories (heavily referenced)

Candidates are flagged (`metadata_.graduation_candidate = true`), not auto-graduated. A curator reviews and calls `graduate` explicitly.

### Phase 3: Enterprise approval workflow (deferred)

Enterprise-scoped knowledge graduation requires human-in-the-loop approval. The graduation is queued, an approver reviews, and the action completes only after sign-off. Details deferred to the enterprise governance track.


## 6. Interaction with Existing Roadmap

| Issue | Relationship |
|---|---|
| #170 (graph-enhanced memory) | Knowledge nodes participate in entity graph like any memory. `content_type` filter added to `_build_search_filters`, which #170's graph traversal already respects. Note: #170 Phase 2 introduces `scope="entity"` for extracted entity nodes. Entity nodes can carry `content_type="knowledge"` when the entity assertion is graduated (e.g., "PostgreSQL" as a canonical entity vs "postgres" as an alias). The two dimensions compose: `scope` classifies structural role, `content_type` classifies epistemic status. |
| #171 (knowledge compilation) | Compiled articles (`branch_type="compiled_article"`) gain a trust signal: `content_type="knowledge"` vs `"experiential"` distinguishes articles built from governed facts vs raw observations. |
| #235 (memory promotion) | Scope promotion changes WHO can see it. Graduation changes TRUST LEVEL. These compose: graduate user-scoped memory to knowledge, then promote to project-scoped knowledge. Independent operations. |
| #237 (behavioral memory) | `behavioral` is a third `content_type` value. Behavioral memories (agent configuration) are neither experiential observations nor graduated facts. |
| #240 (extraction pipeline) | Extraction writes `content_type="experiential"` always. Graduation is a separate, downstream process. |


## 7. RetrievalHub Boundary

This proposal **preserves** the boundary defined in `strategy/platform-architecture.md`.

**MemoryHub knowledge:** Governed assertions that graduated from agent experience. "We use connection pool size 25" is knowledge derived from operational decisions, deployment configurations observed by agents, and team preferences accumulated over time. It is experiential knowledge made durable.

**RetrievalHub knowledge:** Curated reference material from external sources. Architecture documents, compliance standards, API specifications, vendor documentation. It enters the system through ingestion pipelines, not through agent experience.

The test: if the fact emerged from operational history, it is MemoryHub knowledge. If it would exist regardless of any agent's experience (documentation, standards, reference data), it is RetrievalHub's domain.

What this proposal explicitly does NOT do:
- No document ingestion pipeline
- No ontology or schema definition language
- No external knowledge source connectors
- No SPARQL, OWL, or RDF

MemoryHub's knowledge layer is the experience-to-assertion pipeline. RetrievalHub is the corpus-to-answer pipeline.


## 8. Open Questions (Resolved)

1. **Should `content_type` be mutable via `update`, or only via `graduate`?**
   **Answer: only via `graduate`.** Direct mutation via `update` bypasses the governed graduation path -- no provenance chain is created, no evidence is recorded, no curator authorization is checked. If an agent can call `update(memory_id, options={content_type: "knowledge"})`, the entire graduation model is advisory. The `update` action should reject changes to `content_type`; the `graduate` action is the sole write path for that field.

2. **Minimum weight floor for knowledge nodes?**
   **Answer: leave weight orthogonal.** Weight currently serves as a visibility threshold (full-content vs stub), not a ranking signal in RRF. Adding a floor conflates two signals and creates a hidden coupling between graduation and search visibility. The right mechanism for ranking knowledge higher is question 3 (knowledge boost in RRF), which is explicit, tunable, and composable. Graduation metadata (`metadata_.graduation`) already marks the node distinctly; a curator who wants a graduated fact to rank higher can set weight manually as a separate intentional act.

3. **Knowledge boost in mixed search results?**
   **Answer: yes, as a fifth RRF signal.** Add `knowledge_boost_weight` to `search_memories_with_focus`, carved from the remaining budget exactly like `domain_boost_weight` and `graph_boost_weight` already are. Knowledge nodes receive rank 1 (highest); experiential nodes receive a penalty rank. Default `0.0` (disabled) for backward compatibility -- agents opt in by setting it > 0. This composes with all existing signals and requires no changes to `_build_search_filters`.

4. **Naming: `graduate` vs `certify` vs `curate`?**
   **Answer: `graduate`.** Consistent with the language in #235, the research docs, and this proposal. `certify` implies cryptographic or legal guarantee beyond what we provide. `curate` collides with the existing curation subsystem (`manage_curation` action, `CurationRule` model). `graduate` accurately describes the epistemic transition: a memory has earned a higher trust status through evidence and review, not been rubber-stamped.
