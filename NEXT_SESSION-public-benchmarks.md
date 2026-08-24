# Next Session — public-benchmarks

## Next: Handle AMB PR feedback, then build AML adapter

Wait at least one week from PR submission (2026-08-21) for Vectorize review
feedback on PR #34. If there's feedback, address it first. Then start Phase 3:
build and deploy the AML HTTP adapter so we're ready for the November submission
window.

1. **Check AMB PR status and handle feedback**
   Check vectorize-io/agent-memory-benchmark#34 for review comments. If there's
   feedback, address it on the `memoryhub-provider` branch in the fork at
   `~/Developer/agent-memory-benchmark`. If merged, verify MemoryHub appears on
   agentmemorybenchmark.ai. If no review yet and it's been <2 weeks, move on to
   the AML work.

2. **Read AML API guide and document schemas**
   Read https://agentmemories.ai/api-guide to understand the exact contract:
   `POST /add`, `POST /search`, `GET /health`. Document the request/response
   schemas before writing code. Pay attention to auth requirements (Bearer token
   or X-Api-Key) and any field-level constraints.

3. **Build FastAPI AML adapter**
   Thin FastAPI app (~200 lines) translating AML's API contract into MemoryHub
   SDK calls. Add endpoint writes memories, Search endpoint queries memories,
   Health returns 2xx. Write integration tests simulating AML's smoke test
   format. This lives in the memory-hub repo (not the AMB fork).

4. **Deploy to OpenShift with public route**
   Deploy the adapter to `mcp-rhoai` cluster with a public route. The adapter
   needs to stay up 30+ days (AML stability requirement). Use the standard
   deploy pattern (BuildConfig + Deployment, not local build).

5. **If AML submission window is open, begin submission process**
   Apply for eval key at agentmemories.ai/evaluation. If the window isn't open
   yet (~November 2026), park the issue and note the date to revisit. If it is
   open, run the smoke test (1 attempt per hour).

**Sequencing.** Step 1 first (quick check). Steps 2-4 are the core work and
should flow in order within a single session. Step 5 depends on AML's calendar.

**Constraints for the session:**
- Do not start this session before 2026-08-28 (one week from PR submission)
- AML controls the answer LLM (gpt-4o-mini); our score will differ from the AMB result
- The adapter needs its own OpenShift namespace and BuildConfig
- Decide category before submission: Academic (must be open-source) vs Commercial

**Session start protocol:**
- Premise checks (~5 min, report before acting):
  - AMB PR status: `gh pr view 34 -R vectorize-io/agent-memory-benchmark --json state,reviews,comments`
  - If >2 weeks since submission with no review, ping maintainers on issue #33
  - MemoryHub cluster health: `oc get pods --context mcp-rhoai -n memory-hub-mcp`
  - Check AML site is accessible: `curl -s https://agentmemories.ai/api-guide | head -20`
  - Check if anyone else submitted a MemoryHub entry to AML since last session
- Rules with history:
  - External repo writes require `/issue-gate` + explicit user approval (PR feedback iterations on the existing PR #34 are fine without re-gating)
  - Use GEMINI_API_KEY exclusively, never GOOGLE_API_KEY (see CLAUDE.md)
  - Deploy scripts run in main context, not delegated to sub-agents
- Stop-and-ask before:
  - Creating a new OpenShift namespace for the AML adapter
  - Applying for an AML eval key (irreversible registration)
  - Any public-facing write on a repo not owned by rdwj
- Close ritual: session summary; update this epic file with what landed

## What landed last session (2026-08-21)

Reproduction run and upstream PR submission. Full pipeline completed in one session.

- Full PersonaMem 32k reproduction: 83.7% (493/589) with gemini-3.1-pro-preview
- Upstream issue vectorize-io/agent-memory-benchmark#33
- Upstream PR vectorize-io/agent-memory-benchmark#34 (adapter + results + manifest)
- GOOGLE_API_KEY cleanup in fork, CLAUDE.md updated
- Memory: `feedback_publish_what_we_get`

See `session-summaries/2026-08-21-public-benchmarks-reproduction-and-pr.md`.

**Prior sessions:**
- 2026-08-21 (earlier): Adapter, checkpointing, and infrastructure. See `session-summaries/2026-08-21-public-benchmarks-adapter-and-checkpointing.md`.
- 2026-08-18: Research/planning and prep/clone. See `session-summaries/2026-08-18-public-benchmarks-*.md`.

## Remaining epic phases

Get MemoryHub onto both public agent-memory benchmark leaderboards (AMB and AML) with verified, reproducible results. Marketing-driven: ship at a decent level now, resubmit as scores improve. We already have 84.9% on PersonaMem 32k (2nd behind Hindsight at 86.6%) — the work is packaging and submitting, not running new benchmarks.

### Phase 1: AMB Upstream Provider Adapter — COMPLETE

Adapter shipped. 83.7% (493/589) on PersonaMem 32k with Gemini 3.1 Pro Preview. PR #34 submitted to vectorize-io/agent-memory-benchmark.

### Phase 2: AMB Leaderboard PR — SUBMITTED, AWAITING REVIEW

PR #34 open. Issue #33 filed. Waiting on Vectorize maintainer review.

**External wait:** Vectorize PR review — no SLA, could be days or weeks. Ping after 2 weeks if no response.

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

**Dependencies:** None — can start immediately

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

**Reminder:** Revisit this phase in late October 2026 to confirm AML window timing and prepare submission.

### Phase 5 (optional): Score Improvement Sprint

Cherry-pick the highest-ROI retrieval improvements to close the gap to Hindsight (86.6%). Resubmit to whichever leaderboard(s) are live.

Candidates from open issues:
- #370 Ablation Matrix B — focus, domain, and graph signals not yet tested; could reveal untapped retrieval signals
- #389 S3 hydration for large-content tail — rank on prefix, hydrate top-k; could improve context quality
- #453 disabled_signals reimplementation — needed to properly A/B test individual signals

**Definition of done:** At least one retrieval improvement measurably increases PersonaMem 32k accuracy above 83.7%, verified by full 589-query re-run. Updated result submitted to live leaderboard(s).

**Dependencies:** None for improvement work. Resubmission depends on Phase 2 or 4 being complete.

---

## Execution order (updated)

```
Phase 1 (AMB Adapter)  ── COMPLETE
Phase 2 (AMB PR)       ── SUBMITTED, awaiting review
                                ↓ parallel
Phase 3 (AML Adapter)  ── NEXT SESSION ──→  Phase 4 (AML Submit, ~Nov 2026)
                                ↓ parallel
Phase 5 (Score Sprint)  ── optional, any time ──→  resubmit to whichever board is live
```

## What this covers (and what it doesn't)

**In scope:**
- AMB leaderboard submission with MemoryHub provider adapter (upstream PR) — DONE
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

- PersonaMem 32k benchmark: 84.9% (500/589) with Granite embeddings + reranker, Gemini 3.1 Pro Preview (2026-07-16, internal run)
- PersonaMem 32k reproduction: 83.7% (493/589) with same model, upstream adapter (2026-08-21, submitted as PR #34)
- LongMemEval oracle: R@5=0.999, R@10=1.000, MRR=1.000 (2026-07-10)
- Full ablation data: 15+ chunk configs, source ablation, signal ablation, routing experiments
- Competitive landscape cataloged in `benchmarks/amb-harness/external_results.json` (~40 systems)
- Provider adapter in upstream fork: `~/Developer/agent-memory-benchmark/src/memory_bench/memory/memoryhub.py` (~130 lines)
- Internal adapter: `benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py` (503 lines)
- Results documented in `benchmarks/RESULTS.md` and cited in project README

## Watch out for

- **AMB PR review**: No SLA. If no review by 2026-09-04 (2 weeks), ping maintainers on issue #33. Other PRs (#24, #25, #29) have been waiting weeks to months.
- **AML controls the answer LLM**: gpt-4o-mini. Our score will differ from the 83.7% AMB result. The retrieval quality is what we're showcasing, not the final accuracy number.
- **AML stability requirement**: The adapter needs 30+ days uptime. Use a proper Deployment with health checks, not a one-off pod.
- **Context token gap**: Upstream run averaged 160k context tokens vs 26k in the original. Root cause: K=70 retrieval depth with large verbatim memories. Not a bug, but may draw reviewer questions on the AMB PR.
- **Use GEMINI_API_KEY exclusively** for all Gemini calls. GOOGLE_API_KEY is a different account without credit visibility.

## If blocked

- **AMB PR stalls past 2 weeks**: Ping maintainers on issue #33. Fallback: submit via `external_results.json` (simpler, no adapter code needed).
- **AML site down or API guide not accessible**: Check agentmemories.ai status. If the API guide is unavailable, check their GitHub for docs or contact via their submission form.
- **Cluster down**: MemoryHub must be running. Check `oc get pods --context mcp-rhoai -n memory-hub-mcp`.
- **AML submission window not open**: Park the submission, note the revisit date (late October 2026), and optionally start Phase 5 (score improvement) in the gap.
