# Next session: Merge PKCE broker + Playwright e2e test (#81)

The PKCE broker flow (#75–#80) is implemented, deployed, and verified on the cluster. This session merges that work and ships the e2e test that exercises the full flow through a real browser.

## What's on the branch

`feat/pkce-broker-flow` has 13 commits on top of main (112 tests, all passing):

| Commit | What |
|--------|------|
| 49ee8a6 | #75: auth_sessions table + OAuthClient PKCE columns |
| e00b229 | #79: OAuthClient CR + broker env vars |
| 18739ad | #80: Well-known metadata advertises PKCE |
| 75cef45 | #76: GET /authorize endpoint |
| e64643d | #77: GET /oauth/openshift/callback |
| cd92e4e | #78: POST /token authorization_code grant + PKCE |
| 6a8238e | Lint cleanup |
| 1b4e534 | Review fixes: TLS verify, atomic code redemption, input validation |
| 8521421 | httpx in requirements.txt |
| 13d529f | CLAUDE.md IaC conventions + memoryhub-auth CLAUDE.md |
| df2f013 | Alembic setup + initial migration |
| 950e300 | Admin API: redirect_uris and public fields |
| daf1f25 | deploy.sh: OAuth secret, OAuthClient CR, Alembic |

## Step 1: Merge to main

The branch is ready. Review the retro at `retrospectives/2026-04-13_pkce-broker-flow/RETRO.md` if you want context on decisions made.

```bash
git checkout main && git merge feat/pkce-broker-flow
```

## Step 2: Playwright e2e test (#81)

### What it tests

The full PKCE broker flow end-to-end against the live cluster:
1. Generate PKCE verifier/challenge pair
2. `GET /authorize` with a registered public client
3. Follow the 302 to OpenShift OAuth
4. Drive the OpenShift htpasswd login form in a headless browser
5. Follow the callback chain back to the client redirect_uri
6. Extract the authorization code from the redirect
7. `POST /token` with grant_type=authorization_code + code_verifier
8. Decode the JWT and verify claims (sub, tenant_id, scopes)
9. Call MCP `search_memory` with the Bearer token to prove it works

### Cluster details

- Auth server: `https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com`
- OpenShift OAuth: `https://oauth-openshift.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com`
- OpenShift uses htpasswd auth — the login form has `inputUsername` and `inputPassword` fields
- Test user credentials: use `$OC_USER` / `$OC_PASSWORD` from `.env`
- MCP endpoint: `https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`

### Prerequisites

- A public OAuth client registered with redirect_uris. Create one via admin API:
  ```bash
  ADMIN_KEY=$(oc get secret auth-admin-key -n memoryhub-auth -o jsonpath='{.data.AUTH_ADMIN_KEY}' | base64 -d)
  curl -sk -X POST -H "X-Admin-Key: $ADMIN_KEY" \
    -H "Content-Type: application/json" \
    -d '{"client_id":"e2e-test","client_name":"E2E Test Client","tenant_id":"default","default_scopes":["memory:read:user","memory:write:user"],"redirect_uris":["https://localhost:9999/callback"],"public":true}' \
    https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/admin/clients
  ```
- Playwright installed: `pip install playwright && playwright install chromium`

### File location

`memoryhub-auth/tests/integration/test_pkce_e2e.py`

This is an integration test, not a unit test — it hits real endpoints. Keep it separate from the unit test suite. Run with:
```bash
pytest memoryhub-auth/tests/integration/test_pkce_e2e.py -v --timeout=60
```

### Things to watch for

- The OpenShift consent screen (`grantMethod: prompt`) shows on first login for a new OAuthClient. The test needs to handle both "consent already granted" and "consent needed" paths.
- The callback redirect goes to `https://localhost:9999/callback` — Playwright should intercept this rather than expecting a server there.
- TLS verification: the test runs from outside the cluster, so use `verify=False` for the test HTTP client (this is a test, not production code).
- The `OC_USER` in `.env` must have access to the cluster. The test should skip gracefully if credentials aren't available.

## Open issues to be aware of

- #179: `openshift_allowed_group` declared but unenforced (Backlog)
- #176: Multi-user usage tracking issue (this work is the prerequisite)

## Cluster state

- Auth server: `auth-server` deployment in `memoryhub-auth` (Running, freshly deployed)
- OAuthClient CR: `memoryhub-auth-broker` (grantMethod=prompt)
- DB: `memoryhub-pg-0` in `memoryhub-db`, Alembic at revision 001
- MCP: `memory-hub-mcp` in `memory-hub-mcp` (Running)
