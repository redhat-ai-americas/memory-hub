# Retrieval-Unit Routing

Status: skeleton
Issue: #447
Epic: #349 (dreaming benchmark)

## Problem

The 2026-07-20 source ablation benchmark showed that naive pooling of
extracted facts with full conversation transcripts produces negligible
lift (+0.1pp: 72.8% combined vs 72.7% library-only). Dreaming-only
achieves 50.9%, proving the facts contain useful information, but full
transcripts dominate the top-k retrieval window and crowd facts out.

Raw SQL confirms dreaming facts appear at cosine rank ~13-15 per persona,
behind ~12 agent memories whose embedding similarity is inflated by shared
persona-header prefixes. With k=70 and ~100 agent memories per persona,
facts rarely surface in results.

Hindsight (86.6%, #1 on PersonaMem) uses LLM fact extraction into a
semantic graph searched separately -- the architecture pattern this
design addresses.

## Approaches

### A. Retrieval-unit routing (search separately, merge)

Search facts and transcripts as independent retrieval units with separate
top-k pools, then interleave/merge results before passing to the LLM.

Pros: clean separation, tunable mix ratio, easy to A/B test.
Cons: doubles search cost (two embedding lookups + two reranker passes).

### B. Fact-aware RRF scoring

Boost `source=dreaming` memories in the RRF blend with a configurable
weight multiplier, similar to the existing domain boost.

Pros: single search path, minimal code change.
Cons: boost factor requires tuning, may over-promote low-relevance facts.

### C. Two-stage retrieve-then-enrich

Retrieve transcripts first, then for each result find related facts
(by parent thread or entity overlap) and append them to context.

Pros: facts serve as enrichment rather than competing for rank.
Cons: requires relationship traversal, adds latency.

## Decision

TBD -- benchmark each approach against the Flash Lite ablation baseline.

## Implementation plan

TBD

## Benchmark validation

Baseline: 72.7% library-only, 72.8% combined (Flash Lite).
Target: measurable lift from dreaming facts (>= +2pp on combined).
Method: same ablation protocol (combined vs library-only vs dreaming-only).
