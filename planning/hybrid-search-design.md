# Hybrid Search: Keyword Fallback for Retrieval Pipeline

**Status:** Design (for #305)
**Date:** 2026-07-10

## Problem

Pure vector search misses exact-match queries. An agent searching for "FIPS-140-2" or "deploy-full.sh" gets results about compliance or deployment scripts generally, but may miss the memory that contains the exact string. Embedding models compress lexical detail into semantic space; rare terms, proper nouns, acronyms, and CLI commands lose fidelity.

## Approach: PostgreSQL `tsvector` as a fifth RRF signal

No new dependencies. PostgreSQL's built-in full-text search (`tsvector`/`tsquery`/`ts_rank`) provides BM25-equivalent keyword ranking using the same database. The keyword signal slots into the existing RRF blend alongside query, focus, domain, and graph.

### Schema change

Add a generated `tsvector` column to `memory_nodes`:

```sql
ALTER TABLE memory_nodes
  ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(stub, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(content, '')), 'B')
  ) STORED;

CREATE INDEX idx_memory_nodes_search_vector
  ON memory_nodes USING GIN (search_vector);
```

Stub gets weight A (higher) because it's the summary line. Content gets weight B. The column auto-updates on INSERT/UPDATE with zero application code changes.

Alembic migration, not `create_all`.

### SQLAlchemy model change

Add to `MemoryNode`:

```python
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import TSVECTOR

search_vector: Mapped[Any] = mapped_column(
    TSVECTOR,
    Computed(
        "setweight(to_tsvector('english', coalesce(stub, '')), 'A') || "
        "setweight(to_tsvector('english', coalesce(content, '')), 'B')"
    ),
    nullable=True,
)
```

### Retrieval change

In `search_memories_with_focus`, after the pgvector recall stage, add a parallel keyword recall:

```python
# Keyword recall: ts_rank against the same filter set
tsquery = func.plainto_tsquery('english', query)
keyword_stmt = (
    select(MemoryNode, func.ts_rank(MemoryNode.search_vector, tsquery).label("rank"))
    .where(*filters, MemoryNode.search_vector.op('@@')(tsquery))
    .order_by(func.ts_rank(MemoryNode.search_vector, tsquery).desc())
    .limit(k_recall)
)
```

Merge keyword results into the candidate pool (dedup by ID). Rank the keyword results and add as a fifth RRF signal:

```
score(m) = w_q/(K+rank_query) + w_f/(K+rank_focus) + w_d/(K+rank_domain)
         + w_g/(K+rank_graph) + w_k/(K+rank_keyword)
```

Memories found only by keyword (not in the vector recall set) get a miss rank for the query signal but a real rank for keyword. This is exactly what RRF is designed for: fusing disjoint recall sets.

### Configuration

| Parameter | Default | Effect |
|-----------|---------|--------|
| `keyword_boost_weight` | 0.15 | Keyword signal weight in RRF blend |

When `keyword_boost_weight > 0` and the query produces at least one `tsquery` match, the keyword signal is active. When no keyword matches exist (purely semantic query like "how do I feel about testing"), the weight redistributes to the remaining signals. Same pattern as domain and graph boosts.

### What this does NOT do

- No external search engine (Elasticsearch, Meilisearch). PostgreSQL handles this at our scale.
- No `pg_trgm` for fuzzy matching. That's a future enhancement if exact-match proves insufficient.
- No changes to `search_memories` (the no-focus path). Keyword search only activates in the focused pipeline where RRF is already running. The plain path stays pure vector for simplicity. If benchmarks show keyword helps without focus too, we can extend later.
- No query parsing. `plainto_tsquery` handles the common case (space-separated terms become AND). Quoted phrases and boolean operators are future work.

### Fallback behavior

- SQLite (tests): `tsvector` is PostgreSQL-only. The keyword stage is skipped with `keyword_fallback_reason = "tsvector not available (non-PostgreSQL backend)"`. Tests continue to work.
- Empty query: `plainto_tsquery('')` returns an empty tsquery. The `@@` operator matches nothing. Keyword stage returns empty, weight redistributes. No special handling needed.

## Sizing

- GIN index on `tsvector`: ~20-30% of content size. For 10K memories averaging 500 bytes, roughly 1-1.5 MB. Negligible.
- `ts_rank` query: milliseconds on GIN index. Runs in parallel with the vector recall (both hit PostgreSQL).
- Generated column: zero write-path code changes. PostgreSQL maintains it.

## Test plan

1. Unit test: keyword recall finds exact-match memories that vector search misses
2. Unit test: RRF blend with keyword signal ranks exact-match higher than semantic-only
3. Unit test: keyword stage gracefully skips on SQLite
4. Integration: benchmark before/after on the existing two-vector fixture set, plus a new fixture set with exact-match queries (CLI commands, config keys, acronyms)

## Implementation sequence

1. Alembic migration (schema)
2. SQLAlchemy model update
3. Keyword recall in `search_memories_with_focus`
4. RRF integration + weight redistribution
5. Tests
6. Benchmark comparison
