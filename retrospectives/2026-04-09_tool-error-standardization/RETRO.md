# Retrospective: #97 Tool-Error Standardization

**Date:** 2026-04-09
**Effort:** Standardize all 15 MCP tools to raise `ToolError` instead of returning error dicts. Add SDK prefix classifier. Regression test.
**Issues:** #97 (umbrella), #128–#139 (12 sub-issues). 10 closed, 2 remaining (#138 docs, #139 close-out).
**Commits:** `b6dd026`..`8adfee1` (10 commits on main)
**PRs:** #140–#149 (10 merged)

## What We Set Out To Do

Per the NEXT_SESSION briefing: file 12 sub-issues, land #47 (already closed), land sub-issues 1 and 9 (the reference pair), deploy. Expected output: 4 PRs + 12 issues in ~one session.

## What Changed

| Change | Type | Rationale |
|---|---|---|
| #47 was already closed — briefing referenced stale state | Scope discovery (recurring) | Third time a briefing lists an issue as open that's already closed (#98, #83, now #47). The "30-second sanity check" gap from the last two retros recurred. |
| Landed 10 sub-issues instead of 2 | Good pivot | Once the pattern was proven with sub-issues 1 and 9, the remaining 6 tool conversions were mechanical. Parallel worktree agents made this efficient. ~25 min for 6 simultaneous conversions. |
| Deploy blocked on PG password placeholder | Blocker discovered | `deploy/openshift.yaml:40` has `REPLACE-ME`. Pre-existing, not a session regression. |
| set_curation_rule sub-agent failed to commit/push | One-off failure | Agent completed code changes but stalled at pre-commit. Manual pickup was fast (~5 min) since the pattern was identical. |

## What Went Well

- **Parallel worktree agents at scale.** 6 tool conversions launched simultaneously, each in an isolated worktree. 5 of 6 landed their PRs autonomously. Zero git state collisions. The `isolation: worktree` rule from the 2026-04-08 retro is fully validated — this is the first session that exercised it with 6+ concurrent agents.
- **Pattern-first sequencing.** Landing sub-issues 1 (smallest tool, 1 error site) and 9 (SDK) first established the canonical pattern. Every sub-agent prompt included "read commit 4b901b2 for reference." Result: all 8 tool diffs are consistent in shape, import ordering, guard placement, and log format.
- **Review throughput.** 10 PRs reviewed and merged in ~30 minutes. CI was the gate, not manual review — the mechanical nature of the conversions meant reviewing one diff closely and spot-checking the rest was sufficient.
- **The `except ToolError: raise` guard.** Discovered during sub-issue 2 (read_memory) that ToolErrors raised inside the try block get caught by the `except Exception` handler and re-wrapped. The fix (`except ToolError: raise` before the generic handler) was added to the pattern and propagated to all subsequent tools. Caught by a test failure, not by inspection.
- **Regression test ships with the fix.** `test_no_error_dicts.py` (39 lines) greps all tool files for `"error": True` and fails if any found. Prevents reintroduction without any ongoing maintenance.

## Gaps Identified

| Gap | Severity | Resolution |
|---|---|---|
| Deploy not done — PG password placeholder blocks it | Medium | Manual fix: `oc get secret postgresql -n memoryhub-db -o jsonpath='{.data.database-password}' \| base64 -d` then update `deploy/openshift.yaml:40`. Do before next contributor session. |
| Docs sub-issue (#138) not started | Low | Issue exists, Backlog. No functional impact. |
| Briefing listed #47 as open (was closed) | Process (recurring, 3rd time) | See Patterns below. |
| Sub-agent can't invoke slash commands | Process | The set_curation_rule agent was told to run `/pre-commit`, which is a slash command. Sub-agents should be told `gitleaks detect --source=. --no-banner` directly. |
| Cross-consumer audit for write_memory was delegation-only | Low (no issues found) | The write_memory sub-agent grepped `memoryhub-ui/backend/`, `sdk/src/`, and `memoryhub-cli/` and found no consumers depending on error-dict shape. Reported in PR body. Trusted but not independently verified. |

## Action Items

- [ ] Fix PG password placeholder and deploy (`deploy/openshift.yaml:40`)
- [ ] Land #138 (docs update) — TOOLS_PLAN.md, README, docs/mcp-server.md
- [ ] Close #139 and #97 after #138 lands
- [ ] In sub-agent prompts, always use `gitleaks detect --source=. --no-banner` not `/pre-commit`

## Patterns

**Recurring (3rd time): Briefing references stale issue state.** #98 (retro 2026-04-08), #83 (retro 2026-04-08), #47 (this session). Filed as #126 (`scripts/issue-sanity-check.sh`) in the last retro — still in Backlog. The workaround this time was cheap (just skipped #47), but the pattern persists. Recommendation: **land #126 or accept the cost.** Partial mitigation already exists — the briefing author (previous session's Claude) should `gh issue view` each referenced issue and include its state in the briefing. That's a convention fix, not a tooling fix.

**Validated: `isolation: worktree` for parallel git-modifying sub-agents.** First large-scale test (6 concurrent agents). Zero collisions, 5/6 success rate. The one failure was a slash-command issue, not a git issue. Rule is load-bearing and should stay.

**New: sub-agent prompts need explicit gitleaks command, not slash-command reference.** Sub-agents cannot invoke `/pre-commit`. One agent stalled because of this. Include the direct command in every prompt that expects a commit.

**Continue:**
- Pattern-first sequencing (land the reference implementation, then parallelize the mechanical copies)
- Regression tests that ship with the fix, not as follow-ups
- CI as the primary merge gate for mechanical changes — spot-check review is sufficient when the pattern is proven
