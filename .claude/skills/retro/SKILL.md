---
name: retro
description: Run a retrospective after a major feature, sprint, or effort. Reviews what was planned vs built, identifies gaps, documents findings, and checks for recurring patterns across past retros.
---

# Retrospective Skill

Facilitate a structured retrospective after completing a significant piece of work. The retro examines what was planned, what was actually built, what changed along the way, and what to improve.

## Invocation

```
/retro "<feature or effort name>" [--review-patterns]
```

- **`<feature or effort name>`** — Short label for the effort being reviewed (e.g., "weekly check-in", "auth migration", "Q1 sprint")
- **`--review-patterns`** — Instead of running a new retro, scan all past retros in the project and surface recurring patterns (start/stop/continue)

## Retro Directory Convention

Each project stores retros in `retrospectives/` at the project root:

```
retrospectives/
  2026-04-01_some-feature-name/
    RETRO.md          # The retrospective document
  2026-03-15_another-feature-name/
    RETRO.md
```

Directory name format: `YYYY-MM-DD_<slug>` where the date is when the retro was conducted and the slug is a kebab-case label.

If `retrospectives/` doesn't exist in the project, create it. Add `retrospectives/` to `.gitignore` only if the user explicitly asks — by default, retros are committed to the repo as project artifacts.

## Workflow

### Phase 1: Gather Context

Before starting the discussion, silently gather:

1. **Git history** — Commits related to this effort (by issue number, branch, date range, or keyword). This establishes what was actually built.
2. **GitHub issues** — If issue numbers are referenced, fetch their original descriptions and acceptance criteria. This establishes what was planned.
3. **Conversation context** — Review the current conversation for architectural discussions, pivots, and decisions that were made along the way.
4. **CLAUDE.md completion checklist** — Check if post-completion steps were followed (error boundaries, catalog updates, SYSTEMS.md, etc.)

Summarize your findings to the user in a brief "here's what I see" opener before moving into the structured discussion.

### Phase 2: Structured Discussion

Walk through these sections with the user. This is a **conversation**, not a report — ask questions, get the user's perspective, don't just dump a wall of text.

#### 2a. What we set out to do

Summarize the original plan or issue description. Note the key deliverables and acceptance criteria.

#### 2b. What changed and why

Identify architectural pivots, scope changes, and deferred items. For each change, note whether it was:
- A **good pivot** (improved the design through discussion)
- A **scope deferral** (consciously moved to V2/backlog)
- A **missed requirement** (forgot or overlooked)

#### 2c. What went well

Concrete wins — things that worked out, good patterns established, performance targets met, clean implementations.

#### 2d. Gaps and concerns

Be honest and specific. Categories:
- **Untested paths** — code that compiles but hasn't been exercised end-to-end
- **Missing checklist items** — CLAUDE.md or project conventions that were skipped
- **Quality unknowns** — AI output quality, edge cases, error handling
- **Documentation gaps** — features catalog, SYSTEMS.md, README updates
- **Discoverability** — can users actually find and use what was built?

#### 2e. Immediate action items

Things that should be fixed now (before moving on), vs things that can be tracked as follow-up issues. Offer to create GitHub issues for the follow-ups.

### Phase 3: Pattern Review (if past retros exist)

If this isn't the first retro in the project, scan previous `RETRO.md` files and look for:
- **Recurring gaps** — same types of things being missed repeatedly
- **Process improvements that stuck** — things we started doing and kept doing
- **Process improvements that didn't stick** — things we said we'd do but keep forgetting

Present a brief **Start / Stop / Continue** summary based on patterns.

### Phase 4: Document

Create the retro directory and write `RETRO.md` with the agreed-upon findings. The document should be structured and scannable, not a transcript of the conversation.

## RETRO.md Template

```markdown
# Retrospective: {Feature Name}

**Date:** {YYYY-MM-DD}
**Effort:** {Brief description}
**Issues:** {#123, #456}
**Commits:** {short hashes or range}

## What We Set Out To Do

{Original plan summary}

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| {description} | Good pivot / Scope deferral / Missed | {why} |

## What Went Well

- {concrete win}

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| {description} | Fix now / Follow-up issue / Accept | {issue link or "fixed in {commit}"} |

## Action Items

- [ ] {immediate fix}
- [ ] {follow-up issue link}

## Patterns (if applicable)

**Start:** {things to begin doing}
**Stop:** {things to stop doing}
**Continue:** {things that are working well}
```

## `--review-patterns` Mode

When invoked with `--review-patterns`, skip the retro workflow and instead:

1. Read all `retrospectives/*/RETRO.md` files in the project
2. Extract the "Gaps Identified" and "Patterns" sections from each
3. Look for recurring themes across retros
4. Present a consolidated **Start / Stop / Continue** analysis
5. Highlight any gaps that appeared in 2+ retros (these are systemic)

## Guidelines

- **Be direct, not diplomatic.** The point is to improve, not to feel good. If something was missed, say so plainly.
- **Use specific evidence.** "The prompt had field name mismatches" is useful. "There were some issues" is not.
- **Distinguish between process problems and one-off mistakes.** A field name mismatch is a one-off. Not testing with real data is a process gap.
- **Don't over-document.** The retro should be useful to re-read in 3 months, not exhaustive. One page is ideal, two is the max.
- **Create issues for follow-ups.** Don't let action items live only in the retro doc — they'll be forgotten. Track them where work is tracked.
