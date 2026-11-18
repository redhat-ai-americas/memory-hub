# Stage 2.3.1 — Auth boundary and entity metadata remediation

Date: 2026-11-18. Verdict: **PARTIALLY COMPLETED**. This does not change the Stage 2.3 `AUDIT FAILED` verdict or begin Stage 3.

## 1. Git baseline and preservation

- Working copy: `/Users/kromashk/ui for memoryhub/memory-hub-backend-admin-user-roles`.
- Branch: `backend-admin-user-roles`.
- Initial and final HEAD: `c34a15c3a83378fffccd647fe6884681b60ff37a`.
- Initially staged changes: none. Initially modified tracked files (9): `memoryhub-ui/backend/src/{human_adapters.py,main.py,routes.py}`, `memoryhub-ui/backend/tests/{test_human_adapters.py,test_routes.py,test_stage2_security.py}`, `src/memoryhub_core/services/{graph.py,memory.py}`, `tests/test_services/test_graph_service.py`.
- Initially untracked files (7): `docs/ui/{role-separation-stage-2.2-2026-11-18.md,role-separation-stage-2.3-audit-2026-11-18.md}`, `memoryhub-ui/backend/src/{export_adapter.py,graph_adapters.py,memory_context.py,search_adapter.py}`, `memoryhub-ui/backend/tests/test_stage22_adapters.py`.
- The pre-existing Stage 2.2 and 2.3 changes and untracked files were retained. The two previously modified entity files were edited only at the S2 code and regression-test sites.
- No branch switch, reset, clean, commit, push, Frontend edit, or edit in another working copy was performed. A temporary test environment was created under `/tmp`; the existing Frontend `dist` and Auth test environment in the other checkout were read only.

## 2. Changes made in this stage

| File | Purpose |
| --- | --- |
| `memoryhub-auth/src/main.py` | Add `public_app` with only OAuth discovery, authorization, callback, token, and health routes; keep existing `app` with `/admin/*` and `/internal/*`. |
| `memoryhub-auth/openshift.yaml` | Add public Auth listener on 8082 and `auth-server-public` Service; point the existing public Route only to that Service. Keep `auth-server` Service on 8081 for internal callers. Do not mount technical service keys in the public container. |
| `memoryhub-auth/deploy.sh` | Check both container image digests after rollout. |
| `memoryhub-auth/pyproject.toml` | Add PyYAML to Auth test dependencies for the manifest regression test. |
| `memoryhub-auth/tests/test_public_boundary.py` | Test public route absence, internal key enforcement, OAuth endpoints, and manifest wiring. |
| `memoryhub-auth/tests/integration/test_pkce_e2e.py` | Require an explicit `AUTH_ADMIN_INTERNAL_URL` for live test-client bootstrap; no `/admin/*` call through the public OAuth Route. This test was not executed. |
| `memoryhub-ui/backend/src/human_adapters.py` | Filter entity mention sources through the human content predicate and return `hidden_mentions: 0` for UI shape compatibility. |
| `memoryhub-ui/backend/tests/test_human_adapters.py` | Test visible-only detail aggregates, personal/project/tenant exclusions, list SQL filters, and merge/rename authorization regressions. |
| This report | Evidence and remaining verification. |

## 3. S1 HIGH — public Auth `/admin/*`

**Status: `FIXED IN CODE, DEPLOYMENT NOT VERIFIED`.**

Before this change, the single `auth-server` Route targeted Service port 8081, where the same FastAPI app registered both OAuth and `/admin/*`. Knowledge of `X-Admin-Key` therefore enabled a direct public bypass of BFF human checks.

The Route now targets `auth-server-public:8082`, whose container starts `src.main:public_app`. That app registers `/authorize`, `/token`, `/oauth/openshift/callback`, OAuth discovery/JWKS, and `/healthz`; it does not register `/admin/*` or `/internal/*`. Sending the correct technical key to the public app still returns 404 for those paths. The existing private `auth-server:8081` Service and `src.main:app` keep the technical routes; missing or wrong admin keys still return 401. The Route name and host stay the same, so the configured OAuth issuer and redirect URL do not change. The public container does not load `auth-admin-key` or `auth-internal-service-key`.

Internal callers checked in code and manifests:

- BFF client list/create/update/credential rotation and roster enrichment: `memoryhub-ui/backend/src/routes.py` through `MEMORYHUB_AUTH_SERVICE_URL=http://auth-server.memoryhub-auth.svc:8081` in `memoryhub-ui/openshift.yaml` and `memoryhub-ui/backend/src/config.py`. Existing `_authorize_client`, tenant, owner, identity-type, and scope checks remain unchanged in this stage.
- MCP API-key validation: `memory-hub-mcp/deploy/openshift.yaml` uses `http://auth-server.memoryhub-auth.svc:8081/internal/validate-api-key` and retains its service key.
- The live PKCE integration test now requires an explicitly internal admin URL, for example a suitably authorized port-forward to `svc/auth-server:8081`; it skips bootstrap if that URL is absent.

The source manifest contains no other public Route to the private Service. It does not define a NetworkPolicy for in-cluster traffic; the private Service continues to rely on service-key authentication for technical callers. Actual cluster routing, image rollout, NetworkPolicy/RBAC state, and direct requests to the deployed public Route have **not** been checked. The Route boundary must therefore not be described as deployed or proven closed in OpenShift.

## 4. S2 MEDIUM — `hidden_mentions`

**Status: `FIXED AND VERIFIED` locally; PostgreSQL integration not verified.**

The audited UI expects a numeric `hidden_mentions` field (`EntityDetail`), so it remains in the response with the fixed value `0`. No count of inaccessible relationships is calculated or returned. `_entity_sources` now selects sources with `_human_content_clause(access)` and also verifies each selected source's tenant, deletion/current state, content visibility, and relationship tenant before building detail projections. `memory_count`, scopes, writers, projects, months, first/last seen, memories, and co-mentions use only those visible sources. The entity list's visibility subquery and project projection already use the human content predicate; tests inspect every generated list query, including aggregate/facet and pagination queries. A foreign entity with no visible sources remains 404 unless the entity itself is owned by the requester.

Regression cases cover all-visible sources, a mixed visible/foreign personal set, an inaccessible project source, a cross-tenant source, a hidden-only set, list query filtering, and rename/merge rejection of inaccessible linked sources. The tests compare the complete entity detail response with and without a hidden source, including aggregates; both responses are equal. These are local mock and SQL-shape tests, not a live PostgreSQL/pgvector execution.

## 5. S3 — `X-Forwarded-User`

**Status: `NOT VERIFIED`. No authentication-architecture change was made.**

The BFF process binds to `127.0.0.1:8080` with `--no-proxy-headers` (`memoryhub-ui/Containerfile`). The source Deployment has only the BFF and OAuth proxy containers in one pod. The proxy listens on 8443, forwards to `localhost:8080`, and uses `--pass-user-headers=true`; the Service and Route expose only 8443 (`memoryhub-ui/openshift.yaml`). `get_principal` requires a loopback peer, exactly one `X-Forwarded-User`, and a server-configured allowlist/role/tenant (`memoryhub-ui/backend/src/authorization.py`). A normal external client cannot reach 8080 through the declared Service or Route.

The [OpenShift oauth-proxy release-4.14 source](https://github.com/openshift/oauth-proxy/blob/release-4.14/oauthproxy.go) calls `setRequestHeader` for `X-Forwarded-User` when user headers are enabled; that helper strips normalized client-supplied variants before setting the authenticated session user. This is source-code evidence for the configured proxy version, not proof about the exact deployed image or live request path. An actor with pod `exec` or pod port-forward privileges might reach loopback directly; repository manifests do not establish whether such privileges are granted in the cluster. No reproducible external header-spoofing path was established. A live RBAC review and a forged-header test through the actual Route and a separately authorized port-forward are still needed.

## 6. Verification

| Check | Result |
| --- | --- |
| Auth `pytest -q tests --ignore=tests/integration` | **155 passed**. Includes admin, OAuth, internal key, public-app, and manifest tests. |
| BFF `pytest -q tests/test_human_adapters.py` | **37 passed** after S2 test additions. |
| BFF full `pytest -q tests` with `FRONTEND_DIST` pointing to an existing read-only build | **173 passed**. |
| BFF full run without a `dist` directory | **171 passed, 1 failed**: pre-existing `/api/auth/login` test expects SPA fallback 405; this checkout has no built `dist`, so the route returns 404. Re-run with existing `dist` passed. |
| Ruff on changed Python files; `bash -n memoryhub-auth/deploy.sh`; `git diff --check` | Passed. |
| PyYAML parse of `memoryhub-auth/openshift.yaml`; Route/Service/container assertions | Passed; 9 YAML resources parsed. |
| Internal service URL reference review | BFF and MCP still target `auth-server.memoryhub-auth.svc:8081`; live PKCE bootstrap no longer targets public `/admin/*`. |
| `oc whoami --context mcp-rhoai` | Failed: OpenShift API host DNS lookup failed. No deployment or live Route request performed. |

No destructive integration test was run. PostgreSQL/pgvector, OpenShift, live OAuth proxy, and live port-forward/RBAC behavior were not available for verification. Core code was not changed in this stage, so Core test runs were not required for this fix. No production or user data was changed.

## 7. Remaining gate

To mark S1 `FIXED AND VERIFIED` and this stage `PASSED`, deploy the manifest and image in an authorized environment, confirm the public Route serves OAuth endpoints but returns 404 for `/admin/*` even with the correct service key, confirm the private Service serves `/admin/*` only with the correct key, and verify BFF client operations plus tenant/owner checks against that deployment. Validate proxy header behavior and pod port-forward privileges separately for S3. The unrelated Stage 2.3 functional gaps remain outside this remediation.
