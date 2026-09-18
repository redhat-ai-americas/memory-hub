# Open Issue Audit — 2026-08-18

55 issues reviewed against the codebase. "Open" = not closed, not assigned, and not linked to a PR.

## Can Be Closed (5 issues — work is done in code)

| # | Title | Evidence |
|---|-------|----------|
| **#395** | MinIO content does not survive uninstall-full.sh --skip-db | Closed 2026-08-14. MinIO PVC preservation implemented. |
| **#453** | retrieval: Reimplement disabled_signals for RRF signal toggling | `disabled_signals` wired into `search_memory.py`, tests pass. Still open on GitHub. |
| **#454** | retrieval: Reimplement entity-aware search and entity service | Entity extraction, `MENTIONS` relationship, `entity_names` filter all implemented. Still open on GitHub. |
| **#458** | CLI: create-agent table output omits api_key | Closed 2026-08-14. |
| **#518** | UI deploy script hard-fails without RHOAI installed | Closed 2026-08-14. |

## Already Closed Since Last Audit (3)

#395, #458, #518 — closed between 2026-08-14 and 2026-08-18.

## Assigned or Has Linked PR (18 issues — in progress, excluded from open list)

| # | Title | Status |
|---|-------|--------|
| **#272** | benchmarking: Entity extraction throughput/accuracy | Assigned: rdwj |
| **#273** | benchmarking: Graph-traversal vs flat vector comparison | Assigned: rdwj |
| **#306** | Time-decay recency bias in search | Assigned: khaledsulayman, rdwj |
| **#312** | Multi-harness support (tracking) | Assigned: srampal |
| **#337** | Platform memory management benchmark design | Assigned: rdwj |
| **#375** | Full local test suite hangs indefinitely | Assigned: valeriiashapoval |
| **#404** | Effective-k observability | Assigned: KatyaRomashko, has PR #530 |
| **#459** | CLI: rotate-api-key subcommand | Assigned: KatyaRomashko, has PR #529 |
| **#489** | integrations: openclaw | Assigned: srampal |
| **#492** | CLI: per-project identity selection | Assigned: srampal |
| **#493** | CLI: delete-agent command | Assigned: srampal |
| **#494** | OpenClaw: scope/project_id nested wrong | Assigned: srampal |
| **#495** | OpenClaw: connection leak in resetSession | Assigned: srampal |
| **#496** | OpenClaw: as-never casts cleanup | Assigned: srampal |
| **#497** | Surface last_updated_by in API responses | Assigned: srampal |
| **#507** | Demo: quantitative memory sharing benefits | Assigned: srampal |
| **#512** | Chunk/fact logical_id NOT NULL violation | Assigned: Hazey000 |
| **#514** | authz: project membership bypass in list/search | Assigned: Hazey000 |
| **#526** | uninstall confirm lists RHOAI on non-RHOAI | Assigned: raycarroll, has PR #528 |
| **#527** | deploy print_summary RHOAI route noise | Assigned: raycarroll, has PR #528 |

---

## Truly Open Issues — Prioritized by Core Stability Impact

**Effort key:** XS (<1h) | S (1-4h) | M (1-2d) | L (3-5d) | XL (1-2wk)

Issues below are unassigned, have no linked PR, and are not closed.

---

### Tier 1: CRITICAL — Production reliability, core operations

| # | Title | Type | Effort | Why critical |
|---|-------|------|--------|-------------|
| **#523** | Embedding /info lazy fetch race at startup | Bug | S | `create_memory()` calls `max_tokens` (sync) before the first async `embed()` triggers /info fetch. First-call truncation uses wrong default. |
| **#104** | Session state lost on pod restart | Design | L | Auth state is in-process memory. Pod restart = all connected agents get `Session not found`. Valkey covers focus/registration but not auth. |

---

### Tier 2: HIGH — Governance, operational quality

| # | Title | Type | Effort | Impact |
|---|-------|------|--------|--------|
| **#70** | Audit log is still a stub | Feature | M | `audit.py` is explicitly a fire-and-forget logger stub. No durable persistence. Governance gap for production. |
| **#524** | Cache embedding fallback max_tokens in __init__ | Feature | XS | Env var read on every call instead of once at init. Minor perf, easy fix. |

---

### Tier 3: MEDIUM — Core feature gaps affecting product value

| # | Title | Type | Effort | Impact |
|---|-------|------|--------|--------|
| **#389** | S3 hydration: rank on prefix, hydrate top-k | Feature | M | Search hydrates ALL results from S3, not just final top-k. Wastes I/O on discarded results. Partial impl exists. |
| **#397** | Hard-stop mode for token-limited results | Feature | M | Small-context models get stubs instead of truncated full results. No hard-stop alternative. |
| **#431** | Session-close memory capture (SessionEnd hook) | Feature | M | Benchmark hook shipped, product feature (consent, gitleaks gate, drain) is not built. |
| **#491** | Memory rewind/rollback for wedged agents | Feature | L | Versions exist but no external lever to restore a known-good state. Needs design. |
| **#310** | Framework-agnostic onboarding | Feature | M | `InstructionFormat` enum added (partial), but `config init` still defaults to Claude Code artifacts. |
| **#350** | Curator agent scaffold | Feature | M | Framework exists (leader election, config, lifecycle) but no actual Curator plugin. Partial. |
| **#313** | Turn-level hooks (rebias + extraction) | Design | L | Planning doc exists, no implementation. Needed for non-Claude-Code harnesses. |

---

### Tier 4: FUTURE — Research, benchmarks, advanced features, integrations

| # | Title | Type | Effort | Notes |
|---|-------|------|--------|-------|
| **#345** | Provenance-driven reflection (Layer 3) | Feature | L | Churn detection + insight memories. No implementation. |
| **#82** | LibreChat integration | Feature | M | Auth fixtures and docs exist (PARTIAL), no end-to-end deployment. |
| **#87** | SDK full-content push notifications | Feature | M | Server-side done, SDK consumption not implemented. |
| **#353** | Curator: staleness sweep + conflict detection | Feature | L | No implementation. |
| **#352** | Curator: deep-dedup with judge | Feature | L | No implementation. |
| **#351** | Curator: labeled dedup pair set | Feature | M | No implementation. |
| **#346** | Curator: domain ontology refinement | Feature | L | No implementation. |
| **#289** | Statistician Agent | Feature | XL | No implementation. |
| **#290** | Curator + five-stage promotion pipeline | Feature | XL | No implementation. |
| **#517** | GAL-aligned trust lifecycle | Feature | L | No implementation. Compliance/governance. |
| **#516** | PTC-aligned provenance/taint metadata | Feature | L | No implementation. Compliance/governance. |
| **#71** | Intersection authorization (actor+driver) | Feature | L | OBO captures both IDs, but authz uses actor only. |
| **#72** | driver_id redaction on read | Feature | M | No redaction logic. Privacy feature. |
| **#68** | HIPAA/PHI detection patterns | Feature | M | No healthcare-specific PII detection. |
| **#40** | Curation rule versioning + UI editing | Feature | M | No version history on rules. |
| **#270** | Semantic search over conversation messages | Design | M | Thread tool has metadata filtering only, no content search. |
| **#241** | Pluggable storage backend adapter | Design | XL | No abstraction layer. Direct Postgres. |
| **#239** | Convergent learning for cross-user dedup | Feature | XL | No implementation. |
| **#330** | LongMemEval_S full-haystack variant | Benchmark | M | Only oracle variant run. |
| **#331** | LongMemEval answer-quality with LLM judge | Benchmark | M | RESULTS.md explicitly flags as a gap. |
| **#334** | Adversarial write / poisoning resistance | Benchmark | L | No implementation. |
| **#370** | Ablation Matrix B (post-dreaming) | Benchmark | M | Only Matrix A exists. |
| **#400** | Evaluate AutoRAG | Investigation | M | No findings anywhere. |
| **#383** | Capability-claim sweep of docs | Design | M | Not done. "Verify Before Propagating" rule added but no sweep. |
| **#426** | EvalHub sidecar result-drain retry | Feature | S | No retry logic in adapter. |
| **#508** | Design document (agent memory case) | Design | M | Vague scope ("tbd"). Guides exist but not a positioned argument doc. |
| **#509** | OpenCode integration | Feature | L | No implementation. |
| **#505** | Test deployment of Hindsight | Ops | M | No scripts/configs. |
| **#506** | Test deployment of GBrain | Ops | M | No scripts/configs. |

---

## Summary

| Category | Count |
|----------|-------|
| **Can be closed** | 5 (2 still open on GitHub: #453, #454) |
| **Assigned / has PR** | 18 |
| **Tier 1 — Critical** | 2 |
| **Tier 2 — High** | 2 |
| **Tier 3 — Medium** | 7 |
| **Tier 4 — Future** | 29 |
| **Truly open total** | 40 |
