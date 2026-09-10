---
name: plan-epics
description: Portfolio view across all in-flight epics. Inventories active NEXT_SESSION-{epic}.md files, identifies stalled or done epics, surfaces new epics not yet captured, and helps decide which to push next. Sibling to /plan-epic (one epic's arc) and /plan-next-session (one session within an epic). Use monthly, at session start when picking a focus, or when something feels off about the portfolio.
---

# Plan Epics

A portfolio-level planning step across all in-flight epics. Output is
usually a conversational digest — optionally a persistent `EPICS.md`
snapshot. The skill helps with the "which epic should we push next?"
question, surfaces stalled or done epics, and identifies new epics that
should have a file but don't.

This sits above `/plan-epic` and `/plan-next-session`:

- `/plan-epics` — "which epic should we push?" *(this skill)*
- `/plan-epic <name>` — "lay out the arc for THIS epic"
- `/plan-next-session [epic]` — "pick what THIS session does within an epic"

Use this skill when:

- **Starting a session and not sure what to work on.** Run this to see
  the portfolio, pick an epic, then drop into `/plan-next-session`.
- **Monthly cadence.** Catch stalled epics, archive done ones, identify
  new ones that have been getting commits but no file.
- **Something feels off** — a parallel session is unexpectedly stepping
  on another epic, a tracking issue you thought was done isn't actually
  closed, a "done" epic still has open issues. Run this to see the
  whole picture.

## Invocation

```
/plan-epics
```

No arguments. Operates on the current working directory.

Optional `--snapshot` flag writes a persistent `EPICS.md` summary file
to project root (tracked in git by default, like the epic planning files).
Without the flag, output is conversational only.

## What it operates on

- `NEXT_SESSION*.md` files at project root — the active epic plans
- GitHub tracking issues — issues labeled `tracking` or `epic`, or with
  titles that match active epic files
- Recent commit log — to compute per-epic activity / staleness
- Optionally: `EPICS.md` if present (the persistent snapshot from a
  prior run)

## Workflow

The skill runs in four phases. **Each phase is a conversation, not a
report.** Surface findings, then wait for the user's input.

### Phase 0: Gather context (silent)

Collect:

1. **Active epic files** — `ls NEXT_SESSION*.md`. For each, read:
   - The `## Next:` line (what's the current focus?)
   - The `## What landed last session` date (most recent session)
   - The `## Remaining epic phases` section count (how many phases
     are sequenced, if any)
2. **File mtimes** — `stat` on each epic file. Proxy for "when was
   this last touched."
3. **Recent commits per epic** — `git log --since="60 days ago"
   --oneline`. Group commits by epic by matching commit subjects and
   file paths to each epic's known scope (rough heuristic: the file
   paths mentioned in each epic file's "Watch out for" / "In scope"
   sections).
4. **Tracking issues** — `gh issue list --label tracking,epic
   --state open --json number,title,labels,updatedAt`. Cross-reference
   with epic file names.
5. **Closed issues per epic** — `gh issue list --state closed --since
   60d --json number,title`. Match to epics; useful for "what
   shipped from this epic recently" framing.
6. **Existing `EPICS.md`** (if present) — read it as the prior
   snapshot. Compare current state.

Summarize Phase 0 in a short opener (≤10 lines) before Phase 1.

### Phase 1: Inventory the portfolio

Present each epic in a compact format:

```
{epic-name}
  File: NEXT_SESSION-{epic}.md  (mtime: 2026-05-31)
  Last session: 2026-05-31 — "<Next: line>"
  Recent activity: 12 commits in last 30d
  Tracking issue: #680 — Bedrock consumers inventory (open)
  Phases remaining: 7 of 7 sequenced
  Open issues: 4
  State: active | stalled | new | done?
```

Group by state:

- **Active** — file exists, recent commits (within 14 days), open
  tracking issues
- **Stalled** — file exists but no commits in 30+ days. Flag for
  re-evaluation — still relevant? still right priority?
- **Fresh** — file exists but no commits yet (just bootstrapped)
- **Done?** — file exists but no remaining phases, no open tracking
  issues, recent commits all map to "closure" / "cleanup" subjects.
  Candidate for archive.
- **Hidden** — recent commits cluster around a theme that doesn't have
  an epic file yet. Surface as "should this be an epic?"

Ask the user:

- Any "Done?" candidates that should actually be archived now?
- Any "Stalled" candidates that should be paused (note in file) vs.
  killed vs. revived?
- Any "Hidden" clusters that should get an epic file via `/plan-epic`?
- Anything in the inventory that's mislabeled or wrong?

### Phase 2: Identify portfolio-level decisions

Cross-cutting questions surfaced by the inventory:

- **Which epic carries the most momentum?** Most recent commits, most
  tracking-issue movement. Often the natural answer to "which to push
  next."
- **Which epic has the longest external wait?** A designer answer
  pending, a vendor SLA, a deploy window. If something has been waiting
  30+ days, surface it as "do we need to escalate or accept the wait?"
- **Which epics are competing for the same surfaces?** If two epics
  both want to touch `src/lib/X.ts`, they're not parallel-safe. The
  user should sequence them or split the surface.
- **Which epics have completed their tracking-issue parents?** If
  #680 closes, the bedrock epic is structurally done — surface as
  closure candidate.

Dialogue, not report:

- Surface the cross-cutting findings.
- Ask the user which deserve action vs. which are notes.

### Phase 3: Act on the decisions

Based on Phase 2, offer concrete actions per category:

**Archive a done epic:**
- Move `NEXT_SESSION-{epic}.md` → `archive/next-session/NEXT_SESSION-{epic}-{YYYY-MM-DD}.md`
- Update its closing date in the file header
- Close any final tracking issues
- Mention briefly in the next-active-epic's "What landed" ledger that
  this epic closed (helps future sessions see the chain)

**Mark a stalled epic for revival:**
- Add a "Stalled since YYYY-MM-DD" note to the epic file header
- File a tracking issue if there isn't one, with the stall reason
- Offer to schedule a `/plan-epic {name} --review` to refresh the arc
  in the next session

**Bootstrap a hidden epic:**
- Confirm the epic name (lowercase, hyphen-separated)
- Offer to run `/plan-epic {new-name}` to lay out the arc
- File a tracking issue for the epic if it doesn't have one

**Pick the next epic to push:**
- Surface the top 1–2 candidates with rationale (momentum, unblocks,
  designer-answered, time-sensitive — same lenses as
  `/plan-next-session` Phase 3, but at the epic level).
- If the user picks one, offer to run `/plan-next-session {epic}`
  next.

Do not auto-act on any of these without explicit per-item approval.
Bulk archive / file moves are easy to regret.

### Phase 4 (optional, only if --snapshot was passed): Write EPICS.md

Write a persistent portfolio snapshot to `EPICS.md` at project root
(tracked in git by default). This is optional because the conversational
output is usually enough; the file is useful when you want to share the
portfolio state with another session or revisit it offline.

Use this structure:

```markdown
# Epics

Snapshot as of <YYYY-MM-DD HH:MM>. Active operating mode: parallel
sessions, per-epic planning files.

## Active

### {epic-name}
- File: `NEXT_SESSION-{epic}.md` (last touched <date>)
- Current next-session focus: <one-line>
- Recent activity: <N commits in last 30d>
- Tracking issue: #N — <title>
- Phases remaining: <N>
- Notes: <if any>

### {epic-name}
…

## Stalled

(same shape, plus "Stalled since: <date>" line)

## Recently archived

- {epic-name} — closed <date> — file: `archive/next-session/{filename}`

## Hidden / candidate epics

- {topic} — N commits in the area, no epic file yet. Consider
  `/plan-epic {name}` to bootstrap.

## Portfolio-level notes

<one or two paragraphs of cross-cutting observations from this run>
```

## What this skill does NOT do

- **Does not write or modify individual epic files.** Those are owned by
  `/plan-epic` (arc) and `/plan-next-session` (next-session slice).
  This skill only inventories and proposes.
- **Does not auto-archive, auto-close, or auto-bulk-edit.** Every
  action needs per-item approval. Bulk decisions are easy to regret.
- **Does not estimate dates or commitments.** Portfolio sequencing is
  about priority and dependencies, not calendars.
- **Does not commit or push.** It writes files; committing is left to the user or `/session-close`.
- **Does not plan within an epic.** If the user picks an epic to push,
  hand off to `/plan-epic` or `/plan-next-session`. Don't try to do
  their job.
- **Does not file new tracking issues** unless the user explicitly
  asks. Filing happens during work or `/session-close`.

## Fresh start (first run on a project)

When there's no `EPICS.md` and the project has multiple
`NEXT_SESSION*.md` files but they haven't been organized as a
portfolio:

- Phase 0 is the bulk of the work — discovering what exists.
- Phase 1 surfaces the inventory; the user mostly confirms and
  corrects.
- Phase 2 is the first portfolio decision-making — often "yes, that
  one's done, archive it" / "this hidden cluster should be its own
  epic."
- Phase 3 acts on per-item approval.
- Phase 4 (optional snapshot) is more useful on first run because
  there's no prior snapshot to anchor on.

If the project has only ONE epic file (or zero), this skill is
overkill — point at `/plan-next-session` for a single-epic project.

## Guidelines

- **Dialogue, not report.** The portfolio digest is the prompt for the
  conversation, not the output.
- **Right-size the digest.** A project with 12 epics needs grouping;
  a project with 3 epics doesn't. Adapt to scale.
- **Respect epic ownership.** If another session is actively working in
  an epic (recent commits to its file or its code surfaces), don't
  propose archiving it just because the file looks quiet to you.
- **Parallel-safe is first-class.** A portfolio that funnels everything
  through one epic at a time leaves capacity on the table. Surface
  parallel-ok pairs explicitly.
- **Closure is a feature.** "Done" is harder than "in flight" to
  recognize at the portfolio level — push for it when the signals line
  up (tracking issues closed, phases all complete, recent commits are
  cleanup). The cost of leaving a done epic open is that it stays in
  the inventory mentally; the cost of premature archive is recoverable
  (un-archive the file).
- **Cross-epic dependencies surface here.** If Phase 4 of bedrock hands
  off to phase 1 of pipeline, this skill is the right place to make
  that visible — that's exactly the kind of seam that gets lost when
  you only see one epic at a time.
- **Don't replan within an epic.** If a phase needs revising, that's
  `/plan-epic`'s job. This skill notices the need and points there.
