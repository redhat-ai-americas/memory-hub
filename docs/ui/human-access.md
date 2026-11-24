# Dashboard human access

Status: **transitional bootstrap** (#667). Replacing the username lists with
OpenShift RBAC grants for groups and individual users is tracked in
[#744](https://github.com/redhat-ai-americas/memory-hub/issues/744), including
the OIDC/group-to-role follow-up for non-OpenShift deployments. Identity and
role resolution produce a verified `Principal`; the shared `Access` policy
enforces permissions. The future resolver replaces the list lookup without
changing those policy interfaces or requiring UI refactoring.

The MemoryHub dashboard has two human roles:

| Role  | Sees and does |
|-------|---------------|
| User  | Their own personal memories, plus the shared memories their projects and teams can read. |
| Admin | Tenant-wide metadata for project, campaign, role and organizational memories; content and actions require the configured scope and object grants. Manages users, clients and agents. **No personal (user-scope) data of anyone**, not even IDs, owners, timestamps or counts. Enterprise memories are unavailable to Admins in this release. See "Admin privacy" below. |

## Where roles come from

The dashboard reads two comma-separated lists of OpenShift usernames:

- `MEMORYHUB_UI_ADMIN_USERS`: Admins
- `MEMORYHUB_UI_ALLOWED_USERS`: Users

On OpenShift both lists live in the Secret `memoryhub-ui-human-access` in
the UI namespace. The Deployment mounts it as required, so a pod never starts
without it. A person on neither list gets `403`. If both lists are empty the
API answers `503` with the fix, and the BFF logs an error at startup. It does
not quietly refuse everyone.

The username is the one the OpenShift OAuth proxy sends in
`X-Forwarded-User`. The BFF accepts that header only from the proxy on
loopback. It refuses a request that has no such header or more than one.

## Provisioning

`memoryhub-ui/deploy/deploy.sh` always runs `memoryhub-ui/deploy/human-access.sh`.
`scripts/deploy-full.sh` calls `deploy.sh`. `human-access.sh` can also be run
on its own:

```bash
# Set the lists (replaces both)
MEMORYHUB_UI_ADMIN_USERS=alice,bob MEMORYHUB_UI_ALLOWED_USERS=carol,dan \
  memoryhub-ui/deploy/human-access.sh --context <ctx> --namespace memoryhub-ui

# Restart to pick up the change (env vars are read at start)
oc rollout restart deployment/memoryhub-ui -n memoryhub-ui
```

What the script does:

| Input | Existing Secret | Result |
|-------|-----------------|--------|
| either variable set | any | Secret written with exactly these lists |
| none | yes | Secret left as it is; counts printed, with a warning if there is no Admin |
| none | no | the deployer (`oc whoami`) becomes the first Admin; the script fails if the deployer is a service account |

The script runs on the macOS system shell (Bash 3.2). Its scenarios are
tested against a stub `oc` in
`memoryhub-ui/backend/tests/test_human_access_script.py`. On a Mac, run them
with `HUMAN_ACCESS_BASH=/bin/bash`.

Names are trimmed, de-duplicated and checked against
`^[A-Za-z0-9._@:+-]{1,255}$`. The script refuses to write two empty lists.

## Audit trail

Each write sets these annotations on the Secret:

- `memoryhub.io/human-access-updated-by`: `oc whoami` of the person who ran it
- `memoryhub.io/human-access-updated-at`: UTC timestamp
- `memoryhub.io/human-access-source`: `deploy-input` or `bootstrap-deployer`

The Secret also carries the label `memoryhub.io/transitional=true`. The
cluster's API audit log records every change to the Secret, including edits
made without the script.

To see the current state:

```bash
oc get secret memoryhub-ui-human-access -n memoryhub-ui \
  -o jsonpath='{.metadata.annotations}{"\n"}'
oc get secret memoryhub-ui-human-access -n memoryhub-ui \
  -o go-template='{{range $k,$v := .data}}{{$k}}={{$v|base64decode}}{{"\n"}}{{end}}'
```

At startup the BFF logs the identity mode and the size of each list. It
does not log the names. Each refused sign-in is logged with its username.

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

Delete capabilities cover the complete version chain and descendant branches.
Writing a revision of someone else's shared memory does not grant permission
to delete their earlier versions. Already deleted descendants do not block
deleting the remaining authorized rows. The API rechecks permissions under
lock when the deletion is submitted.

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
- Group/user role provisioning via OpenShift RBAC and the OIDC role-source
  follow-up: #744. For now, edit the lists and restart.
- Enterprise content access, approval and moderation for Admins are not
  implemented. Enterprise metadata is also excluded from their dashboard.
  Ordinary Users retain the existing read access to enterprise policies.
