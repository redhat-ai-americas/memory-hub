---
name: reconcile
description: Mid-tier review between /session-close and /retro. Reconciles the backlog against what recent sessions actually did — fed by the tracked session summaries — to catch issue drift (issues that decayed, or were quietly satisfied by adjacent work), then offers critique and guidance. Use after a big session or several moderate ones, mid-epic. Not per-session (that's the session summary) and not per-epic (that's /retro).
---

# Reconcile Skill

The **rolling / mid-epic** review tier. Between `/session-close` (per session) and `/retro` (per epic). Its job is to fight **issue drift**: issues describe the problems and intended fixes as understood *at the time they were written*, but a few sessions of work later, some no longer apply as framed — the picture changed, the thing is partly done, it should merge or split, or a session already built something a *later* issue envisioned. Reconciliation is expensive judgment, so it batches here over several sessions rather than being paid every session.

## Where reconcile sits — the review cadence ladder

- **Per session** — the session summary from `/session-close` (check 11). Cheap capture, no dialogue, tracked in `session-summaries/`. It *flags* drift candidates (the "Drift & forward-collisions" section); it does not reconcile.
- **Rolling / mid-epic — this skill.** Batches the expensive reconciliation over the accumulated summaries. Warm and bounded: it works the candidate list the summaries already flagged, not every issue cold.
- **Per epic** — `/retro`. The reflective reckoning + deep cross-retro pattern scan. Reconcile does *not* do the deep pattern analysis — it surfaces only what's blatant and leaves the systemic pattern review to retro.

The cost split is the whole point: capture cheaply every session, reconcile in batch periodically, reflect deeply once per epic.

## Invocation

```
/reconcile [epic] [--since YYYY-MM-DD]
```

- **`epic`** — which epic to reconcile (matches `NEXT_SESSION-{epic}.md` / `EPIC-{epic}.md`). If omitted, glob the plan files and ask.
- **`--since`** — reconcile summaries dated on/after this. Default: since the most recent `reconciliations/*-{epic}.md` record; if none exists, since the epic's start (or the last ~5 summaries).

## Reconciliation record convention

Records live in `reconciliations/` at the project root, **tracked** (like `session-summaries/` and `retrospectives/`): `reconciliations/YYYY-MM-DD-{epic}.md`. The record's date is also how the *next* reconcile knows where to resume.

## Workflow

Dialogue, not a report. Surface findings, get the user's calls, then write the record.

### Phase 0: Gather (silent)

1. **Session summaries in range** — read the `session-summaries/` entries for this epic since `--since` / the last reconcile. These are the primary input; they already carry plan-vs-actual, judgment calls, backlog delta, and the drift flags.
2. **Candidate list** — collect every issue named in the summaries' "Drift & forward-collisions" and "Backlog delta" sections. This *is* the working set — warm and pre-filtered. Do not re-scan the whole backlog cold (that's grooming, and it's unbounded).
3. **Open issues for the epic** — `gh issue list` scoped to the epic's labels/milestone, to fetch each candidate's current title/body/labels and spot any obviously-related issue the summaries missed.
4. **The plan** — `NEXT_SESSION-{epic}.md` and `EPIC-{epic}.md` (the arc, if present), to judge drift against intent.

Open with a ≤10-line "here's what I see": how many summaries, how many candidate issues, split backward vs forward.

### Phase 1: Reconcile the backlog

**Backward — issues that may have decayed.** For each candidate, before proposing anything, apply **strategic uncertainty**: the summary's flag is a hypothesis. Quick-verify against the current code/issue (grep the named symbol, read the issue's acceptance criteria) — the obviously-drifted ones are exactly where a stale flag hides. Then propose one action per issue:

- **Keep** — still valid as written.
- **Re-scope** — still real but the framing/acceptance criteria changed; propose the edit.
- **Close** — done, or obsoleted by the work. Cite the commit/summary that settled it.
- **Merge / split** — collapses into or fans out from another issue.

Present these as a **batch table** for approval (`#N — current framing → proposed action → why`). **Never auto-close or auto-edit** — issue mutations are external and are the user's call; execute them only after approval, then in one pass (`gh issue edit/close`, commenting the reason + the settling commit).

**Forward — capability that outran the backlog.** For each forward-collision in the summaries:

1. Verify the pointer comment actually landed on the target issue (session-close posts it for owned repos; a proposed one may still be undrafted). Post/propose any missing per the ownership policy below.
2. Judge the downstream impact: does a *future epic phase* now shrink, drop, or change because this capability already exists? Flag it against `EPIC-{epic}.md` and propose the plan edit. **This is the anti-duplicate-rebuild payoff** — catching it here means the later phase never re-derives what's already built.

**Issue-comment / mutation posting policy (external writes).** Determine whether the target repo is one the user owns — `gh repo view <owner>/<repo> --json viewerPermission -q .viewerPermission`. Determine the authenticated user via `gh api user -q .login`. If `viewerPermission` returns `ADMIN` or `MAINTAIN` (the user's own repos and org repos they administer), **post forward-collision pointer comments automatically**. Otherwise **draft and propose** them. Issue *edits/closes/merges* (Phase 1 backward actions) always go through the batch-approval gate regardless of ownership — those change state, not just annotate.

### Phase 2: Critique & guidance

Against the plan, briefly and honestly:

- **On track?** Is the epic converging on its definition-of-done, or has scope crept / the target moved?
- **Blatant recurring friction only** — if the same drift or the same gap shows up across multiple summaries, name it. Leave the *systemic* Start/Stop/Continue pattern analysis to `/retro --review-patterns`; don't duplicate it here.
- **Highest-leverage next focus** — given what's real now (post-reconciliation backlog), what should the next session(s) attack? This feeds `/plan-next-session`, it doesn't replace it.

### Phase 3: Write the reconciliation record

Write `reconciliations/YYYY-MM-DD-{epic}.md` (tracked). Keep it to ~one screen — it's a decision log, not a transcript.

```markdown
# Reconciliation — YYYY-MM-DD · {epic}

**Range:** summaries {first-date}..{last-date} ({N} sessions)   **Plan:** EPIC-{epic}.md / NEXT_SESSION-{epic}.md

## Backlog reconciled
| # | Was | Action | Why |
|---|-----|--------|-----|
| #N | <framing> | Closed / Re-scoped / Merged / Kept | <commit or reason> |

## Forward-collisions banked
- #N/<phase> — <capability already built at `path`> — comment landed / plan phase trimmed

## Critique
- On track? <1–2 lines>. Recurring friction: <blatant only, or none>.

## Guidance for next
- <highest-leverage focus given the now-real backlog>
```

Then apply the approved issue mutations, mention the record, and point the user at `/plan-next-session` to turn the guidance into the next slice.

## Guidelines

- **Bounded by the summaries, not the whole backlog.** The warm candidate list is what makes this affordable. If you find yourself grooming every open issue, stop — that's `/plan-epics` triage, not reconcile.
- **Capture was cheap; reconciliation is the judgment.** Trust the summaries as leads, but verify each before mutating an issue — a session's in-the-moment flag can itself be wrong.
- **Never mutate issues without approval.** Comments on owned repos post automatically (they annotate); closes/edits/merges always go through the batch gate (they change state).
- **Forward-collisions are the expensive miss.** Prioritize banking them — an unrecorded "we already built this" is what causes a later session to rebuild duplicate capability.
- **Don't reach into retro's job.** Deep cross-retro pattern analysis and Start/Stop/Continue stay in `/retro`. Reconcile is backlog-truth + light critique.
