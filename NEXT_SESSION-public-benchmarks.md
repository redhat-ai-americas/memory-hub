# Next Session — public-benchmarks

## Next: AMB upstream provider adapter + submission

Fork `vectorize-io/agent-memory-benchmark`, contribute a clean MemoryHub provider
adapter, reproduce our 84.9% result through the upstream harness, and submit the PR.
This is Phases 1+2 combined — the adapter and submission are tightly coupled and
small enough to land in one session.

1. **Fork and adapter cleanup**
   Fork the upstream repo. Derive a clean `memoryhub.py` from our existing 503-line
   adapter at `benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py`. Strip
   ablation-specific env vars (routing mode, chunk sweep params, extraction model
   config) down to the three essentials: `MEMORYHUB_URL`, `MEMORYHUB_API_KEY`,
   `MEMORYHUB_PROJECT_ID`. Keep `kind: "cloud"` since MemoryHub is a hosted service.
   Check upstream providers (Hindsight, Cognee, mem0_cloud) for conventions on
   class attributes, docstrings, and import style — match their patterns.

2. **Verify reproduction**
   Run `uv run amb run --dataset personamem --domain 32k --memory memoryhub` from
   the fork against our cluster. Confirm the result is within 1% of 84.9% (500/589).
   If it diverges, investigate before proceeding — don't submit a result we can't
   reproduce through the upstream harness.

3. **Submit to upstream**
   Open an issue on `vectorize-io/agent-memory-benchmark` introducing MemoryHub
   (follow the pattern from their issue #11). Then submit PR with: adapter code,
   results JSON, manifest entry. Use `/issue-gate` since this is a write to an
   external repo.

**Sequencing.** Fork and adapter first (step 1), then reproduce (step 2), then submit
(step 3). Steps 1-2 are the bulk of the work; step 3 is mostly process.

**Constraints for the session:**
- The upstream repo has no CONTRIBUTING.md — review existing PRs and issues for norms before submitting
- Our cluster must be accessible during reproduction (verify MemoryHub is healthy before starting)
- External repo write requires `/issue-gate` and explicit user approval per CLAUDE.md rules

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  - `oc get pods --context mcp-rhoai -n memory-hub-mcp` — confirm MemoryHub is running and healthy
  - `gh repo view vectorize-io/agent-memory-benchmark` — confirm upstream repo still exists and is active
  - Check if anyone else has submitted a MemoryHub provider since planning (search upstream issues/PRs)
  - Verify our 84.9% result file exists: `ls benchmarks/amb-harness/outputs/personamem/granite-pro/rag/32k.json.gz`
- Rules with history:
  - External repo writes require `/issue-gate` + explicit user approval (CLAUDE.md: "External Repository Gate")
  - Do not push to the fork without user review of the diff — this will be publicly visible
- Stop-and-ask before:
  - Opening the issue on the upstream repo
  - Submitting the PR
  - Any public-facing write on a repo not owned by rdwj
- Close ritual: session summary; update this epic file with what landed

## What landed last session (2026-08-18, session 2)

Prep session on slow connection. Completed premise checks and upstream repo analysis,
but lost the working window to clone timeouts (738 MB repo).

**Completed:**
- Fork created at `rdwj/agent-memory-benchmark`
- Filtered clone landed at `~/Developer/agent-memory-benchmark/` (needs `git checkout` to populate working tree)
- Studied all upstream provider conventions: base class, __init__.py registry, catalog.json format, results-manifest.json format
- Read 4 reference adapters (Hindsight, Cognee, mem0_cloud, Ogham) and extracted the pattern
- Verified our result file exists (500/589 = 84.89%, ingestion 99.6s, avg retrieve 2491ms, avg context 26695 tokens)
- Confirmed no prior MemoryHub submissions exist upstream (no issues or PRs)
- Reviewed PRs #9 (Ogham, merged), #24 (AutoMem), #29 (Letta) and issue #11 (Audrey) for submission norms
- Confirmed MemoryHub cluster is healthy (pod running 5d)

**Not started:**
- Writing the clean adapter (ready to start: all conventions documented, our 503-line source adapter read)
- Reproduction run
- PR submission

**Prerequisite for next session:**
- Fast network connection (clone checkout needs blob downloads)
- Run `cd ~/Developer/agent-memory-benchmark && git checkout main` to populate working tree

**Artifacts created:**
- Memory: `feedback_keep_upstream_fork_local.md` (clone upstream repos on fast connections before working sessions)

## What landed session 1 (2026-08-18)

Research and planning session. Mapped both submission venues (AMB and AML), audited
existing benchmark data, wrote the epic arc.

**Key findings:**
- AMB (Vectorize): PR-based, open timeline, three memory systems already on PersonaMem board (Hindsight 86.6%, hybrid-search 84.4%, Cognee 81.8%). MemoryHub would be 2nd.
- AML (agentmemories.ai): Managed platform, Aug 7 deadline passed, next window ~November 2026.
- PersonaMem (original): Dataset only, no submission process.

**Artifacts created:**
- `NEXT_SESSION-public-benchmarks.md` (this file)

## Remaining epic phases

Get MemoryHub onto both public agent-memory benchmark leaderboards (AMB and AML) with verified, reproducible results. Marketing-driven: ship at a decent level now, resubmit as scores improve. We already have 84.9% on PersonaMem 32k (2nd behind Hindsight at 86.6%) — the work is packaging and submitting, not running new benchmarks.

### Phase 1: AMB Upstream Provider Adapter

Port our 503-line `memoryhub.py` adapter from `benchmarks/amb-harness/` into a fork of `vectorize-io/agent-memory-benchmark`. Clean it up for upstream consumption: a third party pointing at any MemoryHub instance should be able to run `uv run amb run --dataset personamem --domain 32k --memory memoryhub` and get results. Strip our env-var-heavy ablation config down to the essentials (URL, API key, project ID).

**Work:**
1. Fork `vectorize-io/agent-memory-benchmark`
2. Write a clean `memoryhub.py` adapter for upstream (derive from our existing one, trim to essentials)
3. Verify `uv run amb providers` discovers it
4. Run `uv run amb run --dataset personamem --domain 32k --memory memoryhub` against our cluster and confirm result within 1% of 84.9%
5. Generate results JSON in their manifest format

**Definition of done:** Adapter in fork passes provider discovery and reproduces our 84.9% result (within 1%) when pointed at our cluster. Results JSON committed in their manifest format.

**Dependencies:** None — can start immediately

**Parallel-ok:** Yes, independent of Phases 3-5

### Phase 2: AMB Leaderboard PR

Submit MemoryHub to the AMB leaderboard via PR to `vectorize-io/agent-memory-benchmark`. Open an issue first (their apparent convention from issue #11), then submit the PR with adapter + results.

**Work:**
1. Open issue on upstream repo introducing MemoryHub as a provider
2. Submit PR with adapter code + results JSON + manifest entry
3. Iterate on maintainer feedback
4. Verify MemoryHub appears on [agentmemorybenchmark.ai](https://agentmemorybenchmark.ai) after merge

**Definition of done:** PR merged (or accepted) on upstream repo. MemoryHub visible on the AMB leaderboard website, placing 2nd on PersonaMem (behind Hindsight at 86.6%, ahead of hybrid-search at 84.4% and Cognee at 81.8%).

**Dependencies:** Gated on Phase 1 (adapter must be ready)

**External wait:** Vectorize PR review — no SLA, could be days or weeks

**Parallel-ok:** No (sequential after Phase 1), but Phases 3/5 can run during the PR wait

### Phase 3: AML HTTP Adapter

Build a thin FastAPI app that exposes MemoryHub through AML's required API contract: `POST /add` (ingest messages), `POST /search` (return ranked memories), `GET /health`. Translates their request format into MemoryHub SDK calls. Deploy on our cluster with a public OpenShift route.

AML uses gpt-4o-mini as the answer model (platform-controlled), so our score will differ from the 84.9% we got with Gemini Pro — but the retrieval quality is what we're showcasing.

**Work:**
1. Read [AML API guide](https://agentmemories.ai/api-guide) and document the exact request/response schemas
2. Build FastAPI adapter (~200 lines): Add endpoint writes memories via SDK, Search endpoint queries via SDK
3. Handle auth (Bearer token or X-Api-Key)
4. Write integration tests simulating AML request format
5. Deploy to OpenShift with public route, verify health endpoint accessible
6. Ensure deployment can stay up 30+ days (AML stability requirement)

**Definition of done:** FastAPI app deployed on `mcp-rhoai` cluster with public route. Passes a local integration test simulating AML's smoke test (Add messages, Search returns ranked results, Health returns 2xx).

**Dependencies:** None — can start in parallel with Phase 1

**Parallel-ok:** Yes, independent of Phases 1-2

### Phase 4: AML Submission

Submit to AML when the next evaluation window opens (~November 2026). Mostly process, not code.

**Work:**
1. Apply for AML Eval Key at [agentmemories.ai/evaluation](https://agentmemories.ai/evaluation)
2. Pass smoke test (1 attempt per hour, compatibility check)
3. Run formal evaluation (1 attempt per 3 months)
4. Request publication to leaderboard
5. Decide category: Academic (must be open-source) vs Commercial

**Definition of done:** MemoryHub appears on the AML leaderboard at [agentmemories.ai](https://agentmemories.ai) with a published score.

**Dependencies:** Gated on Phase 3 (adapter deployed and stable). Gated on AML submission window (~November 2026).

**External wait:** AML submission window opening, eval key issuance, formal evaluation run

**Parallel-ok:** No (sequential after Phase 3 + calendar gate)

**Reminder:** Revisit this phase in late October 2026 to confirm AML window timing and prepare submission.

### Phase 5 (optional): Score Improvement Sprint

Cherry-pick the highest-ROI retrieval improvements to close the 1.7-point gap to Hindsight (86.6%). Resubmit to whichever leaderboard(s) are live.

Candidates from open issues:
- #370 Ablation Matrix B — focus, domain, and graph signals not yet tested; could reveal untapped retrieval signals
- #389 S3 hydration for large-content tail — rank on prefix, hydrate top-k; could improve context quality
- #453 disabled_signals reimplementation — needed to properly A/B test individual signals

**Work:**
1. Triage candidates by expected accuracy lift vs effort
2. Implement highest-ROI improvement
3. Re-run full 589-query PersonaMem 32k benchmark
4. If score improves, resubmit to AMB and/or AML

**Definition of done:** At least one retrieval improvement measurably increases PersonaMem 32k accuracy above 84.9%, verified by full 589-query re-run. Updated result submitted to live leaderboard(s).

**Dependencies:** None for improvement work. Resubmission depends on Phase 2 or 4 being complete.

**Parallel-ok:** Yes — can run concurrently with any phase

---

## Execution order

```
Phase 1 (AMB Adapter)  ──→  Phase 2 (AMB PR)  ──→  [wait for PR review]
        ↕ parallel                                          ↕ parallel
Phase 3 (AML Adapter)  ──→  ··· park until Nov ···  ──→  Phase 4 (AML Submit)
        ↕ parallel
Phase 5 (Score Sprint)  ── optional, any time ──→  resubmit to whichever board is live
```

AMB first (no deadline, first memory system on board, high marketing value). AML adapter built early but submission parks until November. Score improvements float into any gap.

## What this covers (and what it doesn't)

**In scope:**
- AMB leaderboard submission with MemoryHub provider adapter (upstream PR)
- AML leaderboard submission with HTTP adapter (November 2026 window)
- Score improvements that directly increase leaderboard position
- Issues #370, #389, #453 if they yield measurable accuracy gains

**Out of scope (other epics or backlog own):**
- Internal benchmark infrastructure (EvalHub, KubeFlow jobs) — existing tooling
- Science-project benchmarks (adversarial resistance #334, entity extraction throughput #272) — backlog
- LongMemEval full-haystack #330, LongMemEval LLM judge #331 — relevant to AML (which includes LongMemEval) but secondary to PersonaMem submission
- Graph-traversal vs flat vector comparison #273 — research, not leaderboard-facing
- arXiv survey paper — separate effort, see `project_arxiv_survey_paper` memory

## What landed already

- PersonaMem 32k benchmark: 84.9% (500/589) with Granite embeddings + reranker, Gemini 3.1 Pro Preview (2026-07-16)
- LongMemEval oracle: R@5=0.999, R@10=1.000, MRR=1.000 (2026-07-10)
- Full ablation data: 15+ chunk configs, source ablation, signal ablation, routing experiments
- Competitive landscape cataloged in `benchmarks/amb-harness/external_results.json` (~40 systems)
- Provider adapter exists in `benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py` (503 lines)
- Results documented in `benchmarks/RESULTS.md` and cited in project README

## Watch out for

- AMB upstream repo has no CONTRIBUTING.md — submission norms are informal. Open an issue first.
- Our adapter has heavy env-var config for ablation experiments — upstream version needs to be much simpler.
- AML controls the answer LLM (gpt-4o-mini) — our score will differ from the 84.9% we got with Gemini Pro.
- AML requires 30+ days API stability post-submission — cluster must stay up through eval period.
- The AMB PersonaMem board has three memory systems (Hindsight 86.6%, hybrid-search 84.4%, Cognee 81.8%). We'd be 4th entry, 2nd place. The long-context LLM baselines (49-52%) are in `external_results.json`, not the main manifest.

## If blocked

- **AMB PR stalls:** If Vectorize doesn't review within 2 weeks, ping maintainers on the issue. Consider whether `external_results.json` (simpler, no adapter code needed) is an acceptable fallback.
- **AML window unclear:** Email contact@agentmemories.ai or check Twitter @AgentMemoryL for next cycle dates. Current intel says ~November 2026 but this isn't confirmed.
- **Score regression on re-run:** If reproducing our 84.9% against the upstream harness yields a lower number, investigate before submitting. Don't submit a result we can't explain.
- **Cluster instability during AML eval:** Have a backup plan for the 30-day stability window — monitor the route, set up a health check alert.
