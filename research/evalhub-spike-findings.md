# EvalHub BYOF Adapter Spike Findings

**Date:** 2026-07-12
**Issue:** #357
**Design reference:** `planning/evalhub-integration.md`

## Recommendation: GO

The eval-hub-sdk (v0.4.2) integrates cleanly with the AMB harness. All four
verification points passed on the first attempt. The adapter is ~150 lines of
straightforward mapping code. Local mode works as documented; the SDK imposes
no constraints that conflict with our benchmark workflow.

## What worked

- **SDK installs cleanly.** `uv add eval-hub-sdk` resolved without conflicts
  against the harness's existing dependency tree (Python 3.14). Two transitive
  dependencies (`oras`, `olot`) needed explicit installation; they should be
  declared as extras or dependencies in a future SDK release (filed as a note,
  not a blocker).
- **FrameworkAdapter is minimal.** One abstract method (`run_benchmark_job`)
  with clear contract. No framework magic, no lifecycle hooks beyond
  init/run/return.
- **DefaultCallbacks works in local mode.** Status updates log locally when no
  sidecar URL is reachable. No errors, no hangs.
- **JobSpec.parameters is fully opaque.** The SDK does not validate or inspect
  the `parameters` dict. Our benchmark-specific config (mode, pipeline_sha,
  k, dataset_variant) passes through without friction.
- **EvaluationResult is flexible.** `metric_value` accepts float/int/str/bool.
  `metadata` dict allows arbitrary per-metric context. Per-question-type
  slices map naturally to separate `EvaluationResult` entries.

## What fought the SDK

Nothing significant. Minor friction points:

- **Missing transitive deps.** `oras` and `olot` are imported at module load
  by `evalhub.adapter.callbacks` but not declared in `eval-hub-sdk`'s
  dependencies. This means `pip install eval-hub-sdk` alone would fail on
  import. Workaround: `uv add oras olot`. This should be reported upstream.
- **Environment Card auto-capture.** `DefaultCallbacks.report_results()`
  auto-captures an `EnvironmentCardMetadata` if none is provided. This is
  benign (12% completeness on Mac) but logs a warning. Suppress or provide
  our own card in production.

## Verification results

### 1. Metrics flow: PASS

MCQ accuracy lands in `JobResults.overall_score` (0.55 for the 20-query
BM25 + Haiku smoke). The same value appears as an `EvaluationResult` entry
with `metric_name="mcq_accuracy"`. Five per-question-type slices were
produced as separate `EvaluationResult` entries with names like
`accuracy/Question Type:recall_user_shared_facts`.

### 2. Parameters pass-through: PASS

All five comparability-pinning parameters echo into
`JobResults.evaluation_metadata`:

| Parameter | Value |
|-----------|-------|
| mode | library |
| answer_model | claude-haiku-4-5-20251001 |
| k | None (not set for BM25) |
| dataset_variant | 32k |
| pipeline_sha | 90f6bff24d14c31dab25e41c93837d46e6978a87 |

Additional metadata preserved: `memory_provider`, `ingestion_time_ms`,
`ingested_docs`, `answer_llm`, `judge_llm`.

### 3. Model contract: PASS

`JobSpec.model.name` = `claude-haiku-4-5-20251001` (answer LLM).
`JobSpec.model.url` = `https://api.anthropic.com` (endpoint).
MemoryHub URL/API key travel in `parameters`. The SDK's `ModelConfig`
validator only checks that `url` and `name` are non-empty strings; no
endpoint reachability check or model-type validation. No fights.

### 4. Checkpoint-resume feasibility: FEASIBLE (pattern sketch)

The harness saves incremental checkpoints: every 10 queries in batch mode,
after every isolation unit in unit-sequential mode. The output file at
`outputs/<dataset>/<run_name>/<mode>/<split>.json` contains all completed
query results and is loaded on re-run to skip already-completed queries.

**EvalHub integration pattern:** An adapter job resumes by sharing the same
`output_dir` across job invocations. In Kubernetes, this means a PVC mounted
at the output path. Alternatively, the adapter could persist/restore the
checkpoint file as an OCI artifact between jobs.

**Limitation:** EvalHub jobs have a hard `timeout_seconds`. RPD-bound
leaderboard runs (589 queries, Gemini Pro, multi-day) cannot complete in a
single job. The chain-of-jobs pattern (each job resumes from the previous
checkpoint) is feasible but adds operational complexity. Recommendation:
use EvalHub for non-quota-bound workloads (Flash matrix, judge P/R, MTEB)
and keep Pro confirmation runs on the existing cron loop until checkpoint
chaining is validated.

## Effort estimates

### (a) TrustyAI operator deploy on mcp-rhoai

**Estimate: 1-2 sessions.**

- Install TrustyAI operator via OperatorHub (straightforward on RHOAI).
- Create EvalHub CR + MLflow instance (the operator manages both).
- Register the memoryhub-amb provider via ConfigMap.
- Build and push the adapter container (UBI base, pip install evalhub-sdk +
  harness dependencies). Remote build on ec2-dev-2.
- Validate with a 20-query smoke job submitted via `evalhub eval run`.
- IaC: add to `deploy-full.sh` or create `deploy-evalhub.sh`.

### (b) Migrating #355 and #351 onto EvalHub

**Estimate: 2-3 sessions (after operator deploy).**

- **#355 (ablation matrix):** 7 configs as 7 EvalHub jobs, each with
  different `parameters` flags. Kueue manages GPU quota. The premise guard
  (abort if pipeline SHA changed) falls out of job tags. Need to wire
  config-specific toggle flags into the adapter's parameter handling.
- **#351 (judge P/R eval):** Separate adapter or extend AMBAdapter with a
  `benchmark_id` switch for judge evaluation mode. MLflow tracks precision
  and recall per threshold.
- Both require: collection definition (`memoryhub_retrieval_v1`), CI
  integration (`evalhub eval run --config eval.yaml --wait`), results
  dashboard wiring.

## Open questions for human review

1. **Transitive dependency gap.** Should we report the `oras`/`olot` missing
   deps upstream, or just pin them in our `pyproject.toml`? The SDK is new
   enough that this may already be known.
2. **Checkpoint chaining vs cron loop.** For Pro leaderboard runs, is the
   operational complexity of PVC-mounted checkpoint chaining worth it, or
   should we keep those on the existing cron loop and only put Flash/judge
   workloads on EvalHub?
3. **Operator deployment timing.** Should operator deploy happen before or
   after #354 (toggle flags + smoke)? The spike code works in local mode
   regardless, but cluster deployment enables Kueue-parallelized matrix runs.
4. **MLflow experiment naming.** What naming convention for experiments?
   Suggestion: `memoryhub/<benchmark_id>/<dataset_variant>` (e.g.
   `memoryhub/personamem-mcq/32k`).
5. **Environment Card.** Should we populate a custom `EnvironmentCardMetadata`
   with MemoryHub-specific fields (server version, pipeline SHA, retrieval
   config) or rely on the auto-captured card?
