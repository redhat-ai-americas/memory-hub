# Token Compression Layer -- Design

Issue: #246
Status: Design
Author: rdwj
Date: 2026-06-03

## Problem

Memory search results carry structural metadata (id, owner_id, scope, weight,
created_at, updated_at, tenant_id, content_type, metadata, domains, branch_type,
storage_type, content_ref, version, etc.) alongside content. For 10 memories,
this adds ~350-400 tokens of structural overhead the model doesn't need. Content
itself may also contain redundant whitespace, verbose formatting, or
near-duplicate passages across overlapping memories.

Beyond raw token count, there is a cognitive load dimension. Structural metadata
in the context window can activate model reasoning about that metadata (e.g., the
model starts reasoning about weights, scopes, and timestamps instead of the task
at hand). This was the motivating insight behind the compact CLI output design
and is documented in planning/archive/hooks-memory-injection.md.

## What's already shipped

### Structural overhead reduction

| Feature | Location | Token savings | Status |
|---------|----------|---------------|--------|
| MCP tool consolidation (10->2) | memory-hub-mcp v0.9.0 | ~5,750 tokens (85% tool def reduction) | Shipped |
| Compact MCP responses (#255) | search_memory.py, list_memory.py | ~300-400 tokens per 10-result query | In progress |
| Compact CLI output | memoryhub-cli `--output compact` | Eliminates all metadata for startup injection | Shipped |
| Hook pre-loading | `.claude/hooks/load-memories.sh` | Zero MCP overhead for startup context | Shipped |

### Content-level optimization

| Feature | Location | Mechanism | Status |
|---------|----------|-----------|--------|
| Token budgeting | search_memory.py `max_response_tokens` | Soft cap (default 4000); excess results degrade to stubs | Shipped |
| Weight-based stubbing | search_memory.py `mode`/`weight_threshold` | Low-weight matches return stub only | Shipped |
| Cache-optimized assembly | compilation.py | Stable ordering for KV cache reuse (#175) | Shipped |

## Proposed: Pre-LLM content normalization

This section covers retrieval-time transformations that reduce token count
without altering the meaning of memory content. These complement the structural
overhead reductions above by operating on the content payload itself.

### Candidates

1. **Whitespace normalization** -- Collapse multiple consecutive newlines to
   double-newline (paragraph break), strip trailing spaces, normalize
   inconsistent indentation. Low risk, immediate savings. Estimated 5-15% token
   reduction on memories with verbose formatting (e.g., pasted code blocks with
   blank-line padding, multi-line YAML with trailing whitespace).

2. **URL shortening** -- Replace verbose URLs with shortened references or
   domain-only placeholders when the full path is not semantically load-bearing.
   Example: `https://docs.example.com/v3/api/authentication/oauth2/client-credentials#token-endpoint`
   becomes `[docs.example.com/.../client-credentials]`. Moderate savings on
   documentation-heavy memories. Must preserve URLs that are direct action items
   (e.g., "deploy to https://console.example.com/project/foo" keeps the full
   URL).

3. **Cross-memory deduplication** -- When multiple search results share
   overlapping content (common with branched memories or version chains),
   deduplicate at response time. Show full content for the first occurrence;
   subsequent overlapping passages reference back. Higher complexity, significant
   savings for branch-heavy queries where rationale branches repeat the parent's
   context verbatim.

4. **Metadata stripping** -- Already addressed by compact response mode (#255).
   Content-only projection eliminates structural metadata. This is the
   highest-impact single change and ships independently.

5. **Stub quality improvement** -- Generate more informative stubs at write time.
   Currently stubs are the first 200 characters, which may cut mid-sentence or
   include boilerplate. Better stubs mean agents need fewer full-content reads,
   reducing follow-up `read_memory` calls and their associated token cost.

### Not in scope

- **Semantic summarization** -- LLM-based compression at retrieval time is too
  expensive and too slow. Pre-compute summaries at write time if needed. The
  context compaction design (docs/design/context-compaction.md) covers governed
  summarization at the storage layer; this design covers retrieval-time
  formatting.

- **Lossy content compression** -- Never drop facts from content. Compression is
  lossy on formatting, not meaning. If a transformation could change what the
  agent concludes from the memory, it does not belong here.

## Architecture

### Where the layer lives

Three candidate insertion points, each with different tradeoffs:

| Location | Pros | Cons |
|----------|------|------|
| **MCP server response path** | Uniform for all consumers; single implementation; testable in isolation | Opinionated; can't be disabled per-consumer without adding parameters |
| **SDK client** | Consumer controls compression; reversible | Each SDK language needs its own implementation; CLI already has its own path |
| **Both (layered)** | Server does safe defaults; SDK does consumer-specific | Two implementations to maintain |

**Recommendation:** Server-side for safe, universal normalization (whitespace,
metadata stripping). These are lossless and uncontroversial -- no consumer should
prefer trailing whitespace or inconsistent newlines. SDK-side for
consumer-specific formatting (URL shortening, dedup preferences) where the
consumer's use case determines whether the transformation is appropriate.

This matches the tiered integration model described in
planning/archive/hooks-memory-injection.md: Tier 1 (SDK) consumers control their own
formatting; Tier 2/3 (MCP) consumers get safe defaults from the server.

### Implementation location

Server-side normalization applies in `_format_entry` and `_format_entry_cached`
in `search_memory.py`, after content is extracted from the model but before
serialization. This is the natural choke point: both cache-optimized and raw
result paths flow through these functions.

```
search_memories() -> results
    |
    v
_format_entry / _format_entry_cached
    |
    v
normalize(content)    <-- new step
    |
    v
JSON serialization -> response
```

### Configuration

Extend the `options` dict on search/list actions with a `compression` level:

```
options: {
  compression: "none" | "standard" | "aggressive"
}
```

- `none`: raw content, no normalization. For debugging or when the consumer needs
  exact content fidelity.
- `standard` (default): whitespace normalization + compact response mode. Safe
  for all consumers.
- `aggressive`: standard + URL shortening + cross-memory deduplication. Opt-in
  because URL shortening and dedup change the shape of the content in ways some
  consumers may not expect.

The `compression` option composes with existing parameters. `mode=index` +
`compression=standard` produces normalized stubs. `max_response_tokens=2000` +
`compression=aggressive` applies dedup before token budget packing, potentially
fitting more results within the budget.

### Normalization functions

```python
def normalize_whitespace(content: str) -> str:
    """Collapse redundant whitespace without altering meaning.

    - Strip trailing whitespace from each line.
    - Collapse 3+ consecutive newlines to 2 (preserve paragraph breaks).
    - Normalize tabs to spaces within non-code content.
    """
    ...

def shorten_urls(content: str) -> str:
    """Replace long URLs with domain + final path segment.

    Preserves URLs shorter than 60 characters (already compact).
    Preserves URLs in explicit action items (heuristic: preceded by
    'deploy to', 'open', 'navigate to', 'go to').
    """
    ...

def dedup_across_results(entries: list[dict]) -> list[dict]:
    """Deduplicate overlapping content across result entries.

    Uses 3-sentence sliding window fingerprinting. When overlap exceeds
    70% of a result's content, replace with a cross-reference:
    '[see memory <id> above for shared context]'.
    """
    ...
```

## Measurement methodology

### Metrics

1. **Token count** -- before/after compression, measured by tiktoken
   (cl100k_base). Measure per-result and per-response-envelope.

2. **Content preservation** -- automated check that key facts survive
   compression. Extract entity-claim pairs from content before and after
   normalization; assert bijection. This catches any normalization that
   accidentally drops meaningful content.

3. **Agent task accuracy** -- does compression affect downstream task quality?
   Measure on a held-out benchmark of memory-dependent agent tasks (e.g.,
   "retrieve deployment preferences and apply them to a new project" -- verify
   the agent reaches the same conclusions with compressed vs. uncompressed
   input).

### Measurement protocol

1. Sample 100 real search queries from production logs (anonymized by
   replacing content with synthetic equivalents if needed for privacy).
2. Record full responses (baseline) and compressed responses (treatment) at
   each compression level.
3. Measure token savings per query (mean, median, p90).
4. Run the entity-claim preservation check on all 100 samples.
5. Run agent-accuracy benchmark on a subset of 20 representative queries.

### Success criteria

- >=30% token reduction for `standard` compression on top of compact response
  mode (measured against raw content with metadata already stripped).
- Zero regression in entity-claim preservation (bijection check passes for all
  100 samples).
- Zero regression in agent task accuracy on the 20-query benchmark.
- P99 latency increase <=10ms for the compression step (normalization is string
  processing, not LLM calls; this should be trivially met).

## Implementation phases

1. **Phase 0 (shipped):** Compact response mode (#255), token budgeting,
   weight-based stubbing. This is the baseline all subsequent phases measure
   against.

2. **Phase 1:** Whitespace normalization in the MCP server response path.
   Add `normalize_whitespace()` to `_format_entry` / `_format_entry_cached`.
   Gate behind `compression != "none"` (on by default). Measure token savings
   on production queries. Ship when >=10% reduction confirmed.

3. **Phase 2:** URL shortening (opt-in via `compression=aggressive`).
   Add `shorten_urls()` after whitespace normalization. Measure incremental
   savings. Ship when entity-claim preservation passes.

4. **Phase 3:** Cross-memory deduplication for branch-heavy queries. Apply
   `dedup_across_results()` after individual entry formatting but before JSON
   serialization. This operates on the assembled result list, not individual
   entries. Measure savings specifically on queries that return parent + branch
   results.

5. **Phase 4:** SDK-side compression API for consumer-specific formatting.
   Add `MemoryHubClient.search(..., compression="aggressive")` that passes the
   option through to the MCP server. SDK consumers who call the REST API
   directly can apply their own post-processing.

6. **Phase 5:** Stub quality improvement. Change stub generation at write time
   to produce a complete first sentence (up to 200 chars) rather than a
   character-count truncation. Requires an Alembic migration to backfill
   existing stubs. Measure reduction in follow-up `read_memory` calls after
   stub improvement.

## Interaction with other work

- **#255 (Tiered integration):** Compact response mode is Phase 0 of this work.
  This design extends it with content-level normalization.

- **#203 (Skill wrappers):** Skills use CLI `--output compact` which already
  strips metadata. Token compression at the CLI level is orthogonal; skills that
  use the MCP server mid-conversation benefit from server-side normalization.

- **#256 (Hooks):** Hook startup injection uses compact CLI output. Server-side
  compression applies to mid-conversation MCP searches, not to hook-injected
  startup context.

- **Context compaction services (docs/design/context-compaction.md):** That design
  covers governed compaction (dedup + merge + archival) at the storage layer
  with full provenance tracking and compliance guarantees. This design covers
  retrieval-time formatting -- lightweight, reversible, no storage mutation.
  The two are complementary: storage-layer compaction reduces what's stored;
  retrieval-time compression reduces how it's presented.

## References

- tinyhumansai/openhuman "TokenJuice" -- inspiration for pre-processing layer
  (up to 80% reduction reported on unstructured memory content)
- OpenAI token counting: tiktoken cl100k_base
- MemoryHub context compaction design: docs/design/context-compaction.md
- MemoryHub hooks memory injection design: planning/archive/hooks-memory-injection.md
- Factory.ai structured summarization benchmark (referenced in
  docs/design/context-compaction.md)
