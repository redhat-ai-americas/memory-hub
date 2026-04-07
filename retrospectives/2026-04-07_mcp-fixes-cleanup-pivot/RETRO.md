# Retrospective: MCP Fixes — Cleanup Pivot

**Date:** 2026-04-07
**Effort:** Plan + execute fixes for the 8 mcp-server issues filed in the 2026-04-06 `/exercise-tools` session
**Issues planned:** #47, #48, #49, #50, #51, #52, #53, #54
**Issues touched:** none of the planned 8 — all still in Backlog
**Issues filed:** #55 (deferred Cleanup B — memoryhub package naming collision)
**Commits:** `8a970bb`, `303bc36`, `03cd774`, `65bca6c`

## What We Set Out To Do

Execute four waves of fixes against the 8 issues filed during the 2026-04-06 exercise session:

- **Wave 1** (mcp-server only): #47 (broken `get_similar_memories` RBAC filter), #48 (orphan branches), #53 (`search_memory` `has_more`)
- **Wave 2** (`read_memory` schema redesign): #50 (drop `depth`, add `branch_count`), #52 (auto-resolved by #50)
- **Wave 3** (parent `memoryhub` package + service layer): #49 (bidirectional version walker), #51 (`current_version_id` pointer)
- **Wave 4**: #54 (TOOLS_PLAN.md sync)

Two deploys planned (after Wave 2 and Wave 3), one commit per issue, plus a separate `memoryhub` version bump commit.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Discovered two competing deploy scripts (`memory-hub-mcp/deploy.sh` working but template-derived; `memory-hub-mcp/deploy/deploy.sh` half-finished refactor with a path bug) and pivoted to fixing the deploy foundation **before** any feature work | Good pivot | A duplicate-deployment incident from the previous retro was caused by exactly this kind of inconsistency. Doing fixes against a broken deploy foundation would have re-created the problem. User explicitly approved the cleanup-first sequencing. |
| Discovered `src/memoryhub/` (server-side, root) and `sdk/src/memoryhub/` (client SDK) both declare `name = "memoryhub"` in their `pyproject.toml` despite having completely different code — and filed it as deferred Cleanup B | Good pivot (deferred) | Surfaced while planning Wave 3 (need to know which `memoryhub` the MCP container actually runs). Renaming is a cross-package refactor that doesn't belong in a feature session. Filed as #55 with a skeleton design doc at `docs/package-layout.md`. SDK is for future custom-agent work that does not yet exist; MCP server is critical path. |
| Added a Step 0 preflight to `deploy/deploy.sh` that catches the static-registration silent failure | Recovery of recurring action item | The 2026-04-06 retro filed an action item to add this and it had not been done. We were rewriting the entire deploy script — that was the moment to add it. Caught during this retro before the doc was written. |
| Did not start any of the 8 planned issues | Scope deferral | Cleanup work consumed the session. All 8 issues remain in Backlog with the wave plan and consumer-audit task already documented in `NEXT_SESSION.md` for direct continuation. |
| First-party / main-context-only working mode for the entire session | Deliberate mode shift | User requested it explicitly: "be very thoughtful... plan to delegate less to sub agents." The exception was a single delegated `make deploy` invocation in the sanity test, which produced exactly the right scoped output and no scope drift. |

## What Went Well

- **The cleanup-first pivot was the right call** and the user confirmed it in this retro: *"I'd rather stop and pay down technical debt than keep wading through the mud."* The position we'll be in next session is materially stronger as a result.
- **Discovery during planning surfaced two pre-existing problems** that would have bitten us during Wave 2 or Wave 3. The half hour spent reading the slash command files, both deploy scripts, and the SDK pyproject was high-leverage time.
- **The sanity test caught a real verification-logic bug** (terminating pods being counted as Running by the `--field-selector=status.phase=Running` check) **before** we needed to trust the script for actual fixes. The fix uses `.status.availableReplicas` from the Deployment, which is the actual source of truth.
- **Deploy script now has documented intent.** Comments explain *why* the namespace is hardcoded, *why* the rollout-restart is forced, *why* verification uses Deployment status not pod count. Future agents will understand the reasons, not just the rules.
- **Recurring action item closed.** The tool-registration preflight check (recurring from the 2026-04-06 retro) is now in `deploy/deploy.sh` Step 0, with both happy and failure paths verified before commit.
- **Three feedback memories saved** capturing the recurring patterns for future sessions: slash commands live in `memory-hub-mcp/.claude/commands/`, deploy is project-customized (not template), and don't delegate MCP work to sub-agents on memory-hub. Plus two retro-derived memories on pause-for-forks and default-to-delegation.
- **Cleanup B was scoped tightly.** Skeleton design doc + filed issue, no actual rename. The temptation to "just rename it while we're here" was real and was correctly resisted.
- **Issue #55 was filed cleanly** — properly added to project board, set to Backlog, references the new design doc, captures the placeholder→real-SDK history so future sessions know it isn't a stale leftover.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Recurring action item from previous retro (tool-count check) was not picked up until called out during this retro | Process — recurring | Fixed in `65bca6c`. Pattern below. |
| Pauses for direction were sometimes for unambiguous next-step decisions rather than real forks | Behavior | Saved as feedback memory `feedback_pause_for_forks_not_for_permission.md`. Going forward: announce, don't ask, when the next step is unambiguous within an agreed scope. |
| Zero issues from the planned 8 were fixed | Scope | Justified by the cleanup pivot, but worth being explicit about: this session under-delivered on the planned issue count. The next session is set up to make this back via `NEXT_SESSION.md` continuation. |
| `read_memory.branches` consumer audit (task #4 in this session's task list, prerequisite for #50) was never run | Carryover | Documented as the first item in `NEXT_SESSION.md`. |
| The `/deploy-mcp` slash command's verification step uses `mcp-test-mcp` to spot-check tools after deploy, but does not yet automatically diff the deployed tool count against expected (the build-time preflight catches the same failure mode but only at build time, not after deploy) | Defense-in-depth | Acceptable. The preflight runs before every build and is sufficient for the static-registration failure mode. A post-deploy automated tool-count check would require the slash command to call `mcp-test-mcp` programmatically, which is awkward to script. Leave for now. |

## Action Items

- [x] Add tool-count regression check to deploy script (closed in `65bca6c` during this retro)
- [ ] **Next session, first thing:** continue from `NEXT_SESSION.md`. Wave 1 → consumer audit for #50 → Wave 2 → deploy → Wave 3 → deploy → Wave 4 → retro
- [ ] All 8 planned issues remain in Backlog. Move each to In Progress as it is started, Done after this session's retro
- [ ] #55 stays in Backlog until the SDK becomes critical path (no action needed)

## Patterns

**Recurring (3rd time): Recurring deploy-script action items not picked up.** The previous retro filed "add tool count check"; this session rewrote the entire deploy script and didn't add it. We caught it during the retro and fixed it in `65bca6c`. **The lesson is not just "remember the action items" — it's that a retro action item that survives one session is much more likely to survive the next one. Patterns to break it:**

1. When touching a system that has open action items in a recent retro, **read the previous retro first**. Two-minute investment, high signal.
2. When closing a session with `NEXT_SESSION.md`, copy in any **carried-over action items** that still apply, not just new ones.

**New pattern: Discovery during planning saves time, even when it consumes time.** The half hour spent reading slash commands, deploy scripts, and the SDK pyproject during the planning phase looked like overhead. It revealed two pre-existing problems that would have caused 2x-bigger problems during Wave 2/3. Pattern to keep: **when entering a session that touches infrastructure, read the actual files before planning, not after**.

**New pattern: First-party verification mode is right for tech-debt paydown.** Default mode is aggressive delegation to preserve main context. For sessions where the user signals "we have a mess" or "be thoughtful," switch to first-party / main-context-only and treat sub-agents as a last resort. Saved as `feedback_default_delegation_except_paydown.md`. **The mode should switch back to default delegation as soon as the foundation is clean** — don't carry heavyweight mode into the next thing.

**New pattern: Pause for forks, not for permission.** Distinct from harness-level permission flags. Saved as `feedback_pause_for_forks_not_for_permission.md`.

**Confirmed by user:** *"This was an important adjustment that will help the next few sessions stay pointed the right direction. The position we'll be in a week from now is a function not only of our speed, but of our direction."* Direction matters more than per-session throughput.

**Start:** Read the previous retro before touching a system that has open action items in it.

**Start:** When closing with `NEXT_SESSION.md`, carry over still-relevant action items from the previous retro, not just new findings from this session.

**Stop:** Asking for permission to take the next obvious step in an agreed scope. Announce, don't ask.

**Stop:** Treating "be thoughtful" as "approve every micro-decision." Thoughtful means careful planning + clear communication, not necessarily more pauses.

**Continue:** Discovery-first planning. Read the actual files before proposing a plan.

**Continue:** Mode-switching between aggressive delegation (default) and first-party verification (tech-debt paydown), based on what kind of work the session is doing.

**Continue:** Filing tightly-scoped deferred issues with skeleton design docs when a problem is discovered mid-session but doesn't belong in the current scope. #55 was a clean example.
