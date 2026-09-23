---
name: plan-next-session
description: Plan the next working session through structured dialogue for ONE epic. Reflects on what landed and what didn't, triages open issues with priority labels, surfaces design-call answers waiting on implementation, and writes the epic-specific NEXT_SESSION-{epic}.md. Intended to run after /session-close. For multi-session epic-arc planning use /plan-epic; for portfolio-across-epics use /plan-epics.
---

# Plan Next Session

A dialogue-driven planning step that runs after `/session-close`. The goal is a written next-session file that lets the next session start with a clear focus rather than re-discovering state.

This is **single-session, single-epic planning**, not sprint planning and not epic-arc planning. If the dialogue surfaces work that genuinely needs multiple sessions within one epic, use `/plan-epic` to lay out the arc; if it surfaces work that spans multiple epics, use `/plan-epics` for the portfolio view; if it surfaces enough to warrant a retrospective, escalate to `/retro`.

## Invocation

```
/plan-next-session
```

Optional epic name as a positional arg: `/plan-next-session bedrock` picks the bedrock epic without dialogue. Otherwise the skill globs `NEXT_SESSION*.md` and asks which epic you're planning for (or offers to bootstrap a new one).

## Where the file lives

Project root, **tracked in git by default**. Filename is `NEXT_SESSION-{epic}.md` (one file per independent epic). Default assumption: parallel sessions exist or will exist, so per-epic files prevent merge clobbering. Filename convention prefers hyphen separator; if a file already uses underscore (`NEXT_SESSION_pipeline.md`), match the existing style when extending it.

If a project's `.gitignore` still excludes `NEXT_SESSION*.md` from the old convention, remove that pattern and commit the planning files. Projects may override this at the project level (in their own `CLAUDE.md` or `.gitignore`) to keep planning files untracked if preferred.

If the project has a memory or convention that says otherwise, follow it. Some projects may still use a single global `NEXT_SESSION.md` — that's fine; the workflow below collapses naturally.

## Workflow

The skill runs in four phases. **Each phase is a conversation, not a report.** Surface findings, then wait for the user's input before moving on. Do not write the artifact until Phase 4.

### Phase 0: Gather context (silent)

Before the dialogue starts, collect:

1. **Existing epic plan files** — `ls NEXT_SESSION*.md` to discover all active epic plans. If an epic name was passed as an arg, target that file (`NEXT_SESSION-{epic}.md`); otherwise, surface the list to the user in Phase 1 and ask which epic this session worked on. Read the relevant file. If no file matches, this is a fresh start for a new epic — see "Fresh start" section.
2. **Recent commits** — `git log --oneline --since="<inferred date of last plan>"` to see what actually landed. If no relevant epic file exists, use the last 7 days. **Note any commits that touch other epics** (parallel session work) — those are out of scope for this skill's output but worth flagging in Phase 1 so the user knows what else moved.
3. **Git status** — uncommitted/staged/untracked files. In-flight work that needs a decision.
4. **Task list** — `TaskList` for any pending/in_progress tasks not yet wrapped up.
5. **Open issues** — `gh issue list --state open --limit 200 --json number,title,labels,updatedAt,assignees`. Group by priority label. Compute staleness (no `updatedAt` change in 14+ days).
6. **In Progress column** — items labeled `in-progress` should be examined first.
7. **Design-call answers** *(only if the project uses the design-call pattern — look for `design-docs/` with `* - design call.md` / `*-answers.md` files)* — `ls design-docs/*-answers.md` or the project's convention. Cross-reference against recent commit subjects to identify answers that haven't been wired into code yet. Also flag any that are **untracked** in git — those should be committed alongside the implementation. Skip this step entirely if the convention isn't in use.

Summarize Phase 0 findings in a short "here's what I see" opener (≤10 lines) before starting Phase 1.

### Phase 1: Reflect on this session

A short dialogue. Anchor on the existing epic file if present:

- **What we planned to do** (from prior epic file's "Next" section)
- **What landed** (from `git log` + closed issues)
- **What didn't** — planned items that didn't ship, with reasons if known (deferred / blocked / out of scope)
- **What came up mid-session** that's worth tracking (new issues filed, surprises, follow-ups)

Ask the user:
- Anything you'd add to the "what came up" list?
- Anything in-flight (uncommitted, half-done) that should carry over to next session vs. get cleaned up now?

If there's uncommitted work that should be cleaned up rather than carried, point at `/session-close` — don't try to do its job here.

### Phase 2: Triage the open-issue landscape

Present issues as a **digest grouped by priority label**, not a list. Suggested groupings:

- **In Progress** — items labeled `in-progress`. Should each continue, get paused, or close?
- **High priority Todo** — `priority: high` + status Todo. Top candidates.
- **Medium priority Todo** — same, medium.
- **Stale** — anything (any priority) with no `updatedAt` change in 14+ days. Flag for re-evaluation: still relevant? still right priority?
- **Unlabeled / mislabeled** — issues missing a `priority:` or `type:` label, per the project's labeling convention. Note them; offer to fix in bulk at the end.
- **Design-call answers awaiting implementation** *(only if the project uses the pattern)* — call these out separately. Each one is a designer commitment that needs to land. If an answer is untracked or has no follow-up issue yet, point at `/design-call` (ingest mode) as the right entry point before this session's work starts.

Keep the digest scannable: counts per group + the top 3-5 candidates per group with `#N — title — staleness`. The user can ask to drill in.

Ask the user:
- Anything in this triage that's mislabeled or in the wrong column?
- Anything in Stale that should be closed (no longer relevant) vs. demoted vs. refreshed?

### Phase 3: Choose next session's focus

Based on Phases 1 + 2, propose candidates for next session with rationale. **The goal of this phase is to land on a single focus** — one coherent topic the next session will work on. Multiple issues within that focus are fine if they share a theme (e.g., "voice sweep across 8 surfaces" is one focus even if it touches 8 issues); what's not fine is two unrelated paths sitting side-by-side in the file.

**Why single-focus matters:** the next session's agent reads the epic file cold and has to understand what it's looking at. If the file presents Path A *or* Path B with sequencing notes like "either run all in one session OR split," the agent has to study and reason about both paths before doing anything — that's wasted context on a decision that's already yours to make, not the next agent's. Force the pick now.

Use these lenses when picking the focus:

- **Carries momentum** — continues a cluster from this session
- **Unblocks others** — a primitive, a decision, or a token that lets later work proceed
- **Time-sensitive** — has a deadline, a deferred-until date that's now arrived, or a freeze window
- **Load-bearing** — fixes drift in a foundational surface (auth, schema, brand primitive)
- **Designer-answered** *(if the project uses design-calls)* — a design-call has answers; the implementation diff is the next step
- **Right-sized** — fits a single session realistically given the in-progress state

For each candidate, give a 1-2 sentence rationale and note dependencies (e.g., "needs designer to confirm the answers file first" or "blocked on #X").

**Before discussing candidates, run a reality check on each one.** External sources of "this needs doing" — designer answers, issue descriptions, stakeholder requests, your own notes from three sessions ago — can be stale by the time planning happens. The fix is **strategic uncertainty:** treat any external claim of "this is undone" as a hypothesis until verified. A 5-minute check beats a 3-hour dead-end session.

For each candidate, do a fast smoke check before promoting it:

- **Named primitive / component / route** — grep for the name in the relevant directory. If the file exists, read its first 30 lines. Already implemented?
- **"Implement design from answer doc Y"** — read Y, identify the primitives / copy / patterns it specifies, then grep for those. Designers sometimes write answer docs against an older codebase state; the work may already be done in spirit.
- **"Add token X / canonize register Y"** — check `DESIGN.md`, the brand layer source files, and copy modules. Token may already be defined under a different name.
- **"Fix bug in Z"** — check recent commits touching Z and the file's current state. Bug may already be fixed.
- **"Migrate / sweep / retire X"** — check the lint rule (if one was added per the pattern-sweeps convention), check the count of remaining sites. Sweep may be functionally complete with only edge-case warnings left.

Three possible verdicts per candidate:

- **Done** — drop from the candidate list. Note which artifact made you think it was undone (the stale source), so the user knows to discount it next time it surfaces.
- **Partially done** — narrow scope to just the undone slice. Often the right move when a designer answer is 80% implemented and the remaining 20% is a discrete piece.
- **Genuinely undone** — proceed to discussion.

Don't skip this for "obvious" candidates. The whole point of strategic uncertainty is that the obviously-undone ones are exactly where stale framings hide. The cost is 30 seconds of grep per candidate; the upside is not burning a session on a dead end.

**Evaluate whether the focus is loop-shaped.** After landing on a focus, check whether the work fits a loop pattern: batch sweep, mechanical work-list, poll-until-done, research-until-cited, or any shape where judgment can be front-loaded and execution is repetitive with a checkable exit. Signs the work is loop-shaped:

- The focus touches N similar items (files, endpoints, modules, issues)
- There's a deterministic "done" condition (lint=0, grep returns zero, all tests pass, count reaches target)
- The per-item step is mechanical once the rules are decided
- The work could run autonomously if the rules were clear enough

If the work IS loop-shaped, shift the dialogue to front-load judgment — resolve the unknowns NOW so the session file can describe an autonomous loop:

- **What's the verifier?** What deterministic check proves an item is done? (test passes, lint clean, grep returns zero, specific exit code)
- **What's the exit predicate?** When is the whole loop done? (all items processed, counter hits zero, external state goes green)
- **What needs human judgment vs. what's mechanical?** If per-item decisions still need judgment, the work isn't loop-ready — either shape a real verifier or keep the human in the loop.
- **What's the circuit-breaker?** How many iterations before failing gracefully? (Rule of thumb: 2-3 retries per item, then hand to a human queue.)
- **What premise could go stale mid-loop?** (Target file gets deleted by a parallel session, the issue gets superseded, the test gets rewritten.)

This front-loading IS the planning value — it converts "do the sweep" into a designed loop with a checkable exit, so the next session can run autonomously without re-discovering the rules.

Then discuss with the user:
- Which one? Any reordering within the focus?
- Is the scope realistic for one session, or should we split and pick the first slice?
- Anything I should swap in from the digest instead?

**If the user is genuinely torn between two paths, push for a pick.** The dialogue here is the right place to weigh paths against each other; the file is not. Saying "let's leave both in the epic file and decide next session" is a tell — it means we're punting a decision to a session that has less context than we do right now. Force the pick by surfacing what makes one higher-priority (load-bearing, time-sensitive, designer-answered, momentum) and lean on that.

If a candidate genuinely needs multiple sessions, **don't try to plan all of it here**. Either pick the first slice for next session and run `/plan-epic` to lay out the full arc, or recommend opening a tracking issue and stop. Single-session planning is the design constraint.

### Phase 4: Write the epic file

Once Phase 3 lands on a focus, **write the file directly** — don't ask for a second approval. The Phase 3 selection IS the approval; gating again on the draft is redundant and slows the loop.

Populate the Session start protocol block as part of writing the file -- the planning dialogue just surfaced the risks, staleness vectors, and irreversible actions; encode them now rather than letting the session rediscover them. Keep "rules with history" to the two or three rules this specific session could plausibly bend; restating everything dulls all of it.

After writing, mention briefly what was written and offer to revise if anything's off. That converts the gate from "approve before action" to "redirect after action if needed" — same safety, less friction.

Write to `NEXT_SESSION-{epic}.md` (e.g., `NEXT_SESSION-bedrock.md`, `NEXT_SESSION-design.md`) at the project root. If a file for this epic already exists, **edit in place** — preserve the multi-session arc section if there is one (that's `/plan-epic`'s territory), and replace only the "Next session" slice and the rolling "What landed" ledger.

**Do not write to a generic `NEXT_SESSION.md`** unless the project explicitly uses a single-file convention. The default assumption is parallel sessions exist; per-epic files prevent clobbering. **Do not edit files for other epics** (e.g., don't touch `NEXT_SESSION-pipeline.md` while planning the bedrock epic).

Use this structure (matches the existing project convention; don't reinvent):

```markdown
# Next Session — {epic}

## Next: <single focus theme>

<1-2 sentence framing of the next session's focus. Single topic. Not "either A or B."
If multiple issues, they share the theme.>

1. **#N — <title>** (<status flags: needs designer / blocked / mechanical / etc.>)
   <2-4 sentence rationale + pointers to relevant files, design-call answers, or constraints>

2. ...

**Sequencing.** <ordering within the focus only. NOT "Path A OR Path B" — if there's a fork,
it gets decided in Phase 3 dialogue, not deferred to the file.>

**Constraints for the session:**
- <e.g., uncommitted design-call-answers should be committed first>
- <e.g., catalog drift rule applies, schema sync needed, etc.>

**Session start protocol:**
- Premise checks (before item 1, ~5-10 min, report before acting):
  <tracker-vs-plan drift check if issue ops ran since planning; git state
  (expected merges landed? stale index.lock?); live-state probe (run the
  preflight / check the checkpoint / confirm nothing already did this
  work via cron or a parallel session)>
- Rules with history (max 2-3, only ones THIS session could bend):
  <e.g., read-only means read-only; exit predicate as amended, don't
  chase deltas; deploy scripts main-context only>
- Stop-and-ask before: <the irreversible actions specific to this
  session — destructive commands, cross-namespace changes, large quota
  spends, anything touching production data>
- Close ritual: session summary + reconciliation per convention;
  <if the session produces numbers: record them against registered
  predictions, not post-hoc>

**Loop design (if the focus is loop-shaped):**
- **Exit predicate:** <deterministic condition — e.g., "grep -r 'old_pattern' returns zero", "all items in work-list processed">
- **Max iterations:** <hard cap / circuit-breaker — e.g., "3 retries per item, 50 items total">
- **Per-item verifier:** <what checks each item is done — e.g., "lint passes on the file", "test suite green">
- **Premise to re-validate each pass:** <what could go stale — e.g., "target file still exists", "issue not yet closed by parallel session">
- **Maker ≠ checker:** <how verification is independent of execution — e.g., "worktree isolation + separate review agent">
- **If stuck:** <what happens when no progress — e.g., "after 2 passes with no new items fixed, stop and file remaining as issues">

## Remaining epic phases (if any)

<If the epic file already has a multi-session arc from `/plan-epic`, preserve it unchanged here.
This skill is single-session-focused; it does not author or edit the multi-session arc. If the
user wants to revise the arc, point them at `/plan-epic`. The phases list IS the queue of what
comes after next session — no separate "Session after next" section is needed.>

## What landed last session (<YYYY-MM-DD>)

<2-4 line summary + a `Closed:` list with #N — title — context>

<If there were notable commits, a `Commits:` subsection grouped by theme>

<If new follow-ups were filed, a `Follow-ups filed:` list>

<If commits from parallel sessions touched related epics, mention briefly:
"Parallel session also moved on: <epic> — <1-line summary>." Don't restate their full work.>

## Watch out for

- <known risks, in-flight migrations, telemetry to monitor, untracked files that should be committed, etc.>

## If blocked

- <alternative work the user can pick up if the primary focus is blocked. Include enough pointers (which file, which design-call doc) that picking it up is fast>
```

Write to `NEXT_SESSION-{epic}.md` in the project root immediately, then summarize what landed in 2-3 lines and ask if anything needs revision.

### Phase 5 (optional, only if asked): Bulk fixups

After writing, if Phase 2 surfaced labeling/column problems, offer to fix them:
- Re-label mislabeled issues (`gh issue edit N --add-label "..." --remove-label "..."`)
- Move stale Todo items back to Backlog
- Close stale items the user confirmed are no longer relevant

Do not do this without explicit per-item approval. Bulk label changes are easy to regret.

## What this skill does NOT do

- **Does not run after session-close automatically.** It's a separate invocation. If session-close found uncommitted work, the user decides whether to commit/discard before running this.
- **Does not commit or push.** It writes the epic file; committing is left to the user or `/session-close`.
- **Does not auto-fix issue labels** without per-item approval.
- **Does not plan beyond next session.** For multi-session epic arcs (Phase 1/2/3 with definitions-of-done, dependency gating), use `/plan-epic`. The phases section it writes IS the queue of what comes after next session.
- **Does not plan across epics.** Portfolio decisions ("which epic should we push next? what's stalled?") belong in `/plan-epics`. This skill plans one session within one epic.
- **Does not edit files for other epics.** If `NEXT_SESSION-pipeline.md` exists and this session worked on bedrock, leave the pipeline file alone. Parallel sessions own their own files.
- **Does not create new GitHub issues** unless the user explicitly asks. Filing issues for mid-session findings is a `/session-close` responsibility (or just inline during the work).
- **Does not duplicate /retro.** If the user wants a full retrospective on a feature or sprint, point them at `/retro` instead of doing a heavyweight version here.

## Fresh start (no prior file for this epic, or new project)

When there's no existing `NEXT_SESSION-{epic}.md` for the chosen focus — first run on the epic, or after the file was archived — the workflow shifts:

- **Phase 1 (Reflect)** becomes a brief orientation instead of a comparison: "Here's the recent activity I see (commits, open issues, in-flight branches). Anything you want me to know about that I wouldn't see from git?" If other epic files exist, mention them so the user can confirm this is a genuinely new epic and not a session in an existing one.
- **Phase 2 (Triage)** runs as normal — the issue digest is the primary input when there's no prior plan to anchor on.
- **Phase 3 (Choose)** leans harder on the digest. With no momentum to carry, "load-bearing" and "unblocks others" tend to win over "carries momentum." **Decide the epic name** during this phase if it's not already obvious — short, lowercase, hyphen-separated (`bedrock`, `design`, `pipeline`, `auth`, etc.).
- **Phase 4 (Write)** uses the template below as the starting structure. Sections may be sparse on the first pass; that's fine — the file fills in over time. If this is the first session of a multi-session epic, mention `/plan-epic` as the natural next step to lay out the arc.

### Starter template

Drop this into a new `NEXT_SESSION-{epic}.md` when bootstrapping. Sections are optional — delete any that don't apply to the project (e.g., "If blocked" only makes sense if there's a queue of alternatives; design-call references only if the project uses that pattern).

```markdown
# Next Session — {epic}

## Next: <focus theme>

<1-2 sentence framing>

1. **#N — <title>**
   <rationale + pointers to files, docs, or constraints>

**Sequencing.** <if multiple items, how they relate>

**Constraints for the session:**
- <e.g., needs schema migration first, depends on #X, deadline of Y>

**Session start protocol:**
- Premise checks (before item 1, ~5-10 min, report before acting):
  <tracker-vs-plan drift check if issue ops ran since planning; git state
  (expected merges landed? stale index.lock?); live-state probe (run the
  preflight / check the checkpoint / confirm nothing already did this
  work via cron or a parallel session)>
- Rules with history (max 2-3, only ones THIS session could bend):
  <e.g., read-only means read-only; exit predicate as amended, don't
  chase deltas; deploy scripts main-context only>
- Stop-and-ask before: <the irreversible actions specific to this
  session — destructive commands, cross-namespace changes, large quota
  spends, anything touching production data>
- Close ritual: session summary + reconciliation per convention;
  <if the session produces numbers: record them against registered
  predictions, not post-hoc>

**Loop design (if the focus is loop-shaped):**
- **Exit predicate:** <deterministic condition — e.g., "grep -r 'old_pattern' returns zero", "all items in work-list processed">
- **Max iterations:** <hard cap / circuit-breaker — e.g., "3 retries per item, 50 items total">
- **Per-item verifier:** <what checks each item is done — e.g., "lint passes on the file", "test suite green">
- **Premise to re-validate each pass:** <what could go stale — e.g., "target file still exists", "issue not yet closed by parallel session">
- **Maker ≠ checker:** <how verification is independent of execution — e.g., "worktree isolation + separate review agent">
- **If stuck:** <what happens when no progress — e.g., "after 2 passes with no new items fixed, stop and file remaining as issues">

## What landed last session (<YYYY-MM-DD>)

<2-4 line summary>

**Closed:** #N — title — context

## Watch out for

- <known risks, in-flight migrations, untracked files, deferred-until dates, etc.>

## If blocked

- <alternative work the user can pick up WITHIN THIS EPIC — include enough pointers that picking it up is fast>
```

For projects without GitHub Issues, replace `#N — title` with whatever the work-tracking unit is (Jira ticket, Linear issue, a `TODO:` in code, etc.) — the skill's structure works as long as candidates are addressable.

## Guidelines

- **Dialogue, not report.** Each phase should pause for input. A skill that writes the file in one shot defeats the purpose.
- **Single focus per session, per epic.** "Next" gets one topic within one epic. Multiple issues OK if they share the theme. Alternative paths within the same epic surface as later phases in `/plan-epic`'s arc, or as fallbacks in "If blocked." Cross-epic work belongs in other epic files — don't reach across.
- **Parallel sessions are the default.** Assume another session is or will be running in another epic. Glob `NEXT_SESSION*.md` at start to see the landscape; write only to your epic's file; don't restate other epics' work in yours. Cross-epic coordination belongs in `/plan-epics`.
- **Strategic uncertainty about "this needs doing."** External claims (designer answers, issue descriptions, stakeholder requests) describe a moment in time and can be stale by planning time. Verify before promoting to "Next." A 30-second grep beats a multi-hour dead-end session start. The obviously-undone candidates are exactly where stale framings hide.
- **Anchor in the artifact that exists.** The current epic file's template works. Don't restructure it just because the skill could. Preserve any "Remaining epic phases" section (it's `/plan-epic`'s output).
- **Right-size the digest.** With 100+ open issues, dumping all of them is noise. Group, count, surface the top few per group, let the user drill in. Within an epic, the universe of relevant issues is usually small (<30) — even better.
- **Be specific in rationales.** "Carries momentum from #473" beats "good follow-up." Cite issue numbers, file paths, and the lens that made you pick it (load-bearing / time-sensitive / etc.).
- **Surface drift, don't fix it silently.** If issues are mislabeled or design-call-answers are uncommitted, name it in Phase 2 and offer Phase 5. Don't quietly fix things mid-dialogue.
- **One page, not three.** The "Next session" section should fit on a screen. If a single issue needs more context than two paragraphs, link to the design-call doc or the tracking issue instead. The "Remaining epic phases" section (if present) can be longer — that's `/plan-epic`'s output and you're preserving it, not authoring it.
- **Loop-shaped work gets a designed loop.** When the next session's focus is batch/mechanical/iterative, the planning dialogue should front-load all judgment and produce a session file that can run autonomously. The session file IS the loop design — exit predicate, counter, verifier, and premise guard baked in. Don't defer to `/loop-design` at session start; do the design work here in the planning conversation where the user is present to resolve unknowns.
- **The file carries its own opening ritual.** A well-written epic file makes "Read the file and begin" a complete session start. If the operator needs a long kickoff prompt, the protocol block is missing or stale -- fix the file, not the prompt.
