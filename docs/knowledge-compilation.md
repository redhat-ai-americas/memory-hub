# Knowledge Compilation

**Issue**: #171
**Date**: April 2026
**Status**: Design

## Summary

Knowledge compilation is an LLM-driven pipeline that transforms raw agent data — conversation threads, extracted memories, and entity graphs — into structured, interlinked knowledge articles stored as versioned memory nodes. Compilation runs on dedicated cluster pods (not in agent context windows), produces deterministic Markdown articles keyed by `(tenant, scope, topic_hash)`, and is shared across all agents in a scope. A virtuous loop feeds query results back as new source material. A health-check linter runs periodic sweeps for inconsistencies, staleness, and missing connections. This is the layer that turns MemoryHub's episodic memory into an institutional knowledge base — the governed multi-user version of Karpathy's `raw/ → wiki/ → index.md` pattern that nobody else has built.

---

## Strategic Context

Karpathy's April 2026 "LLM Knowledge Bases" post (16M+ views, 5,000+ stars in days) described compiling raw sources into a persistent wiki so that knowledge is derived once and kept current rather than re-synthesized on every query. The community responded with a wave of personal-use implementations — all filesystem-based, all single-user, none governed. The community explicitly identified the gap: multi-user conflict resolution, access control, audit trails, and concurrent edit safety remain unsolved.

Meta's enterprise deployment is the closest precedent: 50+ specialized agents reading 4,100+ files across three repos, producing 59 structured context files encoding tribal knowledge that previously existed only in engineers' heads. That effort reduced research time from ~2 days to ~30 minutes and cut AI agent tool calls per task by 40%. It was a one-time extraction, not a continuously-maintained living knowledge base.

MemoryHub's governance substrate — scoped RBAC, tenant isolation, versioned memory tree, contradiction detection, auditable provenance — is the differentiator. Every existing implementation is personal and filesystem-based. MemoryHub can deliver the governed multi-user version: compilation respects scope boundaries, articles are owned artifacts with RBAC, contradictions block publication, and every compilation event is auditable. This is the capability that turns the memory system into an institutional knowledge engineering platform.

The `compilation_hash` determinism from issue #175 (compilation epochs, already shipped) means that multiple agents receiving the same compiled article get identical token prefixes. Combined with llm-d's KV Block Index routing on OpenShift AI, this is expected to produce cross-agent KV cache hits at the vLLM pod level with no application-level coordination (based on how prefix-keyed KV caching works; not yet validated against production llm-d deployments). The knowledge compilation service is also a prompt cache amplifier.

---

## Architecture

### Compilation Pipeline

The full flow from raw data to compiled articles:

```
Conversation threads (#168)
    │
    ▼
Memory extraction pipeline (#168)
    │  writes memory_nodes + conversation_extractions
    ▼
Entity extraction (#170, Phase 2)
    │  writes entity nodes + mentions relationships
    ▼
Knowledge Compilation (this document)
    │  compilation pods read memory_nodes + relationships
    │  LLM synthesizes Markdown articles
    │  articles stored as compiled_article nodes + S3 content
    ▼
Health-Check Linting
    │  periodic LLM sweep: inconsistencies, gaps, staleness
    │  linting reports stored as lint_report branches
    ▼
Compiled Articles (queryable via query_knowledge)
    │
    ▼ (virtuous loop)
Agent query results → file_finding → new source memories
```

Each subsystem contributes a distinct artifact class:

- **#168 (conversation threads)**: Raw source material as `conversation_messages` and extracted `memory_nodes` with `conversation_extractions` provenance.
- **#170 (graph-enhanced memory)**: Entity nodes (POLE+O taxonomy via `scope="entity"`), `mentions` relationships linking memories to entities, and temporal validity on all relationships.
- **#169 (context compaction)**: The structured summarization template and ACE Generator/Reflector/Curator pattern. The health-check linter in this document is the evolution of #169's memory-level Curator, operating at the article level with richer cross-article analysis (health-check linter). A separate article-level Curator component within the ACE pattern adjusts compilation prompts based on Reflector findings. These are two distinct components: the health-check linter sweeps for inconsistencies across the corpus; the article-level Curator tunes generation quality within the ACE loop. Compaction's `compilation_epoch` invalidation mechanism from #175 is the cache coordination layer.
- **#171 (this document)**: The compilation service that reads all of the above and writes `compiled_article` nodes.

### On-Cluster Service Architecture

Compilation runs on dedicated cluster pods, not in the requesting agent's context window. This is a firm design constraint.

Rationale: compiling a knowledge article for a project scope may require reading hundreds of memory nodes, running multiple LLM passes (entity disambiguation, cross-reference resolution, article synthesis), and validating against existing articles for contradictions. These operations would consume an unacceptable fraction of an agent's context budget and add unbounded latency to tool calls.

Compilation pods are themselves agents that use MemoryHub's own MCP tools (`search_memory`, `read_memory`, `manage_graph(action="create_relationship", ...)`, `write_memory`) with a service identity. They do not have a human user; they authenticate with a service API key scoped to the `compilation-service` role. This role has read access to all memories within the tenant (bounded by scope) and write access only to `compiled_article` nodes and their relationships.

```
┌─────────────────────────────────────────────────────────────┐
│                   Compilation Service                         │
│                                                               │
│  ┌───────────────┐    ┌───────────────┐    ┌──────────────┐  │
│  │ Compilation   │    │ Lint Worker   │    │  Scheduler   │  │
│  │ Worker Pod(s) │    │ Pod(s)        │    │  Pod         │  │
│  │               │    │               │    │              │  │
│  │ reads: MCP    │    │ reads: MCP    │    │ enqueues via │  │
│  │ writes: MCP   │    │ writes: MCP   │    │ Valkey queue │  │
│  └───────┬───────┘    └───────┬───────┘    └──────────────┘  │
│          │                    │                               │
│  ┌───────▼────────────────────▼──────────────────────────────┐│
│  │              Valkey (job queue + cache coordination)       ││
│  │  compile_queue:{tenant}:{scope}                            ││
│  │  article_cache:{tenant}:{scope}:{topic_hash}               ││
│  │  compile_status:{job_id}                                   ││
│  └───────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**HPA scaling**: The Compilation Worker Deployment uses a `HorizontalPodAutoscaler` targeting the `compile_queue` depth in Valkey. At queue depth 0, minimum replicas is 1 (idle worker). At queue depth 10+, scale to the configured maximum (default: 5 workers). The Lint Worker Deployment scales similarly on the `lint_queue` depth. The Scheduler Pod is a single replica with a `PodDisruptionBudget` of `minAvailable: 1`.

**Token budget isolation**: Each compilation job receives a configurable token budget (default: 32K tokens for article synthesis). Jobs that would exceed budget trigger hierarchical compilation (see §Scaling Considerations). Worker pods do not share LLM capacity with agent-facing `search_memory` calls — compilation uses a separate LLM endpoint or a dedicated model serving replica configured in the deployment manifest.

### Async-First Request Model

When an agent calls `compile_knowledge(topic="PostgreSQL connection pooling", scope="project", scope_id="memory-hub")`:

1. **Cache check**: Look up `article_cache:{tenant}:{scope}:{topic_hash}` in Valkey. If the cached article is fresh (within `stale_after` window), return the article immediately with `status: "fresh"`.

2. **First request (cache miss)**: Enqueue a compilation job to `compile_queue:{tenant}:{scope}`. Return `status: "compiling"` with the `job_id`. The response is immediate; the agent is not blocked.

3. **Status polling**: The agent calls `get_compilation_status(job_id=...)` to check progress. Status values: `queued`, `compiling`, `complete`, `failed`.

4. **Completion subscription**: Agents that prefer push over polling can subscribe to a Valkey pub/sub channel `compile_complete:{job_id}`. The worker publishes to this channel when the article is ready.

5. **Stale article**: If the cache entry exists but is stale (new memories arrived since `compiled_at`), the cached article is returned immediately with `status: "stale"` while a background recompilation is queued. Agents receive a usable article without blocking; the next call within a few minutes will return the fresh version.

The staleness signal comes from the `compilation_epoch` mechanism (#175): when new memories arrive for a `(tenant, owner)` pair, the Valkey epoch key is invalidated. The article cache checks whether the epoch at `compiled_at` matches the current epoch; mismatch means stale.

---

## Compiled Articles

### Article Data Model

Compiled articles are stored as `memory_nodes` with `branch_type = "compiled_article"`. This reuses the full memory tree machinery — RBAC, versioning, soft-delete, provenance branches, pgvector embeddings — without a new table.

The article content is stored in MinIO/S3 (not inline) because article Markdown is large (commonly 2–10KB, occasionally 50KB+ for comprehensive concept pages). The `content` column on `memory_nodes` holds a one-paragraph abstract. The `content_ref` column holds the S3 object key. The `metadata_` JSON column holds article-level metadata.

```python
MemoryNode(
    scope="project",                       # inherits from compilation request
    scope_id="memory-hub",
    branch_type="compiled_article",
    owner_id="compilation-service",        # service identity
    tenant_id=tenant_id,
    content="<one-paragraph abstract>",    # inline summary for search results
    content_ref="articles/{tenant}/{scope}/{scope_id}/{article_id}",  # S3 key
    weight=0.9,                            # articles are high-weight by default
    metadata_={
        "article_type": "concept",         # concept | entity | timeline | cross_ref | index
        "topic": "PostgreSQL connection pooling",
        "topic_hash": "sha256:<hash>",
        "compiled_at": "<ISO8601>",
        "stale_after": "<ISO8601>",        # compiled_at + freshness_ttl
        "compilation_job_id": "<uuid>",
        "source_memory_count": 42,
        "source_entity_count": 7,
        "article_version": 3,              # increments on each recompilation
        "lint_status": "clean",            # clean | issues | pending
        "lint_checked_at": "<ISO8601>",
    },
)
```

Source memories link to the compiled article via `memory_relationships` with `relationship_type = "derived_from"` (article → source memory). This is the same relationship type used for provenance elsewhere in the tree; no new relationship type is needed.

**S3 key schema**: `articles/{tenant_id}/{scope}/{scope_id}/{article_id}` where `article_id` is the `memory_node.id`. Prior compiled versions are archived to `articles/{tenant_id}/{scope}/{scope_id}/{article_id}/v{N}` before overwrite. Version retention follows the standard compaction cold-path `retention_days` policy.

Add `compiled_article` to the application-layer enum of valid `branch_type` values. No schema migration is needed (the column is `String(50)`; both `compiled_article` at 17 chars and `lint_report` at 11 chars fit comfortably).

### Article Types

**Concept page**: Synthesizes all memories related to a conceptual topic. Includes definition, how it is used in the project, known edge cases, and links to related concepts. Example: "PostgreSQL connection pooling in MemoryHub."

**Entity page**: One page per named entity (person, system, organization, location, event). Aggregates all memory mentions of the entity, organized chronologically and by relevance. Populated primarily from entity nodes (#170) and their `mentions` relationships. Example: "pgvector — usage history and configuration."

**Timeline page**: Chronological view of events, decisions, or changes related to a topic. Built from memories with `valid_from`/`valid_until` temporal data (#170 Phase 1). Example: "MemoryHub deployment history, Q1 2026."

**Cross-reference index**: A topic-to-topic linking article that identifies relationships between concept pages. Built by the compilation service after individual concept and entity pages exist. Used to surface non-obvious connections. Example: "Connection pooling ↔ FIPS compliance — implications."

**Master index**: One index article per `(tenant, scope, scope_id)` tuple. Lists every compiled article with its one-paragraph abstract, sized to fit in a single context window. The master index is the agent's entry point — it reads the index first, then drills into specific articles. The index is rebuilt on every recompilation of any article in the scope.

Article types compose: an entity page for "PostgreSQL" links to the concept page for "connection pooling" which links to the timeline page for "schema migrations." The master index is the root that makes the full graph navigable.

### Scoped Compilation

Compilation respects MemoryHub's scope hierarchy:

| Scope | Knowledge Base | Contents |
|---|---|---|
| `user` | Personal KB | Memories owned by the user; private to that user |
| `project` | Project wiki | Memories in the project scope; shared by all project participants |
| `organizational` | Institutional knowledge | Org-scope memories; accessible to all org members |
| `enterprise` | Enterprise policy base | Enterprise-scope memories; read-only to most callers |

**Scope inheritance in articles**: A project article may reference an org-scope article by topic hash. The reference is a `related_to` relationship in the memory tree. The project compilation service reads org-scope articles as source material (read permission required) but cannot modify them. An org article compiles independently; the project article cites it.

**Authorization for compilation requests**: A caller can request compilation only for scopes they can read. A user can request compilation of their personal KB unconditionally. Project compilation requires project membership. Org compilation requires org membership. Enterprise compilation requires `memory:admin`.

The compilation service runs with a service identity that has read access to the target scope. The compiled article is written with the scope of the compilation request. The agent that requested compilation is recorded in the compilation job metadata (not as `owner_id` — the service owns the article — but in `metadata_.requested_by`).

---

## The Virtuous Loop

Agent explorations produce new knowledge. The virtuous loop captures this automatically.

When an agent uses `query_knowledge` to answer a question, the returned article content is grounded in the compiled knowledge base. When the agent also performs original research — calling tools, running queries, reading external documents — those findings are richer than what compilation alone would produce. The `file_finding` tool lets the agent contribute those findings back.

### `compile_and_file` operation

`file_finding(content=..., topic=..., scope=..., scope_id=...)` writes the agent's finding as a regular memory node (using `write_memory` internally) and then immediately enqueues a delta compilation job for the relevant topic. The delta job re-reads source memories for the topic and updates the article without full recompilation of the scope.

The virtuous loop is:

```
agent queries topic → receives compiled article
    → agent performs original research
    → agent calls file_finding with new insight
    → delta compilation queued
    → article updated within minutes
    → next agent query returns enriched article
```

### Preventing infinite loops

Compilation depth is tracked in the job metadata:

```json
{
  "compilation_depth": 1,
  "source_job_id": null
}
```

A compilation job triggered by `file_finding` has `compilation_depth: 1`. If that compilation's article publication triggers a downstream re-index (because the master index changed), the index recompilation gets `compilation_depth: 2`. The maximum allowed depth is 3. Jobs at depth 3 do not trigger further compilation; they complete and log the depth ceiling reached. The depth cap of 3 is a backstop against model-collapse feedback loops; the primary guard is the quality gate in `file_finding` that rejects circular-source submissions. Depth 3 allows raw → topic summary → meta-summary compilation without enabling unbounded recursion.

Circular topic references (concept A links to concept B which links to concept A) are allowed in article content but do not create circular compilation jobs. Job triggering is topic-keyed, not article-keyed — one compilation per `(tenant, scope, topic_hash)` at a time. A second enqueue for the same key while a job is running is coalesced (not added to the queue separately).

### Quality gates before filing

`file_finding` submissions pass a lightweight pre-flight check before the memory is written:

1. Content must be non-empty and at least 50 characters.
2. Content must not duplicate an existing memory with cosine similarity > 0.92 (checked via `manage_graph(action="get_similar", ...)`).
3. Content must not be an article abstract (detect `branch_type = "compiled_article"` in the similar memories result — prevents agents from re-filing compiled content as source material, which would create a circular source chain).

If any check fails, `file_finding` returns an error with an explanation. The agent is not blocked from writing memories directly via `write_memory`; the quality gate applies only to the compilation-triggering path.

---

## Health-Check Linting

The health-check linter runs periodic LLM sweeps over the compiled article corpus for a given scope. It is the evolution of #169's memory-level Curator applied at the article level. Note that the article-level Curator within the ACE pattern (described in §Incremental Compilation) is a separate component: the health-check linter performs corpus-wide inconsistency sweeps, while the article-level Curator tunes compilation prompts based on Reflector findings — two distinct components operating at different layers.

### What the linter checks

For each article in the scope:

- **Internal consistency**: Does the article contain contradictory assertions? (Example: claims version 2.0 is the latest in one section and references version 3.0 in another.)
- **Staleness**: Are any claims in the article contradicted by memories written after `compiled_at`? Checked by querying the memory store for the article's topic with `as_of = now()` and comparing against the article's assertions.
- **Missing connections**: Are there entity nodes or concept pages in the scope that this article should reference but does not? Detected by comparing the article's `related_to` relationships against entity pages for entities mentioned in the article content.
- **Orphaned articles**: Does an article reference a topic hash for which no compiled article exists? (Example: a cross-reference to a concept page that was deleted.)
- **Coverage gaps**: Are there topic clusters in the memory store with no corresponding compiled article? Detected by clustering memory embeddings and checking whether each cluster centroid has a corresponding article.

### Lint report storage

The linter writes its findings as a branch on the relevant `compiled_article` node with `branch_type = "lint_report"`. Each lint report is a JSON document:

```json
{
  "lint_job_id": "uuid",
  "checked_at": "<ISO8601>",
  "issues": [
    {
      "issue_type": "internal_inconsistency",
      "severity": "high",
      "description": "Article claims X in section 2 and contradicts it in section 4.",
      "location_hint": "section:4",
      "suggested_resolution": "Remove the contradictory claim in section 4 or update section 2."
    }
  ],
  "coverage_gaps": [
    {
      "cluster_centroid_topic": "Valkey pub/sub patterns",
      "memory_count": 8,
      "suggested_article_type": "concept"
    }
  ],
  "orphaned_references": ["topic_hash:abc123"],
  "lint_status": "issues"
}
```

The `compiled_article` node's `metadata_.lint_status` is updated to `"clean"`, `"issues"`, or `"pending"` after each lint run. Agents calling `query_knowledge` receive the `lint_status` in the response envelope so they can decide whether to trust the article or request recompilation.

### Linting schedule

The lint worker runs on a configurable schedule (default: nightly at 03:00 UTC for each scope). Articles with active source memory writes (detected by comparing current epoch to `compiled_at` epoch) are linted with higher priority — if the article is stale, linting its current content is lower value than recompiling first. The lint scheduler checks staleness before enqueuing; stale articles are sent to the compile queue instead.

---

## Incremental Compilation

Full recompilation of all articles in a scope is expensive and unnecessary when a small number of new memories arrive. The delta compilation path handles the common case.

### Affected article detection

When new memories arrive (via `write_memory` or `file_finding`), the compilation service determines which existing articles are affected:

1. Extract entities from the new memory (reuse the Phase 2 entity extraction cascade from #170).
2. Find all `compiled_article` nodes that have `related_to` or `derived_from` relationships to those entities.
3. Find all `compiled_article` nodes whose topic overlaps with the new memory's content (vector similarity > 0.75 against article abstracts).
4. Union the two sets. These articles are candidates for delta recompilation.

Delta recompilation does not rebuild the article from scratch. Instead, the compilation worker:

1. Reads the current article content from S3.
2. Reads the new memories since `compiled_at`.
3. Calls the LLM with: current article + new memories + instruction to integrate new material, flag contradictions, and update the abstract.
4. Writes the updated article back to S3, advances `article_version`, and updates `compiled_at`.

### ACE Curator pattern for articles

The ACE pattern from #169 applies at the article level:

- **Generator**: The initial compilation that produces a full article from source memories.
- **Reflector**: Tracks which articles are queried most frequently, which lint issues recur, and which delta compilations consistently expand coverage in the same sections. Writes findings as system-layer memories.
- **Curator**: Adjusts compilation prompts and article structure templates based on Reflector findings. Example: if the Reflector finds that the "Open Questions" section is consistently the most-queried section, the Curator raises its prominence in the template. Curator changes are logged and require admin review before they modify the active template.

The ACE pattern specifically addresses brevity bias and context collapse: without the Reflector, the compilation LLM will progressively shorten articles as each delta integration trims rather than enriches. The Reflector detects truncation-then-retrieval patterns (the article got shorter, then that section was queried more) and flags them for the Curator.

### Freshness policy

Each `compiled_article` node carries:

```json
{
  "compiled_at": "<ISO8601>",
  "stale_after": "<ISO8601>",
  "compilation_epoch": 7
}
```

`stale_after` is computed as `compiled_at + freshness_ttl`. Default `freshness_ttl` by scope:

| Scope | Default freshness TTL |
|---|---|
| `user` | 1 hour |
| `project` | 4 hours |
| `organizational` | 24 hours |
| `enterprise` | 7 days |

These are defaults. Callers can request recompilation at any time via `compile_knowledge`. The TTL controls when `query_knowledge` returns `status: "stale"` versus `status: "fresh"` for a cached article.

---

## Caching

Article cache keys follow the pattern: `article_cache:{tenant}:{scope}:{scope_id}:{topic_hash}`.

`topic_hash` is the SHA-256 of the normalized topic string (lowercased, stripped, canonical form). Two agents asking about "PostgreSQL connection pooling" and "postgres connection pooling" receive the same cache entry.

The cache stores two values per key:
1. The `compiled_article` node ID (UUID) — allows direct `read_memory` retrieval.
2. The `compilation_epoch` at time of compilation — used for staleness detection.

**Multi-agent sharing**: All agents in the same `(tenant, scope, scope_id)` tuple share the same cache entry. The first agent to request a topic triggers compilation; subsequent agents receive the cached article with no additional LLM cost. This is the primary cost amortization mechanism.

**Cache invalidation**: When the memory store's compilation epoch changes (new memories written, compaction ran), the epoch mismatch marks the cache entry stale. The Valkey key is not deleted immediately — the stale entry continues to serve `status: "stale"` responses while recompilation runs in the background. On completion, the worker updates the cache entry atomically (SET with new epoch and compiled_at).

**Master index cache**: The master index for a scope is cached at `article_cache:{tenant}:{scope}:{scope_id}:__index__`. It is invalidated whenever any article in the scope is compiled or deleted.

**Valkey TTL**: Cache entries carry a Valkey TTL of `stale_after + 1 hour`. This ensures the entry is not retained indefinitely if no agents are active in the scope, but it provides a grace window where the stale article is still servable while recompilation runs.

---

## MCP Tools

All tools inherit MemoryHub's existing authorization flow (`get_claims_from_context()`). Scope and tenant checks enforce isolation before any other predicate.

### `compile_knowledge`

Request compilation of a knowledge article for a topic.

Input:
- `topic` (required) — natural language topic description
- `scope` (required) — `user | project | organizational | enterprise`
- `scope_id` (optional) — project or role identifier for project/role-scoped compilation
- `article_type` (optional, default `concept`) — `concept | entity | timeline | cross_ref`
- `force_recompile` (optional, default `false`) — bypass cache and trigger fresh compilation even if a fresh article exists

Output: `{ "status": "fresh" | "stale" | "compiling", "article_id": uuid | null, "job_id": uuid | null, "compiled_at": ISO8601 | null, "abstract": str | null }`

Authorization: caller must have read access to the specified scope. Compilation of `enterprise` scope requires `memory:admin`.

### `query_knowledge`

Retrieve a compiled article. If no article exists for the topic, triggers compilation and returns `status: "compiling"`.

Input:
- `topic` (required)
- `scope` (required)
- `scope_id` (optional)
- `include_lint_status` (optional, default `true`)
- `hydrate` (optional, default `true`) — if `false`, return only the abstract and metadata; if `true`, fetch and return full article Markdown from S3

Output: `{ "status": "fresh" | "stale" | "compiling" | "not_found", "article_id": uuid | null, "content": str | null, "abstract": str | null, "article_type": str, "compiled_at": ISO8601 | null, "lint_status": str | null, "source_memory_count": int }`

Authorization: same as `compile_knowledge`.

### `lint_knowledge`

Request an immediate lint run for an article or all articles in a scope.

Input:
- `article_id` (optional) — lint a specific article
- `scope` (optional) — lint all articles in the scope (requires `memory:admin`)
- `scope_id` (optional)

Output: `{ "job_id": uuid, "status": "queued" | "complete", "issues_found": int | null }`

Authorization: lint of a specific article requires read access to that article. Scope-wide lint requires `memory:admin`.

### `get_compilation_status`

Poll the status of a compilation or lint job.

Input:
- `job_id` (required)

Output: `{ "job_id": uuid, "status": "queued" | "compiling" | "complete" | "failed", "article_id": uuid | null, "error": str | null, "queued_at": ISO8601, "started_at": ISO8601 | null, "completed_at": ISO8601 | null }`

Authorization: caller must be the job's requestor or have `memory:admin`.

### `file_finding`

File a finding from agent research back into the knowledge base and trigger delta recompilation.

Input:
- `content` (required) — the finding to persist
- `topic` (required) — topic this finding relates to
- `scope` (required)
- `scope_id` (optional)
- `metadata` (optional)

Output: `{ "memory_id": uuid, "delta_compile_queued": bool, "similar_memories": list | null }`

Pre-flight checks: deduplication (similarity > 0.92 blocks write), circular-source detection, minimum content length. Errors return a structured message explaining which check failed.

Authorization: caller must have write access to the specified scope.

---

## Scaling Considerations

When a topic's source memories exceed the compilation LLM's context window (a project with 500 memories all tagged to "architecture decisions"), a single-pass compilation is not feasible. Hierarchical compilation handles this.

### Hierarchical compilation

1. **Cluster**: Group source memories by sub-topic using k-means on their embeddings. Default k = `ceil(source_count / 50)` (targeting ~50 memories per cluster). k-means with cosine distance is pragmatic at MemoryHub's scale but topic clusters in embedding space are often non-convex; topics that bridge two clusters (e.g., "connection pooling in FIPS mode") may land in either. Accept as a known limitation; revisit with HDBSCAN or spectral clustering only if empirical clustering quality becomes a bottleneck.
2. **Sub-compile**: Compile one article per cluster as a sub-topic page. Each sub-compilation is a standard compilation job; jobs run in parallel across available workers.
3. **Synthesize**: Once all sub-topic pages complete, run a final compilation pass that reads the sub-topic page abstracts (not full content) and synthesizes the top-level concept page.
4. **Cross-reference**: The final synthesis pass builds the cross-reference index linking the sub-topic pages.

The top-level article's `source_memory_count` reflects the total across all sub-compilations. The `derived_from` relationships point from the top-level article to the sub-topic articles (not directly to source memories, which would produce an unmanageably large relationship set).

Hierarchical jobs track depth via `compilation_depth`: sub-topic pages get depth 1, the synthesizing top-level page gets depth 2. This depth is distinct from the virtuous-loop depth (they use separate depth counters in job metadata to avoid conflating the two recursion types).

### Cost management

Compilation is an LLM-intensive operation. Cost controls:

- **Per-job token budget**: Configurable cap (default 32K tokens). Jobs exceeding the cap during synthesis are split using hierarchical compilation automatically.
- **Per-scope daily budget**: Admins can set a daily token cap per scope. When reached, new compilation jobs are queued but not started until the next UTC day. The queue is processed in FIFO order.
- **Lint token budget**: Lint jobs use a cheaper LLM endpoint configured separately (default: same model, lower temperature, smaller output token limit). Lint results are not article content — they are structured JSON reports; a small model is sufficient.
- **Delta vs. full recompile cost**: Delta recompilation (ACE pattern) is typically 30–50% of the cost of full recompilation because it provides the existing article as context and asks for targeted integration rather than full synthesis.

---

## Migration

### New tables

```sql
-- Compilation job tracking
CREATE TABLE compilation_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           TEXT NOT NULL,
    scope               TEXT NOT NULL,
    scope_id            TEXT,
    topic               TEXT NOT NULL,
    topic_hash          TEXT NOT NULL,
    article_type        TEXT NOT NULL DEFAULT 'concept',
    article_id          UUID REFERENCES memory_nodes(id),
    status              TEXT NOT NULL DEFAULT 'queued',  -- queued | compiling | complete | failed
    requested_by        TEXT NOT NULL,
    compilation_depth   INTEGER NOT NULL DEFAULT 0,
    parent_job_id       UUID REFERENCES compilation_jobs(id),
    token_budget        INTEGER NOT NULL DEFAULT 32768,
    tokens_used         INTEGER,
    error               TEXT,
    queued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ
);

CREATE INDEX ix_compilation_jobs_tenant_scope  ON compilation_jobs (tenant_id, scope, scope_id);
CREATE INDEX ix_compilation_jobs_topic_hash    ON compilation_jobs (tenant_id, scope, scope_id, topic_hash);
CREATE INDEX ix_compilation_jobs_status        ON compilation_jobs (status) WHERE status IN ('queued', 'compiling');
CREATE INDEX ix_compilation_jobs_article_id    ON compilation_jobs (article_id) WHERE article_id IS NOT NULL;
```

No changes to `memory_nodes` or `memory_relationships` are required. The `compiled_article` branch type and `lint_report` branch type are application-layer enum additions (the column is `String(50)`). The `derived_from` and `related_to` relationship types already exist in the `RelationshipType` enum; no new relationship types are required.

Alembic migration: `015_add_compilation_jobs.py`. Creates the `compilation_jobs` table. Non-destructive; no backfill required.

### Integration with compilation epochs (#175)

Issue #175's compilation epoch mechanism (Valkey key `memoryhub:compilation:<tenant>:<owner>`) already exists. The knowledge compilation service reads the current epoch when writing an article's `compilation_epoch` metadata field, and checks epoch freshness when evaluating cache staleness. No changes to the epoch mechanism are required; the compilation service is a consumer of the existing invalidation signal.

---

## Dependencies

**What this depends on**:

- **#168 (conversation thread persistence)**: Source material for compilation. The `conversation_extractions` table provides the memory→thread provenance that compilation can surface in article footnotes.
- **#169 (context compaction)**: ACE Curator pattern, structured summarization template, and the `compaction_events`/`compaction_retrievals` infrastructure that the Reflector component mirrors at the article level. Compilation epochs from #175 (referenced in #169's compaction trigger) are the cache staleness signal.
- **#170 (graph-enhanced memory)**: Entity nodes (Phase 2) and `mentions` relationships are the primary source for entity page compilation. Temporal validity on relationships (Phase 1) enables timeline page compilation.
- **S3/MinIO**: Article Markdown content stored externally; follows the same decoupling pattern established in commits `9ad20ba`/`efe1df9`. S3 unavailability causes compilation to fail with a structured error (not silent degradation).
- **Valkey**: Job queue, article cache, epoch staleness checks, pub/sub for completion notification. No new Valkey infrastructure beyond what compaction already uses.
- **LLM inference endpoint**: Compilation workers require an LLM endpoint with sufficient context window (32K tokens default) and structured output support. Configured via environment variables in the deployment manifest; not hardcoded.

**What depends on this**:

- Any agent calling `query_knowledge` or `compile_knowledge` (the primary consumer).
- The master index article is consumed by agents as the entry point to navigate the knowledge base.
- `file_finding` creates a feedback loop from agent work back into the source memory pool — this is the virtuous loop and any agent performing original research is a potential contributor.
- llm-d prefix cache routing (OpenShift AI): deterministic article content is expected to produce cross-agent KV cache hits via llm-d's KV Block Index routing (based on how prefix-keyed KV caching works; not yet validated against production llm-d deployments). No code change required; the benefit is structural.

---

## Open Questions

**Model collapse prevention**: The research community flagged model collapse (Shumailov et al., Nature 2024) as a risk when LLMs iteratively process their own outputs. Compilation reads agent-authored memories and produces articles; agents then use those articles to write new memories; the cycle repeats. Mitigation: track `compilation_depth` in article provenance and flag articles that have been through more than three compilation cycles without fresh `raw_input_memory_count` (memories extracted from conversation threads, not from prior articles). High-depth articles with no raw memory refresh are candidates for human review. This is a policy decision, not an architectural one; define the threshold and escalation path before enabling compilation in production.

**Compilation scheduling strategy**: The current design triggers compilation reactively (on `file_finding` or explicit `compile_knowledge` calls) and periodically (lint schedule). Should there be a proactive compilation pass when a scope's source memories grow significantly but no agent has requested a compilation? Options: (a) no proactive pass — agents discover and request; (b) proactive pass triggered when `appendix_count / compiled_set_size > auto_recompile_threshold` (reuse the #175 threshold). Recommend option (b) to keep articles current without requiring explicit agent requests; needs a decision before the scheduler pod is implemented.

**Cost budgets as first-class configuration**: The per-job and per-scope token budgets described in §Scaling Considerations are specified here but not wired into a user-facing configuration API. Before production deployment, define whether these are configured via `curator_rules` (consistent with compaction policy) or via a new `compilation_policy` table. Lean toward `curator_rules` to avoid a new table.

**Human-in-the-loop for published articles**: Enterprise or organizational scope articles may require human review before they are visible to other agents. The current design publishes articles immediately on compilation completion. Add a `require_review` flag to compilation requests (scope-configurable, default `false` for `user`/`project`, `true` for `enterprise`). Reviewed articles are published; rejected articles are archived with the reviewer's feedback as a `lint_report` branch.

**Contradiction blocking at article publish**: The compaction service blocks compaction for memories with unresolved `contradiction_reports`. The same guard should apply to article publication: if source memories have open contradictions, the article is published with `lint_status: "issues"` and the contradiction count noted. A stricter policy (block publication entirely) is appropriate for `enterprise` scope; this needs a configuration decision.
