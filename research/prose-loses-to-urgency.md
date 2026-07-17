# Prose Loses to Urgency: Field Notes on Controls Engineering for Agents

**Date:** 2026-07-17
**Provenance:** distilled from a two-week, ~20-session engineering effort
executed almost entirely by coding agents (benchmark and pipeline work on
an agent-memory platform), during which process rules were written,
violated, amended, and progressively mechanized — with every violation
and every hold documented in session summaries and reconciliations. The
value of the case study is that the enforcement record is complete: we
can say which rules held, which lost, to what force, and what fixed them.

---

## 1. The observation

The project ran on written rules: a constitution file loaded into every
agent session, per-session plans with constraints, and standing process
rules. Compliance was good — but not uniform, and the non-uniformity had
structure:

| Rule (prose form) | Violations | Lost to | Eventual enforcement layer |
|---|---|---|---|
| Investigation sessions are read-only | 0 in 3 sessions | — | stayed prose (held) |
| Exit predicates close issues, or get amended first | 2 early, ~0 after adoption | schedule pressure | prose + close ritual (held after being made a named rule) |
| Verify capability claims before propagating | 8 incidents | convenience of assumption | tripwires: inline citations required, preflight checks, audit docs |
| All pushes to main via PR | 2 incidents | **urgency, both times** | repository settings (mechanically impossible) |
| Surfaced limitations get written down | 1 (a surfaced product gap became unreconstructable in 48h) | "it didn't block anything" | rule amended: "surfaced means written" + issue-filing gate |
| Credentials never in documents | 1 (live key committed to a public repo) | none — pure oversight | secret-scanner pattern + standing rule + scrubbing protocol |
| Don't run benchmarks on unverified config | repeated silent failures (wrong corpus, truncated content, capped k) | invisibility, not pressure | enforced preflight manifest: run refuses to start on mismatch |

Two patterns fall out immediately. First, the rules that lost to
*urgency* specifically (direct-push) were rules whose compliance cost
spiked at exactly the moment the rule mattered most. Second, the rules
that failed *silently* (benchmark config, capability claims) weren't
losing to pressure at all — they were losing to invisibility, and needed
detection, not willpower.

## 2. The discriminator

Prose holds when two conditions are met simultaneously:

1. **Compliance is cheap** at the moment of decision, and
2. **The rule is salient** at the moment of decision.

Prose loses when either fails — and urgency is uniquely destructive
because it attacks both at once: it raises the perceived cost of the
compliant path ("the cluster test is running NOW") and crowds the rule
out of attention. A rule whose enforcement depends on the actor's state
of mind will fail precisely when the actor's state of mind is the
problem.

**The core principle: a control's enforcement mechanism must be
independent of the pressure that tempts its violation.** A branch
protection setting does not experience urgency. A preflight gate does
not find the assumption convenient. A secret-scanner does not get tired
at the end of a long session.

## 3. Agents break rules differently than humans

Human rule-breaking is usually motivated — someone weighs the rule and
decides against it. Agent rule-breaking, observed across this project,
is almost never that. It is **salience decay**: the rule entered context
forty thousand tokens ago; an urgent framing reorganized the agent's
priorities; a compaction dropped the nuance; a subagent never saw the
rule at all. The agent that violated branch protection cited a memory
that *used to be true* and had been superseded. The agent that skipped
writing down a surfaced limitation complied with the letter ("surface
it") while the intent ("make it actionable later") decayed.

This reframes agent compliance as a **memory phenomenon**. Which yields
the central duality of the field:

- **Memory systems** attack the problem from one side: keep the right
  prose salient at the right moment (session-start injection, weighted
  policies, retrieval at decision time).
- **Controls engineering** attacks it from the other: make the important
  invariants not depend on salience at all.

You need both, and they are not redundant: machinery can only enforce
*anticipated* rules. Salient prose is how agents handle the
unanticipated cases well — it trains judgment, carries rationale, and
covers the space between the gates. The design question for any given
rule is which layer it belongs in *today*, and when to migrate it.

## 4. The enforcement ladder

Rules migrate downward through four layers as violation evidence
accumulates:

1. **Prose** — the constitution, design docs, session constraints.
   Carries the *why*. Cheap to write, degrades under pressure and
   context distance.
2. **Protocol** — checklists executed at known moments (session-start
   premise checks, close rituals). Converts salience from ambient to
   scheduled: the rule doesn't need to be remembered, only the ritual.
3. **Automated check** — detection and gating: preflight manifests that
   refuse to run on config mismatch, secret scanners, staleness checks
   ("is any session summary newer than this plan?"), honesty flags on
   degraded output, decision logs, parameterized parity tests.
4. **Setting** — mechanical impossibility: branch protection, permission
   boundaries, schema constraints. Holds always; encodes nothing about
   why; ossifies if overused.

**Migration trigger — the two-strikes heuristic:** the first violation
of a rule might be noise; the second is data about where pressure
concentrates. Mechanize on the second strike. Mechanizing speculatively
(before any violation) fails in the other direction: gate fatigue,
ossified process, and the classic death spiral where one flaky required
check teaches everyone to bypass all checks. This project's flaky-test
lesson: only stable checks may be required, or the control destroys
itself.

## 5. Design principles extracted

- **Enforcement independence** (Section 2): the mechanism must not share
  the actor's pressure. Corollary: any control implemented as "the agent
  will remember to..." is a layer-1 control regardless of how firmly it
  is phrased.
- **Friction asymmetry, never lockout:** make the routine path cheap and
  the violation path *deliberate* — but keep an escape hatch that
  requires stepping visibly outside the flow (an admin settings edit),
  because a control with no escape hatch gets removed the first time it
  blocks legitimate work. (Design detail that mattered: sole-operator
  repos must use PR-required-with-zero-approvals — enforcement WITHOUT a
  self-approval deadlock. Controls that can deadlock their sole operator
  are controls that get turned off.)
- **Detective before preventive where uncertainty is high:** when you
  don't yet know the failure modes, visibility beats gates. Honesty
  flags ("this content is truncated"), decision logs, and manifests
  recorded into results converted an entire class of silent failures
  into observed events — and the observed events then justified the
  preventive controls.
- **Exit predicates as contracts:** every unit of delegated work carries
  a deterministic done-condition, and the standing rule "close on a met
  predicate, or amend the predicate in writing first" makes scope
  pressure visible instead of silent. This held as prose because it is
  cheap and scheduled (checked at close ritual) — evidence that layer
  assignment, not rule importance, predicts survival.
- **Circuit breakers as bounded autonomy:** timeboxes, max-iteration
  caps, and stop-and-surface conditions written *at planning time*, when
  judgment is cheap, so the executing agent inherits boundaries rather
  than improvising them under pressure.
- **Surfaced means written:** an observation that exists only in a
  session transcript is not surfaced; it is temporarily visible. If it
  can't be acted on without the original context, it doesn't count.
- **Maker ≠ checker:** verification independent of execution — a
  reviewer role auditing session outputs against plans caught material
  errors (wrong attributions, stale claims, overclaimed projections)
  that the executing agents, and the sole human, each missed alone.

## 6. Measurement: controls are benchmarkable

Whether a control holds under pressure is an empirically testable
property of an agent system, and most agent benchmarks cannot see it —
they score affirmative task completion, under which an agent that fires
three unnecessary irreversible actions and an agent that correctly
dissolves all three through investigation can score identically.

The task classes that measure control-holding:

- **Restraint tasks:** the correct outcome is to NOT act (don't file the
  issue, don't re-run the destructive command). Binary, judge-free
  ground truth; memoryless/ruleless agents have no reason to hesitate,
  so the class isolates the control's contribution cleanly.
- **Correction tasks:** the request conflicts with a standing rule or
  stored decision; the agent should surface the conflict, not silently
  comply or silently override.
- **Escalation tasks:** the rule says "stop and ask a human at this
  boundary"; did the agent stop?
- **Reliability under repetition:** score pass^k across repeated trials,
  not single-run success — a control that holds three runs in four is a
  failing control.
- **Attribution requirement:** a correct behavior only counts if the
  trace shows the rule/memory was retrieved and applied; correct
  behavior in the control-absent baseline disqualifies the task as
  non-discriminating.
- **Seed tasks from real incident ledgers,** not synthetic vignettes:
  a project's own violations, paired with the documented correct
  behavior, are labeled ground truth with realism no simulator matches.

## 7. Incident ledger (the evidence, condensed)

| Incident class | Count | Control adopted | Layer |
|---|---|---|---|
| Unverified capability claims propagated (own system, infra, third-party, competitors) | 8 | verify-before-propagating rule + inline-citation requirement + capability audit docs | 2-3 |
| Direct push to main under urgency | 2 | branch settings: PR-required, approvals=0, admin-enforced, stable checks required | 4 |
| Silent benchmark misconfiguration (wrong corpus / truncated content / capped k) | 3+ | enforced preflight manifest; refuses to run on mismatch; manifest recorded in results | 3 |
| Credential in committed/public artifact | 2 | scanner patterns incl. project key format + standing rule + storage-location-reference convention | 3 + 1 |
| Surfaced-but-unwritten product gap | 1 | "surfaced means written" corollary; issue-filing as the definition of surfaced | 1-2 |
| Parallel-session redundant work (stale plan) | 1 | plan-staleness premise check at session start | 2 |
| Constitution edited as a side effect (ghost law) | 1 | "constitution changes require a dedicated, human-approved PR" | 1 -> 4 candidate |
| Sole-operator lockout risk (from our own proposed control) | 1 (caught in design) | zero-approval PR requirement; friction asymmetry principle | design rule |

The ledger reads as a progression: every control at layer 3-4 today
started as prose, earned its migration through documented failure, and
left the prose in place to carry the rationale. That is, we suggest, the
healthy end state for agent-operated systems: **agents follow written
rules most of the time; settings follow them all of the time; and the
written rules remain because they explain the settings and cover what
the settings cannot anticipate.**
