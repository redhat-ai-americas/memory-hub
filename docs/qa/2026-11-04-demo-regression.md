# Demo regression: 4 November 2026

This run revisits findings D01–D13 from the 3 November demo. It does not establish production release readiness. The original 98 evidence files and four frozen oracle files are unchanged, verified by SHA-256.

## Source and deployment

Starting revision: `def2cbad1339a6e252fb06517b9e37a3463c2abd` (`ui-update`). The missing UI project-lifecycle work from `945e356` and `668049e` was integrated in `b5ba8ad`. Regression fixes are in `211e726`.

The original demo UI and a separate regression UI tenant use the same built artifact. MCP was rebuilt with the same core sources. Running Python file hashes and frontend asset hashes match the tested checkout:

- UI build `memoryhub-demo-ui-11`: `sha256:eb9ac6d787036ce10ca4a745ffec31a08ad89103bd755bbb9a92cb1be8e24abc`.
- MCP build `memory-hub-mcp-7`: `sha256:263e1126317f5a527a1d63994e7e96abef02dc5802f026696dccffbd9d923fe7`.
- Each UI: 55 core Python files, 31 application files, 10 frontend assets match.
- MCP: 55 core and 38 application files match.

Demo test mode remains enabled at the user's request. Security checks used real accounts and agent credentials. SDK/CLI checks used editable packages from this checkout; no package-registry release was performed.

## Findings

| Finding | Result and evidence boundary |
| --- | --- |
| D01: provisioning/lifecycle mismatch | Fixed and verified. Shared policies apply through API/MCP/SDK/CLI (40/40 live assertions), plus actual UI form defaults. The starting UI branch lacked lifecycle routes and quota enforcement. |
| D02: null metadata crashes Audit | Fixed and verified. Existing null-safe source deployed; actual audit page renders null-metadata events. |
| D03: semantic relevance | Fixed and verified for new/updated records. Explicit date-only updates, observation-vs-deadline classification, chunk inheritance, and long metadata-only updates tested. Historical bad values were not migrated. |
| D04: stale assistant summary | Not reproduced in the replay: all five baseline and eight extension update groups agree. No universal automatic related-summary maintenance guarantee. |
| D05: driver attribution | Fixed and verified when the host supplies the human context. SDK/CLI support a session default; actor remains authenticated. Driver metadata is attribution, not an authentication or authorization claim. |
| D06: missing serialized provenance | Fixed and verified. DTO and generated chunks retain actor/driver; old unattributed chunks remain in historical evidence. |
| D07: usage analytics | Fixed and verified for new events. Per-memory served events and distinct search-request counts are separate. Three hits add one search and one serve per returned memory. Historical rows were not backfilled. |
| D08: forbidden review buttons | Fixed and verified. Viewer sees an explanation without Approve/Reject; independent server calls return 403. |
| D09: advanced browser controls | Weight/date bounds, branch filters, metadata editing and trust/taint display implemented and verified. Arbitrary scope editing remains not implemented and needs a product/security contract. |
| D10: host integration | Not implemented. Preferences explicitly state hosts do not consume the profile; verifier host_command is still null. |
| D11: future invite time | Fixed and verified in the live page: future deadline shown as in 7 days. |
| D12: HTTP invitation URL | Configuration issue fixed for these deployments with an explicit HTTPS public base URL. |
| D13: graph help | Fixed and verified; shared filter behavior and copy agree. |

Additional defects found and corrected:

- A regular admin could mint `memory:admin:super` credentials. Create, update, and rotation of elevated clients now require elevated authority; real denied calls and three backend tests cover the boundary. The synthetic privilege-probe client was immediately revoked.
- Creating a project relationship omitted project/role membership from authorization. Membership, source write permission and archive policy are now enforced.
- Generated chunks omitted provenance and relevance, allowing an expired parent to leave current-search children. Creation and version copying now inherit the fields.
- Metadata-only updates re-embedded oversized inline content and failed with HTTP 413. They now reuse the stored vector. A deployed 29-chunk record passes date-only update and temporal-search checks.
- The last-project-admin check is serialized; simultaneous demotions return one success and one conflict. Account row locking uses portable SQLAlchemy.

## Verification

| Suite | Result |
| --- | --- |
| Core memory, temporal, project service/lifecycle | 168 passed |
| UI backend | 246 passed |
| MCP | 706 passed, 1 expected failure |
| SDK | 291 passed, 8 skipped environment-dependent tests |
| CLI | 206 passed |
| Playwright full mocked-API suite | 60 passed |
| Updated browser-filter regression subset | 10 passed |
| Live scripted assertions | 117 passed across lifecycle, permissions, provenance, temporal, graph, advanced filters, usage and actual UI-form persistence |
| Real browser checks | Audit, review permissions, invites, graph copy, defaults and metadata-only version editing |

Backend/API/MCP assertions are not substituted for the live browser checks, and mocked Playwright checks are not described as cluster E2E. Frontend builds succeeded locally and in OpenShift. UI/SDK/CLI/temporal Ruff checks pass. Four pre-existing core/MCP lint findings remain; comparison with the pre-change source is recorded. The two new break-glass middleware tests verify that an audit-flush failure returns 503 without private content; the cluster database was not deliberately taken down.

Useful commands, run from their respective directories to avoid conflicting `src`/`tests` packages:

```sh
# Repository root
.venv/bin/pytest tests/test_services/test_memory_service.py tests/test_services/test_temporal.py tests/test_services/test_project_service.py tests/test_services/test_project_lifecycle.py -q
# memoryhub-ui/backend
../../.venv/bin/pytest tests/ -q
# memory-hub-mcp
../.venv/bin/pytest tests/ -q --ignore=tests/examples/
# sdk, then memoryhub-cli separately
../.venv/bin/pytest tests/ -q
# memoryhub-ui/frontend
npm run build
npx playwright test
```

## Independent memory-quality evaluation

Assistants saw actual human turns sequentially and chose real MCP operations themselves. They did not read the frozen oracle. One hundred explicitly marked unrelated fixtures (50 in each project) were seeded separately for retrieval competition and excluded from conversational capture metrics.

| Measure | Original-scenario replay | Extension |
| --- | --- | --- |
| Capture | 20/20 (18 factual + 2 preferences) | 47/47 (45 factual + 2 preferences) |
| Independent answer accuracy | 18/18 fixed comparison units | 56/56 (54 factual + 2 preferences) |
| Planned answers | Original fixed denominator | 59/59; three repeated details excluded from independent denominator |
| Strict human-grounded precision | 91/91 atomic occurrences | 172/180 (95.6%) |
| Never-retain material | 0/4 retained | 0/8 retained, including history |
| Active material after forget | Not part of baseline | 0/2 retained; full content remains in two soft-deleted rows |
| Current decision consistency | 5/5 groups | 8/8 groups |
| Search selectivity | 6/37 conversational result occurrences (16.2%) | 11/183 (6.0%) |

The extension's eight unsupported occurrences are four assistant-origin proposals duplicated in a root and chunk, explicitly labelled proposed/not agreed. They are not false assertions of user approval, but they reduce strict human-grounded precision. Factual correctness excluding those proposals is 172/172.

**Retrieval selectivity is reproduced, fix pending.** Neither initial limit-12 query returned the current Relay plan. Both assistants recovered by increasing the limit to 100, returning the plan plus all 50 project distractors. Correct answers therefore demonstrate broad-retrieval recovery, not reliable top-k selection. Conversational-result selectivity is an upper bound on query usefulness, since a conversational record can still be irrelevant to a particular question.

One deliberate pre-execution transport failure was recovered by reading state and retrying the identical update. This does not test an ambiguous after-commit timeout or guarantee write idempotency. No natural product tool error occurred in extension capture/recall. The baseline found relationship/provenance defects before their fixes; those historical failures remain recorded.

The capture phases span intermediate deployments; this is not a claim that every conversation was rerun on the final SHA. Discovered code defects were checked separately on corrected images. Boundary tests use explicit past/future deadlines, not a multi-day soak. No physical deletion, backup erasure, arbitrary external-host integration, or complete issue acceptance is claimed.

## Remaining work

1. Improve selective retrieval and evaluate a broader, repeatable corpus; current top-k misses are not fixed.
2. Define and implement rescope semantics, permissions, history and linked-record handling.
3. Ship a host profile-consumption contract and host verifier.
4. Plan controlled recovery of historical provenance/relevance and analytics where reliable source evidence exists; never invent a human driver.
5. Distinguish active forgetting from permanent erasure and validate any separately required erasure policy.
6. Improve exhaustive historical-change summaries: current facts are correct, but requested history lists omit some replaced decisions.

The local evidence bundle is `demo-results/2026-11-04-regression-1531` alongside the repository. It includes `REPORT.md`, per-finding evidence, test logs, sanitized live events, screenshots, immutable DB checkpoints, deployment digests, source-hash verification, independent baseline/extension evaluations and item-level oracle ledgers. Credentials are stored separately and are not part of this report or commit.
