# Memory Source Tagging

Status: Design (Session A of dreaming combined-mode split)
Issue: Part of #349 (Layer 2 benchmark run)

## Problem

The extraction pipeline stores provenance in two places:
`metadata.extraction_source` (JSON blob on the memory node) and the
`conversation_extractions` join table. Neither is queryable via a simple
SQL filter. To distinguish "agent wrote this" from "dreaming extracted
this," you need a JSON operator or a join. This blocks three production
use cases:

1. **Ablation testing.** The combined benchmark needs to exclude dreaming
   memories to verify they don't hurt the library-only baseline. Without
   a queryable field, the harness must post-filter results client-side.
2. **Operator audit.** Production operators need to see how much of a
   project's memory is agent-written vs extracted, without writing SQL.
3. **Search filtering.** Agents may want "only show me what I wrote" or
   "only show me extracted facts" in production.

## Decision: Column, not metadata

Add a `source` column to `memory_nodes` (VARCHAR(20), indexed, default
`'agent'`). A `metadata.source` key would avoid a migration but requires
`metadata->>'source'` in every query and can't use a btree index.

The `source` column follows the same pattern as `content_type`: a
top-level indexed string column with a check constraint for known values.

## Source values

Aligned with the existing producer taxonomy in the extraction pipeline:

| Value      | Producer                                        | Set by                    |
|------------|-------------------------------------------------|---------------------------|
| `agent`    | Written directly by an agent via MCP/SDK/API    | Default on column         |
| `dreaming` | Extracted by the background dreaming pipeline   | reconciliation.py create  |
| `import`   | Bulk import / git-transport / membership promo  | Future: import service    |

Why not a generic `extraction` value for all extraction triggers (eager,
background, session-close)? Because the three-trigger design in
eager-fact-extraction.md (Section 5) treats these as distinct producer
identities with different quality characteristics. `dreaming` is the
background pipeline. When eager extraction ships, it gets its own value
(`eager`). The column is VARCHAR, not a Postgres enum, so adding values
requires only a migration to update the check constraint.

The extraction_run_id prefix (`dream:`) already discriminates trigger
type at the run level. `source` is the coarse, indexable projection that
search filters use.

## Search filter

Add two optional parameters to the search path:

- `source: str | None` -- include only memories from this source.
- `exclude_source: str | None` -- exclude memories from this source.

`exclude_source` is the more useful variant for ablation: "give me
everything except dreaming memories" reproduces the library-only
baseline. Both follow the `content_type` filter pattern: simple equality
(or inequality) check in `_build_search_filters`, threaded through all
search entry points.

Mutual exclusivity: if both are provided, `source` wins (the inclusive
filter is more specific).

## Migration

Alembic migration `026_add_source_column`:

1. Add `source` column (VARCHAR(20), NOT NULL, server_default `'agent'`).
2. Add check constraint `ck_memory_nodes_source` for known values
   (`agent`, `dreaming`, `import`).
3. Add btree index `ix_memory_nodes_source`.

Default `'agent'` handles existing rows correctly: all 3,516
amb-granite-pro memories and all 3,620 amb-dreaming-tiny memories were
created before source tagging existed. The amb-dreaming-tiny memories
SHOULD be `dreaming` but backfilling is de-scoped from this session (the
combined benchmark ingests fresh into a copy, so new extractions get the
correct tag at write time). Backfill is a maintenance item.

## Implementation surface

| Layer          | File                                          | Change                                          |
|----------------|-----------------------------------------------|--------------------------------------------------|
| Model          | `models/memory.py`                            | Add `source` column                              |
| Schema         | `models/schemas.py`                           | Add `source` to Create/Read/Stub schemas          |
| Migration      | `alembic/versions/026_add_source_column.py`   | Column + constraint + index                      |
| Reconciliation | `services/reconciliation.py`                  | Set `source='dreaming'` on MemoryNodeCreate       |
| Search         | `services/memory.py`                          | Add source/exclude_source to _build_search_filters |
| MCP tool       | `memory-hub-mcp/src/tools/search_memory.py`   | Add source/exclude_source parameters              |
| MCP dispatch   | `memory-hub-mcp/src/tools/memory.py`          | Add to _SEARCH_OPTS                               |
| SDK            | `sdk/src/memoryhub/client.py`                 | Add source/exclude_source to search()             |
| CLI            | `sdk/src/memoryhub/cli.py`                    | Add --source/--exclude-source flags (if present)  |

## Backfill (de-scoped)

Existing amb-dreaming-tiny memories should eventually get
`source='dreaming'` via a one-shot UPDATE joined on
`conversation_extractions`. This is hygiene, not a prerequisite for the
combined benchmark. Add to the Haiku maintenance list.

## Testing

- Migration: verify column exists, default works, constraint rejects
  invalid values.
- Reconciliation: verify `source='dreaming'` on memories created by the
  extraction pipeline.
- Search: verify `source` and `exclude_source` filters return correct
  results.
- MCP/SDK: verify parameters are accepted and forwarded correctly.
