# Next session: Remaining test debt (#81, #39)

Two test-debt issues remain after closing #95, #85, #177, #101, and #38 in the test-debt-focused session on 2026-04-13. Both require a deployed cluster.

## #81 — auth: End-to-end PKCE flow integration test

**What:** A test script that drives the full OAuth2 PKCE flow against a deployed memoryhub-auth broker: `/authorize` → OpenShift login → `/token` → MCP `search_memory` with the resulting JWT.

**Blockers:** Depends on #75–#80 (PKCE endpoints). Check their status before starting — if `/authorize` (#76) or `/oauth/openshift/callback` (#77) aren't merged, this test can't pass.

**Approach:**
1. Playwright (headless) to drive the OpenShift consent screen. The login form varies by cluster config (LDAP, htpasswd) — parametrize or use a test htpasswd user.
2. File: `memoryhub-auth/tests/integration/test_pkce_e2e.py`
3. After capturing the JWT, decode and verify claims: `sub`, `tenant_id`, `scopes`.
4. Call MCP `search_memory` via HTTP POST with `Authorization: Bearer <jwt>`.
5. Needs a running memoryhub-auth pod. Use `oc port-forward` for local runs or hit the deployed route.

**Key files to read first:**
- Auth endpoints: `memoryhub-auth/src/routes/` (PKCE routes)
- Auth config: `memoryhub-auth/src/config.py` (JWKS URI, issuer, audience)
- MCP route: deployed at `/mcp/` via `memory-hub-mcp/deploy/openshift.yaml`

**Scope:** Medium. Playwright driver for OpenShift login is the tricky part.

## #39 — End-to-end pgvector similarity search through UI

**What:** Verify the full vertical slice: UI search → BFF → embedding service → pgvector cosine distance → ranked results.

**Blockers:** Needs memoryhub-ui deployed, the embedding service (all-MiniLM-L6-v2) running, and the MCP server connected to pgvector.

**Approach:**
1. This is a deployed-stack test — exercises the real embedding service, not MockEmbeddingService.
2. Use `httpx` to hit the BFF search endpoint directly (no browser needed — the data path is what matters).
3. Seed known memories via MCP, then search via BFF and verify:
   - Results ranked by cosine similarity (not text fallback)
   - Scores are real floats, not None
   - Returned node IDs match seeded memories
4. File: `memoryhub-ui/tests/integration/test_search_e2e.py`

**Key files to read first:**
- BFF routes: `memoryhub-ui/backend/src/routes.py` (search endpoint)
- Embedding service config: `MEMORYHUB_EMBEDDING_URL` in deploy manifests

**Scope:** Medium-low if the stack is already deployed. Straightforward HTTP calls.

## Suggested order

1. **#81 first** — tests the auth subsystem, prerequisite for real multi-user usage (#176). Skip to #39 if PKCE endpoints aren't merged yet.
2. **#39 second** — simpler, good candidate for a post-deploy smoke test.

## Session setup

Both issues need a running cluster:
```bash
source .env && oc login "$OC_SERVER" -u "$OC_USER" -p "$OC_PASSWORD" --insecure-skip-tls-verify
oc whoami
oc get pods -n memoryhub-db && oc get pods -n memory-hub-mcp
```

## What shipped in the 2026-04-13 test debt session

| Issue | What landed |
|-------|------------|
| #95 | CI integration-tests job (pgvector + Valkey), `make test-integration` documented |
| #101 | Closed — tests already existed from #46 |
| #85 | Push broadcast integration tests, pydantic serialization roundtrip |
| #177 | PR template structured test plan, search_with_focus + domain boost + ARRAY/GIN integration tests, SQLite conftest freeze |
| #38 | Cleanup script + CronJob + CONTRIBUTING.md convention |

Integration suite: 24 → 47 tests across 4 files.
