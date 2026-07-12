# Planning

In-flight designs for unimplemented or partially implemented features. When a design ships, its content is absorbed into `docs/design/` and the planning doc moves to [`archive/`](archive/) as a point-in-time record. Kagenti platform integration was dropped 2026-07-08 (its planning docs deleted; kagenti-adk remains a downstream SDK consumer — see the archive and `docs/SYSTEMS.md`).

## Active

| File | Topic | Status |
|---|---|---|
| [turn-level-hooks.md](turn-level-hooks.md) | Per-turn (UserPromptSubmit/Stop) hooks for auto-rebias and extraction across agent harnesses | Draft |
| [autonomous-curation-agents.md](autonomous-curation-agents.md) | Curation agent fleet: Curator (#285) and Statistician (#289) remain; framework, Fact Checker, Dreamer shipped | In flight |
| [knowledge-layer.md](knowledge-layer.md) | content_type + graduate action; canonical disambiguation of graduate vs promote (§8.4) | Partially shipped (#237); proposal sections remain |
| [token-compression.md](token-compression.md) | Retrieval-time token reduction (#246); Phase 0 shipped, Phases 1–5 open | In flight |
| [system-benchmarks.md](system-benchmarks.md) | Infra benchmark framework (#271–#274) | In flight |
| [agent-memory-ergonomics-open-questions.md](agent-memory-ergonomics-open-questions.md) | Open-questions tracker for the ergonomics effort (Q5, Q9 still open) | Tracker |
| [observability.md](observability.md) | Prometheus metrics + Grafana dashboards | TBD |
| [operator.md](operator.md) | Kubernetes Operator + CRDs | Skeleton |
| [org-ingestion.md](org-ingestion.md) | Organizational knowledge ingestion pipeline | TBD |
| [llamastack-integration/](llamastack-integration/) | LlamaStack integration (MCP tool group, Vector IO provider) | Design |

## Archive

Shipped designs and point-in-time records: campaign-domain-framework (#154), session-persistence (#168), scope-isolation-project-role (#64), mcp-single-tool-schema (#201/#202), sdk-compacted-tool-rework, hooks-memory-injection (Phases 1–4), scope-expansion-overview (roadmap snapshot), tool-error-standardization, backlog-refinement-2026-06, and the kagenti-adk consumer records (e2e-cluster-url-stability #209, ci-test-data-cleanup #207, sdk-kagenti-contract-test, kagenti-poc-findings).
