# Eager Fact Extraction via MCP Sampling

**Status:** Design (extends `memory-extraction-pipeline.md`; for the
write-time extraction issue, TBD via issue-tracker)
**Date:** 2026-07-16
**Author:** @rdwj (designed with Claude in Cowork)
**Builds on:** `planning/memory-extraction-pipeline.md` (the extraction
pipeline this feeds), #339 (unified stage contracts), #347
(reconciliation), #348 (run provenance)
**Validated by:** chunk sweep + fact extraction prototype
(session 2026-07-15, `benchmarks/amb-harness/extract_facts.py`)

---

## 1. Position: a second trigger, not a fourth pipeline

This project once had three overlapping extraction/curation paths; #339
exists to unify them. Eager fact extraction MUST NOT become the fourth.
It is defined as a second *entry point* into the one extraction pipeline:

| | Background ("dreaming") | Eager (this design) |
|---|---|---|
| Trigger | cron / extraction_runner over stored threads | `write_memory` call with oversized content |
| LLM | server-configured extraction model | **the client's own model, via MCP sampling** |
| Latency | minutes-hours after write | seconds, within the write interaction |
| Output | fact candidates | fact candidates (identical shape) |
| Downstream | reconciliation (#347), provenance (#348), curation | **same — no separate path** |

Everything after candidate production — reconciliation, dedup,
provenance, versioning, curation gates — is shared. If an implementation
decision would fork the downstream, the decision is wrong.

### Third trigger: session-close capture (added 2026-07-16, Wes)

Eager extraction only sees content agents explicitly WRITE to MemoryHub.
Most memorable session content — decisions made, corrections given,
preferences revealed — is never written anywhere; it lives in the
transcript and evaporates at `/exit`. Session-close capture is the
missing ingestion trigger for the original dreaming pipeline: the
conversation-persistence subsystem (#168) built thread storage and the
windowed extractor exists, but nothing feeds interactive-agent
transcripts into them. This does.

| | Session-close capture |
|---|---|
| Trigger | harness session-end hook (Claude Code SessionEnd; harness-agnostic via CLI) |
| Mechanism | hook runs `memoryhub capture-session <transcript-path>` — redaction gate, then transcript persisted as a thread; extraction ENQUEUED |
| LLM | none at close (the session is ending — sampling has no live client). Default: the queue drains at the NEXT connected session via sampling ("session N's close enqueues; session N+1's connect dreams it"). Optional: server-side model where configured (cluster), or `memoryhub dream --model ...` (personal). |
| Output | same fact candidates, same downstream — trigger three, pipeline one |

Design requirements:

1. **Opt-in, per project** (`.memoryhub.yaml`), never default-on.
   Transcripts contain everything — secrets, third-party code, personal
   context.
2. **Redaction gate before the transcript leaves the machine:** run the
   credential patterns (we maintain gitleaks rules; reuse them) over the
   trace pre-persist. The 2026-07-14 credential incident is the
   argument.
3. **Retention choice:** `extract-and-discard` (facts kept, raw trace
   dropped after extraction) vs `retain-thread` (full governed thread,
   the original #168 design). Default extract-and-discard for personal;
   retain-thread is the enterprise/audit posture.
4. **Extraction cursor applies** (already in the conversation-extraction
   schema): a session partially processed by eager extraction mid-flight
   must not be re-extracted wholesale at close — cursor + reconciliation
   absorb the overlap, but the cursor does the cheap half.
5. **Harness-agnostic core:** the CLI is the contract; the Claude Code
   SessionEnd hook is the first integration (`memoryhub config init`
   already writes our SessionStart hook — this is its sibling). Other
   harnesses wire their own end-of-session ritual to the same CLI.

Consequence for sequencing: this raises the stakes on #347 again —
session-close extraction over full traces will re-produce facts eager
extraction already caught, making reconciliation the dedup backstop for
THREE producers, not two.

## 2. Why (evidence)

The 2026-07-15 sweep established that retrieval-unit granularity, not
tuning, is the lever on PersonaMem:

| Mode | Accuracy | Ctx tokens | k |
|------|----------|-----------|---|
| facts-lite-k70 | **63.3%** | **1,256** | 70 |
| c256-o10-k10 (best chunk) | 62.6% | 1,588 | 10 |
| c512-o25-k10 | 62.6% | 2,984 | 10 |
| parents-mode (== corpus-stuffing at this scale) | 70.8% | ~28,000 | 70 |

Chunk size is irrelevant (62.0-62.6% flat across 32-512 tokens, all
overlaps). Facts are the best *budgeted* mode at 22x fewer tokens than
full-context. The per-category signature is the design driver:

| Category | Facts k=70 | Chunks c256 | Delta |
|----------|-----------|-------------|-------|
| generalizing_to_new_scenarios | 89.5% | 73.7% | +15.8pp |
| recalling_reasons_behind_updates | 85.9% | 77.8% | +8.1pp |
| track_full_preference_evolution | 74.8% | 72.7% | +2.1pp |
| provide_preference_aligned_recs | 61.8% | 63.6% | -1.8pp |
| recall_user_shared_facts | 58.9% | 64.3% | -5.4pp |
| recalling_facts_mentioned_by_user | 47.1% | 41.2% | +5.9pp |
| suggest_new_ideas | 16.1% | 23.7% | -7.6pp |

Reading: facts dominate the *synthesis* categories (generalization,
reasons, evolution — the "know me" core, and exactly the substrate
reconciliation/Layer 3 need), and lose where broad raw context helps
(idea suggestion, some recall). Implication: facts are the primary
retrieval unit; parents remain reachable via `content_mode`/
`read_memory` hydration. Category-adaptive delivery is future work
(Section 8).

Caveats carried from the session: single extraction model (Flash Lite),
single run; the +0.7pp over chunks is noise. The pipeline is justified
by token efficiency and by facts being the substrate of Phases 5-7 —
not by that margin.

## 3. Mechanism: MCP sampling

FastMCP (>= 3.4.2) supports server-initiated sampling: during a tool
call, the server sends a `sampling/createMessage` request back to the
client, and the CLIENT's LLM produces the completion.

Strategic property (see `strategy/client-supplied-intelligence.md`):
MemoryHub performs LLM extraction **without server-side model
credentials, GPU inference capacity, or model egress**. The caller's
model — whatever it is, wherever it runs — does the work, under the
caller's existing model governance. For FIPS/air-gapped deployments this
converts extraction from an infrastructure dependency into a protocol
feature.

Flow:

1. `write_memory` receives content above the extraction threshold.
2. Parent memory is written normally (chunk children per existing path).
3. Server issues a sampling request: extraction prompt + content window.
4. Client's LLM returns fact candidates (structured JSON).
5. Candidates enter the shared pipeline: written as `branch_type="fact"`
   children of the parent, tagged with an extraction run ID, subject to
   curation/reconciliation downstream.

## 4. Design decisions (resolved 2026-07-16 review)

1. **Threshold:** same trigger as chunking (content large enough to
   chunk is large enough to extract). Small writes are already
   fact-sized; extracting them is a paraphrase tax. One threshold, one
   concept of "oversized."
2. **Sync vs async:** sampling is client-mediated, so it inherently
   lives inside the request lifecycle — the client must be connected.
   Design: initiate during write handling, await with a hard timeout
   (config, ~10-15s), and on timeout/failure ENQUEUE for the background
   path instead. The write itself never fails because extraction
   failed. Response includes `facts_extracted: n | "deferred"`.
3. **Extraction prompt:** start from the prototype's prompt, moved to
   `prompts/fact_extraction.yaml` per project convention, versioned —
   the prompt version is part of the extraction run ID (#348 pattern).
4. **Deduplication: deferred to #347 reconciliation.** Store-then-
   reconcile. Interim measure ONLY: batch-level dedup within a single
   write's candidate set (the prototype's duplicates were largely
   cross-write, which is reconciliation's job by definition). Do NOT
   build an ad-hoc cross-write dedup here — that is the fourth-path
   trap.
5. **Fallback (client lacks sampling support):** the background dreaming
   path IS the fallback — same prompt, same output shape, same
   downstream, minutes later instead of seconds. Capability-detect at
   session registration; SDK exposes `extract_facts` as
   `eager | background | off`.

## 5. Schema and provenance

- Facts: `branch_type="fact"` children via `parent_id` (joins chunk /
  rationale / insight). Independently embedded. `is_current` semantics
  identical to other memories — facts are first-class, versionable,
  reconcilable.
- Provenance: every fact carries the extraction run ID (model — as
  reported by the client, prompt version, timestamp, trigger=eager|
  background) per #348's rollback-unit design. A bad extraction batch
  must be rollback-able exactly like a dreaming run.
- Weight default: inherit a configurable default (0.7 suggested);
  reconciliation and curation adjust after.

## 6. Retrieval interplay (must be decided BEFORE facts ship to a shared tenant)

The recall pool now potentially contains parents, chunks, AND facts.
Lessons already paid for: chunks competing with parents caused the
#344 regression; `return_chunks` filtering post-RRF still lets parents
influence ranking. Design:

- Introduce an explicit `retrieval_unit` preference on search
  (`facts | chunks | parents | auto`), sibling to `content_mode`.
  Default `auto` = facts-first with parent expansion available via
  flags/read_memory (the proven facts + hydration pattern).
- Pool discipline: a single search draws candidates from ONE unit class
  plus its expansion targets — units never compete head-to-head in RRF
  within one query. (The prototype avoided this with a separate
  project; production gets it by design, not by isolation.)

## 7. Cost model

Eager extraction cost is borne by the CLIENT's model at write time —
zero marginal server LLM cost. For the caller: one extraction call per
oversized write (prototype: ~34 facts/doc avg from 195 PersonaMem docs;
typical agent session summaries will produce far fewer). Background
fallback uses the server's existing dreaming budget (see
memory-extraction-pipeline.md Section 4).

## 8. Open questions

1. Extraction model sensitivity — does a stronger client model move the
   63.3%? (Next session Part 1 tests exactly this before the pipeline
   is built.)
2. `retrieval_unit=auto` policy — facts-first is right for the measured
   synthesis categories; the -7.6pp on suggest_new_ideas argues for
   category- or query-adaptive delivery eventually. Needs its own
   design pass; do not improvise in the implementation session.
3. Sampling trust: the client's model produces content the server
   stores — a new write channel. Curation gates apply, but the
   poisoning-resistance work (#334) should add "sampling-supplied
   facts" to its threat model.
4. Fact granularity vs PersonaMem bias: facts are tuned here against
   one benchmark's question mix. The platform benchmark (D1 temporal
   consistency) is the truer target — facts are what reconciliation
   versions, which is what the cheese test exercises.
