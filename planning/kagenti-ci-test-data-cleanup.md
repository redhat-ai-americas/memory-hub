# Cleanup strategy for kagenti-ci test memories

Status: Decided — 2026-04-30 (issue #207)
Author: @rdwj (drafted with Claude Code Opus 4.7)

## Why this exists

The kagenti-adk project (https://github.com/kagenti/adk) runs an E2E test
against our public MemoryHub MCP route as the `kagenti-ci` user. Each CI
run will create memories. Without a cleanup story, the test instance grows
unbounded — gigabytes of "user mentioned: ..." style fixture writes
accumulating on the cluster, polluting future searches and consuming
storage.

This document records the decision. See [`docs/SYSTEMS.md`](../docs/SYSTEMS.md#kagenti-adk)
for the full integration profile and [`docs/runbooks/add-mcp-api-user.md`](../docs/runbooks/add-mcp-api-user.md)
for the API-key provisioning workflow.

## Decision

**Option A (test-side cleanup) + scoped `kagenti-tests` project with
`invite_only=true`.**

- The kagenti-adk E2E test wipes its memories at start *and* end of every
  run via the `memoryhub` SDK delete path. The start-of-run wipe handles
  orphans from crashed prior runs.
- The `kagenti-ci` user is the only member of a dedicated `kagenti-tests`
  project. The project is `invite_only=true`, so no other actor can
  silently auto-enroll and write into it.
- No scheduled janitor today. Revisit only if orphans actually accumulate
  despite the start-of-run wipe.

This matches @JanPokorny's [confirmation](https://github.com/redhat-ai-americas/memory-hub/issues/207#issuecomment-4345963162):
"If we can have a scoped instance, we can just wipe at the end of test run
(and also at start to make sure)."

## Why this works (enforcement primitive)

`ensure_project_membership()` in `src/memoryhub_core/services/project.py`
raises `ProjectInviteOnlyError` for non-members trying to write to an
invite-only project (lines 83–84). The default `invite_only=false`
auto-enrolls writers, which would NOT bound the blast radius — the
`invite_only=true` flag is load-bearing here.

Read enforcement is already strict regardless: `authorize_read` in
`core/authz.py` (lines 156–161) requires explicit membership for
project-scope memories.

## Options that were considered

### Option A — test-side cleanup (chosen)
Pro: zero state outside the test boundary; cleanup uses the same code
path that exercises `delete()`.
Pro: kagenti-adk owns its own lifecycle, no cross-project coordination.
Con: a crashed test leaves memories behind — handled by the start-of-run
wipe.

### Option B — periodic janitor on our side
Rejected for now. Adds a CronJob to maintain for an external consumer's
test data. Revisit only if Option A's start-of-run wipe is insufficient.

### Option C — accept slow growth
Rejected. Kicks the can; search relevance on the test instance degrades
as fixture noise accumulates.

## Provisioning steps

1. Generate `kagenti-ci` API key with `openssl rand -hex 8`.
2. Patch `memoryhub-users` ConfigMap in `memory-hub-mcp` namespace; scopes
   `["user", "project"]`. Restart the deployment per the runbook.
3. Create the `kagenti-tests` project with `invite_only=true` via
   `memory(action="create_project", project_id="kagenti-tests",
   options={"invite_only": true})`.
4. Add `kagenti-ci` as the only member via `memory(action="add_member",
   project_id="kagenti-tests", options={"user_id": "kagenti-ci"})`.
5. Hand the key to @JanPokorny over a private channel for the
   `kagenti/adk` repo secret store.

## Out of scope

- General memory-store retention/TTL policy.
- Cleanup for other downstream consumers (we have one today).
- Tightening default `invite_only` semantics for other projects — that's
  a separate, larger conversation tied to the
  `project_retro_item_project_write_restriction` retro item.
