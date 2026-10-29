# Procedural Graph Extraction and Refinement: Design Doc (#554)

**Status:** Design signed off by the operator on 2026-10-26: D1, D2, D6, D6a, D7 and D10 as
recommended; D6a.5 as recommended (explicit or observed-backed outcomes are strong); D7 `propose`
mode **creates** new graphs as `candidate` (the alternative reading, chosen over the
recommendation). The earlier local branch `feat/procedural-graph-extraction` is not salvaged;
implementation starts clean on `feat/procedural-graph-extraction-554`.
**Date:** 2026-10-26
**Base:** `main` @ `06cfea1` (after #552 / PR #587 and #553 / PR #591)
**Epic:** procedural graphs, phase 3 of 4 (`NEXT_SESSION-procedural-graphs.md`)

## Problem

Issue #554: dreaming should detect multi-step procedures in session transcripts, build a
procedural graph from them, and refine that graph when later sessions cover the same procedure,
instead of creating duplicates. The paper (arXiv 2609.09153, "Offline Evolution") does this by
analyzing successful and failed trajectories, proposing structural edits, and committing only
edits that pass validation.

Today nothing writes a procedural graph automatically. #552 defined the shape (a
`content_type=procedural` root, `procedure_step` children, `precedes`/`requires`/`alternative_to`
edges, attributes in `metadata_.procedure`) and #553 made it retrievable
(`resolve_procedure_entry`, `build_localized_subgraph`, `localized_guidance`). Graphs are built
only by hand through `memory(action="write")` and `manage_graph(action="relate")`.

**Definition of done** (from the epic plan): dreaming can detect a multi-step procedure in a
session transcript and create a procedural graph from it, and later sessions that cover the same
procedure refine that graph instead of creating duplicates.

## What already exists: inventory, verified against `main` @ `06cfea1`

Every claim below was checked against code. Several differ from what the task brief assumed;
those are marked ⚠ because they change the design.

| Area | What is there | Consequence for #554 |
|---|---|---|
| Dreaming entry | `services/dreaming.py::extract_from_thread` (canonical; `conversation_extraction.py` is a re-export shim). Loads messages after `thread.extraction_cursor`, windows them (`per_turn` default, `per_session`, `per_message` via operator-only `retention_policy.extraction_mode`), calls `_call_extraction_llm`, reconciles each fact, commits per window, advances the cursor past failed windows. | The procedural pass hooks in here, after the fact windows, without touching their cursor. |
| Fact transcript | `_format_messages` prints `[ROLE] (seq=N): content`; ⚠ S3-backed messages print `[content stored in S3]`; `tool_call_id` and message `metadata_` are not shown. | The fact path does not hydrate S3. Messages over `conv_inline_max_bytes` (8 KB), typically tool results, are invisible to it. The procedural formatter must hydrate (D2). |
| LLM transport | `conv_extraction_{model,model_url,api_key,timeout}`; POST `{url}/chat/completions`, `response_format=json_object`, retries 0/30/60/120 s on connect/timeout/429/5xx. ⚠ `httpx.AsyncClient(verify=False)`. | Procedural pass uses the same settings and URL convention, its own client with default TLS verification (#604 still open, no shared factory exists). |
| Run id | `dream:{model}:{prompt_hash}:{iso timestamp}`. ⚠ Contains a timestamp. | "The same run id executing twice" only happens if a caller passes one in. Idempotency must key on `(procedure, thread)`, not on run id (D6a). |
| Reconciliation | `reconcile_candidate`: thresholds 0.98 skip / 0.80 tiebreaker / else create; decision row in `reconciliation_decisions`; `rollback_extraction_run(run_id)` soft-deletes creates, restores updates. ⚠ Dreaming never passes `tiebreaker_fn`, so the 0.80–0.98 band always creates. ⚠ `rollback_extraction_run` has no caller (no MCP or CLI surface) and ignores relationships. | The "LLM tiebreaker" has to be built for procedures (D5). Rollback must be extended for procedural actions (D9). |
| Similarity | `check_similarity` filters owner, scope, tenant, current, active. ⚠ Not `scope_id`, not `content_type`, not root-vs-step. Returns nothing on SQLite. | Matching needs its own filtered query (D5). Unit tests inject the matcher; pgvector behaviour is covered in integration. |
| `create_memory` | Embeds, runs curation (regex tier always; similarity tier unless `force`), inserts, ⚠ **commits**, then chunks oversized content (own commit), then fires entity extraction (`trigger_extraction`, fire-and-forget). | Not usable inside one transaction as-is (D4). |
| Curation | `run_curation_pipeline` ⚠ lazily calls `seed_default_rules` the first time a process sees a tenant, and that **commits the session**. With `embedding=None` only the regex tier runs. It scans only the string it is given. | Curation must run as a pre-flight before any write in the transaction, and must scan metadata strings, not just `content` (D4). |
| `create_relationship` | ⚠ **Commits**; on `IntegrityError` rolls the session back. | Needs a non-committing path (D4). |
| `invalidate_relationship` | Sets `valid_until`, does not commit, idempotent. | Usable as-is for `deprecate_edge`. |
| `update_memory` | New version row; re-points active edges from the old id to the new id; deep-copies one level of children. ⚠ Commits; no `commit=False`. | See next row. |
| ⚠ **`update_memory` on a procedure root** | Verified with a probe test against the #552 fixture: steps are deep-copied under **new ids**, but the edges stay attached to the **retired** step rows; the copies also lose `content_type` (reset to `experiential`) and `scope_id`. `resolve_procedure_entry` on the new root then raises `EntryStepResolutionError` (3 entry candidates). | **Refinement must never re-version a procedure root.** This is a live bug for anyone calling `memory(action="update")` on a procedure root today; it gets its own issue and PR (follow-ups), not a fix bundled here. |
| Retrieval (#553) | `resolve_procedure_entry` honours `metadata_.procedure.entry_step_id` when it names a current in-tenant node, else needs exactly one step with no incoming live `precedes`. `render_subgraph_context` renders `action`, `tool_ref`, `guidance`, `preconditions`, `postconditions`, `pitfalls` and edge `condition`, `guidance`, `pitfalls`; list items are rendered with `str(item)`. | Extracted graphs always set `entry_step_id`. The render fields must stay lists of strings; evidence annotations go elsewhere (D4). |
| Outcome signal | ⚠ No outcome field on threads or messages. `thread.metadata_` can only be set at `create` (no update action), i.e. before the outcome is known. `message.metadata_` is settable on `append`. | Explicit outcome = a message-level marker (D-Outcome). Otherwise the LLM infers. |
| Thread scope / policy | `retention_policy` is server-assigned at create (`ttl_days`, …); ⚠ no API sets it. Threads can be `user`, `project`, `campaign`, `role`, `organizational`, `enterprise`. Extract is allowed for thread readers (`authorize_thread_read`); writes go to the thread owner's scope. | A per-thread override in `retention_policy` is an operator knob only. Procedural writes are restricted to `user` and `project` threads. |
| Persona (#608) | Compiles only `source="dreaming"`, `content_type="behavioral"`, `scope="user"` nodes. Fact path marks the synopsis stale after user-scope writes. The fact prompt never emits `content_type`, so facts land as `experiential`. | Procedures (`procedural`) never feed the persona and must not mark it stale. |
| #555 / #562 | Nothing landed. PR #575 (#562) was closed unmerged and touched only SDK-side recall gates. | No reusable code; the #555 seam is defined here (D9). |
| CLI | `memoryhub dream` uses `memoryhub_local` (its own extraction), not `memoryhub_core`. `memoryhub thread extract` goes through the SDK to MCP. | No CLI `dream` change; `memoryhub-local` parity is a follow-up. |
| Tests | Dreaming tests patch `_call_extraction_llm` with `unittest.mock`; `respx` is not a dependency. `tests/integration/` runs against Postgres + pgvector via `compose.yaml`. Baseline on `main`: dreaming, procedural, reconciliation and rollback suites, 79 passed. | Unit tests mock the LLM with `unittest.mock` / `httpx.MockTransport`; no new test dependency. |

### A prior local attempt exists

Branch `feat/procedural-graph-extraction` (2026-10-14, unpushed) contains an earlier #554
implementation built on the #553 branch before it merged. It conflicts with `main` today and its
design differs from this one: a per-thread flag instead of an operator-controlled mode, no
propose/apply split, no per-session evidence replacement, no failure classes, rejections routed
to `audit.record_event`, and refinement through `update_memory`. This doc keeps three of its
ideas (a separate procedural cursor, explicit `entry_step_id` at write time, a post-write
retrieval check) and replaces the rest. Whether to salvage code from it is an open question for
the operator.

## Shape of the pass

```
extract_from_thread(...)                       # unchanged fact windows run first
  └─ if effective procedural mode != off:
       extract_procedures_from_thread(...)      # services/procedure_extraction.py
          1. select + format trajectory         (D2)  hydrate S3, truncate, keep seq numbers
          2. detect                              (D3)  LLM → strict pydantic proposal
          3. validate + filter                   (D3)  deterministic: evidence, min bar, entry
          4. match existing procedure            (D5)  filtered pgvector + alignment + tiebreaker
          5a. no match  → create graph           (D4)  one transaction
          5b. match     → account evidence       (D6a) replace this thread's contribution
                         → derive edits          (D6)
                         → gate                  (D7)  propose: store; apply: apply gated edits
          6. decision log + report               (D9)
```

`extract_procedures_from_thread` is a standalone async function over one thread, so a later
sweep or `AgentPlugin` can call it without going through the fact pass.

---

## D1: Trigger — SIGNED OFF 2026-10-26

**Options**

- **A. Opt-in pass inside `extract_from_thread`**, after the fact windows, controlled by an
  operator setting. Every existing caller (MCP `thread(action="extract")`) gets it without a new
  entry point.
- **B. Standalone sweep** over threads with new messages (cron / admin call).
- **C. `AgentPlugin`** in `memoryhub-agents`, the curation epic's (#350) framework.

**Recommendation: A**, implemented as a standalone function so B or C can call it later.
`memoryhub-agents` stays an optional future home, not a dependency.

**Mode and precedence.** New `AppSettings.procedural_extraction_mode: str = "off"`
(`MEMORYHUB_PROCEDURAL_EXTRACTION_MODE`), values `off | propose | apply`. Unknown values are
treated as `off` with a warning, not a startup failure, because `AppSettings()` is constructed
all over the codebase. The effective mode for a run is the **minimum** (`off < propose < apply`)
of:

1. the server setting (a ceiling: `off` guarantees the pass never runs),
2. `thread.retention_policy["procedural_extraction_mode"]` if present (operator-only today),
3. the caller's `procedure_mode` option, if given (D10).

So nothing a caller or thread does can raise the mode above what the operator configured.
With the default `off`, `extract_from_thread` takes no new branch, issues no new query, and
returns exactly the dict it returns today. This is what keeps R1 dreaming unchanged.

**Ordering.** After the fact windows, independent of the fact circuit breaker and of fact window
failures. A procedural failure never affects facts and is reported under `procedures.error`.

Signed off: overrides can only lower the mode.

## D2: Input window — SIGNED OFF 2026-10-26

**Options**

- **A. Reuse the fact windows.** Wrong for this job: the default `per_turn` window is about 4
  messages, and a procedure spans many turns.
- **B. Messages since a procedural cursor only.** Cheap, but a procedure that continues across
  two extract calls is seen in halves, and each half falls below the minimum bar.
- **C. A sliding run of tool-call-bearing turns.** More selective, but splits a single procedure
  at chit-chat turns and adds a segmentation heuristic that needs its own tuning.
- **D. The whole session (thread), re-read whenever it gained messages**, bounded by a budget.

**Recommendation: D.** The unit of evidence is the session (D6a), and a newer run over a session
that gained messages *replaces* that session's earlier contribution, so re-reading the whole
session is the natural input, not a cost to minimise.

- **Own cursor.** `thread.metadata_["procedural_extraction"] = {"last_seq", "last_run_id",
  "last_attempt_at", "last_error"}`. The pass runs only when the thread has messages with
  `sequence_number > last_seq` *and* at least one `tool_call` message in the session. The fact
  `extraction_cursor` and `last_extracted_at` are never read or written by the procedural pass.
  (`thread.metadata_` is caller-supplied at create; a caller who spoofs this key can only stop
  their own thread from being analysed.) The cursor is written in the same transaction as the
  graph writes; on an LLM or validation error it is not advanced and `last_error` is recorded
  in a separate small commit. `dry_run` writes nothing, cursor included. A caller-supplied
  `turn_range` restricts the transcript to that range and does not move the cursor, mirroring
  the fact path.
- **S3.** Messages with `storage_type="s3"` are hydrated with `s3_adapter.get_content`
  into a plain `TrajectoryEvent` dataclass. ORM rows are never mutated (assigning
  `msg.content` would mark the row dirty and write tool output into the DB column on the next
  commit). Without an adapter, the event is a placeholder and cannot back an `observed` claim.
- **Token budget.** `procedural_max_transcript_chars` (default 60 000). Per message:
  `tool_result` keeps the first 1 500 and last 500 characters with an explicit
  `[… N chars omitted …]` marker; `tool_call` arguments keep 1 000. If the session still exceeds
  the budget, keep the first user message (the goal) plus the most recent messages that fit, and
  insert `[messages a–b omitted]`. Evidence may cite only sequence numbers that are present in
  the formatted transcript; citations of omitted messages are dropped by the validator.
- **Format.** One line per message: `[seq=N] ROLE (tool_call_id=…)`, content on the following
  lines, so `tool_call` / `tool_result` pairs are visible. `message.metadata_` is not shown except
  the outcome marker (D-Outcome).

## D3: Detection contract

New prompt `prompts/procedural_extraction.yaml` (`version: "1.0"`, `system_prompt`, plus a
small `match_tiebreaker_prompt` used by D5). Hash = SHA-256 of the system prompt, cached, the
same way `_load_prompt` does it; recorded in provenance and in the run id
(`dream-proc:{model}:{hash}:{timestamp}`).

**Strict output schema** (pydantic v2, `extra="forbid"`; lengths capped):

```json
{
  "procedure_detected": true,
  "goal": "Deploy service X to staging",
  "summary": "Build the image, run smoke tests, promote, verify health.",
  "steps": [
    {"key": "s1", "action": "Build the container image", "tool_ref": "podman build",
     "preconditions": [{"text": "...", "evidence": "observed", "source_messages": [4]}],
     "postconditions": [], "pitfalls": [], "guidance": null,
     "status": "succeeded", "evidence": "observed", "source_messages": [3, 4]}
  ],
  "edges": [
    {"source": "s1", "target": "s2", "type": "precedes",
     "condition": null, "guidance": null, "pitfalls": [],
     "evidence": "observed", "source_messages": [4, 5]}
  ],
  "entry_step": "s1",
  "outcome": {"result": "success", "confidence": 0.9, "evidence": "observed",
              "source_messages": [14],
              "failure": null},
  "detection_confidence": 0.85
}
```

`failure` (when `result` is `failure` or `partial`) is
`{"step": "s3" | null, "edge": {"source", "target"} | null, "class":
"procedure" | "tool_error" | "environment" | "precondition_unmet" | "unknown",
"evidence", "source_messages"}`. Step `status` is `succeeded | failed | skipped | unknown`.
Pitfalls, pre/postconditions and edge conditions are objects with their own `evidence` and
`source_messages`.

**Prompt rules** (enforced again by the validator where they are checkable):

- Report only steps visible in the transcript: a tool call, a tool result, or an action a user
  or assistant message explicitly states was taken. Never invent intermediate reasoning, never
  reconstruct hidden chain-of-thought, never add "likely" steps.
- `observed` = a cited message shows it. `inferred` = the model's interpretation with no message
  showing it. Every item carries one or the other plus the sequence numbers it rests on.
- A decision point is an edge `condition` only if the condition is stated in a message or shown
  by a tool result (for example "tests failed → rolled back").
- Return `{"procedure_detected": false}` for sessions without a multi-step procedure.

**Deterministic validation after parsing** (no model involved):

1. Every cited sequence number exists in the formatted transcript; otherwise it is dropped. An
   `observed` item left with no citations becomes `inferred`.
2. A step with a `tool_ref` marked `observed` must cite at least one `tool_call` or `tool_result`
   message; otherwise it is downgraded to `inferred`.
3. An `observed` `precedes` edge requires both endpoints observed and the source's first cited
   sequence number below the target's.
4. **Minimum bar:** at least `procedural_min_steps` (3) observed steps, at least one observed
   step citing a `tool_call`, `detection_confidence >= procedural_min_detection_confidence`
   (0.7), at most `procedural_max_steps` (30) steps, an `entry_step` that is an observed step
   with no incoming `precedes`, and every step reachable from the entry over `precedes` /
   `alternative_to` (cycles that do not pass through the entry are allowed; #552 permits retry
   loops). Inferred steps are not written to a new graph.
5. Failing any of these drops the detection with a recorded reason (D9).

**Parsing and retries.** Best-effort JSON (strip code fences, as `_parse_json_best_effort`),
then pydantic validation. On a parse or schema error, one correction retry: the bad response and
the validation error are appended and the model is asked to return the schema only (same pattern
as `procedural_guidance._inject_correction`). Service errors retry like the fact path. A second
format failure records `invalid_proposal`; an exhausted service retry leaves the procedural cursor
where it was so the next extract call retries.

**TLS.** The procedural client is `httpx.AsyncClient(timeout=…, headers=…)` with default
verification, plus `# TODO(#604): replace with the shared outbound LLM client factory`.
Operational note: an endpoint with a private CA needs `SSL_CERT_FILE` (httpx honours it). The
fact path keeps its existing client; it is not touched here.

## D4: Writing a graph

New module `src/memoryhub_core/services/procedure_extraction.py`.

### Atomicity

Root, steps, edges, `entry_step_id`, initial evidence, the `ConversationExtraction` row, the
decision-log rows and the procedural cursor are committed in **one** transaction, or not at all.

- `create_memory(..., commit: bool = True)`: with `commit=False` it adds and `flush()`es the node,
  skips the post-commit chunking and entity-extraction trigger, and returns. It refuses content
  that would need chunking or S3 spill (`ValueError`), and the writer caps step and root text far
  below both thresholds, so that refusal is a programming-error guard. Existing callers pass
  nothing and behave exactly as today.
- `create_relationship(..., commit: bool = True)`: with `commit=False` it adds and flushes, and
  on `IntegrityError` raises without calling `session.rollback()` (the writer owns the
  transaction). Existing callers are unchanged.
- The writer wraps everything in `try: … await session.commit() except: await
  session.rollback(); raise`. After the commit it calls `trigger_extraction` for every created
  node, so entity extraction still runs per node, but only for nodes that actually exist.
- **Curation pre-flight.** Before the first write, the writer runs `run_curation_pipeline` with
  `embedding=None` on the **full text** of every node and edge it will write: content plus every
  metadata string (`action`, `tool_ref`, conditions, pitfalls, guidance). This (a) triggers the
  tenant rule seeding commit while nothing is pending, and (b) applies the regex tier (secrets,
  PII) to content derived from `tool_result` messages, which would otherwise reach metadata
  unscanned. Any `blocked` result rejects the whole proposal (`curation_blocked`). Nodes are then
  created with `skip_curation=True`. This is the same protection the fact path gets
  (`force=True`: regex tier enforced, similarity tier bypassed); it is not a skip.
- Refinement edits that add text (pitfalls, guidance, conditions, new steps) go through the same
  pre-flight.
- **Failure-injection test:** make the writer raise after the root and two steps are flushed;
  assert no root, step, edge, `ConversationExtraction` or decision row for that run exists, and
  the procedural cursor has not moved.

### What is written

Root (`MemoryNode`): `content = "{goal}: {summary}"`, `content_type="procedural"`,
`parent_id=None`, `scope` / `scope_id` / `owner_id` / `actor_id` from the thread,
`source="dreaming"`, `weight = procedural_auto_weight` (0.6; any later automatic change is capped
at `procedural_max_auto_weight` 0.7), `upstream_trust_level = "mixed"` when any cited message is a
`tool_result`, else `"trusted"`.

```json
{
  "extraction_source": {"thread_id": "…", "source_messages": [3, 4, 5, 9, 14],
                        "model": "…", "prompt_hash": "…", "run_id": "…"},
  "procedure": {
    "origin": "extracted", "schema_version": 1, "status": "candidate",
    "goal": "Deploy service X to staging",
    "entry_step_id": "<uuid>",
    "evidence": { "sessions": {…}, "evicted": {…} },
    "pending_edits": [],
    "contradictions": []
  }
}
```

Step (`MemoryNode`, `parent_id=root`, `branch_type="procedure_step"`, `content_type="procedural"`,
same owner/scope/tenant/actor/weight):

```json
{
  "extraction_source": {"thread_id": "…", "source_messages": [3, 4], "model": "…",
                        "prompt_hash": "…", "run_id": "…"},
  "procedure": {
    "action": "Build the container image", "tool_ref": "podman build",
    "preconditions": ["…"], "postconditions": [], "pitfalls": ["…"], "guidance": null,
    "origin": "extracted", "step_key": "s1",
    "evidence": {"success_count": 1, "failure_count": 0, "weak_count": 0,
                 "last_seen": "2026-10-26T…", "sessions": ["<thread_id>"], "session_total": 1},
    "attribute_evidence": {"pitfalls": [{"text": "…", "evidence": "observed",
                                         "source_messages": [7], "threads": ["…"]}]}
  }
}
```

Edges (`MemoryRelationship.metadata_`, `created_by="dreaming:procedural"`): `condition`,
`guidance`, `pitfalls` (render fields) plus `origin`, `evidence`, `attribute_evidence`,
`extraction_source`.

**Render fields hold observed items only.** `action`, `tool_ref`, pre/postconditions, pitfalls,
guidance and edge conditions that #553 renders into guidance prose are lists of plain strings and
contain only `observed` items. Inferred items stay in `attribute_evidence`, so a model hypothesis
is never handed to an agent as fact by `localized_guidance`.

**Provenance row.** One `ConversationExtraction` per (root, thread):
`memory_node_id=root`, `extracted_by="procedural_extraction_pipeline"`, model, prompt hash,
`source_messages`. A later session that refines the procedure adds its own row for the same root.

**Status.** `candidate` at creation; `established` once
`procedural_min_supporting_sessions` (2) distinct sessions with a strong successful outcome
support it. Status is recorded only; #553 retrieval does not filter on it (open question 3).

**Prompt-injection note.** Tool results are untrusted text, and procedural guidance is fed back
into agent context. Mitigations in this design: observed-only render fields, the curation
pre-flight over all text, `upstream_trust_level="mixed"`, `candidate` status, and the D7 rule
that structural edits need at least two independent sessions.

## D5: Matching an existing procedure (dedup)

1. **Candidate set (SQL, tenant-filtered).** Current, active, not deleted `MemoryNode` with
   `content_type="procedural"`, `parent_id IS NULL`, `tenant_id = thread.tenant_id`,
   `owner_id = thread.owner_id`, `scope = thread.scope`, and `scope_id = thread.scope_id`
   (`IS NULL` when the thread has none). Owner-equality mirrors the fact path's
   `check_similarity`. Hand-authored roots are candidates too, so a session that follows a
   documented runbook does not create a duplicate of it. **Amended 2026-10-28:** in a `project`
   thread with a `scope_id`, the owner filter is dropped, so every member's procedures in that
   project are candidates (see "Second review round").
2. **Similarity.** Embed `"{goal}: {summary}"` and rank candidates by pgvector cosine with a
   dedicated query in the new module (`check_similarity` is not changed; it lacks the
   `content_type`, root and `scope_id` filters). Bands reuse `reconciliation.SKIP_THRESHOLD` (0.98)
   and `TIEBREAKER_THRESHOLD` (0.80): ≥ 0.98 same; < 0.80 new; between is ambiguous.
3. **Ambiguous band, top 3 candidates in score order.** First a deterministic step alignment
   (step 4). Overlap ≥ 0.6 → same; ≤ 0.2 → different; otherwise an LLM tiebreaker
   (`match_tiebreaker_prompt`, same endpoint, returns `{"verdict": "same" | "different"}`). If the
   tiebreaker errors, the result is `ambiguous_match`: nothing is created, the detection is
   recorded as a proposal. Not creating is the safer failure for the definition of done.
4. **Step alignment.** One-to-one, greedy by score: (a) equal normalized `tool_ref` (lowercased
   command or tool name, arguments stripped) scores 1.0; (b) otherwise the cosine between the new
   step's action embedding and the existing step's stored embedding, kept if ≥
   `procedural_step_match_threshold` (0.85). Overlap = aligned / max(new observed steps, existing
   steps). Edges map through the alignment.
5. **Logging.** Every match decision (`proc_match` / `proc_create` / rejection) goes to the
   decision log with similarity, overlap and verdict, keyed by run id (D9).

On SQLite the candidate query returns nothing, so unit tests inject a matcher; real pgvector
behaviour is covered by the integration test.

## D6: Refinement edits — SIGNED OFF 2026-10-26

Edits are derived from the **evidence ledger** (D6a), not from the latest session alone.
"Strong" means a session whose outcome is strong per D6a.5; "attributable failure" means a strong
failed session whose `failure.class == "procedure"` names this item with observed evidence.

| Edit | Structural | Driven by | Apply rule (`apply` mode) |
|---|---|---|---|
| `add_pitfall` / `add_guidance` (step or edge) | no | observed pitfall or guidance in any session, any outcome (including `tool_error`) | Apply after curation pre-flight; dedupe by normalized text; at most 5 pitfalls per item. |
| `add_condition` (edge) / `add_precondition` (step) | no | observed condition separating success from failure, or a `precondition_unmet` failure with an observed precondition | Apply after curation pre-flight. |
| `add_step` | yes | an unaligned observed step on the path of strong **successful** sessions | ≥ `procedural_min_supporting_sessions` (2) distinct sessions. Inserted with `precedes` edges from its aligned predecessor and to its aligned successor; the existing direct edge is kept (removing it needs failure evidence). |
| step seen only in **failed** sessions | — | — | Never a main-path step. Becomes a pitfall on the step where the run diverged; if a strong successful session later reaches success through it, it is re-evaluated as an alternative. |
| `add_edge` (`precedes` / `alternative_to`) | yes | a transition between aligned steps, or a path that bypasses existing steps, in strong successful sessions | ≥ 2 distinct sessions confirming that transition (counted per path, D6a.4). Added as `precedes`; a new step that takes the place of an existing one (same predecessor and successor) also gets an `alternative_to` edge to it (see `add_step`). |
| `deprecate_edge` | yes | attributable failures on a main-path edge | ≥ `procedural_deprecation_min_failures` (2) distinct sessions **and** no strong success through that edge. Implemented with `invalidate_relationship` (temporal, never a hard delete). Below the threshold the edge gets a pitfall instead. |
| `deprecate_step` | yes | attributable failures on a step | Same thresholds as `deprecate_edge`. Implemented as soft delete of the step (`deleted_at`) plus invalidation of its active procedural edges, so `_procedure_steps` and `resolve_procedure_entry` stop seeing it; reversible by rollback. Rejected (`breaks_entry`) if it is the entry and no `update_entry` is valid in the same batch. |
| `update_entry` | yes | strong successful sessions consistently starting at another aligned step | ≥ 2 distinct sessions; new entry must have no incoming `precedes`. In-place change to the root's `entry_step_id`. |

**How edits are persisted.** Structural edits use the non-committing create paths from D4 and
`invalidate_relationship`. Attribute and counter changes are **in-place** updates to the
`metadata_` JSON of the root, step or edge (reassigning the dict), recorded with a before/after
snapshot in the decision log for rollback. Nothing in automated refinement calls
`update_memory`:

- on a root it breaks the graph (inventory, ⚠ row);
- on the entry step it would change the step id and invalidate `entry_step_id`;
- it commits on its own, so it cannot be part of the edit transaction.

This trades version history of extracted procedures for graph integrity; the decision log is the
history. Revisit once the root-versioning bug is fixed.

**Hand-authored procedures** (`metadata_.procedure.origin` absent or not `"extracted"`; every
procedure written today is in this group) are never structurally changed and their steps and
edges are never touched. They receive evidence bookkeeping and `pending_edits` on the root only,
and every structural edit is recorded with reason `hand_authored`.

## D6a: Evidence accounting — SIGNED OFF 2026-10-26

1. **Unit of evidence = one session (thread id).** A session contributes at most one success or
   one failure per step, per edge and per path. The ledger lives on the root:
   `metadata_.procedure.evidence.sessions[thread_id] = {run_id, max_seq, outcome,
   outcome_source, outcome_confidence, strong, failure_class, items: {"step:<id>": "success" |
   "failure" | "attributable_failure" | "neutral", "edge:<id>": …, "path:<hash>": "success"}}`.
   Bounded to the most recent `procedural_evidence_session_limit` (50) sessions; older sessions
   are folded into `evidence.evicted` (per-item totals plus the evicted thread ids). Step and edge
   counters (`success_count`, `failure_count`, `weak_count`, `sessions` = last N ids,
   `session_total`, `last_seen`) are **derived** from the ledger and written only when they change.
2. **Retries and reprocessing are idempotent per `(procedure_id, thread_id)`.** Same thread and
   same `max_seq` (a retry, a re-run, or the same `run_id` twice) → the derived counters are
   identical → no write, no version change. A newer run over a session that gained messages
   **replaces** that thread's ledger entry; counters are recomputed, never incremented. A thread
   already folded into `evicted` is not re-added (`evidence_evicted` in the log).
3. **Tool error vs. procedure failure.** Each failed session is classified `procedure`,
   `tool_error`, `environment`, `precondition_unmet` or `unknown`. Only `procedure` failures that
   name the step or edge with observed evidence count as attributable and can drive
   deprecation. The other classes produce pitfalls or conditions, never structural removal.
4. **Alternative paths** are confirmed per path, not per step: a path counts once per distinct
   successful strong session that reached success through it with observed evidence.
5. **Outcome strength (signed off 2026-10-26: recommendation).** The brief says both "refinement must not treat an
   inferred *low-confidence* outcome as strong evidence" and "outcomes that are inferred, *or*
   below the confidence threshold, carry no weight". Read strictly, the second makes refinement
   inert today, because no host emits explicit outcome markers. **Recommendation:** an outcome
   is **strong** when it comes from an explicit marker (D-Outcome), or when the model's outcome
   cites observed evidence (for example a final tool result showing tests passing, or a user
   message confirming it worked) and its confidence is ≥ `procedural_min_outcome_confidence`
   (0.7). An outcome the model judged without a cited observable signal is `inferred` and always
   weak. Weak sessions are recorded in the ledger and count toward nothing.
6. **Conflicting results.** If a step or edge has both strong success and attributable failure
   evidence, no majority vote. First look for an observed separating condition (a precondition,
   a parameter, an environment fact recorded on the failing or succeeding side); if one exists,
   propose `add_condition` / `add_precondition`. If none is observable, append a contradiction
   note (`{"kind": "conflicts_with", "success_threads", "failure_threads", "run_id"}`) to the
   item's `metadata_.procedure.contradictions`, keep the graph as is, and record the structural
   edit as a pending proposal with reason `conflicting_evidence`.
7. **Inferred-only evidence never passes a gate**, at any count.

### D-Outcome: where the outcome comes from

Order of precedence, recorded as `outcome_source`:

1. `explicit_message`: the latest message whose `metadata_.outcome` is `success`, `failure` or
   `partial` (settable today through `thread(action="append", options={"metadata": …})`).
2. `explicit_thread`: `thread.metadata_.outcome`, if a future API makes it settable after create.
3. `llm`: the model's `outcome`, strong or weak per D6a.5.

No host sets either marker today (see Limitations). Defining the convention is cheap and gives
hosts a way to make refinement precise.

## D7: Validation gating — SIGNED OFF 2026-10-26

Deterministic gates, thresholds in `AppSettings` (env `MEMORYHUB_` + upper-case name):

| Setting | Default | Gate |
|---|---|---|
| `procedural_extraction_mode` | `off` | D1 |
| `procedural_min_steps` | 3 | creation minimum (observed steps) |
| `procedural_max_steps` | 30 | creation and growth cap per graph |
| `procedural_min_detection_confidence` | 0.7 | creation |
| `procedural_min_outcome_confidence` | 0.7 | strong outcome (D6a.5) |
| `procedural_min_supporting_sessions` | 2 | every additive structural edit; `established` status |
| `procedural_deprecation_min_failures` | 2 | `deprecate_edge`, `deprecate_step` |
| `procedural_max_edits_per_run` | 10 | circuit breaker on applied edits per run; the rest are `cap_reached` |
| `procedural_auto_weight` / `procedural_max_auto_weight` | 0.6 / 0.7 | weight policy |
| `procedural_evidence_session_limit` | 50 | ledger bound |
| `procedural_max_transcript_chars` | 60 000 | D2 budget |
| `procedural_step_match_threshold` | 0.85 | D5 alignment |

**Graph invariants**, checked on the edited graph before commit: the entry resolves (explicit
id names a current step with no incoming live `precedes`), no current step is orphaned (zero
active procedural edges in a graph of more than one step), no self-edge, no duplicate edge, step
count ≤ max. Then, inside the transaction after `flush()`, the writer calls
`resolve_procedure_entry` and `build_localized_subgraph` on the result; if either fails, the
whole edit batch is rolled back and each edit is recorded as `breaks_entry`.

**Modes.**

- `propose` (signed off: new graphs **are** created): a detection that matches no existing
  procedure is written as a new graph with `status="candidate"`, exactly as in `apply`. For a
  matched procedure nothing structural or attribute-level is applied: the pass updates the
  evidence ledger (bookkeeping, so gates can fire later), appends gated edits to
  `metadata_.procedure.pending_edits` (with evidence, run id and the gate that passed or failed),
  advances the procedural cursor, and returns everything in the response. Consequence accepted
  at sign-off: candidate graphs are retrievable through #553 as soon as they are written.
- `apply`: creates new graphs and applies edits that pass every gate; the rest are recorded as
  pending or rejected.
- `dry_run` (either mode): computes everything, writes nothing (no ledger, no cursor, no log), and
  returns the full proposals.

**Optional validation gate (added 2026-10-28).** As in the paper, an evaluation can be put in
front of structural edits. `MEMORYHUB_PROCEDURAL_VALIDATION_URL` (empty, so off, by default)
names an HTTP service, for example one backed by an EvalHub replay benchmark. In `apply` mode, phase A
plans the edits (a dry run), closes the transaction and POSTs the planned structural edits
(`add_step`, `add_edge`, `deprecate_*`, keyed by `Edit.key()`, no transcript text) to the
service. It answers `accept` or `reject` per key. Phase B applies a structural edit only if that
exact key was accepted. The gate fails closed: rejected, unreachable, or not seen (a concurrent
run changed the plan) edits stay in `pending_edits` with `validation_rejected`,
`validation_unavailable` or `validation_unseen`, and are asked about again with the next
supporting session. Attribute edits are not gated. Contract: `procedure_validation.py`. Related settings:
`procedural_validation_api_key`, `procedural_validation_timeout`,
`procedural_validation_ca_bundle` (TLS verification stays on).

## D8: Interaction with fact extraction

The fact prompt already says to skip "procedural chatter", and facts land as `experiential`.
Residual risk: the fact pass may still write a flat memory such as "to deploy X, build, test,
promote" for the same session. Options:

- **A. Accept and measure.** The procedural report includes `overlapping_facts`: fact memories
  created in the same run with cosine ≥ 0.85 to the procedure summary. Decide later with data.
- **B. Suppress the fact.** This changes default fact-extraction behaviour, which needs its own
  sign-off.
- **C. Run the procedural pass first and feed its goal into the fact prompt.** Same objection as B,
  plus it couples the two prompts.

**Recommendation: A.** Two things make the overlap low-harm. Reconciliation can never update a
procedure root, because fact candidates are `experiential` and the update path requires a content
type match. Persona compilation reads only `behavioral`. The procedural pass does not call
`mark_synopsis_stale`.

## D9: Observability and the decision log (#555 seam)

**Response.** When the effective mode is not `off`, `extract_from_thread` adds:

```json
"procedures": {
  "mode": "apply", "run_id": "dream-proc:…",
  "detected": 1, "created": 0, "matched": 1,
  "edits_proposed": 3, "edits_applied": 1, "edits_rejected": 2,
  "procedure_ids": ["…"], "cursor": 42,
  "rejections": [{"reason": "insufficient_evidence", "edit": "add_step", "item": "…"}],
  "overlapping_facts": []
}
```

With `dry_run`, it also carries the full parsed proposal and the edit plan. On error, it carries
`error` and leaves the cursor in place. When the mode is `off`, the key is absent; it appears as
`{"mode": "off"}` only if the caller explicitly asked for procedures (D10).

**Decision log.** One function, `record_procedural_decision(session, *, kind, reason, proposal,
thread_id, source_messages, run_id, procedure_id=None, snapshot=None)`, writes a
`reconciliation_decisions` row: `extraction_run_id=run_id`, `action` in `proc_create`,
`proc_match`, `proc_propose`, `proc_edit`, `proc_reject` (all ≤ 20 chars),
`candidate_content` = JSON of the proposal or edit plus its before/after snapshot, `reason`, and
`memory_id` / `nearest_match_id` pointing at the procedure. This uses an existing table, so no
schema change. It is the only path for rejections, so #555 can later back it with a rejection
store without touching callers. Rejection reasons: `below_confidence`, `insufficient_evidence`,
`breaks_entry`, `hand_authored`, `cap_reached`, `duplicate`, plus `inferred_only`,
`conflicting_evidence`, `ambiguous_match`, `invalid_proposal`, `curation_blocked`,
`scope_not_allowed`, `evidence_evicted`.

**Rollback.** `rollback_extraction_run(run_id)` is extended for the `proc_*` actions:

- `proc_create` soft-deletes the root and steps (existing behaviour for creates) and removes its
  `ConversationExtraction` rows;
- `proc_edit` restores the `before` snapshot when the current value still equals `after`
  (otherwise it counts as a post-run modification and is skipped, like today);
- edges a run added are invalidated, and steps a run deprecated are un-deleted.

No MCP or CLI surface exists for rollback today and this design does not add one.

**Logs.** INFO per run (mode, counts, run id), WARNING for LLM and validation failures, DEBUG for
per-edit gate results. No transcript content in logs.

## D10: Surface — SIGNED OFF 2026-10-26

**Recommendation: no new MCP tool.** `thread(action="extract")` gains optional options:

- `procedures: bool`: request the procedural pass (default follows the server setting);
- `procedure_mode: "off" | "propose" | "apply"`: can only lower the server mode (D1);
- `dry_run: bool`: forwards the existing service parameter. This also exposes dry run for facts,
  which is additive.

The `thread` docstring and `docs/design/mcp-server.md` are updated in the same PR. No required
parameter changes. The SDK's `extract_thread` and the CLI `thread extract` command pass options
through unchanged; adding typed SDK and CLI flags is a follow-up, and the response gains a key
only when the caller opts in. The consumer audit (`grep` of `memoryhub-ui/backend/`, `sdk/`,
`memoryhub-cli/`) is done in the same commit. CLI `dream` runs `memoryhub_local`, so it is out of
scope here.

## Authorization and scope

- Writes use the thread's `scope`, `scope_id`, `owner_id`, `actor_id`, `tenant_id`, exactly as
  fact extraction does. Procedural writes are limited to `user` and `project` threads; any other
  thread scope is skipped with `scope_not_allowed`, so `organizational`, `enterprise` and `role`
  are never written (`campaign` is excluded conservatively; open question 4).
- Every query in the new module filters `tenant_id` in SQL. Matching sees only procedures of the
  thread owner in the same scope and `scope_id`.
- The extract caller only needs read access to the thread (existing `authorize_thread_read`);
  results are owned by the thread owner. This matches the fact path and is not changed.

## Limitations

- **Input data comes from opt-in recorders.** Two recorders stream trajectories into threads:
  Claude Code hooks (`memoryhub config init --record-trajectories`, which runs
  `memoryhub thread record`) and the opencode plugin (`recordTrajectory.enabled`). Both are off
  by default, redact common secret formats client-side and clip long tool output. Other hosts
  still need `thread(action="append")`.
- **Outcome markers are manual.** `memoryhub thread outcome success|failure|partial` writes the
  explicit marker. Without it, refinement depends on D6a.5 (model-judged outcomes backed by
  observed messages).
- **Assistant corroboration is not proof of intent.** The corroboration rule stops text that
  only a tool result shows from becoming `observed`. It does not stop an assistant that was
  steered by that text from repeating it in a message of its own, which then counts as
  corroboration. The rule narrows injection; it does not close it. Guidance from candidates is
  still not served (`procedural_serve_candidates=false`), and promotion needs two sessions.
- **Truncation.** Long tool results are clipped (D2). A failure visible only in the omitted
  middle of an output is missed.
- **Cross-member matches are proposal-only.** In a shared project, a session that matches
  another member's procedure adds nothing to it. The match and the edits it would make are
  recorded as a proposal (`foreign_owner`) for the owner to review.
- **Personal edition is a subset.** `memoryhub dream --procedures` detects and creates (same
  contract, prompt and gates) and adds matching sessions to the ledger, but does not refine,
  deprecate or promote.
- **No version history** for automated edits beyond the decision log (D6).

## Test plan

Unit tests (`tests/test_services/test_procedure_extraction.py`, SQLite, LLM mocked with
`unittest.mock` / `httpx.MockTransport`; matcher injected where pgvector is needed). Four fixture
transcripts: a success, a failure, a variant of the same procedure, and chit-chat.

- malformed and partial JSON, correction retry, a second failure recorded as `invalid_proposal`;
  below-threshold detections dropped
- chit-chat transcript detects nothing
- a 3+ step success creates one root with ordered `precedes` steps and a resolvable entry
- provenance fields present on the root, the steps and the `ConversationExtraction` row
- tenant and owner isolation: another tenant's or owner's procedure is never matched or edited
- a second similar success session matches and adds evidence, with no duplicate root
- a failure session below the gate produces a pitfall or proposal, not a structural change
- gated `apply` adds an alternative step after two supporting sessions
- hand-authored procedures are never structurally modified
- `propose` applies nothing structural
- mid-write failure injection leaves no partial graph
- re-running the same session, or retrying the same `run_id`, changes no counter or version
- a `tool_error` failure adds a pitfall but never deprecates
- conflicting evidence defers the edit and records a contradiction note
- inferred-only evidence never passes a gate
- `observed` and `inferred` stay apart in output and in the render fields
- `off` mode: existing dreaming tests pass unchanged, plus a test that the response dict and the
  issued queries are identical to the pre-change path
- `dry_run` writes nothing
- rollback removes a run's writes, including edges and in-place edits
- the circuit breaker caps edits
- S3 hydration does not dirty ORM rows
- `create_memory(commit=False)` and `create_relationship(commit=False)` leave existing callers'
  behaviour unchanged

Integration (`tests/integration/test_procedure_extraction.py`, Postgres + pgvector via
`scripts/run-integration-tests.sh`):

- end-to-end create from a transcript
- second session matches through real pgvector, with no duplicate
- the extracted graph is returned by `resolve_procedure_entry` and by
  `localized_guidance` / `build_localized_subgraph` (#553), with the guidance LLM mocked
- failure injection against real transactions

Coverage of new modules ≥ 80%. `ruff check`. Full suites: root `tests/`,
`memory-hub-mcp/tests`; `memoryhub-cli` only if touched. Pre-existing failures are reported
separately and not fixed on this branch.

## PR plan

- **PR 1 ("Part of #554"):**
  - prompt file;
  - settings;
  - trajectory formatter;
  - pydantic proposal model and validator;
  - `commit=False` paths in `create_memory` and `create_relationship`;
  - curation pre-flight;
  - atomic writer;
  - wiring into `extract_from_thread` behind the mode;
  - `dry_run`;
  - decision log and creation rollback;
  - MCP options;
  - docs (ARCHITECTURE, SYSTEMS, mcp-server, CHANGELOG, thread tool description);
  - tests.
- **PR 2 ("Closes #554"):**
  - matching and step alignment;
  - tiebreaker;
  - evidence ledger;
  - edit derivation;
  - gates;
  - `propose` / `apply`;
  - rollback of edits;
  - integration test of refinement;
  - closing open question 1 of `planning/procedural-graphs.md`.

## Out of scope and follow-ups (issues to file via `/issue-tracker`)

Resolved in this branch on 2026-10-28 (see "Second review round"): the `update_memory` graph
bug, `memoryhub-local` parity, the validation gate, host trajectory recorders and cross-member
matching. Still open:

- An EvalHub-backed implementation of the validation endpoint (needs a cluster and an eval
  job; the gate's contract is in place).
- Rollback surface (MCP or admin) for `rollback_extraction_run`.
- #555 rejection memory (seam defined in D9); UI; benchmark against the paper's tasks.

## Open questions requiring a human

1. ~~Sign-off on D1, D2, D6, D6a, D7, D10~~ — signed off 2026-10-26 (see Status).
2. ~~Salvage the earlier local branch?~~ — no; start clean (2026-10-26).
3. Should `candidate` procedures be retrievable through #553 before they are `established`?
   (This design leaves retrieval untouched.)
4. Should `campaign`-scoped threads be allowed to produce procedures?
5. `planning/procedural-graphs.md` open question 1 (whether `precedes` / `requires` /
   `alternative_to` stay manually creatable). This design keeps them manual: hand-authored
   procedures stay first-class and are protected from automatic structural change. The doc is
   closed in PR 2.

## Implementation record (2026-10-26)

Implemented on `feat/procedural-graph-extraction-554`. Modules:
`src/memoryhub_core/services/procedure_extraction.py` (mode resolution, trajectory, prompt and
transport, proposal schema and validation, decision log, curation pre-flight, creation writer,
orchestration) and `src/memoryhub_core/services/procedure_evolution.py` (matching, alignment,
ledger, edit derivation and gates, application, invariants, rollback). Wiring:
`dreaming.extract_from_thread` (`procedures`, `procedure_mode`), MCP `thread(action="extract")`
options, `rollback_extraction_run` (`proc_*` rows). No migration, no new table, no new tool.

Where the build refined the design:

- **D5 matching** loads the owner's procedural roots in scope (at most 200, tenant / owner /
  scope / `scope_id` filtered in SQL) and computes cosine in Python, rather than a pgvector
  `ORDER BY`. Same thresholds. This keeps the path portable, so SQLite unit tests exercise real
  matching decisions instead of an injected matcher. If an owner ever accumulates hundreds of
  procedures in one scope, switch the ranking to pgvector.
- **D6 `alternative_to`.** A transition between existing steps that the graph lacks is added as
  `precedes`. `alternative_to` is used when a new step sits between the same predecessor and
  successor as an existing step: the new step gets `precedes` edges to both anchors and an
  `alternative_to` edge to the step it substitutes for. This matches the #552/#553 reading
  ("the source is another way to do the target").
- **Creation** never happens from a failed session (`failure` or `partial`, strong or weak): a
  failed run would encode the failing path as the main path. It is logged as
  `insufficient_evidence` (`failed_session`). Sessions with unknown or weak outcomes may create
  candidates.
- **Failure-only novel steps** become a pitfall on their predecessor, worded "A failed session
  diverged here to: <action>". The text is derived from the observed action, not generated.
- **`pending_edits`** is recomputed from the ledger on every run (replaced, not appended), so it
  always shows the current set of unapplied edits and stays bounded (50).
- **Rollback unit.** Each refinement run writes one `proc_match` row whose payload carries a
  snapshot of everything the run changed: root ledger, step and edge metadata before and after,
  created nodes, edges and provenance rows, deprecated steps and invalidated edges.
  `proc_create` rollback soft-deletes the root and its steps. Restores apply only where the
  current value still equals the recorded `after`; otherwise the item counts as a post-run
  modification and is skipped.
- **Eviction** folds per-item verdicts of evicted sessions into `evidence.evicted`. Their novel-step
  and transition observations are dropped, so `add_step` / `add_edge` support counts only the
  last `procedural_evidence_session_limit` sessions.
- **Dry run** skips the curation pre-flight, because the pre-flight can seed tenant rules, which is
  a write. The report says `"curation": "not_run_in_dry_run"`; the proposal text is returned only
  to the caller, who can already read the thread.
- **Concurrency.** Outside dry run, the pass locks the thread row (`SELECT … FOR UPDATE`, a no-op
  on SQLite) before reading its procedural cursor, so two concurrent extracts of one thread
  cannot both create a root.
- **Fact pass with no new messages.** The procedural pass still runs, because its cursor is
  independent.
- **`invariants`** run in the same transaction after flush: entry names a current step with no
  incoming `precedes`, no orphan step, step cap, then `resolve_procedure_entry` and
  `build_localized_subgraph`. If structural edits break them, the run is rolled back and re-run
  with structural edits recorded as `breaks_entry`; evidence and non-structural edits still
  land.

### Test record

- Unit (SQLite): `pytest tests/test_services/test_procedure_extraction.py` covers every item of
  the test plan above, including failure injection, idempotent re-runs, `tool_error` vs
  `procedure` failures, conflicts, inferred-only gates, propose and apply, hand-authored
  protection, the circuit breaker, rollback of creates and edits, and `off` mode.
- Integration (PostgreSQL + pgvector): `tests/integration/test_procedure_extraction.py`. Covers
  dreaming end-to-end to `resolve_procedure_entry` and `localized_guidance`, matching and
  refinement plus rollback, and failure injection on real transactions.

## Review follow-ups (2026-10-27)

A code review of the branch found two blocking issues and three more to fix
before the PR. All five are fixed; the reviewer's minor items are partly fixed
and partly recorded as follow-ups.

1. **Prompt injection through tool output (blocking).** Tool results are untrusted text, and
   #553 injects procedural guidance into other agents' context.
   - The prompt (v1.1) now states that the transcript is data, not instructions. The transcript
     is fenced in `<transcript>…</transcript>`, and the fence is neutralized inside message
     content.
   - Validation enforces a corroboration rule: an item is `observed` only when it cites at least
     one message the agent or user wrote (`tool_call`, `assistant`, `user`). This applies to
     steps, edges, pitfalls, conditions, guidance, the outcome and failure attribution. Text that
     only a tool result shows becomes `inferred`, so it never becomes a step and never reaches a
     render field.
   - The tiebreaker prompt carries the same rule.
2. **Lost evidence under concurrency (blocking).**
   - `evolve_procedure(lock=True)` takes `SELECT … FOR UPDATE` on the root and re-reads root,
     steps and edges (`populate_existing`) before updating the ledger.
   - Creating a new root first takes a transaction-scoped advisory lock on
     `(tenant, owner, scope, scope_id)`, then re-runs matching under the lock, reusing phase-A
     tiebreaker verdicts.
   - Two Postgres integration tests run two connections concurrently. Both fail with the locks
     disabled (one loses a session's evidence, the other creates two roots) and pass with them.
3. **No transaction while the model runs.** The pass now has two phases.
   - Phase A reads the trajectory, ends the read transaction, calls the model, runs the curation
     pre-flight (whose rule-seeding commit now happens before any lock) and matching. Matching
     does all its DB work first and releases the transaction before the tiebreaker.
   - Phase B takes the thread lock, re-checks the cursor (`processed_concurrently` when another
     run got there first), takes the scope or root lock, and writes.
   - A test asserts that no transaction is open during either model call.
4. **Candidates are not served as guidance.** `localized_guidance` refuses a step whose procedure
   is an extracted `candidate` (`ProcedureNotEstablishedError`; MCP: a `ToolError` that says so).
   - The check runs after the caller's read authorization, so it reveals nothing to a caller who
     cannot read the step.
   - `MEMORYHUB_PROCEDURAL_SERVE_CANDIDATES=true` restores the earlier behaviour.
   - Hand-authored procedures are unaffected.
   - Flat search still lists candidate memories; only the injected guidance path is gated.
   - This narrows the D7 sign-off ("candidates retrievable through #553 immediately"); that
     change needs operator confirmation.
5. **Rollback is all or nothing per decision.**
   - `rollback_procedural_decision` first verifies every recorded change is still as the run left
     it. If any item was modified since, nothing is touched (`skipped_modified`).
   - Undoing `proc_create` also closes the graph's active edges.
   - Every rollback lookup is tenant-scoped.

Minor items:

- **Fixed: `deprecate_step` rewires its neighbours.** A middle step is removed with
  `pred → succ` edges added (recorded in the snapshot), so it no longer orphans its predecessor
  and takes the run's other structural edits down with it.
- **Fixed: applied attributes keep their provenance.** Each attribute keeps the supporting
  threads' `source_messages` (`sources` per thread) and the run id.
- **Fixed: private CA.** `MEMORYHUB_PROCEDURAL_LLM_CA_BUNDLE` (a path) gives the procedural
  client a CA bundle with verification still on, for cluster endpoints behind a private CA.
- **Follow-up: cross-member matching in project scope.** Matching is still owner-scoped. Two
  members of a project build two copies of the same procedure. The reviewer's proposal (match
  other members' procedures, proposal-only like hand-authored ones) needs a design decision.
- **Follow-up: PR size.** The branch is still one series of commits; the split proposed in the
  PR notes stands.

## Second review round (2026-10-28)

Fixed after the second review:

- **`proc_create` rollback refuses once the graph moved on.** The decision records a fingerprint
  of the graph as it was created (`created_state`). Rollback compares it and returns
  `skipped_modified` when a later session or edit changed the root, a step or an edge. It does
  not delete evidence that other sessions added.
- **Promotion to `established` is apply-only.** In `propose` mode the ledger and counters still
  update, but status stays `candidate`. Once `established`, a procedure stays established. The
  promotion is not re-evaluated downwards.
- **`MEMORYHUB_PROCEDURAL_SERVE_CANDIDATES` stays `false`** (confirmed by the reviewer).
- The limitation "assistant corroboration is not proof of intent" is now listed under
  Limitations.

The follow-up issues drafted for the PR were resolved in this branch instead of being filed:

1. **`update_memory` on a procedure root kept its graph (bug).**
   - The new version's step copies keep `scope_id`, `content_type`, `source` and the actor and
     driver ids.
   - Active edges are re-pointed to the copies, and the entry step id is remapped.
   - Soft-deleted steps are not resurrected.
2. **memoryhub-local parity.**
   - The pure contract (transcript format, schema, parsing, validation with the corroboration
     rule) moved to `procedure_contract.py`. It exists byte for byte in core and in
     memoryhub-local, because neither package can import the other.
   - The system prompt is mirrored as a constant in `memoryhub_local.services.procedure_prompt`.
   - A parity test fails the build when either copy drifts.
   - `memoryhub dream --procedures` runs the pass locally. It is off by default, keeps its own
     cursor, writes only in the thread's own `user` or `project` scope, and does everything in
     one transaction.
3. **Validation gate for structural edits.**
   - Optional and fails closed; see D7.
   - The EvalHub-backed endpoint itself is not in this branch.
4. **Host recorders.**
   - `memoryhub thread record` maps Claude Code hook payloads to messages:
     - `UserPromptSubmit` becomes `user`.
     - `PostToolUse` / `PostToolUseFailure` become `tool_call` + `tool_result`, with `is_error`
       on failures.
     - `Stop` becomes `assistant`.
   - `memoryhub config init --record-trajectories` installs the async hooks.
   - `memoryhub thread outcome` writes the explicit outcome marker.
   - The opencode plugin records `chat.message` and `tool.execute.after` with
     `recordTrajectory.enabled`.
   - Both skip MemoryHub's own tools, redact common secret formats and never fail the host.
5. **Cross-member matching in a project.**
   - Candidates include every member's procedures in the same project (`scope_id`), still
     filtered by tenant in SQL.
   - The member's own procedure wins a tie.
   - A match on another member's procedure writes nothing to it. The session and its edits are
     recorded as a `proc_propose` with reason `foreign_owner`.
   - The scope lock for new roots is project-wide, so two members cannot race to create the
     same procedure.
