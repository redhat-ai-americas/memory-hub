# Stage 2.3.2 — Deployment verification of User/Admin security remediation

Date: 2026-11-18. **Verdict: PARTIALLY COMPLETED.** No live deployment, PostgreSQL integration, or OAuth proxy/RBAC verification was possible. Stage 2.3 remains `AUDIT FAILED`; Stage 3 has not begun.

## 1. Scope, Git baseline, and safety

- Working copy: `/Users/kromashk/ui for memoryhub/memory-hub-backend-admin-user-roles`.
- Branch: `backend-admin-user-roles`; initial and final HEAD: `ae8583e1336c2b32df7de27f1f805cd39dbc5e0f`.
- Initial staged diff: empty. Initial unstaged diff: empty. Initial untracked files: none.
- Existing source and tests were not changed. The only new repository file is this report. No branch switch, commit, push, reset, clean, deployment, secret access, production data change, or Frontend edit was performed. A temporary minimal static `dist` fixture under `/tmp` supported the existing BFF test that expects a mounted SPA route; it was not treated as a deployed Frontend.

The current kube context was `memoryhub-ui/api-ocp-crz5h-sandbox1099-opentlc-com:6443/admin`, pointing to `https://api.ocp.crz5h.sandbox1099.opentlc.com:6443`. The hostname resolved, but TCP connection to port 6443 timed out and `oc whoami` ended with `context deadline exceeded`. No other context was selected. This context was not established as the target non-production environment. Live checks stopped at this connectivity boundary.

## 2. S1 — Auth public/private boundary

**Status: `FIXED IN CODE, DEPLOYMENT NOT VERIFIED`.**

### Source configuration and local results

| Item | Source evidence | Actual deployment evidence |
| --- | --- | --- |
| Public Route | `memoryhub-auth/openshift.yaml`: Route `auth-server` points to Service `auth-server-public`, port 8082. | **NOT VERIFIED**: Route host/spec and ingress behavior could not be read. |
| Public listener | Deployment container `auth-public` runs `src.main:public_app` on 8082. `memoryhub-auth/src/main.py` registers OAuth discovery, JWKS, authorization, token, OpenShift callback, and health routes only. | **NOT VERIFIED**: running command, image digest, pod readiness, and container port could not be read. |
| Private listener | Container `auth-server` serves `src.main:app` on 8081; Service `auth-server` targets 8081 and has no Route in the source manifest. | **NOT VERIFIED**: private Service, EndpointSlice, other Routes, and pod state could not be read. |
| Technical keys | The source public container does not mount `auth-admin-key` or `auth-internal-service-key`; private container mounts both. | **NOT VERIFIED**: deployed environment and mounts could not be read. No secret values were requested. |
| Image rollout | `memoryhub-auth/deploy.sh` compares both container digests with the ImageStream latest digest. | **NOT VERIFIED**: running image digests and rollout status unavailable. |
| Public endpoint behavior | Local ASGI test returns 404 for `/admin/clients` with a valid **test** key and for `/internal/validate-api-key`; discovery, JWKS, and health return 200. A separate local check returned 404 for `/admin/clients`, `/admin//clients`, `/admin/%2e/clients`, `/admin%2Fclients`, `//admin/clients`, `/%61dmin/clients`, and `/internal/validate-api-key`. | **NOT VERIFIED**: no request was sent to a deployed Auth Route; OAuth authorization/token/callback live flows were not exercised. |
| Private endpoint behavior | Local Auth tests show `/admin/clients` 401 without/wrong key and 200 with the test key; internal API-key validation requires its service key. | **NOT VERIFIED**: no in-cluster caller or port-forward was available; no real key was read or used. |

The source YAML parses successfully and its Route → Service → listener mapping is consistent. That is **not** proof of the installed cluster resources or network isolation. A service-key-bearing public request remains unverified in deployment.

### BFF and MCP callers

- BFF source configuration (`memoryhub-ui/openshift.yaml`, `memoryhub-ui/backend/src/config.py`) targets `http://auth-server.memoryhub-auth.svc:8081`. `memoryhub-ui/backend/src/routes.py::_admin_request` uses this configured base URL, not the public issuer. Existing BFF client list/create/update/rotation paths retain human principal, tenant, owner, identity-type, and scope checks. BFF regression tests passed; runtime configuration, DNS, requests from the deployed BFF, and human account scenarios were **not verified**.
- MCP source deployment (`memory-hub-mcp/deploy/openshift.yaml`) sets `AUTH_API_KEY_VALIDATE_URL=http://auth-server.memoryhub-auth.svc:8081/internal/validate-api-key` and a service-key Secret reference. Remote-auth unit tests passed. Deployed env, DNS, and validation from an MCP pod were **not verified**.
- **Configuration-dependent finding:** `memory-hub-mcp/src/tools/auth.py::authenticate_remote` falls back to `AUTH_ISSUER + /internal/validate-api-key` if `AUTH_API_KEY_VALIDATE_URL` is missing. The existing test `test_remote_fallback_derives_url_from_issuer` confirms this code path. `AUTH_ISSUER` is the public Auth Route in `memory-hub-mcp/deploy/deploy.sh`, so a deployment missing the explicit internal URL would send an API key and service-key header to the public hostname and receive a failure from the intended `public_app`. The source manifest does set the private URL; whether the running pod has it is unknown. This is a failover/configuration risk, **not evidence of a live bypass**. Minimal future code hardening is to require an explicit internal validation URL and fail closed when absent, then adjust the fallback test. No MCP code was changed during this read-only verification stage.

### Internal network and RBAC

No `NetworkPolicy` or `pods/exec`/`pods/portforward` grant was found in repository YAML. The Auth source ServiceAccount bindings grant `system:auth-delegator` and namespace read; they do not establish pod-to-pod network isolation or human port-forward privileges. The actual cluster may have other policies, Routes, and RBAC objects. The permitted caller set, namespace boundaries, effective NetworkPolicy, ServiceAccount privileges, and human `pods/exec`/`pods/portforward` rights are **NOT VERIFIED**. We cannot state that only BFF/MCP pods can reach `auth-server:8081`; the service key remains the only demonstrated in-code authentication requirement for technical endpoints.

## 3. S2 — entity visibility

**Status: `VERIFIED LOCALLY ONLY`.**

The fixed `memoryhub-ui/backend/src/human_adapters.py::_entity_sources` applies `_human_content_clause` before returning mention sources and checks tenant, deletion/current state, and per-object content access. `entity_detail` returns `hidden_mentions: 0`; visible source objects alone populate `memory_count`, memories, co-mentions, scopes, writers, projects, and time aggregates. The entity list visibility subquery and project projection apply the human content predicate before counts and pagination. Local tests cover all-visible, mixed foreign personal, inaccessible project, cross-tenant, and hidden-only sources; foreign entities without visible sources; and rename/merge denial for inaccessible linked sources. The full BFF suite passed.

These tests use mocks and inspect generated SQL shape. They do **not** verify PostgreSQL execution, pgvector compatibility, transaction rollback, real pagination/facets, or data-dependent co-mention behavior. No PostgreSQL server listened on `127.0.0.1:5432`; the local Docker daemon was unavailable. No compatible authorized remote database was identified. None of the required PostgreSQL integration cases can be marked `VERIFIED IN POSTGRESQL`.

## 4. S3 — OAuth proxy and forwarded identity

**Status: `NOT VERIFIED`.**

The source UI Deployment uses `registry.redhat.io/openshift4/ose-oauth-proxy:v4.14`, `--pass-user-headers=true`, and `--upstream=http://localhost:8080`. The BFF `Containerfile` binds Uvicorn to `127.0.0.1:8080` with `--no-proxy-headers`; the source Service/Route expose proxy port 8443 only. `get_principal` requires a loopback peer, one `X-Forwarded-User`, and a server-configured allowlist and role/tenant (`memoryhub-ui/backend/src/authorization.py`). The [release-4.14 oauth-proxy source](https://github.com/openshift/oauth-proxy/blob/release-4.14/oauthproxy.go) overwrites normalized variants of that forwarded header with the authenticated session user, as analyzed in Stage 2.3.1.

The running image digest, flags, upstream, ingress wiring, header behavior, and direct 8080 reachability could not be inspected. No forged-header request or unauthenticated-session probe was sent. Effective `pods/exec` and `pods/portforward` permissions are unknown. A direct loopback path through privileged pod access remains a conditional concern; no exploitable route was reproduced. Authentication architecture was not changed.

## 5. Regression and validation results

| Command/check | Result and limit |
| --- | --- |
| `pytest -q tests --ignore=tests/integration` in `memoryhub-auth` | **155 passed**; SQLite/mocked Auth flows, including admin/internal keys, discovery/JWKS, token/authorization logic, and public boundary. No live Route. |
| `FRONTEND_DIST=/tmp/memoryhub-stage232-dist pytest -q tests` in `memoryhub-ui/backend` | **173 passed**; includes human authorization, client management, entity visibility, rename/merge. The temporary `dist` only satisfies the existing SPA fallback test. No browser or deployed BFF. |
| `pytest -q memory-hub-mcp/tests/test_auth_remote.py` | **11 passed**; includes configured internal URL and the issuer fallback finding. No deployed MCP. |
| PyYAML parse of Auth, UI, and MCP OpenShift manifests | Passed (9, 3, and 3 resources respectively). Source Auth Route targets `auth-server-public:8082`; private Service targets 8081. |
| Local public ASGI path-normalization probe | Seven technical-route variants returned 404. No ingress proxy was involved. |
| Ruff on Auth and BFF remediation code/tests; `git diff --check` | Passed. A broader, unchanged MCP file check reported 3 pre-existing style findings (`SIM105` twice, `I001` once); no MCP code was edited for style. |
| OpenShift connectivity | `oc whoami` timed out; retry returned `context deadline exceeded`. API hostname resolved, but TCP port 6443 timed out. No resource reads or live endpoint calls. |
| PostgreSQL availability | Local 5432 connection failed; Docker daemon socket absent. No integration DB or pgvector verification. |

No destructive integration tests, OAuth client mutations, token issuance against a live service, real service-key disclosure, port-forward, or cluster resource changes were performed.

## 6. Exact evidence needed to complete this stage

An authorized owner of a **non-production** MemoryHub environment should first identify the target cluster/context and restore read-only API connectivity. Before any rollout, obtain separate approval for deployment changes. After the Stage 2.3.1 image and manifest are deployed, record only non-secret evidence for:

1. `Deployment/auth-server`, pods, rollout status, ImageStream/image digests, container commands/ports, Service/EndpointSlice targets, all Routes targeting Auth Services, and public/private env **names and Secret references**. Confirm both containers use the intended image and the public Route reaches only port 8082.
2. Public Route status checks for discovery, JWKS, health, safe malformed OAuth requests, and technical paths including normalized variants. Test `/admin/*` with and without a valid service key using an approved test key; record status codes only. Never put the key in a report or command log.
3. From an authorized internal pod, safe read-only `/admin/clients` checks with missing, wrong, and valid key, and MCP API-key validation with approved test data. Confirm BFF and MCP runtime URLs, service DNS, and client management human/tenant/owner/scope behavior. Do not create or rotate real clients.
4. Effective NetworkPolicies, namespace boundaries, Routes, and RBAC for human and service identities, especially `pods/exec` and `pods/portforward`. Determine whether untrusted pods can reach the private Service and whether port-forward can reach BFF loopback.
5. An isolated compatible PostgreSQL/pgvector test database with authorized fixtures for every S2 case, real SQL/result comparisons for list/detail/facets/pagination/co-mentions, and rollback verification for denied rename/merge.
6. The deployed OAuth proxy image digest, flags, and upstream, followed by a permitted forged `X-Forwarded-User` test through the public UI Route with authenticated and unauthenticated sessions. Confirm no direct external access to BFF 8080.

Until those checks are complete, S1 is not `VERIFIED IN DEPLOYMENT`, S2 is not `VERIFIED IN POSTGRESQL`, S3 is not verified, and Stage 2.3.2 cannot be `PASSED`. The independent role-matrix and functional findings from Stage 2.3 still require separate follow-up.
