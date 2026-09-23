# Dreaming Pipeline: Threshold Gates

Issue: #562

## Problem

The dreaming pipeline runs LLM-based consolidation on every extraction candidate. Consolidation is the most expensive step in the pipeline (one LLM call per candidate), and many candidates do not warrant it. A candidate recalled once, by a single query, with a marginal relevance score is unlikely to produce a useful consolidated memory. Running consolidation on these wastes compute and risks promoting weak memories into the long-term store.

## Solution

Add deterministic threshold gates before the LLM consolidation step. Candidates must pass all configured thresholds to qualify for consolidation. Candidates that fail are deferred to the next dreaming cycle, not discarded. Deferred candidates accumulate evidence over subsequent search activity and will eventually pass the gates if they are genuinely useful.

The gates are deterministic (no LLM involved), so evaluation is fast and free.

## Thresholds

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `min_recall_count` | int | 3 | Minimum times the candidate appeared in search results |
| `min_unique_queries` | int | 3 | Minimum distinct queries that surfaced the candidate |
| `min_score` | float | 0.75 | Minimum relevance score from the retrieval pipeline |

All three must be met. A candidate with high recall count but low score is deferred. A candidate with a high score but only one query surfacing it is deferred.

## Data model

### `GateThresholds`

Dataclass holding the three threshold values. Constructed from pipeline configuration with the defaults above. Passed into the gate evaluator, not read from global state.

### `DreamingGate`

Stateless evaluator. Takes a `GateThresholds` and an extraction candidate's retrieval statistics, returns a `GateResult`.

### `GateResult`

| Field | Type | Description |
|-------|------|-------------|
| `passed` | bool | Whether the candidate cleared all thresholds |
| `failures` | list[str] | Which thresholds were not met (empty if passed) |
| `recall_count` | int | Observed recall count for the candidate |
| `unique_queries` | int | Observed unique query count |
| `max_score` | float | Highest relevance score observed |

The `failures` list uses threshold names directly: `"min_recall_count"`, `"min_unique_queries"`, `"min_score"`. This makes logging and debugging straightforward without inventing a separate enum.

### `TraceEventType` additions

Two new trace event types for pipeline observability:

- `GATE_PASSED`: candidate cleared all thresholds, proceeding to consolidation
- `GATE_DEFERRED`: candidate did not clear thresholds, carried to next cycle

These integrate with the existing extraction pipeline tracing so operators can see how many candidates are filtered per cycle.

## Pipeline integration

In `pipeline.py`, gate evaluation runs after candidate extraction and before the consolidation routing step:

```
extract candidates from retrieval logs
    |
    v
evaluate DreamingGate per candidate    <-- new step
    |
    +-- passed --> route to consolidation (existing)
    |
    +-- deferred --> skip, carry to next cycle
```

Deferred candidates remain in the retrieval log. They are not marked, deleted, or moved. The next dreaming cycle re-evaluates them with updated retrieval statistics. A candidate that was recalled two more times since the last cycle may now pass.

## Files touched

| File | Change |
|------|--------|
| `sdk/src/memoryhub/extraction/gates.py` | New. `GateThresholds`, `DreamingGate`, `GateResult` |
| `sdk/src/memoryhub/extraction/pipeline.py` | Gate evaluation before consolidation routing |
| `sdk/src/memoryhub/extraction/models.py` | `GateResult` model, `TraceEventType.GATE_PASSED` and `GATE_DEFERRED` |

## Design decisions

**Deterministic, not learned.** The gates are simple numeric comparisons. An ML-based gate (predicting consolidation value) would be more precise but adds model dependency, training data requirements, and opacity. The numeric thresholds are easy to reason about and tune.

**Deferred, not discarded.** Discarding below-threshold candidates loses information. A candidate that appears weak today may accumulate evidence over the next several sessions. Deferral preserves the option to promote later without re-extracting.

**Configurable defaults.** The defaults (3/3/0.75) are conservative starting points. Operators running high-volume workloads may raise them to reduce consolidation cost; low-volume deployments may lower them to avoid starving the pipeline of candidates.

**AND semantics.** All thresholds must be met. OR semantics would let a single strong signal (high score but single query) bypass the diversity check, which is the primary failure mode this design addresses.
