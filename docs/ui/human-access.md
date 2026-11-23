# Dashboard human access

Status: **transitional bootstrap** (#667). It stays in place until tenant
role assignments replace it. Then this list and `human-access.sh` go away.

The MemoryHub dashboard has two human roles:

| Role  | Sees and does |
|-------|---------------|
| User  | Their own personal memories, plus the shared memories their projects and teams can read. |
| Admin | Tenant-wide shared memories (project, campaign, role, organizational and enterprise scope), moderation, users, clients and agents. **No personal (user-scope) data of anyone**, not even IDs, owners, timestamps or counts. See "Admin privacy" below. |

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

## Admin privacy

Admin queries are filtered at a single point in `authorization.py`
(`clause()` / `can_read()`): `scope != 'user'`. This covers every Admin path:
stats, nav counts, graph and graph search, browse, export, search,
contradictions, detail, history, context and neighbourhood. The dashboard
has no audit read view yet. Audit records are only written, and an Admin can
only act on non-personal memories. Personal memories do not appear in
counts, lists, graphs or exports. A direct
request for one returns `404`. `tests/test_admin_privacy_pg.py` checks this
end to end on Postgres.

### Out of scope: exceptional access (break-glass)

#667 also describes a super-admin exceptional-access workflow, which this
change does **not** implement. That workflow would add a separate privilege,
require an incident reference and a justification, and write an enhanced
audit record. It is tracked separately (see the follow-up issue linked from
PR #710). Until it exists, nobody can see personal memories through the
dashboard except their owner.

## Not here

- No central provisioning (#671). Lists are per deployment.
- No group or role sync from OpenShift. Edit the lists and restart.
