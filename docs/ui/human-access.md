# Dashboard human access

Status: **OpenShift RBAC** (#744). The design, trust boundaries and
revocation timings are in
[`docs/auth/human-role-resolution.md`](../auth/human-role-resolution.md).
The username lists from #667 remain only as a rollback mode
(`MEMORYHUB_UI_ROLE_SOURCE=lists`, below). Identity and role resolution
produce a verified `Principal`; the shared `Access` policy enforces
permissions. Neither changed.

The MemoryHub dashboard has two human roles:

| Role  | Sees and does |
|-------|---------------|
| User  | Their own personal memories, plus the shared memories their projects and teams can read. |
| Admin | Tenant-wide metadata for project, campaign, role and organizational memories; content and actions require the configured scope and object grants. Manages users, clients and agents. **No personal (user-scope) data of anyone**, not even IDs, owners, timestamps or counts. Enterprise memories are unavailable to Admins in this release. See "Admin privacy" below. |

The dashboard Admin role is not a technical scope: it never grants
`memory:admin` and never widens the scopes of clients or agents.

## Where roles come from

Two namespaced Roles in the dashboard namespace, on the virtual resource
`memoryhub.io/dashboard`:

| Role | Verbs | Dashboard role |
|------|-------|----------------|
| `memoryhub-dashboard-user` | `use` | User |
| `memoryhub-dashboard-admin` | `use`, `admin` | Admin |

`admin` allowed → Admin; else `use` allowed → User; else `403`. Anyone with
wildcard RBAC, such as `cluster-admin`, passes `admin` and is therefore an
Admin; see the trust boundary in the design.

How a request is checked:

1. `oauth-proxy` signs the person in (scopes `user:info user:check-access`),
   refuses anyone without `use` (`--openshift-sar`), and forwards
   `X-Forwarded-User` and the person's token (`X-Forwarded-Access-Token`)
   on loopback.
2. The BFF accepts identity headers only from loopback, exactly one of each,
   reads `users/~` with the token and requires the name to match.
3. It checks `admin`, then `use` with a `SelfSubjectAccessReview`
   (`MEMORYHUB_UI_RBAC_CHECK=self`) or, if the cluster needs it, a
   `TokenReview` plus `SubjectAccessReview` by its service account
   (`delegated`, which also binds `system:auth-delegator`).
4. Decisions are cached 30 s per token (denials 5 s). If the API cannot be
   reached the answer is `503`, never an old allow. Invalid identity is
   `401`, no entitlement `403`.

The token is never logged, returned to the browser, or sent to MCP or the
auth service.

## Granting and revoking access

Bind groups wherever possible; MemoryHub manages its own RoleBindings and
never changes group membership.

```bash
S=memoryhub-ui/deploy/dashboard-access.sh
$S --context mcp-rhoai --namespace memoryhub-ui grant  --user  --group data-science
$S --context mcp-rhoai --namespace memoryhub-ui grant  --admin --person alice
$S --context mcp-rhoai --namespace memoryhub-ui revoke --admin --person alice
$S --context mcp-rhoai --namespace memoryhub-ui list
```

A change takes effect within 30 s, without a restart. Plain `oc` works too
(`oc adm policy add-role-to-group memoryhub-dashboard-user data-science
--role-namespace=memoryhub-ui -n memoryhub-ui`); `list` shows those
bindings as well. Admins see the same assignments, read-only, under
*Users & Agents → Dashboard access* (`GET /api/admin/access`). It lists
assignments, not effective users: group members and cluster-wide grants
are not expanded.

How a new person gets access: they exist in the cluster's identity
provider (OpenShift creates their `User` at first sign-in), and they are in
a bound group or are bound directly. On their first successful sign-in the
dashboard records a profile (`human_identities`) keyed by the OpenShift
user's `uid`. The profile grants nothing.

## Provisioning and bootstrap

`memoryhub-ui/deploy/deploy.sh` runs `dashboard-access.sh bootstrap`,
which applies the Roles, binds `MEMORYHUB_UI_ADMIN_GROUPS` and
`MEMORYHUB_UI_USER_GROUPS` (comma-separated), and makes the first Admin
**once**, from the first of:

1. `MEMORYHUB_UI_INITIAL_ADMIN_GROUP` or `MEMORYHUB_UI_INITIAL_ADMIN_USER`;
2. the old lists, if `memoryhub-ui-human-access` exists and was not
   migrated (each listed name becomes a binding; the Secret is annotated
   `memoryhub.io/migrated-to-rbac-at` and kept; delete it after verifying
   sign-in);
3. `MEMORYHUB_UI_ADMIN_GROUPS`, if set;
4. the deployer (`oc whoami`), only from a terminal or with
   `MEMORYHUB_UI_BOOTSTRAP_DEPLOYER=1`, never a service account.

CI and GitOps must use 1 or 3. Bootstrap records itself on the admin Role
(`memoryhub.io/bootstrapped-at`, `-by`, `bootstrap-source`). After that,
removing every binding is treated as a deliberate revocation: a later
deploy only warns.

## Audit trail

Every grant is a RoleBinding labelled `memoryhub.io/dashboard-access` and
annotated `memoryhub.io/granted-by` / `granted-at`. The cluster API audit
log records every change to bindings and Roles, including changes made with
plain `oc`. The BFF logs each fresh decision (`username -> role`) and each
refused identity, never a token.

## Rollback: transitional username lists

`MEMORYHUB_UI_ROLE_SOURCE=lists memoryhub-ui/deploy/deploy.sh` switches back
to the #667 lists: `human-access.sh` provisions the Secret
`memoryhub-ui-human-access` (`MEMORYHUB_UI_ADMIN_USERS`,
`MEMORYHUB_UI_ALLOWED_USERS`), the proxy's access check is dropped, and the
BFF reads the lists at start. Changes need a restart. One source never falls
back to the other automatically.

## Local development

There is no OAuth proxy in `compose.yaml` or `npm run dev`. Set the local
identity mode instead:

```bash
MEMORYHUB_UI_AUTH_MODE=local
MEMORYHUB_UI_LOCAL_USER=local-admin      # who you are
MEMORYHUB_UI_ADMIN_USERS=local-admin     # or MEMORYHUB_UI_ALLOWED_USERS to act as a User
MEMORYHUB_UI_TENANT_ID=default
```

`compose.yaml` sets these by default and publishes the UI only on
`127.0.0.1:8080`. In local mode identity headers are ignored. The BFF
refuses to run in local mode inside a cluster (`KUBERNETES_SERVICE_HOST`
set) or without `MEMORYHUB_UI_LOCAL_USER`.

Local mode is a **static, single-user development mode**. Every browser and
API request acts as the configured user; it provides no interactive login,
per-browser sessions or multi-user authentication. To test another user or
role, change the local identity and lists and restart the BFF. Both local
and OpenShift modes use the same `Principal`/`Access` authorization policy.

When running Vite on `http://localhost:3000` with a standalone BFF on port
8080, also set `MEMORYHUB_CORS_ORIGINS=http://localhost:3000` in the BFF
environment and restart it. Compose already supplies this setting. See the
[Vite instructions](../guides/local-development.md#vite-development-mode).

The local MCP HTTP listener also verifies JWTs. Compose supplies its JWKS
URL over the internal `auth:8081` connection, the same public issuer as the
local Auth service, and the `memoryhub` audience. API-key registration
continues to work on that listener.

## Dashboard capabilities

The frontend loads `/api/me` before rendering protected views. Its
`capabilities.clients` contains the allowed identity types, scopes and
default scopes for client creation. Admins create service clients with
their permitted shared read scopes; Users create their own user clients.
The form uses the session tenant and does not offer arbitrary tenant overrides.

Rule history uses the human session and the same visibility checks as rule
detail. Every returned version is authorized separately. A technical
service key is not required by the browser.

Project focus history contains shared project content. Reading it requires
a current, direct human project membership; Admins additionally need the
configured `project` content grant. A tenant-wide Admin can still inspect
the project roster without gaining access to its focus history. Authorized
members retain access to shared memories and focus history.

## Admin privacy

Admin queries are filtered at a single point in `authorization.py`
(`clause()` / `can_read()`): only project, campaign, role and organizational
scopes are visible. User, entity and enterprise scopes are excluded,
including entity metadata derived from personal memories. This covers every Admin path:
stats, nav counts, graph and graph search, browse, export, search,
contradictions, detail, history, context and neighbourhood. The dashboard
has no audit read view yet. Audit records are only written, and an Admin can
only act on non-personal memories. Personal memories do not appear in
counts, lists, graphs or exports. A direct
request for one returns `404`. Personal curation rules (their names and
patterns) are likewise visible only to their owner.

Admins also get no **individual activity** in shared scopes: combined
values can identify a person and show when and how much they work. That means:

- no memory counts or last-active times per person in the Users roster;
- no "writers" facet in browse;
- no author in the overview's recent-activity feed;
- no per-person filters: `actor`, `owner_id`, search `identity`, and
  metadata search by owner all answer `403` or match memory IDs only.

Project and tenant totals stay. Memory projections, context, search,
exports, contradiction reports and rule history redact writer identities
for Admins. The frontend also hides owner filters and per-person memory
navigation. Identity names remain in the access-management roster without
memory counts or last-active times. `tests/test_admin_privacy_pg.py`
checks all of this end to end on Postgres. CI runs it with
`MEMORYHUB_REQUIRE_PG=1`, so a missing database fails the job instead of
skipping the test.

## Cross-site requests

The dashboard session is a browser cookie, so requests that change state
(POST, PUT, PATCH, DELETE) are accepted only from the dashboard's own
origin (`src/csrf.py`). The guard refuses `Sec-Fetch-Site: cross-site` and
`same-site`. Every Route under the cluster's `*.apps` domain is the same
site. The guard also refuses any `Origin` other than the requested host or
`MEMORYHUB_CORS_ORIGINS`.

### Out of scope: exceptional access (break-glass)

#667 covers User/Admin enforcement. The super-admin exceptional-access
workflow is tracked separately in
[#741](https://github.com/redhat-ai-americas/memory-hub/issues/741), which this
change does **not** implement. That workflow would add a separate privilege,
require an incident reference and a justification, and write an enhanced
audit record. Until it exists, nobody can see personal memories through the
dashboard except their owner.

## Not here

- No central provisioning (#671). Lists are per deployment.
- Corporate OIDC (for example Red Hat build of Keycloak) as an identity and
  role source: a second adapter pair behind the same interfaces (#744
  follow-up).
- Enterprise content access, approval and moderation for Admins are not
  implemented. Enterprise metadata is also excluded from their dashboard.
  Ordinary Users retain the existing read access to enterprise policies.
