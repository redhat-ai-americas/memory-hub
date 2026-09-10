---
name: plan-epic
description: Plan or revise the multi-session arc for ONE epic. Decomposes the epic into phases with explicit definitions-of-done, dependency gating, and ordering. Writes the "Remaining epic phases" section of NEXT_SESSION-{epic}.md (without touching the "Next session" slice that /plan-next-session owns). Use when starting a new epic, re-planning an in-flight one, or formalizing an ad-hoc multi-session arc.
---

# Plan Epic

A dialogue-driven planning step for the multi-session arc of one epic. The
output is the structured "Remaining epic phases" section of
`NEXT_SESSION-{epic}.md` — sequenced phases, each with a clear definition
of done, dependencies, and external-wait notes.

This is **epic-arc planning**, sibling to `/plan-next-session` (one session
within an epic) and `/plan-epics` (portfolio across epics). The split:

- `/plan-epics` — "which epic should we push?"
- `/plan-epic <name>` — "lay out the arc for THIS epic" *(this skill)*
- `/plan-next-session [epic]` — "pick what THIS session does within an epic"

Use this skill when:

- **Starting a new epic** — there's no `NEXT_SESSION-{epic}.md` yet, or it
  exists only as a single-session slice. Lay out the arc so the next 3–7
  sessions have a coherent target.
- **Re-planning an in-flight epic** — phases have shifted, dependencies
  changed, a designer answer reframed the work. Rewrite the arc.
- **Formalizing an ad-hoc multi-session arc** — like today's
  `NEXT_SESSION-bedrock.md` Phases 1–7, which got authored without a skill
  behind it. Run this to canonicalize the structure.

## Invocation

```
/plan-epic <epic-name>
```

Epic name is a **required arg** (lowercase, hyphen-separated). The skill
operates on `NEXT_SESSION-{epic}.md` in the project root. If no file
exists, the skill bootstraps one.

Optional second arg: `/plan-epic <name> --review` skips Phase 1
(decompose) and goes straight to reviewing the existing phases for
staleness — useful when an in-flight epic needs a quick refresh, not a
full re-decompose.

## Where the file lives

Project root, **tracked in git by default**, one file per epic. Same convention as
`/plan-next-session`. See that skill for filename convention details
(hyphen vs underscore separator, naming conventions). Projects may override
this at the project level to keep planning files untracked if preferred.

This skill writes ONLY the "Remaining epic phases" section. The
"Next session" slice + rolling "What landed" ledger are owned by
`/plan-next-session`. If the file doesn't exist yet, this skill creates
a minimal scaffold with a `## Next: <to be planned via /plan-next-session>`
placeholder for the next-session slice.

## Workflow

The skill runs in five phases. **Each phase is a conversation, not a
report.** Surface findings, then wait for the user's input before moving
on. Do not write the artifact until Phase 4.

### Phase 0: Gather context (silent)

Before the dialogue starts, collect:

1. **Existing epic file** — read `NEXT_SESSION-{epic}.md` if present.
   Note the existing "Remaining epic phases" section (if any) as the
   baseline to revise.
2. **Tracking issues** — search GitHub for issues labeled `tracking`,
   `epic`, or with titles matching the epic name. These are usually the
   parent issues that decompose into the phases. Also surface any open
   issues whose body or recent comments mention the epic.
3. **Recent commits** — `git log --oneline --since="<inferred from
   epic file mtime>"` or last 60 days. Identify which commits touched
   files that belong to this epic's area (rough heuristic: paths
   mentioned in the existing file, or owned by the tracking issues).
4. **Design-call answers** *(only if the project uses the design-call
   pattern)* — `ls design-docs/` for answer files or call docs related to
   this epic. These often gate phases.
5. **Other epic files** — `ls NEXT_SESSION*.md`. Note which exist and
   skim their summaries; the user may want to flag cross-epic
   dependencies in Phase 2.

Summarize Phase 0 findings in a short "here's what I see" opener (≤15
lines) before starting Phase 1.

### Phase 1: Decompose into candidate phases

Dialogue. The goal is to enumerate the work units that constitute the
epic, framed as phases that could each be a session (or part of one).
Don't worry about ordering or gating yet — that's Phase 3.

Ask the user:

- **What's the end-state for this epic?** A clear "done" statement.
  ("Phase 6 IAM lockdown complete platform-wide; `bedrock:InvokeModel*`
  granted only to CallModel.") If the user can't articulate the
  end-state, the epic isn't ready for this skill — push back to
  `/plan-epics` or to a longer conversation about scope.
- **What are the work units inside the epic?** Surface candidates from
  the tracking issues, but ask the user to confirm and add.
- **Is there a phase that's already done?** Lift it into the
  "What landed" rolling ledger; don't re-plan it.

For each candidate phase, capture (briefly — full detail comes in
Phase 4):

- A name / one-line description
- Which tracking issue(s) it closes or moves forward
- Whether it's pure work or has an external wait (designer response,
  vendor approval, deploy window)
- Rough size: "fits in a session" vs "needs further decomposition"

If a candidate is too big for one session, split it during the dialogue.
Don't write phases that the next session can't realistically swallow
whole.

### Phase 2: Define done + dependencies per phase

For each candidate phase from Phase 1, dialogue to pin down:

- **Definition of done** — what's the concrete artifact or state change
  that ends this phase? "PR merged" is weak; "stack at UPDATE_COMPLETE
  with drift IN_SYNC and `aws iam get-role-policy` showing the new
  grant" is strong. Bias toward verifiable outcomes.
- **Dependencies** — which other phases must complete first? Make this
  explicit ("Phase 3 is gated on Phase 2's designer answer landing in
  `design-docs/X - answers.md`"). External waits (designer, deploy
  window, vendor) count too.
- **Parallel-safe** — can this phase run concurrently with another? If
  yes, note it; that's useful for `/plan-epics` portfolio planning.

This is the most load-bearing phase of the skill — vague
definitions-of-done are how epics drift. Push for specifics. If the user
says "we'll figure out done as we go," that's a tell — the phase isn't
ready and probably needs a design-call first.

### Phase 3: Order the phases

Lay out the sequence. The user picks, the skill surfaces tradeoffs.

Considerations:

- **Hard gates first** — phases that block multiple downstream items
  should go early.
- **External waits in parallel with work** — if Phase 2 is "designer
  response, ~3 days," queue independent work to run during the wait
  rather than serializing on it.
- **Risk-front-load vs cleanup-back-load** — high-risk phases early
  (more time to recover); cleanup phases at the end (after dependencies
  shake out).
- **Shipping increments** — can the epic ship value incrementally, or is
  it all-or-nothing? Increments are usually better; flag if the proposed
  order requires a big-bang.

Don't be afraid to identify phases that should run **in parallel
sessions**. The default operating mode is parallel sessions; if Phase A
and Phase D are independent, mark them as "parallel-ok" so `/plan-epics`
can schedule them concurrently.

End-state of Phase 3: an ordered list of phases (1, 2, 3, …) with gating
notes and parallel-ok flags.

### Phase 4: Write the file

Edit (or create) `NEXT_SESSION-{epic}.md` at the project root. Write
ONLY the "Remaining epic phases" section. Preserve any existing
"Next session" slice (that's `/plan-next-session`'s territory) and any
existing "What landed" ledger.

If the file doesn't exist, create it with this scaffold:

```markdown
# Next Session — {epic}

## Next: <to be planned via /plan-next-session>

(No next-session focus selected yet. Run `/plan-next-session {epic}` to
pick the first slice from the phases below.)

## Remaining epic phases

<— this skill's output, see template below —>

## What landed last session (<YYYY-MM-DD>)

(No sessions yet for this epic.)

## Watch out for

(Populate as phases progress.)

## If blocked

(Populate as phases progress.)
```

Then write the "Remaining epic phases" section using this structure:

```markdown
## Remaining epic phases

<2-3 sentence framing of the epic: end-state, what's covered, what's not>

### Phase 1: <title>

<1-3 sentence summary of the work.>

**Work:**
1. <step>
2. <step>
3. <step>

**Definition of done:** <verifiable outcome>

**Dependencies:** <none | gated on Phase X | external wait: <what>>

**Parallel-ok:** <yes / no — can run concurrently with which other phases>

### Phase 2: <title>

… (same structure)

---

## What this covers (and what it doesn't)

**In scope:**
- <bullet list of issues / tracking items / work units the epic addresses>

**Out of scope (other epics own):**
- <bullet list — point at the relevant other epic file by name>
```

Write the file immediately. Then summarize what landed in 2-3 lines and
offer to revise.

### Phase 5 (optional, only if asked): Cross-link to /plan-next-session

After writing, if the user wants to start the next session from the new
arc, offer to run `/plan-next-session {epic}` to pick the first phase as
the next-session slice. Don't auto-run.

Also offer to file a tracking issue if the epic doesn't have one — a
tracking issue makes the epic visible to `/plan-epics` even when the
file is tracked.

## What this skill does NOT do

- **Does not write the "Next session" slice.** That's
  `/plan-next-session`. This skill writes the multi-session arc; the
  next-session pick is a separate concern.
- **Does not estimate dates.** Phases are sequenced and gated, not
  scheduled. Calendars belong elsewhere.
- **Does not commit or push.** It writes the epic file; committing is left to the user or `/session-close`.
- **Does not plan across epics.** Portfolio decisions are
  `/plan-epics`. If the user surfaces work that doesn't fit this epic,
  push back and offer to file it under a different epic.
- **Does not create new tracking issues** unless the user explicitly
  asks. Filing issues happens during work or `/session-close`.
- **Does not auto-decompose without dialogue.** Decomposition is a
  conversation; a skill that writes phases without the user's input
  defeats the purpose.

## Fresh start (no prior epic file)

When there's no existing `NEXT_SESSION-{epic}.md`:

- **Phase 0** is shorter — no existing arc to compare against. Focus on
  tracking issues + recent commits + design-call answers.
- **Phase 1** is the bulk of the dialogue. Spend more time enumerating
  candidate phases since there's no prior decomposition to anchor on.
- **Phase 4** uses the full scaffold (Next session placeholder + arc +
  empty ledger sections). Mention `/plan-next-session {epic}` as the
  natural next step.

## Re-planning an in-flight epic

Pass `--review` as a second arg to skip Phase 1 and go straight to
reviewing the existing phases:

- Walk each existing phase: still relevant? still right shape?
  done already (lift to ledger)? gating still accurate?
- Surface phases that have drifted (a designer answer changed the
  approach, a dependency shifted, new work emerged).
- Phase 4 writes the revised arc, preserving the rest of the file.

This is the right entry when the epic has been running for a while and
the arc needs maintenance, not when the epic was just started.

## Guidelines

- **Dialogue, not report.** Each phase pauses for input. A skill that
  decomposes without the user's voice produces phases the user doesn't
  trust.
- **Verifiable definitions of done.** "PR merged" is weak. "Stack
  IN_SYNC + `aws iam get-role-policy` shows new grant + smoke confirms
  curated hits in CloudWatch" is strong. Bias toward outcomes you can
  check.
- **Gating is explicit, not implicit.** "Phase 3 depends on Phase 2" is
  better than "Phase 3 comes after Phase 2 in the list." External waits
  count — call them out by name (designer, deploy window, vendor SLA).
- **Parallel-ok flags matter.** The default operating mode is parallel
  sessions. If two phases are independent, mark them so. `/plan-epics`
  uses this to schedule.
- **Don't restate the next-session slice.** The "Next session" section
  is owned by `/plan-next-session`. If a phase becomes the next session,
  it shows up there too — but this skill doesn't author it.
- **Right-size the arc.** 3–7 phases is the sweet spot for one epic.
  Fewer means the epic is small enough to not need this skill; more
  means it should probably be two epics. Push back on >10-phase arcs.
- **Cross-epic dependencies are first-class.** If Phase 4 of this epic
  hands off to a phase in another epic, say so. Note the receiving
  epic file by name so the cross-reference is grep-able.
- **One page is fine; three is fine if it's well-structured.** Epic arcs
  legitimately need more space than next-session slices. The constraint
  isn't length, it's coherence.
