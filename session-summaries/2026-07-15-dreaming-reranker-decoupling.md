# Session Summary -- 2026-07-15 -- Dreaming -- Reranker decoupling + retrieval signal audit

**Plan:** NEXT_SESSION-dreaming.md (harness audit + ablation matrix)
**Commits:** 7906a64..9ca9e32 (feat/reranker-decoupling-and-focus-harness)
**Deployed:** dev (MCP server, 6 deploys)   **Model:** Opus 4.6

## Plan vs. actual

Planned: harness audit, enable keyword+reranker, run 4-config ablation matrix, analyze.
Shipped: harness audit (clean), 2-config matrix (vector-only and vector+keyword both 70.8%),
discovered reranker was gated behind focus path, decoupled it, added return_chunks feature,
verified full pipeline via response metadata and server tracing.
Slipped: full 589-query runs with reranker and focus deferred -- corpus too small per persona
(4-7 parents) for signals to differentiate; chunking experiment showed promise (94% context
reduction) but needs the full run.

## Shipped

- 7906a64 chore: .gitleaksignore for 3 rotated credentials in git history
- 8b1bb8f search: decouple reranker from focus path + harness focus mode + authorized_tenants fix
- 4094e47 search: pipeline tracing (INFO logs + used_reranker/keyword_matches in MCP response)
- 4432078 search: return_chunks option to skip chunk-to-parent expansion
- aac9d71 search: filter to chunks-only when return_chunks=True (parents were competing)
- 1f93989 search: add return_chunks to compact dispatcher whitelist
- 9ca9e32 bench: raw_results=True when return_chunks active (cache ordering backfills parents)

Also: `.env` for benchmark harness (dotenv format, no secrets), `dev-users.json` + `users-configmap.yaml`
updated with `authorized_tenants` for cross-tenant benchmark access.

## Verification & confidence

- Harness audit: byte-for-byte diff against neutral AMB harness (vectorize-io/agent-memory-benchmark).
  PersonaMem dataset, RAG mode, runner wiring all identical. k=70 within benchmark norms.
- Pipeline stages verified via response metadata: `used_reranker: True`, `keyword_matches: 0-5`,
  `pivot_suggested: False`, `disabled_signals: ['domain', 'graph']`.
- Server trace logs confirm: `focused_search: reranker applied to 24 candidates`,
  `candidates=50 reranker=True keyword_hits=N focus=True`.
- Chunks experiment: 10 queries, 94% context reduction (28K to 1.6K tokens), 7/10 vs 8/10 accuracy.
- Confidence: **medium** -- all pipeline stages fire and produce correct metadata, but the
  PersonaMem 32k corpus is too small per persona to differentiate retrieval strategies.
  Full 589-query runs needed for statistical significance on chunks vs parents.

## Judgment calls & deviations

- Decoupled reranker from focus path (product fix) rather than just wiring focus into the harness.
  The harness-only fix would have been faster but the reranker-requires-focus coupling was a real
  product limitation.
- Skipped the planned 4-config matrix (vector-only / +keyword / +reranker / +both). After
  vector+keyword showed identical results (100% recall at k=70), the remaining configs would
  have been redundant. Pivoted to the more interesting question: chunk-level retrieval.
- Created `.env` file with shell command substitution that poisoned the API key via
  `load_dotenv(override=True)`. Fixed by removing shell commands and using plain dotenv format.
  Root cause was Kepner-Tregoe-diagnosed by Wes: "what changed between when it worked and when it didn't."

## Backlog delta

Filed: none.
Closed: none formally (branch not yet merged).
Deferred: full 589-query chunk-vs-parent run, chunking hyperparameter tuning, GPU machineset
scale-down (still at 3 nodes).

Lessons captured in CLAUDE.md: none yet (branch not merged). Candidates:
- When adding a parameter to `search_memory`, also add it to `_SEARCH_OPTS` in `memory.py`.
- `.env` files loaded by python-dotenv don't evaluate shell commands; use plain values only.

## Drift & forward-collisions

- Backward: #343 (chunk tuning) -- the return_chunks feature changes the evaluation surface;
  chunk size/overlap now directly affects LLM context quality, not just recall pool coverage.
- Forward: #345 (reflection), #347 (reconciliation) -- the pipeline tracing infrastructure
  (used_reranker, keyword_matches in response) will be needed for these phases to verify
  signal contributions.

## For the reviewer

- Sanity-check: the return_chunks feature filters parents post-RRF rather than excluding them
  from the recall pool. This means parents still influence chunk ranking via RRF competition.
  Is that the right design, or should chunks-only mode also exclude parents from the recall query?
- Thin verification: the 10-query chunk experiment (7/10 vs 8/10) is noise-level. The full
  589-query run is needed before drawing conclusions.
- Wants guidance: chunking strategy (size, overlap, semantic boundaries) is the next high-leverage
  area. Should this be a dedicated tuning session or part of the next dreaming session?

## Risks / watch-fors

- 6 MCP deploys in one session is fragile -- each deploy takes ~2 min and can hit timing issues
  (auth error from pod restart during benchmark). Consider batching changes.
- CI Secret Scanning still fails on main due to old credential in history. The .gitleaksignore
  fix is on this branch; will resolve when merged.
- Benchmark .env with `load_dotenv(override=True)` is a footgun -- any shell-style syntax
  in the file silently corrupts env vars. The file now has a warning comment.
- GPU machineset at 3 nodes (scaled from 2 last session). Confirm both Granite models fit on
  2 nodes before scaling back.
