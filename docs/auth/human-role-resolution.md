# Human role resolution: OpenShift RBAC for dashboard and broker access

Status: **in progress** on branch `oauth` (#744).
Replaces the transitional username lists from #667
([`docs/ui/human-access.md`](../ui/human-access.md)).

## Problem

Today a person's dashboard role comes from two comma-separated username
lists in the Secret `memoryhub-ui-human-access`. Changing them needs a pod
restart, they cannot name groups, and they duplicate what the platform
already knows. `memoryhub-auth` has its own, unrelated gate
(`AUTH_OPENSHIFT_ALLOWED_GROUP`) for the browser broker, and its refresh
handler never re-checks the person: once a refresh token is issued, it can
be rotated for as long as it is used, even after the person has lost access.

## Three separate decisions

Every human request answers three questions, in this order. Each has its
own source and its own code. A change to one must not change another.

| Layer | Question | Source | Code |
|---|---|---|---|
| Identity | Who is calling, and what proves it? | OpenShift OAuth (later: corporate OIDC) | `IdentityProvider` → `VerifiedIdentity` |
| Entitlement | May this person use MemoryHub at all, and as User or Admin? | OpenShift RBAC (later: OIDC claim mapping) | `EntitlementResolver` → role |
| Data access | May they read or change *this* memory, project, client? | MemoryHub policy: tenant, ownership, membership, scopes | `Access` (unchanged) |

`Principal` and `Access` keep their current interfaces. Only the source of
the role changes. The Admin privacy rules from #667 (no personal data, no
individual activity) are enforced by `Access` and are untouched.

**The dashboard Admin role is not a technical scope.** It never grants
`memory:admin`, and it never widens the scopes of OAuth clients or agents
the person creates. A person's dashboard role, an OAuth client's scopes and
the delegation to an agent are checked independently. The client-creation
policy (`_client_scopes_allowed`) already enforces this; a regression test
pins it.

## Entitlement model

A namespaced `Role` in the dashboard namespace on a virtual resource:

```yaml
apiGroups: ["memoryhub.io"]
resources: ["dashboard"]
verbs: ["use"]              # Role memoryhub-dashboard-user
# verbs: ["use", "admin"]   # Role memoryhub-dashboard-admin
```

Resolution is one RBAC model for both roles:

```text
admin allowed → Admin
else use allowed → User
else → 403
```

Grants are ordinary `RoleBinding`s to groups or individual users. The
groups `memoryhub-users` and `memoryhub-admins` are only the defaults in
examples; an enterprise install binds its existing corporate groups
(`MEMORYHUB_UI_USER_GROUPS`, `MEMORYHUB_UI_ADMIN_GROUPS`). MemoryHub manages
its own RoleBindings. It never creates corporate groups or changes their
membership; that belongs to the platform team and the IdP.

A `Role` (not `ClusterRole`) keeps the definition next to the one
deployment it governs. A `ClusterRole` bound by namespaced RoleBindings is
a valid later change if several installs share the definition.

### Tenant

A namespaced Role does not separate tenants inside one MemoryHub. In this
version **one dashboard deployment serves exactly one tenant**
(`MEMORYHUB_UI_TENANT_ID`), and its Role lives in that deployment's
namespace. Several tenants mean several deployments in several namespaces.
Per-tenant entitlements inside one deployment need their own design.

### cluster-admin and the trust boundary

Wildcard RBAC (`cluster-admin`, and anyone with `*` on `memoryhub.io`)
passes the `admin` check, so such a person is a dashboard Admin. #744
accepts this. It costs no privacy: Admins never see personal data.

The boundary is stated plainly: **the application cannot protect data
from someone who can change its Deployment, image, Secrets or database.**
A cluster administrator is inside the trust boundary. Group checks inside
the application would not change that.

The future exceptional-access workflow (#741) cannot be a new RBAC verb,
because wildcard grants cover every verb. It needs a separate,
time-limited approval carrying an incident reference, a justification and
an enhanced audit record.

## Identity

### Dashboard (BFF)

`oauth-proxy` authenticates the person and, with
`--pass-access-token=true`, forwards their OpenShift token in
`X-Forwarded-Access-Token`, next to `X-Forwarded-User`. The proxy requests
only `--scope=user:info user:check-access`, so the token cannot do more
than read the person's own user record and check their own access.

The BFF:

1. accepts identity headers only from the loopback sidecar (unchanged)
   and requires exactly one value of each;
2. reads `GET /apis/user.openshift.io/v1/users/~` **with the person's
   token** and requires `metadata.name` to equal `X-Forwarded-User`;
3. checks entitlement (below);
4. never logs the token, never returns it to the browser, never sends it to
   MCP or the auth service. It lives only for the duration of the checks.

`VerifiedIdentity` carries `issuer`, `subject`, `username` and
`display_name`. For OpenShift, `issuer` is `openshift:<API server URL>` and
`subject` is the `User` object's `metadata.uid` (verified in phase 1).

### Two ways to check entitlement

| Mode | How | Privileges of the BFF ServiceAccount |
|---|---|---|
| `self` (preferred) | `SelfSubjectAccessReview` with the person's token | none |
| `delegated` | `TokenReview` of the person's token, then `SubjectAccessReview` for the returned user, uid and groups | `system:auth-delegator` (may review any token and any subject) |

`self` needs the least privilege. It is the default if phase 1 shows that a
token scoped to `user:info user:check-access` gets an unrestricted answer
for `memoryhub.io/dashboard`. `delegated` remains for clusters where it
does not. The mode is `MEMORYHUB_UI_RBAC_CHECK=self|delegated`; deploy
grants `system:auth-delegator` only in `delegated` mode.

### Failure semantics (fail closed)

| Situation | Response |
|---|---|
| no token, malformed token, OpenShift answers 401 to `users/~` or the TokenReview is not authenticated | `401` |
| `users/~` name differs from `X-Forwarded-User` | `401` |
| identity verified, neither `admin` nor `use` allowed | `403` |
| Kubernetes API unreachable, timeout or 5xx | `503` |

A cached allow decision that has expired is never extended because the API
is down. Production never falls back from RBAC to the lists: the role
source is explicit configuration (`MEMORYHUB_UI_ROLE_SOURCE`), and a
failure in one source is never answered by another.

### Cache

Decisions are cached so a dashboard page load does not cost one API call
per request. The key is the SHA-256 of the token, together with tenant,
namespace and the checked resource. Different tokens never share an entry,
so a new, unverified token can never ride on an older session's decision.
Allow and deny entries live `MEMORYHUB_UI_RBAC_CACHE_TTL` (default 30 s)
and `MEMORYHUB_UI_RBAC_DENY_TTL` (default 5 s). The cache is bounded and
in-process.

## Revocation: what happens when, and how fast

"Access revoked" covers several different events. Each has its own
delay, and they add up.

| Event | Dashboard | New/refreshed human tokens (`memoryhub-auth`) | Access tokens already issued | Personal agents of the person |
|---|---|---|---|---|
| RoleBinding deleted | ≤ cache TTL (30 s) | refused at the next refresh (not revoked) | valid until expiry (≤ 15 min) | token issuance refused at next request |
| person removed from an OpenShift `Group` directly | ≤ cache TTL, if the platform re-reads group membership per request (verified in phase 1) | refused at the next refresh | ≤ 15 min | as above |
| person removed from a corporate group (LDAP, AD, Keycloak) | after the change reaches OpenShift **plus** the above | same | same | same |

The last row is not under MemoryHub's control. OpenShift syncs OIDC groups
when the person signs in, and LDAP groups by a separate periodic sync, so
corporate offboarding is as fast as that sync. MemoryHub documents it and
does not promise a number for it.

Already issued JWTs are verified by signature only. Refusing them before
they expire needs state checked on every request (a session or deny list
in the MCP server). That is out of scope here; the 15-minute access token
lifetime is the bound.

### Agents of a person who loses access

Agents have different lifecycles, so they get different rules:

- **Personal agent** — an OAuth client with an owner binding
  (`memoryhub_ui_agent_owners`). It acts on its owner's behalf. Every token
  issuance for it (`client_credentials`, `refresh_token`) requires the
  owner's current entitlement. If the owner has lost it, issuance is
  refused. The client is not deleted, so the decision is reversible and
  auditable; an Admin deactivates or reassigns it.
- **Service agent** — no human owner, managed by Admins. Not affected by
  any single person's entitlement.

## memoryhub-auth (browser broker and refresh)

- The broker callback checks entitlement with the person's OpenShift token
  (`self` check, scope `user:info user:check-access` requested from
  OpenShift) instead of `AUTH_OPENSHIFT_ALLOWED_GROUP`. A person who may
  not use the dashboard gets no MemoryHub token either.
- The refresh handler re-checks the person before rotating. The OpenShift
  token is never stored, so this check is delegated: the auth service
  reads the person's `Group` memberships (ClusterRole `groups` get/list)
  and creates a `SubjectAccessReview` for the user, those groups and the
  implicit `system:authenticated` groups. Denied: `401 invalid_grant`,
  nothing is rotated. API unavailable: `503 temporarily_unavailable`;
  nothing is issued.
- Denial **refuses, it does not revoke**. Every issuance is checked, so
  refusing is as strong as revoking, and two things go better: restoring a
  person's access restores their session, and a misconfiguration (for
  example the dashboard Roles not existing yet while `deploy-full.sh`
  deploys auth before the UI) cannot destroy every session at once.
- `client_credentials`, `refresh_token` and token exchange for a client
  with an owner binding check the owner the same way (`403 access_denied`).
  Clients without an owner are service agents and are not checked.
- Refresh tokens record where they came from (`origin`: `broker` or
  `client`; migration 003 backfills `broker` where `subject <> client_id`),
  so the person check applies to human sessions.
- With `openshift-rbac`, `/authorize` asks OpenShift only for
  `user:info user:check-access`.
- `AUTH_ENTITLEMENT_MODE=off|openshift-rbac` (`off` keeps the legacy
  `AUTH_OPENSHIFT_ALLOWED_GROUP` check for Compose and tests);
  `AUTH_ENTITLEMENT_NAMESPACE` is the dashboard namespace, filled in by
  `memoryhub-auth/deploy.sh` from `MEMORYHUB_UI_NAMESPACE`.

## Stable identity

`Principal.username` is a display name, not a durable key. A username can
change, or later belong to a different person. The durable key is:

```text
verified external identity (issuer, subject) → internal user_id
```

For OIDC the external key is `(iss, sub)`, never email or
`preferred_username` (OpenID Connect Core, "Claim Stability"). For
OpenShift it is the API server and the `User` object's `uid`. A deleted and
recreated `User` gets a new `uid` and therefore a new `user_id`.

The table `human_identities` (`id` = `user_id`, `tenant_id`, `issuer`,
`subject`, `username`, `display_name`, `created_at`, `last_seen_at`,
`disabled_at`, unique `(tenant_id, issuer, subject)` and unique
`(tenant_id, username)`) records this.

- **JIT profile.** After a successful entitlement check the BFF creates or
  refreshes the person's row. JIT never grants a role, a project membership
  or anything else: the row is a profile of someone already admitted.
- **Username reuse.** If a username arrives with an `(issuer, subject)`
  different from the one recorded, the sign-in is refused (`403`, logged).
  A recreated account therefore never inherits the old account's personal
  memories. A known `(issuer, subject)` arriving with a new username is
  refused too: following the rename would free the old name, and whoever
  got it next would inherit the memories. Linking accounts is a controlled
  operator procedure (`docs/ui/human-access.md`).
- **Disabled profiles** (`disabled_at` set) are refused even with a valid
  RBAC grant.
- **Ownership.** `owner_id`, memberships and the audit log still store
  usernames. Moving them to `user_id` is a separate migration; replacing
  `Principal.username` in place would break every ownership check.
  `Principal` gains an optional `user_id` so new code can use it.

## Bootstrap and migration

- `MEMORYHUB_UI_INITIAL_ADMIN_GROUP` or `MEMORYHUB_UI_INITIAL_ADMIN_USER`
  names the first Admin explicitly. CI and GitOps must set one of them.
- Without either, an interactive deploy (a terminal, `CI` unset) may still
  make `oc whoami` the first Admin; a service account never.
- Bootstrap runs once. The Roles carry the annotation
  `memoryhub.io/bootstrapped-at`. Once it is set, removing every binding is
  treated as a deliberate revocation, and a later deploy only warns.
- `dashboard-access.sh migrate` turns the old lists into RoleBindings for the
  same users and marks the Secret as migrated. It does not delete the
  Secret; the operator removes it after verifying sign-in.

## Administration surface

- `dashboard-access.sh grant|revoke --admin|--user --group G|--person U`,
  `list`, `bootstrap`, `migrate`, `apply-roles`. `human-access.sh` stays
  only for the `lists` rollback mode. Every change is a RoleBinding change, so
  the cluster audit log records who made it.
- `GET /api/admin/access` (Admin only, read-only) lists the RoleBindings to
  the two Roles. It shows **assignments**, not the full list of effective
  users: group members, cluster-wide grants and wildcard roles are not
  expanded. The response says so.
- Changing bindings from the dashboard is not offered: the BFF
  ServiceAccount would need permission to bind roles.

## Local mode and other identity providers

Local mode (`MEMORYHUB_UI_AUTH_MODE=local`) keeps its static single user
and the lists. Corporate OIDC (for example Red Hat build of Keycloak) is a
second adapter pair behind the same interfaces: an `IdentityProvider` that
verifies ID tokens and an `EntitlementResolver` mapping configured claims
to roles. No new network service is needed; the BFF and `memoryhub-auth`
share the adapters.

## Acceptance

Built around negative paths:

- a binding is removed while a dashboard session is open;
- a group membership is revoked;
- refresh after revocation is refused, and owned agents stop getting tokens;
- forged `X-Forwarded-User`, a token that belongs to someone else, two
  header values;
- the Kubernetes API is unavailable;
- a request for another tenant's data;
- an Admin still cannot see personal data;
- a recreated account with a reused username is refused.

Unit tests cover these against a fake Kubernetes API. The live checks on
`mcp-rhoai` are in
[`role-resolution-cluster-verification.md`](role-resolution-cluster-verification.md).

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `MEMORYHUB_UI_ROLE_SOURCE` | `lists` | `lists` (transitional) or `openshift-rbac` |
| `MEMORYHUB_UI_RBAC_CHECK` | `self` | `self` or `delegated` |
| `MEMORYHUB_UI_RBAC_NAMESPACE` | pod namespace | namespace of the Roles |
| `MEMORYHUB_UI_RBAC_CACHE_TTL` | `30` | seconds an allow decision is reused |
| `MEMORYHUB_UI_RBAC_DENY_TTL` | `5` | seconds a deny decision is reused |
| `MEMORYHUB_KUBE_API_URL` | `https://kubernetes.default.svc` | API server |
| `MEMORYHUB_KUBE_CA_PATH` | service account CA | CA bundle |
| `AUTH_ENTITLEMENT_MODE` | `off` | `off` or `openshift-rbac` |
| `AUTH_ENTITLEMENT_NAMESPACE` | `memoryhub-ui` | namespace of the dashboard Roles (manifest: from `MEMORYHUB_UI_NAMESPACE`) |
