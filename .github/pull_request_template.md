<!--
Thanks for contributing to MemoryHub!

Before opening this PR, please skim CONTRIBUTING.md and CLAUDE.md in
the repo root for our conventions. A few highlights:

- Small, focused PRs that touch one subsystem land faster than big ones.
- Commit messages follow conventional format: `subsystem: Imperative
  summary`. See `git log` for examples.
- Every non-trivial change references a design document under docs/
  or an in-flight design under planning/. If no design doc exists,
  either add one or call out why the change is outside that workflow.
- We use an `Assisted-by: <tool/model>` trailer when AI tools helped
  draft the change. We do NOT use `Co-authored-by:` for AI assistance.
-->

## Summary

<!-- 1-3 sentences: what changed and why. -->

## Linked issues

<!-- e.g. "Closes #123" or "Refs #456". Every non-trivial PR should
     reference a tracked issue. -->

Closes #

## Design reference

<!-- Point at the design doc this PR implements against. For work
     that's still in planning/, link that instead. -->

- `docs/...`

## Type of change

<!-- Check one. Matches the `type:*` issue labels. -->

- [ ] `type:feature` — new user-visible capability
- [ ] `type:bug` — fix for incorrect behavior
- [ ] `type:infra` — build, CI, deploy, or tooling change
- [ ] `type:design` — design doc only, no code

## Subsystem

<!-- Check the primary subsystem this touches. Matches the
     `subsystem:*` issue labels. -->

- [ ] `memory-tree`
- [ ] `storage`
- [ ] `curator`
- [ ] `governance`
- [ ] `mcp-server`
- [ ] `operator`
- [ ] `observability`
- [ ] `org-ingestion`
- [ ] `auth`
- [ ] `ui`
- [ ] `llamastack`

## Test plan

<!-- Which infrastructure boundaries does this PR exercise?
     Check the option that best describes your test coverage. -->

- [ ] **Unit tests only** — no infrastructure boundaries touched
      (pure logic, no DB/Valkey/embedding service interaction)
- [ ] **Integration tests included for:** <!-- list subsystems -->
      `[ pgvector / Valkey / embedding service / auth / S3 ]`
- [ ] **Integration tests deferred because:**
      <!-- This should be rare. Justify why, and link the follow-up issue. -->

<!-- General verification: -->

- [ ] `pytest` passes locally (or the affected subset)
- [ ] Manual verification against a running cluster (if applicable)
- [ ] New tests added for new behavior

## Reviewer checklist

- [ ] Design doc referenced or created
- [ ] No committed credentials or cluster-specific URLs
- [ ] CLAUDE.md / docs updated if behavior or conventions changed
- [ ] Commit message follows `subsystem: Imperative summary` format
