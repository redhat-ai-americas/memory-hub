# OMP Interoperability: Trust Provenance and Context Assembly

**Issue**: #559, #561, #562, #563, #566
**Date**: September 2026
**Status**: Phases 1 and 2 shipped. Taint metadata shipped.

## Background

This work originates from cross-ecosystem analysis conducted during the Open Memory Protocol (OMP) prior art survey and standards sketching sessions. The analysis of 16 agent harnesses, 10 enterprise memory services, and 12 emerging standards surfaced several gaps in MemoryHub's security posture and provenance tracking. The full improvement roadmap lives in `planning/omp-informed-improvements.md`; this document covers what was implemented in the initial two phases.

The central insight from the OMP analysis: an extraction pipeline is a transform, not an endorsement. When a memory is derived from content that arrived through a channel, the memory must carry the channel's trust level, not the extractor's. MemoryHub's dreaming pipeline was laundering taint: a memory extracted from a web scrape looked identical to one extracted from a direct user statement. This is the security gap that Phase 1 addresses.

## Phase 1: Trust Provenance and Dreaming Gates

### Upstream trust level

A new `upstream_trust_level` column on `memory_nodes` tracks the trust level of the content that produced a memory. Three values are supported:

| Value | Meaning |
|-------|---------|
| `trusted` | Content originated from a trusted channel (direct user or assistant message) |
| `untrusted` | Content originated from an untrusted channel (tool result, web scrape, external API) |
| `mixed` | Memory was extracted from a conversation containing both trusted and untrusted content |

The column defaults to `trusted` for backward compatibility. Existing memories retain their default; no backfill is needed because pre-OMP memories were all extracted without channel-level trust tracking. Migration 028 adds the column and a filtered index for query performance.

#### Trust inference in the extraction pipeline

The SDK's `ExtractionPipeline` determines trust level from trace events at extraction time via `infer_trust_level()`. The logic is:

1. If the trace event carries explicit metadata (`upstream_trust_level` or `trust_level` key), use it
2. Otherwise, `TOOL_RESULT` events default to `untrusted` (tool outputs are external by definition)
3. All other event types (user messages, assistant responses) default to `trusted`

Trust inference runs after extraction but before dedup and routing (step 1b in the pipeline). Each candidate's `upstream_trust_level` field is set based on its source event, and the value flows through to the `write()` call that persists the memory.

The `CandidateMemory` dataclass carries `upstream_trust_level` (default `"trusted"`) so extractors can set it explicitly when they have channel-level knowledge. The pipeline only overrides the default; an extractor that sets a non-default value retains priority.

### Dreaming gates

Configurable threshold gates run before the LLM consolidation step in the extraction pipeline. Candidates that fail any threshold are deferred to the next dreaming cycle, not discarded.

Three thresholds, all configurable via `GateThresholds`:

- `min_recall_count`: minimum times the candidate was retrieved in search results before qualifying
- `min_unique_queries`: minimum distinct queries that surfaced the candidate
- `min_score`: minimum confidence score

All thresholds default to 0 (effectively disabled). When `gate_thresholds` is passed to `ExtractionPipeline`, the `DreamingGate` evaluates all non-duplicate candidates and splits them into passed and deferred lists. Deferred candidates appear in `ExtractionResult.deferred` so callers can track what was held back.

The gate design follows OpenClaw's three-phase dreaming pattern, where deterministic filters reduce LLM costs by ensuring only well-evidenced candidates reach the expensive consolidation step. The key difference: OpenClaw's thresholds are hardcoded; MemoryHub's are configurable per pipeline instance.

## Phase 2: Context Assembly Pipeline and Generating Model

### Context assembly pipeline

The MCP server's post-retrieval injection path is composed as an explicit, ordered pipeline of 9 named stages. Each stage receives a `PipelineState`, may filter or annotate results, and produces structured log entries for auditability. Stages never raise; failures are logged and the pipeline continues with unmodified state.

The stages in order:

| # | Stage | Purpose | Filters? |
|---|-------|---------|----------|
| 1 | `authenticate_source` | Defense-in-depth: verify all results belong to the resolved tenant | Yes |
| 2 | `validate_schema` | Assert results are well-formed Pydantic models (service layer bug detector) | Yes |
| 3 | `enforce_scope` | Re-verify each result's scope is in the caller's authorized set | Yes |
| 4 | `check_freshness` | Log temporal composition of results | No (audit) |
| 5 | `deduplicate` | Remove duplicate results by memory ID, keeping highest-scoring | Yes |
| 6 | `apply_budget` | Log budget parameters (actual packing happens in search_memory) | No (audit) |
| 7 | `screen_content` | Placeholder for content moderation | No (not yet implemented) |
| 8 | `stamp_provenance` | Log source and trust level distribution | No (audit) |
| 9 | `emit` | Log final emission count | No (audit) |

#### Ordering invariants

The stage order encodes two security invariants:

- **Scope before dedup** (stage 3 before stage 5): prevents cross-tenant scope probing via dedup oracle attacks. If dedup ran first, an attacker could infer the existence of out-of-scope memories by observing which of their duplicates survive.
- **Budget before screening** (stage 6 before stage 7): prevents context exhaustion from consuming screening resources. If screening ran on the full candidate set before budget filtering, a large result set could exhaust moderation quotas or latency budgets.

These invariants are documented in the module docstring and enforced by the stage ordering in `run_pre_budget_pipeline()`.

#### Integration with search_memory

Stages 1 through 5 run via `run_pre_budget_pipeline()` after retrieval and domain boosting but before compilation ordering. Stages 6 through 8 run inline in `search_memory` after the compilation/budget packing loop. Stage 9 runs after the formatted response is assembled. The split exists because budget packing, S3 hydration, and compilation ordering are tightly coupled with formatting logic that cannot be cleanly extracted into standalone stage functions.

Each stage logs a `PipelineLogEntry` with stage name, result code, input/output counts, and optional detail dict. `log_pipeline_summary()` emits a single structured log line with the full pipeline trace at INFO level.

### Generating model

A new `generating_model` column on `memory_nodes` tracks which LLM produced a dreaming-extracted memory. User-stated memories leave this null. Migration 029 adds the column.

The field is populated during extraction: `ExtractionPipeline` accepts an optional `generating_model` parameter, and `_write_candidate()` passes it through to the `client.write()` call. Individual candidates can also carry their own `generating_model` value, which takes precedence over the pipeline-level default.

This field supports two use cases:

1. **Confidence calibration**: downstream consumers can weight memories differently based on the extraction model's known accuracy characteristics
2. **Provenance auditing**: the `stamp_provenance` pipeline stage logs the distribution of generating models in the result set, making it visible when dreaming-extracted content dominates a search response

## Taint Metadata in Responses

When a memory has `upstream_trust_level` of `untrusted` or `mixed`, search and read responses include a `taint` metadata block:

```json
{
  "taint": {
    "tainted": true,
    "sources": ["dreaming"]
  }
}
```

The `sources` array contains the memory's `source` field value. For PTC-integrated harnesses, this metadata feeds into `TurnContext.ingest_memory_taint()`, enabling the no-write-up floor on the resulting turn. For non-PTC harnesses, the field serves as advisory information that agents can use to adjust their confidence in the recalled content.

Taint injection happens at the formatting layer:

- `search_memory`: the `_inject_taint()` helper adds the block to both verbose and compact entry formats, and to nested branch entries
- `read_memory`: taint is added directly to the response dict after `model_dump()`

### Bug fix: fields silently dropped

Prior to this change, `upstream_trust_level` and `generating_model` were defined on the ORM model but not propagated through the read/stub construction paths. Specifically:

- `node_to_read()` did not pass these fields to `MemoryNodeRead`, so they were silently replaced by schema defaults
- `MemoryNodeStub` did not declare the fields at all, so stub-form results never carried them
- Backfill entries in `_backfill_compiled_entries()` constructed `MemoryNodeStub` without these fields

The fix added `upstream_trust_level` and `generating_model` to `MemoryNodeRead` (via `node_to_read()`), `MemoryNodeStub` (schema declaration plus construction sites), and the backfill path in `search_memory.py`.

## Schema Changes

### Migration 028: upstream_trust_level

Adds `upstream_trust_level VARCHAR(20) NOT NULL DEFAULT 'trusted'` to `memory_nodes`. Creates a filtered index `ix_memory_nodes_upstream_trust_level` for queries that filter by trust level.

### Migration 029: generating_model

Adds `generating_model VARCHAR(255) NULL` to `memory_nodes`. No index (the field is for provenance display and audit logging, not query filtering).

Both migrations are backward-compatible: the defaults match pre-existing behavior, and no data migration is needed.

## What Is Not Covered

This design covers only the implemented work. The following items from the OMP improvement roadmap remain as future work (see `planning/omp-informed-improvements.md`):

- **MOF export format** (item 2): Standard memory object format for cross-system portability
- **PTC taint ingestion hook** (item 5): Wiring MemoryHub's taint reporting into PTC's `TurnContext`
- **Per-scope consent signals** (item 6): User-controlled memory on/off toggles per scope
- **Contradiction signaling alignment** (item 7): Aligning `report_contradiction` with OMP standard operations
- **Memory source admission** (item 9): Human-ceremony gates for new memory source channels

## Further Reading

- [OMP improvements roadmap](../../planning/omp-informed-improvements.md) -- full 9-item improvement list from the OMP prior art analysis
- [Retrieval pipeline](retrieval-pipeline.md) -- the hybrid retrieval pipeline that feeds into context assembly
- [Curator agent](curator-agent.md) -- the dreaming pipeline that uses the extraction gates
- [Architecture](../ARCHITECTURE.md) -- system-level overview
