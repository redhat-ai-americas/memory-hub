# Next Session — public-benchmarks

## Next: Reproduce benchmark result and submit upstream PR

The adapter, infrastructure, and checkpoint-gated harness are all done. What remains
is operational: top up Gemini credits, run the smoke test + batched reproduction using
`gemini-3.1-pro-preview`, and submit the PR once the score is confirmed.

1. **Verify credits and run smoke test**
   Confirm Gemini prepaid credits are replenished. Run the checkpoint-gated smoke test
   to prove the pipeline end-to-end before committing to the full run.
   ```bash
   cd ~/Developer/agent-memory-benchmark
   amb run --smoke-test --dataset personamem --split 32k \
       --memory memoryhub --skip-ingestion --name memoryhub
   ```

2. **Run full reproduction in batches**
   Execute the 589-query PersonaMem 32k benchmark with checkpoint-gated batching.
   Data is already ingested (project `amb-upstream-repro`, 195 docs). Use
   `gemini-3.1-pro-preview` as the answer LLM to match our original 84.9% result.
   ```bash
   export OMB_ANSWER_LLM=gemini
   export OMB_ANSWER_MODEL=gemini-3.1-pro-preview
   export OMB_JUDGE_MODEL=gemini-3.5-flash-lite
   amb run --batch-size 5 --dataset personamem --split 32k \
       --memory memoryhub --skip-ingestion --name memoryhub
   ```
   Checkpoints every 5 queries to `outputs/.checkpoints/`. If credits run out
   or the session ends, re-run the same command to resume from the last checkpoint.

3. **Investigate the 2x context token gap**
   Our upstream run showed 53k avg context tokens vs 26k in the original. If the
   score diverges significantly from 84.9%, investigate before submitting. Possible
   causes: duplicate data from prior ingestion attempts, different chunk behavior
   post-logical_id fix, or harness-side context formatting differences.

4. **Add results and submit PR**
   Once the score is confirmed, add results to `results-manifest.json`, compress
   the output, commit to the fork, push. Then open issue + PR to
   `vectorize-io/agent-memory-benchmark` using `/issue-gate`. PR draft is already
   at `~/Developer/agent-memory-benchmark/PR_DRAFT.md`.

**Sequencing.** Steps 1-2 are gated on credits. Step 3 only if the score diverges.
Step 4 requires user approval for every external write.

**Constraints for the session:**
- Gemini prepaid credits must be replenished before starting
- The upstream repo has no CONTRIBUTING.md; PR norms were studied (PRs #9, #24, #29)
- External repo writes require `/issue-gate` + explicit user approval

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  - Gemini credits: `python3 -c "from google import genai; ..."` quick generate call
  - `oc get pods --context mcp-rhoai -n memory-hub-mcp` -- confirm MemoryHub healthy
  - Check fork is up to date: `cd ~/Developer/agent-memory-benchmark && git log --oneline -3`
  - Verify ingested data still on cluster: quick search query against `amb-upstream-repro` project
  - Check if anyone else submitted MemoryHub upstream since last session
- Rules with history:
  - Checkpointing is structural: `--smoke-test` then `--batch-size 5`. Do not run without these flags.
  - External repo writes require `/issue-gate` + explicit user approval
  - Do not push to fork without user review of the diff
  - Back up result files before any re-run that writes to the same output path
- Stop-and-ask before:
  - Opening the issue on the upstream repo
  - Submitting the PR
  - Any public-facing write on a repo not owned by rdwj
- Close ritual: session summary; update this epic file with what landed

## What landed last session (2026-08-21)

Adapter and infrastructure session. All code is done; reproduction blocked by
Gemini credit exhaustion. See `session-summaries/2026-08-21-public-benchmarks-adapter-and-checkpointing.md`.

**Shipped:**
- Clean MemoryHub adapter (130 lines) in fork, registered and discoverable
- Server-side `logical_id` NOT NULL bug fixed (`c4b3c06`), deployed as build 33
- Checkpoint-gated batch evaluation (`--smoke-test` / `--batch-size`) in fork
- 195 PersonaMem docs ingested on cluster (project: `amb-upstream-repro`)
- 3/3 smoke test correct with `gemini-3.1-pro-preview`
- Lab notes, PR draft template, run-repro script in fork
- Memories: `feedback_implement_checkpointing_not_notes`, `feedback_keep_upstream_fork_local`

**Not shipped (blocked on credits):**
- Full 589-query reproduction run
- Results manifest entry
- Upstream issue + PR submission

**Open questions:**
- Context tokens 2x higher than original (53k vs 26k). May affect score comparison.
- `gemini-2.5-flash-lite` deprecated mid-session; `gemini-3.5-flash-lite` got 75.2%
  (weaker model). Pro model matched original quality (3/3) but credits ran out.

## Prior sessions

See `session-summaries/2026-08-18-public-benchmarks-*.md` for sessions 1-2
(research/planning, then prep/clone work).

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

- **Gemini credits**: The Pro model burns credits fast with retries on 429s. The 2026-08-21 session depleted all credits after ~540 queries + 25 retries. Monitor credit balance during the run. The checkpoint-gated harness limits exposure to 5 queries per batch.
- **Gemini model deprecation**: `gemini-2.5-flash-lite` was deprecated mid-session (404). Check model availability before starting. Current working models: `gemini-3.1-pro-preview`, `gemini-3.5-flash-lite`, `gemini-3.5-flash`.
- **Context token gap**: Upstream run averaged 53k context tokens vs 26k in the original. Root cause not confirmed. Could affect score even with the same answer model. Investigate if score diverges from 84.9%.
- **Back up results before re-runs**: Three runs lost to overwriting output files. The checkpoint system prevents this going forward, but verify `outputs/.checkpoints/` is populated before re-running.
- AMB upstream repo has no CONTRIBUTING.md; submission norms studied from PRs #9, #24, #29 and issue #11.
- AML controls the answer LLM (gpt-4o-mini); our score will differ. AML submission parks until November 2026.
- The AMB PersonaMem board has three memory systems (Hindsight 86.6%, hybrid-search 84.4%, Cognee 81.8%). We'd be 4th entry, 2nd place.

## If blocked

- **Gemini credits still depleted**: Switch to `gemini-3.5-flash` (cheaper) and accept a different score. The adapter and pipeline are model-agnostic; the PR can note which model was used.
- **AMB PR stalls:** If Vectorize doesn't review within 2 weeks, ping maintainers on the issue. Consider `external_results.json` (simpler, no adapter code needed) as fallback.
- **Score regression on re-run:** If the Pro model doesn't reproduce near 84.9%, the 2x context token gap is the first place to investigate. Check whether the cluster's `amb-upstream-repro` project has stale/duplicate data from earlier failed ingestion attempts.
- **Cluster down**: MemoryHub must be running for retrieval. Check `oc get pods --context mcp-rhoai -n memory-hub-mcp`.
