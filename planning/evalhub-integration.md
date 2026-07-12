# EvalHub Integration for Benchmark and Tuning Infrastructure

**Status:** Spike complete — GO (see `research/evalhub-spike-findings.md`, #357)
**Date:** 2026-07-13 (spike reviewed 2026-07-13)
**Decisions from review:** pin oras/olot AND report upstream; Pro leaderboard
runs stay on cron loop (no checkpoint chaining for now); operator deploy
after #354, before #355, own namespace, IaC via deploy-evalhub.sh; MLflow
experiments `memoryhub/<benchmark_id>/<dataset_variant>` with volatile
dimensions (mode, answer model, SHA, toggles) as tags; custom
EnvironmentCardMetadata populated in the adapter (server version, pipeline
SHA, retrieval config, harness commit).
**Author:** @rdwj (researched with Claude in Cowork)

## What EvalHub is

Open-source (Apache 2.0) evaluation orchestration platform, upstream of the
"evaluation hub" in Red Hat AI 3.4, deployed via the TrustyAI operator — on
RHOAI clusters it is part of the TrustyAI stack, no additional infrastructure
product. Framework-agnostic control plane:

- **Providers:** lm-evaluation-harness, Ragas, Garak, GuideLLM, LightEval,
  MTEB built in; bring-your-own-framework (BYOF) via a `FrameworkAdapter`
  subclass with one method (`run_benchmark_job`), packaged as a UBI container,
  registered via ConfigMap.
- **Per-run record:** MLflow experiment tracking (config, tags, model,
  metrics) + immutable OCI artifacts with SHA-derived tags.
- **Collections:** versioned, weighted benchmark sets with per-benchmark
  thresholds and a single `pass_criteria` gate; CI-friendly
  (`evalhub eval run --config eval.yaml --wait`, non-zero exit on failure).
- **Execution:** Kubernetes Jobs (adapter + sidecar pod), Kueue-managed
  quotas; `EVALHUB_MODE=local` runs the same adapter code on a laptop with
  logged callbacks and no cluster.

References: eval-hub.github.io, github.com/eval-hub/eval-hub-sdk,
github.com/eval-hub/eval-hub-contrib, Red Hat Developer EvalHub series
(May-June 2026).

## Why it fits MemoryHub's tuning phase

1. **Automates comparability pinning.** The "Benchmark harness requirements"
   in `memory-extraction-pipeline.md` (record answer model, harness mode, k,
   dataset variant, commit SHA per run) is exactly what MLflow tracking + OCI
   artifacts give for free once the AMB harness is wrapped in a BYOF adapter.
2. **The ablation matrix (#355) is its natural workload.** 7 configs = 7
   parallel jobs under Kueue, each tagged with config + SHA; the premise
   guard (abort if pipeline code changed mid-matrix) falls out of the tags.
3. **Tuning gates become versioned artifacts.** #351's auto-merge gate
   (judge precision >= 0.95 else flag-only) maps to a collection
   `pass_criteria.threshold`. Reconciliation threshold sweeps (#347 decision
   log) and chunker tuning (#343) are MLflow experiment series. GuideLLM may
   cover #342's p99-under-load measurement (verify TEI endpoint
   compatibility).
4. **Strategic:** packaging the platform benchmark (#337) as an EvalHub
   provider is the AMB playbook — publish methodology as runnable
   infrastructure — inside the product MemoryHub customers already run.

## Known mismatches

1. **Job deadline vs RPD-bound runs.** EvalHub jobs have a hard
   `timeout_seconds`; leaderboard-comparable PersonaMem runs (589 queries,
   Gemini Pro, 250 RPD rolling) are multi-day checkpoint-resume loops.
   Mitigation: checkpoint-aware adapter (each job resumes from OCI-persisted
   checkpoint; a "run" is a chain of jobs), or restrict EvalHub to
   non-quota-bound workloads (Flash matrix, judge P/R, MTEB, GuideLLM) and
   keep Pro confirmation runs on the existing cron loop.
2. **Model-centric contract.** `JobSpec.model` assumes the system under test
   is a model endpoint; ours is MemoryHub + answer LLM. Convention: `model` =
   answer LLM endpoint; MemoryHub URL/config travel in the opaque
   `parameters` dict.
3. **Maturity.** Platform is new (mid-2026); the MCP module is developer
   preview. Spike before committing.

## Adoption plan

- **Spike (1 session, local-only, executed by the coding agent):** wrap the
  vendored AMB harness in a `FrameworkAdapter`; run a 20-query PersonaMem
  smoke in `EVALHUB_MODE=local`; verify metrics, parameters pass-through
  (mode/answer-model/k/SHA), and checkpoint-resume feasibility. The spike's
  deliverable is a findings document at
  `research/evalhub-spike-findings.md` — a go/no-go summary for human review
  before any cluster deployment or migration decision. The adoption decision
  is made in review, not by the spike session.
- **If go:** deploy EvalHub via TrustyAI operator on mcp-rhoai (IaC per
  deploy-reproducibility rules); migrate #355 (Flash matrix) and #351 (judge
  P/R eval) onto it; define a `memoryhub_retrieval_v1` collection.
- **Later:** platform benchmark (#337 follow-on) ships as an EvalHub
  provider.
