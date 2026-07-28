# Next Session -- Deploy

## Next: Cleanup sweep -- prune branches, close stale issues, fix OGX test

Housekeeping before merge. The `fix/make-args-passthrough` branch has 15
commits of deploy hardening + multi-cluster credentials work. Wes is doing
a manual golden test before merge. Meanwhile, prune the 100+ accumulated
branches and worktrees, close OGX/Kagenti issues that will never ship,
and fix the pre-existing OGX test failure.

1. **Delete 37 merged branches + 12 stale worktrees** (mechanical)
   `git branch -r --merged origin/main` gives the list. All worktree
   dirs under `.claude/worktrees/agent-*` are stale (12 dirs, some locked).
   Remove worktrees first (`git worktree remove --force`), then delete
   local and remote branches. No judgment needed -- these are all merged.

2. **Triage ~70 unmerged branches** (needs judgment, batch by category)
   Work through these groups, checking each for unmerged content:
   - `docs/session-summary-*`, `docs/session-close-*` (~15) -- session
     artifacts. Content likely already in `session-summaries/`. Verify,
     then delete.
   - `feat/dreaming-*` (~8) -- dreaming epic sub-branches. Most content
     landed via PR #449. Diff against main to confirm, then delete.
   - `fix/default-context`, `fix/golden-path-*`, `fix/install-vetting`,
     `fix/self-contained-install` -- deploy fixes. Check if content
     landed on `fix/make-args-passthrough` or main.
   - Old numbered branches (`170-*`, `196-*`, `209-*`, `213-*`, `219-*`,
     `220-*`, `221-*`) -- April/May era. Likely superseded. Diff to
     confirm no unmerged value.
   - `worktree-agent-*` remote branches (3 unmerged) -- agent leftovers.
   - Everything else -- triage individually.

   **Rule: if a branch has unmerged commits with real value, surface it
   to the user before deleting. If it's docs/session-summaries that are
   already captured, or code that landed via a different branch, delete.**

3. **Close OGX/Kagenti issues** (6 issues, won't-do)
   - #28, #29, #30 -- Kagenti phases 1-3 (connector never completed)
   - #309 -- OGX demo as fips-agents app (packaging never happened)
   - #316 -- OGX demo blockers (never resolved)
   - #32 -- LlamaStack phase 2 (never built)
   Close with a brief "won't-do" comment. Keep #310 (framework-agnostic
   onboarding) open -- it's broader than OGX.

   Keep: OGX instruction format (working), OGX demo (built), Kagenti
   contract tests (10/10 pass), all historical retros/research.

4. **Fix pre-existing OGX test failure**
   `test_render_instructions_ogx_includes_run_yaml_snippet` asserts
   `provider_id: memoryhub` but the template was updated to use
   `provider_id: model-context-protocol`. Update the assertion.

5. **Remove stale triage labels** from `ops/triage/config.py`
   Remove `subsystem:kagenti` and `kagenti-candidate` from the label
   lists since there won't be new Kagenti issues.

6. **Version bump 0.11.0 -> 0.12.0** (if golden test passes)
   Bump in `memoryhub-cli/pyproject.toml`. Only do this after Wes
   confirms the manual test passed and we're ready to merge.

**Sequencing.** Item 1 first (mechanical, clears the noise). Item 2 is
the bulk of the session -- work through categories, surface anything
with unmerged value. Items 3-5 are quick and independent. Item 6 waits
for golden test confirmation.

**Constraints for the session:**
- Do NOT delete `fix/make-args-passthrough` -- that's the active branch
  awaiting merge
- Do NOT delete branches that have open PRs -- check with `gh pr list`
- For unmerged branches with real value, surface to user before deleting
- Keep all retrospective and research branches (historical record)

**Session start protocol:**
- Premise checks: `git fetch --prune` to sync remote state; `gh pr list
  --state open` to identify branches with active PRs; confirm
  `fix/make-args-passthrough` is still the active deploy branch
- Rules with history: deploy scripts main-context only (2026-05-19
  incident); all pushes to main through PRs
- Stop-and-ask before: deleting any branch with unmerged commits that
  look like real work (not session artifacts); closing issues
- Close ritual: session summary; archive this file if the branch merged

## What landed last session (2026-07-24)

Multi-cluster API key management (#451) -- replaced flat
`~/.config/memoryhub/api-key` with INI-style `~/.config/memoryhub/credentials`
keyed by cluster context. Full implementation: core library + tests, deploy
writers, hook scripts, all readers and docs.

**Commits:** b132fc6..3509c2d on `fix/make-args-passthrough` (5 commits)

**Branch status:** 15 total commits on the branch (7 from prior deploy
hardening + 4 credentials + 1 lint fix + 1 session summary + 2 prior).
Pushed to remote, awaiting manual golden test then PR to main.

**Follow-ups filed:** none. **Issues resolved:** #451 (partial, pending merge).

## Watch out for

- **Locked worktrees.** Two worktrees show as `locked` -- use
  `git worktree unlock` then `git worktree remove --force`.
- **Stale worktree installs.** This session hit a stale `pip install -e`
  pointing at a worktree instead of the main tree. After removing
  worktrees, run `pip install -e .` in memoryhub-cli to ensure the
  editable install points at the right source.
- **Branch deletion is irreversible on remote.** The reflog keeps local
  branches recoverable, but `git push --delete` is permanent. For
  unmerged branches with any doubt, check before deleting.
- **Pre-existing CI failures.** CLI and integration tests may still fail
  from the parallel dreaming session. Don't block on these for the
  cleanup work.

## If blocked

- If Wes hasn't done the golden test yet: do items 1-5 (cleanup) and
  leave item 6 (version bump + merge) for the next session.
- If a branch has valuable unmerged work: create an issue to track it
  rather than blocking the cleanup sweep.
