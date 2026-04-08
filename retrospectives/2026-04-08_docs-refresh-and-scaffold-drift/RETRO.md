# Retrospective: First docs-refresh run + scaffold drift cleanup

**Date:** 2026-04-08
**Effort:** Run `/docs-refresh` for the first time on the repo, act on the findings, fix scaffold drift surfaced along the way, file an upstream bug, and push.
**Issues:** None tracked locally. Filed upstream: [rdwj/fips-agents-cli#5](https://github.com/rdwj/fips-agents-cli/issues/5).
**Commits:** `f255da9` · `78bd2db` · `0ce7694` · `269f6c9` · `b9a80b8` · `caeb910` · `ffe6baa` (pushed `5f298ab..ffe6baa` to `origin/main`).

## What We Set Out To Do

Run `/docs-refresh` — a lighter-weight companion to `/docs-reorg` that scans for broken links, stale path references, placement drift, package README version drift, `llms.txt` decay, and modern-docs posture gaps. Report-only by default. First run on this repo (no prior state file), so Phase 0 backfilled `.claude/docs-state.json` from git log before running the actual scan.

The scan surfaced six advisory findings. After reviewing them, the user triaged as follows:

1. **License fields** missing from 4 of 6 `pyproject.toml` files → fix with Wes Jackson / Apache-2.0.
2. **`CHANGELOG.md` and `SECURITY.md`** missing at repo root → add.
3. **`memory-hub-mcp/.fips-agents-cli/README.md`** had two broken See Also links → fix locally, file upstream issue at `rdwj/fips-agents-cli`.
4. **`memory-hub-mcp/README.md`** was still the unmodified FastMCP scaffold template → rewrite to describe the actual server, using the `/update-docs` skill from `memory-hub-mcp/.claude/commands/update-docs.md` as the process guide.

Push everything when done.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| Self-surfaced "13 → 15 tool count" drift across 7 docs mid-task. The root README, `llms.txt`, `sdk/README.md`, `memoryhub-cli/README.md`, `docs/SYSTEMS.md`, `docs/mcp-server.md`, and `docs/ARCHITECTURE.md` all cited 13 tools. Actual count in `main.py` is 15 — #61's `set_session_focus` and `get_focus_history` landed after the 13-tool number was cemented into narrative docs. Fixed as a follow-on commit. | **Good pivot** — user confirmed post-hoc that "if you see something, say something" is the desired behavior. The drift was directly surfaced by the inventory work for the README rewrite, so the fix stayed in-scope. |
| Self-surfaced stale `.fn` testing convention in both project CLAUDE.md files while verifying whether `set_session_focus` / `get_focus_history` followed the same dev process as other tools. 0 of 16 test files actually use `.fn` at runtime; `test_register_session.py` even has an explicit comment pointing at `test_set_session_focus.py` as the proof that `.fn` is unnecessary. User asked "should we remove that stale note?" — fixed as a one-liner replacement in both the monorepo-root CLAUDE.md and `memory-hub-mcp/CLAUDE.md`. | **Good pivot** — the note was actively misleading future agents, and the user's question implied pre-authorization. |
| Filed `rdwj/fips-agents-cli#5` for the upstream scaffold bug instead of just patching locally. The `.fips-agents-cli/README.md` shipped a See Also section assuming the fips-agents-cli source-repo layout (`../GENERATOR_PLAN.md`, etc.), which breaks inside a generated project where those files don't exist. | **Good pivot** — local patch + upstream tracking is strictly better than either alone. Saved a project-scope reference memory (`181c88c9...`) pointing at the upstream issue so future scaffold syncs know to remove the local patch once upstream ships a fix. |
| Did NOT update `NEXT_SESSION.md`, which still points at "#62 — Pattern E real-time push notifications" as the next effort despite #62 being shipped in commit `a57abbf`. | **Scope deferral** — this session was docs hygiene, not feature planning. `NEXT_SESSION.md` is gitignored local state; updating it is a separate concern from the pushed work. Carry-forward. |

## What Went Well

- **Fork-then-announce-and-proceed held cleanly.** The user's initial ask was a multi-item list (licenses, CHANGELOG, SECURITY, scaffold fix, README rewrite, upstream issue). I sequenced them into separate logical commits with clear commit messages, and surfaced the two follow-on drifts (13→15, `.fn` note) as "I noticed this while doing your ask — fix it?" rather than either silently merging them into the primary task or ignoring them. User pre-approved the CLAUDE.md fix explicitly and retroactively approved the 13→15 sync. Matches `feedback_pause_for_forks_not_for_permission.md`.

- **Verified facts before recommending.** When asked whether to remove the stale `.fn` note, my first grep hit suggested `test_register_session.py` used `.fn`. Re-reading the actual grep output revealed it was a comment explicitly saying `.fn` is unnecessary. Ran the test suite to confirm both session-focus test files (25 tests) and the register_session tests (7 tests) pass without `.fn`. Three independent pieces of evidence before recommending the change — cheap and caught a misread.

- **Small logical commits, one purpose each.** 7 commits total; each is a single concern with a specific subsystem prefix (`docs:`, `infra:`, `memory-hub-mcp:`). No megacommits, no mixed-concern commits. Matches the project's commit-history convention in `user-level CLAUDE.md`.

- **Read the `/update-docs` skill file directly before rewriting the README.** The skill lives at `memory-hub-mcp/.claude/commands/update-docs.md` and is explicitly mentioned in `feedback_mcp_slash_commands_in_subdir.md` as something to read directly (not guess at). Followed the skill's Step 1 (inventory) → Step 2 (README tools section) → Step 4 (verify) structure. The rewritten README is 249 insertions / 578 deletions; every tool is documented with parameters, return semantics, and grouping.

- **Link-verified the rewritten README before committing.** 13 links, all resolved to local files under `memory-hub-mcp/..`. Ran a small Python verification script rather than assuming the links were right. Zero broken links in the new file.

- **Upstream issue filed with repro + three options.** Rather than just "this is broken," I filed `rdwj/fips-agents-cli#5` with the actual broken link listing, three fix options (drop the section / absolute URLs / two separate READMEs) with tradeoffs, and a reproduction command. Followed the user's "rdwj as submitter, no AI attribution" issue rule.

- **Memory hygiene matched the memory rules.** Saved one project-scope reference memory for the upstream issue tracking (derivable from git log is the anti-pattern to avoid; upstream-issue-to-local-commit mapping is NOT derivable). Saved one user-scope feedback memory for the "run /update-docs on any fips-agents scaffolded MCP server" rule the user established mid-session. Did NOT save memories for things already captured in the repo state (README content, tool count, CHANGELOG).

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| `/pre-commit` gitleaks scan was only run once at session start, not before every commit. Strict reading of user-level CLAUDE.md says "run before making a commit." | **Accept** — content added was text-only (metadata, docs, CHANGELOG, SECURITY, README). Zero source code changed. Gitleaks scan result doesn't change between commits on text-only diffs. User confirmed acceptable for this session; normal rule is "run each time when adding a lot of code." Local pre-commit hooks provide safety net. |
| `NEXT_SESSION.md` references `#62 — Pattern E real-time push notifications` as the next effort even though #62 shipped in `a57abbf`. | **Carry-forward** — gitignored local state, next session's concern. |
| `memoryhub-ui` tests and CLAUDE.md weren't touched despite `memoryhub-ui/backend/pyproject.toml` getting a license field. The description field I added (`"Backend service for the MemoryHub dashboard UI"`) wasn't in the original file and was a small judgment add without user approval. | **Accept** — tiny mechanical addition, neutral in impact, matches the pattern of all other sibling packages having a description. If wrong, easy to revise. |
| Did not run `mcp-test-mcp list_tools` post-session to confirm the rewritten README's 15-tool claim matches the deployed MCP server's registered tools. | **Accept** — no code changed in this session, only docs. The tool registration is in `main.py` which I inspected directly; the 15-tool count is authoritative from that file. No deploy happened, so no drift between repo state and deployed state is possible. |
| The fact that **scaffold drift is sticky** was known from the 2026-04-07 concept-close retro (which included "drop template leftovers" in commit `f315bd5`) but today's session surfaced 4 more scaffold artifacts that the earlier sweep missed: `memory-hub-mcp/README.md`, `memory-hub-mcp/.fips-agents-cli/README.md` See Also, the `.fn` CLAUDE.md convention, and the missing license fields. A single "grep for template keywords" pass doesn't catch everything. | **Process gap** — worth addressing by making "scaffold drift" a first-class category in `/docs-refresh` (or a dedicated sweep). See Start items. |

## Action Items

Immediate (this session):
- [x] All 7 commits pushed to `origin/main`.
- [x] Upstream issue `rdwj/fips-agents-cli#5` filed.
- [x] Project-scope reference memory saved for upstream issue tracking.
- [x] User-scope feedback memory saved for the "run /update-docs on any fips-agents-scaffolded MCP server" rule.

Carry-forward (next session):
- [ ] Update `NEXT_SESSION.md` to reflect that #62 shipped and point at whatever the next concrete effort is.
- [ ] Consider whether `/docs-refresh` should grow a dedicated "scaffold drift" phase that grep-checks for known template artifacts (`"FastMCP Server Template"` README title, `.fips-agents-cli/` See Also broken targets, missing license/author on subproject `pyproject.toml`, stale `.fn` test conventions, etc.) — these are all things that a generic link-checker or placement-drift check won't find.

## Patterns

**New pattern — "If you see something, say something" is explicitly welcome, not scope creep.** When drift surfaces as a side effect of the primary task, surfacing and fixing it in-scope is the desired behavior, not an over-reach. User confirmed: "The self-surfaced drift was actually welcome and did exactly what I would have wanted." This extends `feedback_pause_for_forks_not_for_permission.md` — announce-and-proceed doesn't just apply to forks the user asked about, it also applies to drift the agent surfaces organically while doing the asked work. Guardrail: the drift has to be in-scope (tied to the primary task), mechanical (not a judgment call), and announced in the session summary so the user can push back if over-reach happened.

**New pattern — Scaffold drift is sticky and recurring.** The 2026-04-07 "drop template leftovers" pass missed: (a) the MCP server README still titled "FastMCP Server Template", (b) broken See Also links in the `.fips-agents-cli/` directory, (c) the stale `.fn` testing convention frozen at FastMCP 2 behavior, and (d) missing `license`/`authors` on 4 of 6 pyproject.toml files. A grep-for-"template" one-off doesn't catch everything because scaffold drift hides in many shapes: default titles, placeholder authors, outdated convention docs, boilerplate "See Also" sections with wrong relative paths. The user confirmed this is a known problem: "The mcp server template I use comes with some examples and boilerplate stuff. I often forget to remove it." Treat it as a recurring category, not a one-time cleanup.

**New rule (saved as user-scope feedback memory) — Always run `/update-docs` on any MCP server scaffolded from the fips-agents template.** The template ships with boilerplate that the author habitually forgets to remove. Running `/update-docs` after initial scaffolding, after adding/removing tools, or during a docs-refresh sweep catches the drift by forcing an actual-implementation inventory against the README and ARCHITECTURE.md. Saved as a cross-project rule, not memory-hub specific.

**Confirmed pattern — Small, single-purpose commits with subsystem prefix matter.** 7 commits for a docs hygiene session is not "too many"; it's the right shape for a mixed-concern cleanup where each fix has its own rationale. Reviewers and git blame both benefit. Matches the project's existing commit-history discipline.

**Confirmed pattern — Verify facts before recommending, even when "obvious."** The `.fn` grep misread almost had me recommend keeping the note. One extra verification pass (running the test files, re-reading the grep output carefully) caught the misread cheaply. Cost of verification is tiny; cost of recommending the wrong thing to the user is much higher.

**Start:**
- Treating scaffold drift as a named category. Either fold a "scaffold drift" phase into `/docs-refresh` or run a dedicated sweep periodically.
- Running `/update-docs` on any MCP server built from the fips-agents template as part of the standard post-scaffold workflow (now captured as a user-scope memory).

**Stop:**
- Nothing from this session. No process anti-patterns to retire.

**Continue:**
- Self-surfacing drift during related work and announcing it in the session summary.
- Small logical commits, one concern each.
- Verifying facts (re-running grep, running tests) before recommending.
- Filing upstream issues with repro + options when local-only patches leave a latent problem for the next scaffold sync.
- Reading project-local skill files directly (`/update-docs`, `/deploy-mcp`) before executing them in main conversation context.
