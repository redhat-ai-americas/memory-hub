# Session Continuity

Use this rule when your agent works on tasks that span multiple
sessions — document processing pipelines, multi-step research,
compliance reviews, ops runbook execution, or any long-running workflow
where context windows are too small for the full task. If your agent
handles only single-turn Q&A, this rule is not needed.

The core discipline: **pick ONE item per session, complete it fully,
verify it, hand it off clean.** This prevents one-shotting (trying too
much), premature victory (declaring done without testing), and broken
state (leaving partial work).

## Resume Protocol

At the start of each session, before beginning new work:

1. Check for available work items using `check_available_work`.
2. If a work item has a handoff note from a previous attempt, read it
   carefully before planning your approach.
3. Verify the environment is ready (relevant services are reachable,
   previous outputs still exist).
4. Pick ONE item to work on. Do not attempt multiple items in a single
   session.

## During Execution

- Call `update_work_progress` periodically to record status and renew
  your lease.
- If you encounter a blocker you cannot resolve, release the item
  rather than spinning.

## Handoff Protocol

Before your session ends or budget runs low:

1. Verify what you accomplished (run tests, check outputs).
2. If complete: call `complete_work_item` with a result summary and
   list of accomplishments.
3. If incomplete: call `release_work_item` with:
   - **accomplished**: concrete, verifiable statements of what was done
   - **remaining**: scoped to this work item, not the entire project
   - **blockers**: external dependencies, missing access, infrastructure
     issues
   - **context**: anything the next agent needs to know
4. Include artifact references (file paths, commit SHAs, URLs) so the
   next agent can pick up without searching.

## Incremental Progress

- Prefer depth over breadth. Complete one thing well rather than
  starting many.
- If a work item is too large for a single session, release it with a
  detailed handoff note rather than rushing to finish.
