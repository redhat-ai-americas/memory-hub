# SDK contract test for kagenti-adk integration

Status: Follow-up — 2026-04-28
Tracks: (no GitHub issue yet — file when picking up)
Author: @rdwj (drafted with Claude Code Opus 4.7)

## Why this exists

The `memoryhub` Python SDK now has its first known external consumer: the kagenti-adk project (https://github.com/kagenti/adk) ships a MemoryStore extension that wraps `MemoryHubClient`. The integration baseline is `kagenti/adk` PR #231. See [`docs/SYSTEMS.md`](../docs/SYSTEMS.md#kagenti-adk) for the full integration profile.

The SDK currently has no test that mirrors how kagenti-adk consumes it. If we ship a breaking SDK change — rename a field, change a method signature, replace an exception class on the happy path — we will not catch it in our own test suite. We will hear about it when kagenti-adk's CI breaks, or worse, when a downstream user of kagenti-adk reports the failure.

We need a contract test that locks the SDK shape we promised to kagenti-adk. The test does not have to exercise every branch — it only needs to fail when we change something kagenti-adk depends on.

This document is the proposal for that test. **No code in this document.** Implementation is a future session.

## What to mirror

The contract is exactly the surface kagenti-adk's MemoryStore touches. From reading `kagenti/adk` PR #231:

- **Constructor.** `MemoryHubClient(...)` with keyword arguments `mcp_url`, `api_key` *or* `oauth_url` + `oauth_client_id` + `oauth_client_secret`, `project_id`, optional `timeout`. Both auth paths must construct without error against test fixtures.
- **`search`.** `client.search(query, scope=..., max_results=..., project_id=...)` returns a list of memory objects with at least `id`, `content`, `weight`, `scope`, `project_id` fields. The list shape and field names are load-bearing — the kagenti store iterates and projects them.
- **`write`.** `client.write(content, scope=..., project_id=..., domains=..., weight=...)` returns a `WriteResult` with `.id`, `.curation`, and `.curation.reason` accessible. The curation veto path (write blocked by a curation rule) must surface via `WriteResult.curation.reason` — kagenti reads that field directly to log why a memory was dropped.
- **`read`.** `client.read(memory_id)` returns the same memory object shape as `search` results. Must raise `NotFoundError` (importable from `memoryhub.exceptions`) for an unknown id, not return `None` and not raise a generic exception.
- **`update`.** `client.update(memory_id, content=..., weight=..., domains=...)` returns the updated memory object.
- **`delete`.** `client.delete(memory_id)` returns `None` on success and raises `NotFoundError` on missing id.
- **Exception class.** `NotFoundError` must be importable from `memoryhub.exceptions` and must be raised from `read` and `delete` for missing ids. The kagenti store catches it explicitly; renaming it or moving it would break.

## Where the test should live

`sdk/tests/test_sdk_kagenti_contract.py` — sibling to the existing SDK tests, runs as part of the SDK's `pytest tests/ -q` suite.

The test is a *contract* test, not an integration test. It should not require a running MemoryHub server. Use the SDK's existing test doubles / mocked `_call` plumbing (see how `test_client.py` in the SDK already stubs the MCP transport).

If a real-server smoke test is also wanted, a separate `tests/integration/test_sdk_kagenti_live.py` gated behind `MEMORYHUB_E2E_URL` would mirror what kagenti's own E2E gate does. That is optional — the contract test is the part that pays for itself.

## What "fail loudly" looks like

The test should fail with an obvious, attributable error message when:

1. Any of the listed methods is renamed or removed.
2. Any keyword argument the kagenti store passes is renamed.
3. A method's return type loses one of the listed fields.
4. `NotFoundError` is renamed, moved out of `memoryhub.exceptions`, or stops being raised on missing-id reads/deletes.
5. `WriteResult.curation.reason` becomes inaccessible (renamed, removed, or wrapped in a different attribute path).

The test does **not** need to fail when:

- New optional kwargs are added.
- New fields are added to return objects.
- New exception classes are added.
- Internal helpers change.

In other words, this is a "no breaking changes to the kagenti-adk surface" test. Additive evolution stays green; removals and renames go red.

## Coordination with kagenti-adk

When this test exists, the SDK's release process gains one extra rule: **a failure in `test_sdk_kagenti_contract.py` requires a coordination message to kagenti-adk maintainers before the SDK release ships.** The fix is one of:

- Revert the breaking change.
- Land a compatibility shim (e.g., keep the old name as an alias for one release).
- Pre-announce the break and ship a coordinated kagenti-adk update.

## Out of scope

- Testing kagenti-adk's MemoryStore implementation. That is their test suite, not ours.
- Testing the OAuth `client_credentials` exchange end-to-end. The auth service has its own tests; the SDK contract test only needs to verify the constructor accepts the OAuth kwargs without raising.
- Testing the MCP wire format. That is what the existing MCP server tests cover.

## Open questions

- Should the contract test take the kagenti-adk store import as a dependency (so we test against the real consumer code) or duplicate the call patterns inline? Importing locks us tighter and catches more, but creates a circular dev dependency. Inline duplication is looser but does not require kagenti-adk to be installed in our SDK dev environment. Recommend **inline duplication** for the first pass, with the imports documented as the upgrade path.
