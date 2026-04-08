# Retrospective: Build/Deploy Hardening + Tenant Isolation

**Date:** 2026-04-08
**Effort:** Close the recurring build/deploy failure family (#88), then land the governance-mandated multi-tenant data isolation layer (#46). One session, two substantial issues.
**Issues closed:** #88 (build/deploy hardening, subsumed #83), #46 (tenant isolation).
**Issues filed:** #104 (session persistence), #105 (auth admin tenant scoping), #106 (BFF per-request operator identity), #107 (alembic autogenerate drift).
**Commits:** `661bf83` → `29c0a7d` (four session commits, plus two of the user's own from a separate terminal).
**Test delta:** 425 → 516 across root / mcp-server / BFF / integration suites (+91 net new tests).

## What we set out to do

Two things. First, close #88 — the build/deploy/image-resolution failure family that had surfaced across four retros in two days (#9, #12, #14, #18). Each prior retro had proposed a partial fix; none generalized, and each fix was re-discovered on the next component's deploy. The forcing-function rule from earlier retros said: recurring items are decisions, not TODOs — force the decision. Land it fully.

Second, move to #46 (tenant isolation). Memory-hub-auth had been issuing JWTs with `tenant_id` since day one, and `core/authz.py` read the claim — but never compared or filtered on it. A silent data leak in any multi-tenant deployment. The issue body was well-specified and the design lived in `docs/governance.md`. Plan going in: seven phases (migration → authz → service writes → service reads → cross-tenant tests → BFF → deploy), landed as a single atomic commit.

## What changed

| Change | Type | Rationale |
|---|---|---|
| `/ds` build-vs-buy review of kagenti/LlamaStack before starting #46 | **Good pivot** | User pushed back at the phase boundary: "are we reinventing something kagenti/LlamaStack gives us for free?" Delegated to claude-worker via `/ds`, got an evidence-backed "Option A: stay the course" with direct file:line citations and upstream doc fetches. The 20-minute review was cheap insurance against mid-implementation second-guessing. |
| Heavy delegation for #46, paydown-in-main for #88 | **Good pivot (validated)** | Executed the "default delegation except paydown" rule from memory. #88 touched deploy infrastructure where sub-agent "looks done" is too costly to trust. #46 was six well-scoped phases, each 1–3 files per slice, each with clear success criteria. Six claude-worker invocations, ~2000 lines of service/model/test code, all reviewed in main context. Scaled cleanly. |
| Auth service placeholder-Secret removed from `openshift.yaml` entirely | **Good pivot (via user fork)** | When #88 Phase 2 hit the broken auth deploy script, three fix options were on the table (patch the awk, use yq, or restructure). User picked restructuring; removing the placeholder Secret stanza cleaned up ~20 lines and removed an entire class of parser fragility. |
| BFF Phase 6 Option A (static per-deployment tenant) over Option B (per-request lookup) | **Scope deferral (conscious)** | Option B needs a user→tenant mapping table that doesn't exist today and opens a design rabbit hole (who assigns tenants? multi-tenant admin users? SSO claim mapping?). Option A is a ~10-line Settings field and transparently upgradable later. Filed Option B as #106. |
| mcp-server test file `test_tenant_isolation.py` uses mocked claims + FakeMemoryStore, not real pgvector | **Scope clarification** | The real-SQL proof lives in `tests/integration/test_tenant_isolation.py` (12 tests against live pgvector, validated end-to-end in Phase 5). The mcp-server tool-level tests go through the real authz + tool chain with a mocked DB — honest about the boundary. |
| `set_curation_rule` tenant-scoped in the upsert lookup during Phase 3 | **Good pivot (found a bug)** | Technically out of Phase 3's stated scope (populate-tenant-on-insert only), but without it two tenants creating rules with the same name would silently collide on upsert. Worker flagged it explicitly; kept the fix. |

## What went well

- **The /ds build-vs-buy pre-check.** Answered a real architectural question with evidence before a line of code was written. Every claim cited a file:line or upstream doc URL. Clean Option A recommendation, clean user decision, no churn. Do this every time for a substantial new feature.
- **#88's hardened deploy pipeline paid off immediately for #46's deploys.** Three clean #46 deploys in sequence (migration → mcp-server → ui), every verification step load-bearing. Without #88's landing first, the mcp-server label-selector bug I introduced in Phase 7 would have been silently WARNING-logged instead of exit-1 halted. The same-session payoff validates the phasing decision.
- **Forcing-function rule held.** #88 was a four-retros-old failure family (#9, #12, #14, #18). The forcing-function + "be bolder on recurring items" rules together said: land it fully, not partially. Did. It closed.
- **Save-before-deploy memories worked flawlessly twice.** Five memories saved before #88's mcp-server deploy. Three memories saved before #46's mcp-server deploy. Zero lost-memory incidents. The `feedback_deploy_invalidates_mcp_session.md` rule is muscle memory now.
- **Heavy delegation pattern scaled cleanly.** Six claude-worker invocations for #46, each scoped to one phase (1–3 files), each with explicit success criteria, each reviewed in main context via diff spot-check + test run. Zero rework cycles. The prompt quality matters: concrete file paths, forbidden-changes lists, expected test count deltas, and structured output requirements all reduced worker drift.
- **Cross-tenant integration tests via live pgvector.** Phase 5's `tests/integration/test_tenant_isolation.py` was validated end-to-end against a real compose stack. 12 tests prove the SQL filter actually isolates rows, not just that the WHERE clause compiles. The tool-level tests in `memory-hub-mcp/tests/test_tenant_isolation.py` use mocked claims + FakeMemoryStore — honest about where the real proof lives.
- **Three latent bugs surfaced by the hardening.** (1) Auth deploy script's `grep+awk` filter had been producing malformed Deployment manifests for unknown weeks — only manual `oc apply` outside the script made the cluster pod exist. (2) mcp-server deploy-count label-selector returned 0 for the script's entire history because the label wasn't on Deployment metadata. (3) BFF `get_memory_history` was broken at runtime since Phase 4 shipped — calling the service without the required `tenant_id` kwarg; would have `TypeError`ed the moment a user opened the dashboard history view. All three were hiding behind WARNING-only or test-boundary gaps.

## Gaps identified

| Gap | Severity | Resolution |
|---|---|---|
| **Cross-package signature changes need a grep pass.** Phase 4 added `tenant_id` as a required kwarg to `get_memory_history_service` and updated the mcp-server caller, but the BFF route in a separate package (`memoryhub-ui/backend`) wasn't in the worker's test scope. The BFF was broken at runtime until Phase 6 caught it. | **Process** — this is the new load-bearing lesson. The same-commit-consumer-audit discipline needs to generalize from "check consumers within the same test suite" to "grep all callers cross-package, including the BFF, the CLI, and the SDK." Captured below as a Start. |
| **Pre-existing alembic version drift** on the cluster DB (`deleted_at` column existed but `alembic_version` at `006_add_oauth_clients`). Discovered during Phase 7 deploy, repaired ad-hoc with `alembic stamp 007_add_deleted_at`. | **Incident** — captured in #107 (alembic autogenerate drift issue). The repair was safe but should have been a saved memory at the moment of discovery; wasn't. |
| **Phase 1 Pydantic `= "default"` scaffolding shipped and was cleaned up in Phase 3.** It worked because the phased ship plan was under disciplined coordination. In a shorter or less disciplined session it could have leaked to production as a silent "always returns default" lie. | **Low** — no issue. Worth noting as an anti-pattern for future reference: don't ship schema defaults as scaffolding; use test fixtures to inject the intermediate state instead. |
| **#84 (embedding 413) bit twice** when saving multi-paragraph learning memories. Both times I had to split into smaller memories mid-flow. | **Recurring pain** — already filed as #84 during the agent-memory-ergonomics close-out. Session is a vote for bumping its priority; the friction is real and repeats every session. |
| **Test suites don't exercise BFF routes from the root or mcp-server suites.** The BFF tests mock `db.execute()` directly, so a signature change in memoryhub_core.services doesn't fail the BFF suite until the BFF test is itself updated to pass the new kwarg. | **Low-medium** — fundamental test architecture question, not fixable in this retro. Worth considering whether a single "API contract" test suite should exercise the BFF → service interface end-to-end. |

## Action items

- [x] Filed #105 (auth: Tenant-scope memoryhub-auth admin API)
- [x] Filed #106 (ui: Per-request BFF operator identity — Option B)
- [x] Filed #107 (infra: Reconcile alembic autogenerate drift)
- [x] Three follow-up issues on the project board in Backlog
- [x] Both #88 and #46 closed, project items moved to Done
- [x] Migration 008 applied to cluster DB, mcp-server + ui deployed and verified
- [ ] Consider bumping #84 priority — it's bitten three times across sessions now
- [ ] No immediate code action items — everything identified has either been fixed in-session or filed as an issue

## Patterns

**Start:**

- **Cross-package grep when changing a service signature.** When a service function in `memoryhub_core` gains a new required parameter, grep for ALL callers — including `memory-hub-mcp/src/tools/`, `memoryhub-ui/backend/src/`, `memoryhub-cli/`, `sdk/src/memoryhub/`, and any test file in any of those packages. The BFF `get_memory_history` TypeError between Phase 4 and Phase 6 is the forcing example. The worker prompts for signature-changing phases should include an explicit "grep all callers and report which packages were audited" step.
- **`/ds` build-vs-buy review before every substantial new feature.** The kagenti/LlamaStack review was 20 minutes of delegated research that prevented a whole class of second-guessing. Cheap insurance. Do this at the same point in the workflow as the "read the design doc first" rule.

**Stop:**

- **Shipping Pydantic schema defaults as phased scaffolding.** The Phase 1 `tenant_id: str = "default"` lie worked because we had a phased ship plan and the Phase 3 cleanup was disciplined. But it's the shape of bug that survives a handoff between sessions. Next time: use test fixture wrappers to inject the intermediate state, keep the schema honest from phase one.
- **Leaving WARNING-only verification in deploy scripts.** This was the #88 lesson; it surfaced a silent bug in mcp-server during Phase 7 of #46 when the deploy-count label-selector check exit-coded me. Hardening WARNING → ERROR is a forcing function for finding the bugs the checks were originally meant to catch but were failing silently. Keep hardening. No check should log WARNING and then ignore its own finding.

**Continue:**

- **Hybrid paydown + delegation sessions.** First half paydown-style in main context for deploy infrastructure work; second half delegate-per-phase with main-context coordination for well-scoped multi-file features. Both worked; the token cost was bounded; the diff quality was consistent. This is now a default working pattern for mixed-shape sessions.
- **Single-commit atomic ship for coherent features.** #46 landed 46 files, +5685/-212, as one commit. The atomicity is the whole point of a tenant isolation change — no window where the column exists without the filter. Worth the larger diff.
- **Save-before-deploy memories for risky operations.** Zero incidents across two mcp-server deploys in a day that both invalidated the in-conversation MCP session. The rule is working as intended.
- **Same-commit consumer audit** (expanded scope). The original rule was "audit the same-commit consumers" — this session generalizes it to "audit ALL callers cross-package when changing a signature." Same discipline, wider lens.
- **Per-session retros AND epic reviews** (from the earlier concept-close retro). Today had both shapes: the morning's `2026-04-08_agent-memory-ergonomics-concept-close/RETRO.md` was an epic review spanning seven candidates; this retro is a tactical session review spanning two issues. Different audiences, different purposes, both worth writing.

## What this enables next

- **#46 closes the data-plane tenant isolation story.** Multi-tenant deployments are now safe at the MCP, SDK, BFF, and service layers. The remaining gaps (#105 auth admin tenant scoping, #106 per-request BFF operator identity) are narrowly scoped follow-ups that compose cleanly with #46 rather than blocking on it.
- **#88's hardened deploy pipeline is now the baseline** for every future component (operator, curator, any new MCP server). The template in `docs/build-deploy-hardening.md` is green across all three existing components.
- **#104 session persistence is the next natural architectural beat.** Today's deploys invalidated the in-conversation MemoryHub MCP session twice, which is exactly the production concern #104 captures. The design doc skeleton is in place; a future session can pick up the forks.
- **The operator identity thread runs through #106, #104, and the demo scenarios work.** Worth considering a short concept-close design pass to unify the operator-identity story across those three issues before any of them starts implementation.
