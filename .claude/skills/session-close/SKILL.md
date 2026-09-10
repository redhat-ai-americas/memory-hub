---
name: session-close
description: Pre-session-close checklist. Audits tests, lint, tasks, uncommitted changes, doc staleness, version bumps, secrets, design-loop findings, and session-filed issues; remediates non-risky WARN items and writes a durable session summary for later audit review — committing automatically or preparing for approval per the project's commit-approval rule. Run before wrapping up a session.
---

# Session Close Checklist

Run this before ending a session to catch loose ends. The checks below are ordered from fast/mechanical to slow/judgmental. Report all findings as a single summary table, **remediate the WARN items that clear the right-size gate** (see "Remediating WARN items"), then **write the session summary** (check 11). The default is action, not just reporting: fix (or, where the project requires commit approval, prepare) the safe stuff, surface the risky stuff, and leave a durable record. **Whether remediations and the summary are committed automatically or prepared for approval is set by "Commit mode" below** — check it first.

## Invocation

```
/session-close [--no-test]
```

Operates on the current working directory.

**Flags:**
- `--no-test` — skip the test suite (check 1) and lint (check 2). Use for review-only or doc-only sessions where no code was changed. All other checks still run.

## Commit mode — respect the project's approval rule

Three steps in this skill can commit: WARN remediations ("Remediating WARN items"), session-filed fixes (check 10), and the session summary (check 11). Whether those commit **automatically** or **prepare-and-ask** depends on the project. Decide the mode **once, up front**, and state which mode you're in at the top of the final report so the user knows whether commits already happened.

**Prepare-and-ask mode — the safe default.** Use it if ANY of these hold:
- The harness gates commits anyway — plan mode, or `git commit` isn't pre-approved and would prompt. Don't fight the harness.
- The project's CLAUDE.md or a commit-related memory states a "don't commit without approval" / "commit only when the user asks" rule that doesn't carve out session-close or checkpoint commits.
- No project convention either way is found. When in doubt, prepare-and-ask.

**Auto-commit mode — only when explicitly authorized.** Use it only if the project has clearly opted into unattended commits for already-approved work — e.g. a checkpoint-commit / "run the completion checklist and commit at milestones" convention in CLAUDE.md or a `feedback_commit_*` memory. Invoking `/session-close` authorizes running the checklist; it is **not**, by itself, authorization to commit — the project's stance decides that.

- **In auto-commit mode:** make each fix, commit it atomically referencing the cause, push per the project's branch workflow, and report the hashes.
- **In prepare-and-ask mode:** still make the fixes in the working tree and write the summary to disk (they're safe to have on disk), but **do not commit or push**. Stage the changes, present each as a proposed commit (message + one-line diff summary) in the final report, and ask for approval. Nothing lands until the user says go.

Wherever a step below says "commit," it means "commit per Commit mode" — commit outright in auto mode, or stage-and-propose in prepare-and-ask mode.

## Checks to Run

### 1. Test suite

**Skipped when `--no-test` is passed.** Report as `SKIP — --no-test` in the table.

Find and run the project's test command. Look for (in order): `Makefile` with a `test` target, `pyproject.toml` with pytest config, `package.json` with a test script. Run it and report:
- Total passed / failed / skipped / errors
- Flag any **skipped** tests — these are often forgotten and may indicate incomplete work
- Flag any **failures** — these must be fixed before closing

### 2. Lint

**Skipped when `--no-test` is passed.** Report as `SKIP — --no-test` in the table.

Find and run the project's linter. Look for ruff, eslint, golangci-lint, etc. based on the project language. Report pass/fail.

### 3. CI status

Check the status of CI runs on the current branch. Local tests + lint passing tells you the disk is clean; CI tells you the deployed/pushed state is clean. They can disagree (different env, different node version, different secrets), and a green local + red CI is exactly the kind of thing that gets missed at session close.

Check whichever CI surfaces the project uses:

- **GitHub Actions** — if `gh` is installed and `.github/workflows/` exists: `gh run list --branch $(git branch --show-current) --limit 5 --json status,conclusion,name,createdAt,url`. Report the most recent run per workflow.
- **AWS Amplify** — if `amplify.yml` exists or the project documents an Amplify app ID: `aws amplify list-jobs --app-id <id> --branch-name <branch> --max-items 1`. Amplify builds are separate from GitHub Actions and frequently fail independently (env-var drift, monorepo path drift, build-spec changes).
- **Other CI** — `.circleci/`, `.gitlab-ci.yml`, `Jenkinsfile`, etc. Adapt accordingly.

For each surface, report:
- **PASS** — most recent run on this branch succeeded
- **FAIL** — recent run failed; include the run URL or job ID and a one-line summary of what failed if extractable
- **RUNNING** — currently in progress; note it but don't block the close
- **STALE** — no runs since the last local commit (push pending? CI not configured for this branch?)

Do not auto-retry failed builds. Surface the failure, include the retry command (e.g., `aws amplify start-job ... --job-type RETRY --job-id <id>`), and let the user decide whether the failure is transient (retry) or real (investigate).

### 4. Task list

Call `TaskList` to check for incomplete tasks. Report any tasks still in `pending` or `in_progress` status. These represent work that was planned but not finished — the user should decide whether to complete, defer, or delete them.

### 5. Git status

Run `git status` and report:
- **Staged but uncommitted** changes — likely a forgotten commit
- **Modified but unstaged** files — work that may need committing or discarding
- **Untracked files** — new files that may need to be added or gitignored
- Whether the branch is ahead of remote (unpushed commits)

For each category, list the files so the user can make a decision.

### 6. Secrets scan

If `gitleaks` is installed, run `gitleaks detect --source . --no-banner --verbose` and report findings. If not installed, note it as skipped and suggest installing.

### 7. Doc staleness

Check whether key documentation files reflect the current state of the code. This is a judgment call — read the files and look for references to things that changed during this session. Common places to check:
- `CLAUDE.md` (project-level) — architecture decisions, dependencies, conventions
- `docs/architecture.md` or equivalent — if it exists
- `README.md` — if significant features were added
- `NEXT_SESSION.md` or equivalent — if it exists and tracks session work

For each stale doc, report what's outdated and what needs updating. Do not auto-fix docs — present findings for the user to approve.

### 8. Version bump

Check if the project has a version number (pyproject.toml, package.json, Cargo.toml, etc.) and whether the changes in this session warrant a bump:
- **Patch** — bug fixes only
- **Minor** — new features, new public API surface
- **Major** — breaking changes

Report the current version and a recommendation. Do not auto-bump — present the recommendation for the user to approve.

### 9. Design-loop findings

**Run this check when the project has a design system** (look for `DESIGN.md`, `design-docs/`, a `src/components/brand/` directory, or design-related skills in `.claude/skills/`). Skip otherwise.

The premise: every session that touches UI accumulates micro-knowledge about the design system — bugs found in primitives, gaps between spec and code, ambiguities resolved on the fly, validations of brand stances. If these aren't surfaced back to the designer, the design loop weakens and the spec drifts from reality. Capturing them as you go means a fully built design system at the end, ready to power other screens and companion apps.

Audit the session for any of:

- **Brand-layer bugs found and fixed.** A primitive that didn't work right in some theme/mode/state (e.g. "Button primary text-white invisible in dark mode"). Even if patched in this session, the designer needs to know the spec described something that didn't actually work.
- **Missing primitives** that you had to work around or inline. A pattern that should be a brand primitive but isn't.
- **Undefined tokens.** CSS variables or design tokens referenced in code (or in spec docs) that aren't actually defined in the token source. They render as silent fallbacks.
- **Spec contracts that don't match reality.** A pattern doc (DESIGN.md, brand-stance.md, design response.html) describes behavior that the live primitive doesn't implement. Or vice versa: the primitive does something the spec doesn't document.
- **Design ambiguities resolved ad-hoc.** Places where the spec was silent and you made a judgment call. The designer should ratify or correct.
- **Live-vs-canonical drift.** The brand layer says one thing, but the production app uses a different component. (e.g. brand `<Sidebar>` extended, but live app uses a different nav component.) These gaps are usually invisible until someone goes to use the brand primitive somewhere else.
- **Brand stances validated under real use.** "Coral-soft reads as identity, not alarm" or "gold segmented stack reads as treasure pile" — positive validations are findings too, and reassure the designer their stance is working.
- **New patterns or copy that should be canonized.** Ad-hoc copy or layout you composed that's likely to recur — should it move into a copy module, a brand primitive, or DESIGN.md?

**Where findings go.** Look for an existing design-loop ledger in `design-docs/` (names vary by project: `Findings.md`, `Brand System Findings.md`, `Design loop ledger.md`). If none exists, suggest creating one. Append a dated section per session — one heading per finding, with: what was observed, the fix taken (if any), and the question for the designer (if any). Don't open a heavy design-call doc for every finding; the ledger is the lightweight running surface.

Cross-reference major findings: if a finding is also a real product bug, file a GitHub issue. If a finding is a real design question (not just a bug), flag it for a design-call doc per the project's design-call pattern — the next step there is `/design-call` (compose mode), which produces the call doc from the flagged finding.

Do not auto-write the ledger — present the findings as part of the summary, then ask if the user wants you to append them.

### 10. Session-filed issue close-out — you find it, you fix it

The premise: when you hit a problem mid-task that isn't what you're working on, the right move is to file an issue and stay focused — don't rabbit-hole into it. But the issue captures *what* without the loaded context that makes it cheap to fix: the files already understood, the root cause already in hand, the fix often already half-formed in the reasoning. That context evaporates at session end and gets re-paid next session as cold-start re-discovery. This check recovers it: before the context is gone, revisit the issues *this session* filed and close out the cheap ones now. The filing-during / fixing-at-close split is sequential, not contradictory — filing protects focus during the work; this step banks the context before it's lost.

**Scope: only issues created or touched during this session.** Enumerate them from the conversation — you filed them, so you have the numbers. As a backstop, cross-check the tracker (`gh issue list --author @me --search "created:>=<session-start-date>" --state open`, adapt to the project). Do **NOT** pull in arbitrary backlog issues: the entire value is the in-context discount, and sweeping cold issues is unbounded work that belongs to `/plan-next-session` triage, not here.

**Triage each against the project's right-size gate** — blast radius / reversibility / detectability (per the "Right-Size the Change First" section of CLAUDE.md; use equivalent judgment if the project has no such gate):

- **High on all three → fix it now.** Small blast radius, revertable in a single commit, and the build / a test / a smoke run would catch a mistake. The context is loaded — this is the cheapest this fix will ever be.
- **Low on any one → leave it filed.** Needs design, large blast radius, or a mistake would ship silently (e.g. `tsc`-invisible surfaces, data-destructive changes). That's exactly what makes it a real deferred issue — and confirming the deferral with a one-line reason ("kept open: needs design call") is itself a useful output.

**For each issue you fix:**
1. Make the fix to the project's normal standard — tests, lint, and the non-mocked verification step the project requires (smoke test / manual dev check), not mocks alone.
2. Commit it referencing the issue (`fix: … (#N)`) per the project's commit convention **and per Commit mode** (commit + close the issue with the hash in auto mode; stage + propose the commit and defer closing the issue in prepare-and-ask mode).
3. Add it to the summary so the user can review or revert.

Run it **before** `/plan-next-session` so planning triages a smaller, realer backlog.

### 11. Write the session summary (default, always)

Write a durable, honest overview of the session to `session-summaries/YYYY-MM-DD-{epic}-{slug}.md` (tracked in git — an append-only audit log). Run this **last**, after checks 1–10, so it reflects their results and any WARN remediation / check-10 fixes.

**The audience is a future audit reviewer** — a fresh session (largest model, high thinking) reading *several* summaries at once to judge work *against the plan*, offer critique and special guidance, and do backlog refinement. It has no context and can't trust a rosy write-up, so the summary's job is to **make its skepticism efficient**: state the planned scope so it can measure the delta, and point it at the soft spots instead of hiding them. Commit messages carry the implementation detail — this doc is the overview + the meta layer commits don't capture (plan-vs-actual, judgment calls, verification confidence, what entered the backlog).

**Honesty guardrail:** over-claiming wastes the reviewer's skepticism budget. Surface thin verification, skipped steps, and uncertain calls explicitly. This doc's value is calibration, not advocacy — a summary that hides a weak spot is worse than none.

**Credential guardrail:** never include literal credentials (API keys, tokens, passwords, client secrets) in the summary. If the session created or rotated a credential, reference its storage location instead (e.g., "rotated amb-benchmark key; stored in memoryhub-auth cluster secret"). This also applies to plans, issues, and any other committed text. Incident: a hex-format API key committed in a 2026-07-14 session summary required rotation and history scrubbing.

Keep it to roughly one screen. Use this fixed skeleton (uniform structure lets the reviewer compare the same section across sessions and spot cross-session patterns — recurring friction, repeated deferrals):

```
# Session Summary — YYYY-MM-DD · {epic} · {one-line title}

**Plan:** NEXT_SESSION-{epic}.md / #{issue}   **Commits:** {first}..{last} ({branch})
**Deployed:** dev+prod / dev / none   **Model:** {model}

## Plan vs. actual
Planned: <the plan's "Next", 1 line>. Shipped: <1 line>. Slipped: <+ why, or none>.
Scope: <stayed in scope / expanded to X because Y>.

## Shipped
- <one terse bullet per logical change; ref the commit hash — it carries the detail>

## Verification & confidence
- <what was proven and how: live-driven on real data / tsc-only / tests-only / asserted>
- Confidence: <high|med|low> — <one line why>

## Judgment calls & deviations
- <each non-obvious choice or departure from plan + one-line why>   (or "none")

## Backlog delta
Filed #N… · Closed #N… · Re-scoped #N… · Memory <slug> · Design-call <topic> · Deferred <item — reason>

## Drift & forward-collisions
- Backward — open issues this session's work changed the picture for: #N <still-valid | partly-done | now-stale | should-re-scope — one line why>   (or "none")
- Forward — capability built (or partly built) that a *later* issue or future epic phase envisioned: #N/<epic phase> <what was built + "→ commented on #N" | "→ comment proposed"> (or "none")

## For the reviewer
- Sanity-check: <1–2 calls most worth a second opinion>
- Thin verification: <anything proven weakly or not at all>
- Wants guidance: <where reviewer input would help>   (or "none")

## Risks / watch-fors
- <not-yet-an-issue risks; recurring friction worth a cross-session pattern check>
```

Write the file directly (don't gate *writing* on approval — it's a record, not a change). **Committing** it follows Commit mode: commit `docs: session summary YYYY-MM-DD {epic}` in auto mode, or leave it staged with that proposed message in prepare-and-ask mode. Either way, mention it in the final report and offer to revise if anything reads wrong.

### Drift capture — cheap now, reconcile later

The "Drift & forward-collisions" section fights **issue drift**: issues describe a point in time, and a session's work can decay them (backward) or quietly satisfy something a later issue/epic wanted (forward). Capturing this is cheap *only right now*, while you have the context — so capture it here; the expensive reconciliation (close / re-scope / merge) batches into `/reconcile`, not every session. Don't reconcile the backlog at session close; just flag candidates.

- **Backward:** you don't need to scan every open issue. Only flag the ones this session's work plausibly *touched* (same files/subsystem, or an issue you read/referenced). One line each — the reconcile step adjudicates.
- **Forward — post the pointer where the future session will look (the anti-duplicate-rebuild keystone).** The summary is read at review time, but a future session picking up issue #N reads *the issue*, not this summary. So for each forward-collision, leave a one-line comment on the target issue: *"<YYYY-MM-DD> session (#thisissue) built <capability> at `path` — check before building the <thing> here; see session-summaries/<file>."*

  **Posting policy (external write):** determine whether the target issue's repo is one the user owns — `gh repo view <owner>/<repo> --json viewerPermission -q .viewerPermission`. Determine the authenticated user via `gh api user -q .login`. If `viewerPermission` returns `ADMIN` or `MAINTAIN` (the user's own repos and org repos they administer), **post the comment automatically** and record "→ commented on #N". Otherwise **draft it and list it in the final report for approval** — record "→ comment proposed". Report which were posted vs proposed.

## Output Format

Present findings as a summary table:

```
| Check            | Status | Notes                                    |
|------------------|--------|------------------------------------------|
| Tests            | PASS   | 307 passed, 0 skipped                    |
| Lint             | PASS   | Clean                                    |
| CI               | PASS   | Amplify + GHA green on main              |
| Tasks            | PASS   | All completed                            |
| Git status       | WARN   | 2 modified files uncommitted             |
| Secrets scan     | PASS   | No secrets detected                      |
| Doc staleness    | WARN   | architecture.md references old API        |
| Version          | INFO   | 0.1.0 — recommend 0.2.0 (new features)  |
| Session issues   | INFO   | Fixed #412, #418; kept #415 (needs design)|
```

After the table, expand on any WARN or FAIL items with specifics, and on the session-issue close-out list the issues fixed (with commit hashes) and those kept open (with the one-line deferral reason).

## Remediating WARN items (default: fix the safe ones)

The default is **action, not a prompt**. After presenting the table, remediate every WARN item that clears the **right-size gate** — small blast radius, single-commit revertable, and a build / test / smoke run would catch a mistake — **committing each atomically per Commit mode** (outright in auto mode; staged + proposed in prepare-and-ask mode) with a message that names what it fixes. This generalizes check 10's "you find it, you fix it" from session-filed issues to all WARN items (uncommitted-but-clearly-yours changes, a stale doc, a self-inflicted red CI, lint you introduced, etc.). Note: making the *fix* in the working tree is fine in either mode — only the **commit** is gated by Commit mode.

**Surface — don't auto-fix — the risky ones.** A WARN item is risky (report it and let the user decide) if it is any of:
- **Ambiguous ownership** — could be a parallel session's in-flight work (unexpected uncommitted changes you didn't make). Never commit someone else's half-done work; check `git log`/blame first.
- **Data-destructive or security-state** — migrations that drop data, auth/MFA/secret changes, anything touching money movement.
- **Needs design or judgment** — the fix isn't obvious, or a mistake would ship silently (`tsc`-invisible surfaces, deploy-config).
- **Version bumps** — recommend, never auto-bump.

Report each remediation (with commit hash) and each surfaced-risky item (with the one-line reason it was left) in the final summary. Then, for anything left unfixed, ask: "Want me to handle any of these?"

## What This Skill Does NOT Do

- Does not commit or push *unrelated* in-flight work of ambiguous ownership — it surfaces that (see "Remediating WARN items"). Its own scoped remediations (check 10 + WARN fixes) and the session summary (check 11) are committed **only in auto-commit mode**; in prepare-and-ask mode they're staged with proposed messages and left for the user (see "Commit mode").
- Does not commit at all without the project's authorization — the default is prepare-and-ask (see "Commit mode"). Auto-commit requires an explicit project opt-in.
- Does not update NEXT_SESSION.md — run `/plan-next-session` after this for that
- Does not run deployment checks — those belong in a deploy skill
- Does not silently fix *risky* WARN items — those are surfaced for the user. Non-risky WARN items that clear the right-size gate are remediated by default (committed or prepared per Commit mode) and reported.

## Next step

After this skill finishes — WARN items remediated and the session summary written — run `/plan-next-session` to write NEXT_SESSION.md for the next working session.

**Division of labor with `/plan-next-session`:** the session summary (check 11) is the *backward-looking audit record*; NEXT_SESSION is the *forward-looking handoff*. Both are tracked in git. Don't duplicate the full "what landed" ledger in both — NEXT_SESSION's "What landed" can shrink to a one-line pointer at the summary file, keeping the forward handoff tight.

**The review cadence ladder.** The summary this skill writes is the *per-session* review tier and the raw feed for two coarser tiers above it: **`/reconcile`** (a rolling mid-epic review that reconciles the accumulated summaries against the plan and refines the backlog) and the **per-epic `/retro`**. Don't do heavy backlog reconciliation here at session close — capture cheaply now (the summary's backlog-delta / drift notes), and let `/reconcile` adjudicate them in batch. That cost split is deliberate: cheap capture every session, expensive reconciliation only periodically.
