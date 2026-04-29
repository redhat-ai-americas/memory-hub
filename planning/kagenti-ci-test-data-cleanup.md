# Cleanup strategy for kagenti-ci test memories

Status: Skeleton — 2026-04-29
Tracks: (no GitHub issue yet — file when picking up)
Author: @rdwj (drafted with Claude Code Opus 4.7)

## Why this exists

The kagenti-adk project (https://github.com/kagenti/adk) now runs an E2E test against our public MemoryHub MCP route as the `kagenti-ci` user. Each CI run will create memories. Without a cleanup story, the test instance grows unbounded — gigabytes of "user mentioned: ..." style fixture writes accumulating on the cluster, polluting future searches and consuming storage.

We need to decide how cleanup happens. See [`docs/SYSTEMS.md`](../docs/SYSTEMS.md#kagenti-adk) for the full integration profile and [`docs/runbooks/add-mcp-api-user.md`](../docs/runbooks/add-mcp-api-user.md) for how the `kagenti-ci` user was provisioned.

This document is the proposal for the cleanup strategy. **No code in this document.** Implementation is a future session.

## Options

### Option A — test-side cleanup (preferred)

The kagenti-adk E2E test creates and deletes its own memories within a single test run.

- Pro: zero state outside the test boundary; cleanup is the same code path that exercises `delete()`.
- Pro: kagenti-adk owns its own lifecycle, no cross-project coordination.
- Con: a crashed test leaves memories behind; needs a sweeper for those orphans.
- Con: kagenti-adk has to write the cleanup; coordination with @JanPokorny.

### Option B — periodic janitor on our side

A scheduled task on our cluster wipes everything in a dedicated `kagenti-tests` project at a regular cadence (daily? weekly?).

- Pro: kagenti-adk doesn't need to care about cleanup.
- Pro: handles orphans from crashed tests automatically.
- Con: we own and maintain a cron job for an external consumer's test data.
- Con: requires the kagenti-ci user to be scoped to a specific project so the wipe is bounded.

### Option C — accept slow growth

Do nothing. Revisit when storage actually hurts.

- Pro: zero work today.
- Con: kicks the can; the longer we wait, the more painful the eventual cleanup.
- Con: search relevance on the test instance gets worse over time as fixture noise accumulates.

## Recommendation

Option A as the v1 (kagenti-adk creates and deletes within the test) plus Option B's *idea* without the cron — i.e., scope the `kagenti-ci` user to a `kagenti-tests` project so the blast radius is bounded. Add a manual `oc exec` recipe to wipe that project on demand (operator-triggered, not scheduled). Move to a real scheduled janitor only if orphans become a problem.

## What needs deciding

- Which option (or hybrid) do we land on?
- If Option A: who writes the kagenti-adk PR — us or @JanPokorny?
- If Option B: cadence, what counts as a "test memory" (whole project? memories tagged `kagenti-ci`?), and where the janitor runs (CronJob in `memory-hub-mcp` namespace? scheduled-agent?).
- Does the `kagenti-ci` user need to be scoped down to a `kagenti-tests` project regardless of option chosen? (Recommend yes — bounds the blast radius cheaply.)

## Out of scope

- General memory-store retention/TTL policy. That is a separate, larger conversation.
- Cleanup for other downstream consumers. We have one (kagenti-adk) today; revisit when there are more.
