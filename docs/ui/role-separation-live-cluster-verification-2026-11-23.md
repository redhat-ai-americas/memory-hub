# PR 710 — Live OpenShift and RHOAI verification

Date: 2026-11-23. Branch: `backend-admin-user-roles`.

Status: **PASSED for the checks below.** This closes the previously pending live OpenShift/RHOAI verification for application source commit `00301c1`. This report records a fresh installation and real OAuth, MCP, database, and browser checks. It supplements the historical November 18 reports; their unavailable cluster is not the environment tested here.

## Environment

- OpenShift API: `https://api.ocp.4nvv6.sandbox2317.opentlc.com:6443`, version `4.21.42`.
- MemoryHub UI: <https://memoryhub-ui-memoryhub-ui.apps.ocp.4nvv6.sandbox2317.opentlc.com/>.
- RHOAI dashboard: <https://rh-ai.apps.ocp.4nvv6.sandbox2317.opentlc.com/applications/enabled>.
- RHOAI launch route: <https://memoryhub-ui-redhat-ods-applications.apps.ocp.4nvv6.sandbox2317.opentlc.com/>.
- MCP: <https://memory-hub-mcp-memory-hub-mcp.apps.ocp.4nvv6.sandbox2317.opentlc.com/mcp/>.
- Auth: <https://auth-server-memoryhub-auth.apps.ocp.4nvv6.sandbox2317.opentlc.com/>.

The complete MemoryHub stack was built from this branch using `scripts/deploy-full.sh`: PostgreSQL/pgvector, MinIO, Valkey, CPU embedding and reranking models, Auth, MCP, and UI. The deployment's write/search/read/delete smoke check passed. Core migrations reached `033_ui_agent_owners`; Auth migrations reached `002`.

RHOAI was initially absent. Operator `rhods-operator.3.5.3` was installed from `redhat-operators`, channel `stable-3.x`. DataScienceCluster `default-dsc` reached `Ready`, with `dashboard: Managed` and other components `Removed`. This verifies dashboard integration; workbenches, training, and KServe were not installed. MemoryHub uses its own CPU model deployments.

## Real authentication and authorization checks

Two temporary users were created in the cluster's existing Keycloak identity provider. Both signed in through the real OpenShift OAuth flow. Human roles came from the deployment's access-list Secret. No authentication middleware or principal dependency was replaced in these live checks.

| Check | Observed result |
| --- | --- |
| RHOAI application tile | MemoryHub appears under Enabled and resolves to the secondary launch route. |
| Secondary route | Reencrypt TLS to port 8443; health 200 and complete OAuth callback to the UI. |
| Verified principal | `/api/me` returns `source: oauth-proxy`, the expected username, and distinct Admin/User capabilities. |
| Spoofed headers | Sending `X-Forwarded-User` for the Admin and `X-User-Role: admin` in the User's session leaves the verified User identity unchanged. |
| Personal memory | User creates and reads it; Admin detail, history, and context return 404. |
| Admin projections | Graphs, search, stats, browse, and export exclude personal IDs/content and personal-only entities. Personal memories do not increase Admin counts. |
| Shared project memory | A real project and human membership allow User writes and Admin reads. Admin owner/actor/driver attribution is null across memory projections. |
| Owned agent memory | A client with an atomic human owner binding writes through MCP; its human owner reads the private memory through the BFF. Admin cannot read it. |
| Entity sources | A mixed entity linked to two authorized memories and one foreign private memory reports exactly two sources and `hidden_mentions: 0`. A foreign-only entity and the foreign private memory return 404 to User. Entity nodes are absent from Admin graphs and memory totals. A name derived from an authorized shared source may appear on that source's browse row. |
| Rule history | Owner reads personal history; Admin receives 404. Organizational rule history remains readable with `edited_by: null` for Admin, including old versions. |
| User client form | Only User identity type, fixed tenant, and permitted scopes are offered. Creating a client succeeds and it appears in the owner's list. |
| Admin client form | Only Service identity type and shared read scopes are offered. Creating a service client succeeds. |
| Client escalation | User requests for Service identity or another tenant return 403. |
| CSRF | A credentialed POST from the RHOAI origin to MemoryHub, carrying browser `Sec-Fetch-Site: same-site`, is rejected with 403 in the running BFF log. Normal same-origin mutations succeed. |

## Auth and MCP transport checks

These requests reached the public cluster Routes and the private Auth service through an authorized port-forward. TLS verification was enabled for Python requests, using the cluster certificate chain and public CA roots. Secret values were not included in this report.

| Check | Result |
| --- | --- |
| Auth health, OAuth discovery, JWKS | 200 on the public Route. |
| Public `/admin/clients` | 404 even with a valid admin key. |
| Public encoded/double-slash admin paths | `/admin//clients`, `/%61dmin/clients`, `/admin%2Fclients`: 404. |
| Public `/internal/validate-api-key` | 404 even with a valid service key and API key. |
| Private `/admin/clients` | 401 without a key, 200 with the valid key. |
| Private API-key validation | 200 for the dedicated test client with a valid service key. |
| Client-credentials grant | A real signed access token is issued by public `/token`. |
| Valid / altered JWT | MCP initialize returns 200 / 401 respectively. |
| Real FastMCP client | FastMCP 3.4.2 discovers `admin_memory`, `memory`, `persona`, `register_session`, and `thread`. |
| JWT and API-key flows | Both register the expected identity and complete real memory write/read/vector-search operations. API-key flow also deletes its test memory. |

Runtime Auth routing is `auth-server` Route → `auth-server-public:8082`; the private service is ClusterIP port 8081. The UI service exposes only the OAuth proxy's 8443 port; its BFF binds to loopback with proxy-header interpretation disabled. The test User cannot create `pods/exec` or `pods/portforward` requests in the Auth namespace. No NetworkPolicy is installed there: the demonstrated private endpoint boundary is authentication by service/admin keys, not a claim of network isolation to only two workloads.

## Defects reproduced and fixed during this deployment

1. **RHOAI OAuth callback registration.** The secondary route returned health 200 but OAuth rejected sign-in as `invalid_request`. Its callback was absent from the UI ServiceAccount's redirect allowlist. `deploy/deploy.sh` now registers the secondary route's exact callback URI after resolving its host, and fails if the host is unavailable. The same real Admin session then completed OAuth and reached `/api/me` through that route.
2. **Retired branch versions in BFF projections.** Updating a branch left both versions in the parent's context and branch counts. Context, detail counts, browse counts/facets/filters, and graph branch filters now select current undeleted branches. The PostgreSQL regression reproduces branch creation, versioning, deletion, and parent versioning. Before the fix it failed because context returned both branch versions.

## Validation and deployment identity

- BFF regression suite against the new cluster's PostgreSQL: **209 passed in 320.60 seconds**, with no skipped tests. Tests use a separate synthetic tenant and local ASGI clients; these results supplement the independent real OAuth browser checks above.
- UI production image build: passed in OpenShift, including TypeScript and Vite compilation.
- Changed Python files: Ruff passed. Shell syntax and `git diff --check`: passed.
- Frontend production dependency audit (`npm audit --omit=dev`): zero vulnerabilities reported.
- Final live branch-version regression: passed on the rebuilt image. After editing a branch, User and Admin context show exactly one current branch; detail and browse counts are both one. After parent versioning, the old parent's context has no current branches and browse/graph branch filters select the new parent only.
- Final deployments: ready; Auth, MCP, and UI image references match their selected ImageStream digests. SHA-256 hashes of all four changed BFF modules inside the running UI container match the committed source exactly.

| Component | Selected image digest |
| --- | --- |
| Auth, both listeners | `sha256:582448ef64b4cfcc3fef1471cebb4b2e2a0ed7f7262285ac6fdebc478bc2c2fe` |
| MCP | `sha256:e290a9ef6fe759a17e8fe1c409d2f0d1d79fae84ecadf47fed9bacb78b7cd849` |
| UI | `sha256:851497a78c99b9f945d2001b513fae2f5e7adb83fe347f53e2c2744a9d68bb11` |

## Cleanup and remaining scope

Temporary Keycloak/OpenShift identities, their OAuth access tokens and authorizations, three QA clients, synthetic memories/entities/rules, and the QA project were removed. The PostgreSQL test tenant was cleaned as well. Final QA memory/client/project/rule counts are all zero. The temporary RHOAI administrator-group membership was removed. The human access list now contains the real deployment Admin `admin` only, and the UI was restarted to apply that list.

MemoryHub, persistent storage, models, RHOAI, the application tile, and the real deployment Admin remain installed. PostgreSQL, MinIO, and Valkey PVCs are `Bound` on `gp3-csi`. No cluster login token, OAuth secret, API key, cookie, or test password is committed.

This verification covers the deployed PR's functional and authorization paths. It does not exercise failover, backup restoration, GPU models, large-scale load, or uninstalled RHOAI components.
