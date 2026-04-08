# Epic Review: Agent Memory Ergonomics

**Date:** 2026-04-08
**Effort:** Close out the agent-memory-ergonomics design concept — seven implementation candidates, three layers plus a real-time push pattern, all the supporting research files, the design doc itself, and the SDK / CLI / docs surface that came with them.
**Issues closed (in concept order):** #56, #57, #58, #59, #60, #61, #62 (plus #73 prep, #55 rename, and #46328d3 / #f315bd5 doc work folded in along the way).
**Issues filed during close-out:** #84, #85, #86, #87.
**Concept lifetime:** ~30 hours from `8c49102` (design doc lands) to `a57abbf` (#62 ships and the concept closes).
**Final commit:** `a57abbf` (#62: Ship Pattern E real-time push broadcast for swarm).

## The Concept

Memory-hub launched on 2026-04-03 with twelve MCP tools but no policy layer around them. The agent-memory-ergonomics concept doc was the first attempt to ask not "what tools does the system expose" but **"how does it feel to consume those tools as an agent."** The design doc identified two entangled problems:

1. **Response shape.** When `search_memory` returned, the agent had to mentally re-associate branches with parents, the stub-vs-full policy was undocumented, the response could blow up unbounded, and "give me an index, I'll drill in later" was impossible to express.
2. **Loading policy.** Tools without policy don't get used well. Every project hand-wrote its own "when to call memory-hub" rule. Some projects loaded everything eagerly. Others lazy-loaded after the first turn. Nobody knew what rebias meant in practice. The right answer was project-shape-dependent and the system gave no help.

The doc proposed a layered solution:

- **Layer 1** — fix the search response shape itself.
- **Layer 2** — give retrieval a sense of what the session is *about* via two-vector ranking.
- **Layer 3** — let projects declare their session shape in `.memoryhub.yaml`, generate the right rule file from a CLI, and stop hand-writing loading instructions.

Plus two extensions that emerged as the concept matured:

- **#61** — turn the per-session focus declaration into a stored usage signal so projects can answer "what have we actually been working on lately?"
- **#62 (Pattern E)** — when one agent writes a memory, push a notification to other connected agents instead of forcing them to poll. The active-swarm case the pull patterns can't address.

Seven candidates total, sketched as a single design doc on 2026-04-07 at the start of an intense 30-hour push.

## The Journey

The implementation didn't follow the design doc in a straight line. It was punctuated by mid-session pivots, scope expansions the user pre-authorized in flight, and at least three "the design said X but the implementation needed Y" moments that forced research-file rewrites. The story is worth telling in chronological order because the order is part of the lesson.

**Layer 1 (#56 + #57) — `5409a36`, 2026-04-07 morning.** Branch nesting, `mode: full | index | full_only`, `max_response_tokens` token-budget cap, `include_branches`. Both issues shipped in one commit because they touched the same surface. The most important call: **stub format stayed snippet-based, not topic-label-based.** The design doc has a long section pushing back on the topic-label proposal because the asymmetry between "agent skips a relevant memory" (silent failure) and "agent reads an irrelevant full memory" (visible waste) makes aggressive stubbing risky. That argument carried.

**Layer 2 (#58) — `754adfe` + `0f3b9bc`, 2026-04-07 afternoon.** This is where the design doc met its first real surprise. The brief expected to benchmark three cosine-blend ranking options (A/B/C from the original research file). Mid-session, the user dropped a deployed cross-encoder reranker (`ms-marco-MiniLM-L12-v2`) into the conversation. The original three options collapsed because they all assumed cosine-only blending. The session pivoted to a new four-way comparison: NEW-1 (RRF blend over cross-encoder rerank), NEW-2 (focus-augmented query), NEW-3 (cross-encoder alone), and the cosine baseline. **NEW-1 won decisively at `session_focus_weight ∈ [0.2, 0.4]`.** NEW-2 collapsed cross-topic recall by 37% and was eliminated. NEW-3 was roughly neutral on the synthetic corpus. The benchmark methodology stayed honest about uncertainty — the research file marked the original A/B/C analysis as historical and documented the new decision with empirical numbers rather than retrofitting the new winner into the old framing.

The numpy bug shipped on the first deploy. `_cosine_distance` propagated `numpy.float32` from real pgvector through to `relevance_score`, which Pydantic refused to serialize. Caught post-deploy by `mcp-test-mcp` end-to-end verification — not by the unit tests that had 100% line coverage. Fix shipped same session in `0f3b9bc` with a regression test. **The lesson — that mock-vs-real type boundaries are a systemic test gap, not a one-off — became the load-bearing rule for the next four candidates.**

**Layer 3 (#59 + #60 + #73) — `5edc821` + `420bdb5`, 2026-04-07 afternoon/evening.** The `.memoryhub.yaml` schema, the CLI generator, the per-pattern rule templates. #73 was the prep commit that surfaced `mode`/`max_response_tokens`/`include_branches` on the SDK so the schema had something to consume. #59 added the schema and loader. #60 added `memoryhub config init` with templates for Patterns A/B/C/D. The forks that mattered: **focus inference belongs in the SDK, not the server** (Q3 resolution — server only sees the final string), and the migration path for existing rule files was **replace-with-backup, not merge** (Q4 — freeform markdown is too hard to reconcile mechanically). Both shipped in single sessions by pre-authorizing the forks at session start.

**Doc refresh + #55 rename + concept-close attempt #1 — 2026-04-07 evening.** The user asked "are SYSTEMS.md and ARCHITECTURE.md up to date with what we've shipped?" The honest answer was no — four subsystems (SDK, CLI, UI, auth) were running but absent from the inventory. Scope expanded to a full repo doc refresh (`31fb079`), then to the #55 server-side package rename (`b89b7eb`) which had been parked for a week, then to CONTRIBUTING + NOTICE + kagenti accuracy (`f315bd5`). **Every expansion was user-initiated and the work was ready.** The 2026-04-07 evening retro framed this as the concept "almost closing" — six of seven candidates landed, with only #62 outstanding behind a Q7 spike against FastMCP 3.

**#61 (session focus history as a usage signal) — `2447f95`, 2026-04-07 night.** Two new MCP tools backed by a single-pod Valkey 8 deployment. The interesting design call: **advisory-only.** The histogram is a readable usage signal. Humans and agents consume it informationally. The original #61 body raised three feedback-mode options (periodic batch tuning, inline retrieval bias, advisory-only); the session went with advisory-only to ship cleanly without the empirical justification the other options would have required. Two key prefixes: `memoryhub:sessions:<session_id>` (active hash, TTL) and `memoryhub:session_focus_history:<project>:<yyyy-mm-dd>` (per-day list, 30-day retention). **The schema was deliberately designed so #62's broadcast filter could read the active-session vector without re-embedding** — a piece of foresight that paid off the next day.

The interim session model — `session_id = JWT sub claim` — was documented as "interim" in the #61 close-out. It solved the immediate "one session per user" need without forcing a JWT shape upgrade. We knew it would need fixing when multi-concurrent-session-per-user became a real use case. We didn't know that case would arrive the next morning with #62.

**#62 (Pattern E real-time push) — `a57abbf`, 2026-04-08, today.** The session opened with the Q7 spike against FastMCP 3.2.0's source. Q7 came back UNBLOCKED on first read: `ensure_subscriber_running` is idempotent and decoupled from task submission, so `register_session` could call it directly. **But the same spike turned up something the research file didn't catch** — `_send_mcp_notification` hard-codes a method whitelist that raises `ValueError("Unsupported notification method for subscriber")` for anything other than `notifications/tasks/status`. FastMCP's built-in subscriber pipeline is single-purpose for task status events and would silently drop memory-hub's `ResourceUpdatedNotification`.

This was a **real fork** — the research file's "reuse FastMCP's distributed notification queue directly" recommendation was wrong. Two options surfaced: (1) memory-hub owns its own parallel Valkey-backed pipeline (full design fidelity, ~370 LoC larger), or (2) in-process session registry with direct dispatch (adequate for single-pod scale, ~80 LoC, no cross-pod story). The user picked Option 1 for design fidelity and to keep the YAML knob honest. Phases 1-5 shipped end-to-end:

- ValkeyClient gained six new helpers and two new key prefixes (`memoryhub:active_sessions`, `memoryhub:broadcast:<session_id>`).
- `push_broadcast.py` and `push_subscriber.py` cloned FastMCP's reference subscriber loop verbatim but method-agnostic.
- `register_session` got `_start_push_for_session` wired into both auth paths with `_exit_stack` cleanup.
- `write_memory` / `update_memory` / `delete_memory` got a post-commit broadcast hook with a fast-path skip when no other subscribers are listening.
- The SDK got `MemoryHubClient.on_memory_updated(callback)` opt-in via `live_subscription`.

The full-content notification path shipped server-side but is **deferred client-side** because the typed Python SDK can't deserialize custom-method notifications against the closed `ServerNotification` Pydantic union. That's now #87.

## What Shipped — What Users Can Now Do

The concept's outcome is best measured by what consumers of memory-hub can express that they couldn't before.

**Search ergonomics (Layer 1).** Agents can request `mode: index` for an exploratory "what's in here?" pass, get nested branches when they want them, and trust that responses will fit in a token budget. Branch handling is no longer a manual re-association step.

**Focus-aware retrieval (Layer 2).** Agents can pass `focus="auth token rotation"` per call and get retrieval biased toward that topic without losing cross-topic recall when the immediate query is strong enough. The cross-encoder reranker is wired through with a graceful cosine fallback when it's unreachable. Server-side pivot detection fires when the query and focus diverge enough to suggest the conversation has moved on.

**Per-project loading policy (Layer 3).** A single `memoryhub config init` walks the project through three or four questions and generates a coherent `.memoryhub.yaml` plus a hand-readable rule file. Projects no longer hand-write their own loading instructions. Patterns A/B/C/D each have a complete template. The SDK applies `retrieval_defaults` to outbound `search_memory` calls automatically.

**Usage signal as data (#61).** Projects can answer "what has this team been focused on for the last 30 days?" by calling `get_focus_history` and getting a sorted histogram. The signal is advisory-only — no auto-tuning, no surprise weight adjustments — but it's actionable for humans and agents who want to understand drift.

**Real-time swarm coordination (#62).** When one agent writes a memory, other connected agents receive a `ResourceUpdatedNotification` without polling. Composes with any of the pull patterns rather than replacing them. Opt-in via `memory_loading.live_subscription: true`. Single-session deployments pay zero overhead because the broadcast helper short-circuits when there are no other subscribers.

## What Changed Along the Way

| Change | Type | Rationale |
|---|---|---|
| Cross-encoder reranker dropped into the #58 session mid-flight, collapsing the original Options A/B/C design space. | **Good pivot** | The user had deployed it precisely for this work. Surfacing it as a sixth fork ("here are three new variants + baseline; here's my pick; confirm") let the design space pivot cleanly in one pass. The new four-way comparison was tighter than the original 3 × 5 weight sweep. |
| #58 shipped focus as **stateless per-call**, not stored on `register_session`. | **Good pivot** | Avoided every coordination/scaling question. Stored focus came back as an opt-in via #61's `set_session_focus`, then became the substrate the #62 broadcast filter reads — additive composition, three layers of state, none disturbing each other. |
| #58's `numpy.float32` leaked into production on the first deploy. | **Real bug, caught post-deploy** | Mock-vs-real type boundary. 100% line coverage in unit tests. Caught only because `mcp-test-mcp` ran a focus-path call against the deployed server. Fix shipped same session. **Became the load-bearing argument for verify-on-every-deploy as a hard rule.** |
| Layer 3 session expanded from "land #59/#60/#73" to "land Layer 3 + full doc refresh + #55 rename + CONTRIBUTING + kagenti accuracy + #83 filed." | **Good pivot** | Every expansion was user-initiated ("are docs up to date?" "what about CONTRIBUTING?" "is kagenti accurate?"). Work was ready in each case. The natural concept-closing boundary was the right time to clear the deck. |
| Concept "closed" three times. First close was Layer 3 + #55. Then #61. Then #62. | **Inherent shape, not a problem** | The "concept" is a design doc, and the design doc grew capabilities (#61, #62) that weren't in the v1 candidate list. Each close was honest at the time. The retro doc trail shows the evolution rather than papering over it. |
| #62's Q7 spike came back UNBLOCKED, then surfaced a separate blocker (`_send_mcp_notification` method whitelist) the research file didn't anticipate. | **Research file was wrong** | The research file said "reuse FastMCP's distributed notification queue." That recommendation was based on `ensure_subscriber_running`'s only existing caller (task submission) being mistaken for the only possible caller. The function itself is reusable; the helper that calls it (`_send_mcp_notification`) is not. The research file gained an "Implementation Notes 2026-04-08" section preserving the original analysis and explicitly marking the divergence rather than silently rewriting it. |
| #62 Option 1 vs Option 2 fork (own pipeline vs in-process registry). | **Real architectural fork** | The user picked Option 1 for design fidelity even though Option 2 was ~370 LoC smaller and adequate for current scale. The reasoning (don't ship a degraded version of what the research file described, keep the YAML knob honest, cross-pod fanout from day one) held. The fast-path skip in `broadcast_after_write` keeps the runtime cost zero in the common single-session case anyway. |
| Full-content notification shipped server-side but deferred client-side. | **Scope deferral** | The typed Python SDK's underlying `mcp` library deserializes against a closed `ServerNotification` union with no slot for vendor-prefixed methods. URI-only is spec-compliant and works for memory-hub's first real consumer. Filing #87 for the upstream-or-workaround discussion when a real consumer needs full-content delivery. |
| `session_id = sub` interim model from #61 became visible as a constraint in #62. | **Inherited limitation** | Single-user-multi-instance: actually nice noise reduction (your other Claude windows don't get pinged by your own writes). Multi-agent-same-user swarm: real correctness gap. Filed as #86 with explicit "swarm-blocker" framing. Local change to two tool files when the time comes. |

## What Went Well

- **Tests grew honestly.** ~+180 net new tests across the seven candidates: `memory-hub-mcp` 127 → 172 (**+45**), root services/models 108 → 178 (**+70**), `sdk` 38 → 76 (**+38**), `memoryhub-cli` 0 → 27 (**+27**, new suite), BFF 39 (unchanged — confirms BFF stays out of search/write tool changes). Every delta was a real test exercising real code, not baseline drift.
- **Forking pattern with announce-and-proceed scaled across seven candidates.** Every session that touched the concept used the same loop: surface forks at start, lock them in one pass, execute the agreed scope without re-confirming, pause only on genuine mid-session surprises (cross-encoder, FastMCP whitelist). The pattern is now muscle memory.
- **Save-before-deploy held perfectly across every candidate's deploy.** Five learning memories saved before #58's deploy. Five before #62's. Zero lost-memory incidents. The `feedback_deploy_invalidates_mcp_session.md` rule did its job every time.
- **Same-commit consumer audit caught zero bugs and produced lots of structural knowledge.** The audit was negative for every shape change in the concept. As a side effect it surfaced (and recorded in memory `cf907154`) that BFF talks to the database via raw SQL not through the SDK, that CLI is tier-1 for tool shape changes, and that memoryhub-auth is fully self-contained. The habit is muscle memory and pays dividends beyond bug-catching.
- **mcp-test-mcp post-deploy verification caught the only real production bug** (numpy.float32 in #58) and confirmed the only end-to-end success criterion that mattered for #62 (SADD on register, SREM on disconnect). It's now a hard rule, not a "should."
- **The research files are now honest.** When the design space changes mid-session (cross-encoder for #58, FastMCP whitelist for #62), the research files get an "Implementation Notes" section preserving the original analysis and explicitly marking the divergence. No silent rewrites. Future-me reading the research file will see both the original prediction and what actually happened.
- **Stateless-where-possible** held as a discipline across all three layers of state introduced by the concept. #58 made focus stateless per-call. #61 added stored focus as an opt-in tool. #62 added push lifecycle as another opt-in (`live_subscription: false` default). Each layer composes additively. None disturbs the layer below.
- **The design doc itself stayed authoritative.** Every candidate that shipped updated `docs/agent-memory-ergonomics/design.md` with a `[SHIPPED · #N]` marker and a paragraph describing what actually landed. The doc reads as the canonical record of the concept rather than as a stale plan. The "What Shipped" section above could be written entirely from the design doc without consulting any other source.
- **Per-session retros built up consolidatable signal.** Six retros from 2026-04-07 alone, plus today's. The retro discipline is mature enough that the concept-close retro can reference earlier retros rather than re-litigate them. `/retro --review-patterns` would now have 19+ retros to consolidate.

## Concept-Close Patterns

This is the first retro in the project to span a multi-session, multi-day **design concept** rather than a single-feature implementation. A few patterns emerged that don't fit any single-session retro:

**1. Concepts close more than once, and that's fine.** The agent-memory-ergonomics concept "closed" three distinct times: when Layer 1+3 + #55 landed (the 2026-04-07 evening retro), when #61 landed, and finally today when #62 landed. Each close was honest at the moment it happened — the candidate list grew as the design matured. The right move was to write a retro at each closing rather than wait for the "real" close. The retro trail shows the evolution.

**Lesson:** when a design doc is alive and the candidate list is growing, retro at each shipping milestone. Don't wait for the "final" close — there may not be one, and even if there is, the intermediate retros capture context that's stale by then.

**2. The design doc IS the concept's source of truth — research files are tactical.** The design doc evolved alongside the implementation: every candidate that shipped added a SHIPPED marker and a paragraph. The research files (`research/two-vector-retrieval.md`, `research/fastmcp-3-push-notifications.md`) gained "Implementation Notes" sections marking divergence from the original analysis. The pattern is **design doc tracks state, research files track journey.** When the journey diverges from the original research, the research file gets an explicit divergence note rather than a silent rewrite. Future readers see both.

**Lesson:** for multi-session concepts, the design doc must be a living document that the implementation continuously updates. The research files preserve the analysis trail. Neither one should be touched in a way that erases history.

**3. Cross-cutting infrastructure earns its keep across multiple candidates.** Valkey arrived with #61 to back session focus history. The schema was deliberately designed so #62's broadcast filter could reuse the active-session hash without re-embedding. That single design decision is what made #62's "no re-embedding" guarantee possible the next morning. **Cross-cutting infrastructure pays off most when it's designed with multiple candidates in mind, even if only one is ready to ship.** The temptation to design narrowly for the immediate candidate is real and would have cost an extra round-trip per broadcast in #62.

**Lesson:** when introducing infrastructure (Valkey, the cross-encoder reranker, the consumer audit) as part of one candidate, ask "what other candidates in the same concept could benefit?" and shape the schema or interface to serve them.

**4. Multi-session forks need a "session-level brief" not just a "candidate-level brief."** Every session in this concept opened with a `NEXT_SESSION.md`-style brief that pre-identified forks at session start, set scope, and named the explicit "save before deploy" / "verify on deploy" disciplines. The discipline of writing the brief at the END of each session for the NEXT session was load-bearing. The 2026-04-07 evening session's brief made today's #62 session work because it captured the Q7 spike status, the Valkey schema decisions, the consumer audit tier list, and the exact open forks before context was lost.

**Lesson:** for multi-session efforts, end every session by writing the next session's brief. Capture the forks, the in-progress state, the gotchas, and the explicit "do this first" steps. The brief is not optional documentation — it's the protocol for surviving context loss between sessions.

**5. Per-user vs per-session identity matters more than it first appeared.** The `session_id = sub` interim from #61 looked like a small note at the time. By #62 it had become a real architectural constraint visible in the broadcast filter. It's now #86. **The pattern: interim decisions that affect downstream candidates need explicit forward pointers in the retro of the candidate that introduced them, not just in the design doc.** The #61 retro documented it; the #62 implementation re-encountered it; the concept-close retro consolidates it.

**Lesson:** when a candidate ships with a documented interim limitation, the retro should explicitly name which downstream candidates will inherit that limitation. Future-me reading the retro should not have to discover the inheritance by stubbing toes.

**6. The "research file is not authoritative" pattern.** At least three candidates discovered that the research/design file was wrong or stale once implementation started. #58's cross-encoder pivot. #62's Q7 was "blocked" but turned out to be unblocked, AND the real blocker — the FastMCP method whitelist — wasn't in the research file at all. The Layer 1 stub-policy section had a similar moment where the research's "topic-label stubs" framing got rejected during implementation in favor of snippet-based stubs. **The research file is a starting point; the implementation finds the real shape.**

**Lesson:** treat research files as the analyst's first sketch, not as a contract. Implementation will find things the analyst missed. The right habit is to update the research file with an "Implementation Notes" section the moment the divergence is found, not at session end.

**7. Multi-session efforts need a separate "epic review" cadence.** The per-session retros are tactical: what went wrong, what to improve, what to start/stop/continue. They're invaluable but they don't tell the story of the concept as a whole. This concept-close epic review is a different shape — it tells the journey, names what shipped to users, and identifies what the concept enables next. **Per-session retros and concept-close epic reviews serve different audiences and should both exist.** A reader picking up the project six months from now should be able to read this epic review and understand what agent-memory-ergonomics is, what it delivered, and why it was worth doing.

**Lesson:** reserve "epic review" framing for concepts that span multiple sessions and ship a coherent set of capabilities. Use the standard retro format for single-session work.

## Gaps and Follow-up Issues

| Gap | Severity | Resolution |
|---|---|---|
| **Embedding service 413 limit on long memory content.** Recurring across multiple sessions including today's. The MemoryHub embedding service returns 413 when content exceeds the model's max sequence length. Currently the only signal is the raw 413 error. | Recurring | **Filed as [#84](https://github.com/rdwj/memory-hub/issues/84)** — needs a design call between truncate/chunk/hard-cap. |
| **Integration test coverage for `search_memories_with_focus` (carry-forward from #58 retro) extended to push broadcast paths from #62.** Both code paths are unit-test-only today. The numpy.float32 bug shipped despite 100% line coverage; the same class of bug could surface in the push pipeline. | Process | **Filed as [#85](https://github.com/rdwj/memory-hub/issues/85)** — pgvector + Valkey integration tests, no infrastructure work needed. |
| **`session_id = sub` interim model.** Inherited from #61, exposed in #62's broadcast filter. Single-user-multi-instance is desirable noise reduction; multi-agent-same-user swarm is a correctness gap. | Inherited | **Filed as [#86](https://github.com/rdwj/memory-hub/issues/86)** — local change to two tool files when the swarm use case becomes real. |
| **Full-content notification receive-side.** Server-side ships in #62 but the typed Python SDK can't receive custom-method notifications because `mcp.types.ServerNotification` is a closed Pydantic union. URI-only is spec-compliant and works. | Deferred | **Filed as [#87](https://github.com/rdwj/memory-hub/issues/87)** — upstream `mcp` library issue or downstream raw transport subscriber. |
| **Q9 (push fanout cost at scale).** Not actionable until a real swarm deployment exists to benchmark against. The `open-questions.md` entry is the right home for this; no GitHub issue needed. | Watch | Stays as a note in `docs/agent-memory-ergonomics/open-questions.md` Q9. Revisit when a real swarm lands. |
| **Demo scenarios retro carry-overs from 2026-04-07** (4 domain curation pattern issues, synthetic-name cross-check, SME validation outreach, "data ownership" framing lift). | Carry-forward | Not concept work — separate effort. Documented in `retrospectives/2026-04-07_demo-scenarios-and-identity-model/RETRO.md`. Pick up when the concept-close hangover settles. |
| **`#83` memoryhub-ui deploy script gotcha** (no `oc rollout restart`, image digest pinning). | Carry-forward | Already filed in 2026-04-07 evening retro as #83. Not a concept item. |
| **Pre-existing untracked `docs/auth/`, `docs/identity-model/`, `demos/scenarios/` directories** + dirty `.claude/skills/issue-tracker.md`. | Process | Carry-forward from 2026-04-07 evening retro. Not concept work but clutters every `git status`. Worth resolving in a housekeeping pass. |

## Action Items

- [x] Save concept-close memories before deploy (#62 ship summary, FastMCP method whitelist, full-content limitation, broadcast self-exclusion invariant)
- [x] Update `docs/agent-memory-ergonomics/design.md` Candidate 7 with SHIPPED marker
- [x] Resolve open questions Q6, Q7, Q8 in `docs/agent-memory-ergonomics/open-questions.md`
- [x] Update `research/agent-memory-ergonomics/fastmcp-3-push-notifications.md` with Implementation Notes section
- [x] Deploy #62 to OpenShift and verify end-to-end via `mcp-test-mcp`
- [x] Close #62 with detailed close-out comment matching #61 style
- [x] File [#84](https://github.com/rdwj/memory-hub/issues/84), [#85](https://github.com/rdwj/memory-hub/issues/85), [#86](https://github.com/rdwj/memory-hub/issues/86), [#87](https://github.com/rdwj/memory-hub/issues/87) for follow-up work
- [x] Write this concept-close epic review
- [ ] Run `/retro --review-patterns` after this retro lands — 20+ prior retros is enough signal to consolidate cross-concept patterns
- [ ] Decide what's next: tenant isolation (#46) is the next-major-design-item; alternative is the demo scenarios retro carry-over items if the user wants to consolidate the "make memory-hub demo-able" thread

## What This Enables Next

- **Tenant isolation (#46) is the next major design item.** Memory-hub now has the agent-side ergonomics story complete; the next layer is the multi-tenant story. Cross-tenant memory isolation, per-tenant curation rules, audit boundaries. The `agent-memory-ergonomics` concept established the patterns (advisory-only, opt-in, additive composition) that #46 will inherit.
- **Kagenti integration phase 2 unblocks.** The original kagenti integration design pointed at MemoryHub as the memory layer for kagenti's agent swarms. Pattern E push (#62) is what makes that workable — without it, swarm agents would have to poll. Real swarm deployment is now mechanically possible (modulo the #86 session_id upgrade for the multi-agent-same-user case).
- **Demo scenarios get a new story to demo.** The 2026-04-07 demo scenarios retro shipped five domain scenarios. Pattern E adds a sixth: "swarm coordination via real-time memory broadcast." Worth a demo update at some point.
- **The concept doc is now a reference, not a plan.** Future contributors landing on `docs/agent-memory-ergonomics/` will read it as documentation of what shipped, not as a roadmap of what's coming. The seven candidates are all marked SHIPPED. The open questions are all resolved or explicitly deferred. The concept is closed. Time to start the next one.

## Patterns

**Start:**
- Writing concept-close epic reviews (this format) for multi-session efforts. Per-session retros stay tactical; epic reviews tell the story.
- Designing cross-cutting infrastructure with multiple downstream candidates in mind, even if only one is ready to ship.
- Adding "Implementation Notes" sections to research files at the moment of divergence, not at session end.

**Stop:**
- Treating research files as authoritative once implementation starts. They're starting points, not contracts.
- Treating "the concept will close in one session" as a working assumption for multi-session efforts. Plan for multiple closes.

**Continue:**
- Forking-then-announce-and-proceed within agreed scope.
- Save-before-deploy memories for any risky operation that could invalidate the MemoryHub session.
- `mcp-test-mcp` post-deploy verification on EVERY deploy, even when unit tests are green.
- Same-commit consumer audit on every tool shape change.
- Updating the design doc with SHIPPED markers as each candidate lands.
- Per-session retros AND concept-close epic reviews — different audiences, different purposes, both worth writing.
- Reading the project-local `/deploy-mcp` slash command first, never invoking the template default.
