# Combined Ingestion Mode

Status: Design (Session B of dreaming combined-mode split)
Issue: Part of #349 (Layer 2 benchmark run)

## Problem

The dreaming benchmark tests extraction in isolation: extracted facts
REPLACE original session transcripts instead of AUGMENTING them.
In production, dreaming is additive -- agents write memories, the
pipeline extracts facts asynchronously, and search returns both. A
combined benchmark models this production behavior.

## Design: library-first, then dreaming-on-top

Combined mode runs two phases sequentially in the same project:

1. **Library ingest** -- call `_run_library_ingest(documents)`. This
   writes each session as a memory (parent + chunks) via `client.write()`.
   All memories get `source=agent` (the default).

2. **Dreaming ingest** -- call `_run_dreaming_ingest(documents)`. This
   creates threads per persona, appends session messages, and calls
   `extract_thread()`. Extracted facts get `source=dreaming` (set by
   reconciliation).

This models production: agents write memories during conversations,
dreaming runs asynchronously afterward. Both coexist in the same
project.

## Pool discipline

Combined mode puts transcripts (parents/chunks) AND extracted facts in
one search pool. This is exactly the units-competing-in-RRF scenario
that `retrieval_unit` (planning/eager-fact-extraction.md Section 6) was
designed to govern.

**Default search behavior**: no `retrieval_unit` set. Let facts,
chunks, and parents compete in RRF. The reranker should sort by
relevance. The registered prediction says combined ~ 84.9% +/- noise
because transcripts already saturate recall at 4-7 parents/persona.

**If accuracy drops below 84.9%**: that's a pool-discipline failure.
Diagnose with `retrieval_unit=auto` (facts-first with parent fallback)
to separate the units. This is a diagnostic step, not the default.

**Ablation support via source filter**: `exclude_source=dreaming`
reproduces the library-only baseline without re-ingesting.

## Search parameters

Add three env vars to the harness search path, following the existing
`MEMORYHUB_DISABLED_SIGNALS` pattern:

| Env var                    | Maps to              | Purpose                      |
|----------------------------|----------------------|------------------------------|
| `MEMORYHUB_RETRIEVAL_UNIT` | `retrieval_unit`     | Control unit class returned  |
| `MEMORYHUB_SOURCE`         | `source`             | Include only this source     |
| `MEMORYHUB_EXCLUDE_SOURCE` | `exclude_source`     | Exclude this source          |

These are search-time filters, not ingestion-time. They compose with
existing parameters (disabled_signals, focus, etc.).

## Project isolation

Fresh project for the combined run (e.g., `amb-combined-pro`).
amb-granite-pro (84.9% baseline) must not be modified.

## Skip-ingestion shortcut

If a project already has library memories from a previous run, set
`MEMORYHUB_INGESTION_MODE=combined` with `--skip-ingestion` to skip
the library phase. The dreaming phase creates threads and extracts on
top of existing data. But for the benchmark, always ingest fresh to
ensure clean state.

## Implementation

All changes in one file:
`benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py`

1. Add `"combined"` to the mode validation set (line 117).
2. Add a third branch in `_run_ingest` for combined mode.
3. New method `_run_combined_ingest(documents)`:
   - Calls `_run_library_ingest(documents)` first.
   - Then calls `_run_dreaming_ingest(documents)`.
   - Both methods already handle project creation idempotently.
4. Add `retrieval_unit`, `source`, `exclude_source` to `_run_retrieve`
   search kwargs (conditional on env vars being set).

## Running the benchmark

```bash
# Combined mode -- fresh ingest
MEMORYHUB_INGESTION_MODE=combined \
MEMORYHUB_PROJECT_ID=amb-combined-pro \
MEMORYHUB_EXTRACTION_MODEL=gemini-3.1-flash-lite \
MEMORYHUB_EXTRACTION_MODEL_URL=https://generativelanguage.googleapis.com/v1beta/openai \
uv run omb run --name combined-pro --description "Combined library+dreaming"

# Ablation: exclude dreaming
MEMORYHUB_EXCLUDE_SOURCE=dreaming \
MEMORYHUB_PROJECT_ID=amb-combined-pro \
uv run omb run --name combined-no-dreaming --skip-ingestion

# Ablation: dreaming-only
MEMORYHUB_SOURCE=dreaming \
MEMORYHUB_PROJECT_ID=amb-combined-pro \
uv run omb run --name combined-dreaming-only --skip-ingestion
```

## Predictions (registered per standing practice)

- **Aggregate**: combined ~ 84.9% +/- noise (transcripts saturate
  recall). Upside is category-level, not aggregate.
- **Category-level**: facts' synthesis signature may lift generalization
  and reasons questions even alongside transcripts.
- **Below 84.9%**: pool-discipline failure. Diagnose with
  `MEMORYHUB_RETRIEVAL_UNIT=auto`.
- **exclude_source=dreaming**: should reproduce library-only 84.9%.
- **source=dreaming**: should approximate dreaming-only 70%.
