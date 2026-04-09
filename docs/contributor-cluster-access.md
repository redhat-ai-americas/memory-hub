# Contributor Cluster Access

This document describes how external contributors get access to MemoryHub's development infrastructure — specifically, the demo OpenShift cluster that runs `memory-hub-mcp`, `memoryhub-ui`, and the supporting services.

If you just want to contribute code, you do **not** need cluster access. Everything in this repo can be built, tested, and linted locally against SQLite or a podman-run PostgreSQL container. Only read this document if you need to run the live MCP server, hit the deployed dashboard, or debug something that can only be reproduced in-cluster.

## The short version

- **New contributors do not get deploy access.** Read-only access to logs, pods, and events — yes. The ability to `oc apply`, `oc rollout restart`, or start builds — not at first.
- **The cluster is shared demo infrastructure.** It runs live demos for conferences and customer calls. A mid-demo breakage is a serious problem.
- **Everything you need for local development is already in `CONTRIBUTING.md`.** Most PRs should never touch the cluster.
- **If you do need access**, file a request following the flow below. The cluster admin (`@rdwj`) will review.

## The cluster

MemoryHub's demo cluster is a Red Hat OpenTLC sandbox. It is disposable — if something goes catastrophically wrong, the sandbox gets rebuilt. That's a good safety net, but it also means: **don't treat it as production**. Don't store anything there you can't afford to lose. Don't point it at real customer data.

| Property | Value |
|---|---|
| Cluster type | OpenShift 4.x on OpenTLC sandbox |
| Identity provider | GitHub OAuth (see below) |
| Namespace: MCP + UI | `memory-hub-mcp` |
| Namespace: Auth server | `memoryhub-auth` |
| Namespace: PostgreSQL | `memoryhub-db` |
| MCP streamable-HTTP route | `mcp-server-memory-hub-mcp.apps.<cluster>.<sandbox>.opentlc.com` |
| Auth server route | `auth-server-memoryhub-auth.apps.<cluster>.<sandbox>.opentlc.com` |
| Dashboard UI route | `memoryhub-ui-memory-hub-mcp.apps.<cluster>.<sandbox>.opentlc.com` |

The exact `<cluster>.<sandbox>` identifier rotates when the sandbox is rebuilt. Ask `@rdwj` for the current value; don't hardcode it into anything that lives in git.

## GitHub IdP configuration

The cluster uses GitHub as its identity provider. To log in as a contributor:

1. You must be a public member of the `redhat-ai-americas` GitHub organization — or have your GitHub username explicitly added to the cluster's OAuth allowlist. Public membership is simpler; ask to be invited to the org if you are not already a member.
2. Visit the OpenShift console URL (ask `@rdwj` for the current one — it's also on the sandbox's landing page).
3. Click **Log in with GitHub** on the OpenShift login screen.
4. Authorize the OAuth application the first time you log in.
5. You will be logged into OpenShift with your GitHub username as your OpenShift username. For example, if your GitHub username is `jdoe`, your `oc whoami` will report `jdoe`.

**First-time users have no role bindings.** By default you can see the list of projects but you cannot see pods, logs, or secrets in any of them. You need explicit role grants — see the next section.

### How the cluster admin configures GitHub IdP

This is reference material for the person maintaining the cluster, not for new contributors.

The GitHub IdP is configured at `oauth/cluster` under `.spec.identityProviders`:

```yaml
apiVersion: config.openshift.io/v1
kind: OAuth
metadata:
  name: cluster
spec:
  identityProviders:
  - name: github
    mappingMethod: claim
    type: GitHub
    github:
      clientID: <github-oauth-app-client-id>
      clientSecret:
        name: github-oauth-secret
      organizations:
      - redhat-ai-americas
```

The `clientID` and `clientSecret` come from a GitHub OAuth App registered under the `redhat-ai-americas` org (Settings → Developer settings → OAuth Apps). The callback URL must be the cluster's OAuth server route — typically `https://oauth-openshift.apps.<cluster>.<sandbox>.opentlc.com/oauth2callback/github`.

Restricting `organizations` to `redhat-ai-americas` means only members of that org can log in; users who are not org members get an "Access denied" error on the OpenShift login page.

## Requesting access

New contributors default to **no cluster access**. If you need it for a specific piece of work, file a request:

1. Open an issue in `redhat-ai-americas/memory-hub` with:
   - Your GitHub username
   - What you need to do in-cluster (e.g., "view MCP server logs to debug a session-focus regression")
   - How long you expect to need access ("one-off" vs "ongoing development")
   - Whether you need read-only or write access
2. Use the `type:infra` label and assign it to `@rdwj`.
3. Wait for approval. Do not start work assuming access will be granted.

Once approved, the cluster admin will grant you the minimum role that satisfies the request. The default progression is:

| Level | Role | What it lets you do |
|---|---|---|
| **Observer** | `view` on `memory-hub-mcp`, `memoryhub-auth`, `memoryhub-db` | Read pods, logs, events, routes, services, deployments. No secrets. No writes. This is where every new contributor starts. |
| **Debugger** | `view` + `pods/exec` | Everything above, plus `oc rsh` / `oc exec` into running pods. Useful for live debugging. Still no writes to manifests. |
| **Developer** | `edit` on one namespace | Deploy, rollout restart, apply manifests in a single namespace. Granted only for active development work, and only for the namespace that work touches. |
| **Admin** | `admin` (cluster-wide) | Reserved for `@rdwj`. Not granted to contributors. |

You start at Observer. Most contributor work never needs more than that. If you hit a wall, ask for the next level up — explain why in the issue.

## No-deploy policy for new contributors

**Newly onboarded contributors do not deploy to the cluster, even if they have write access to the manifests.** This is a hard rule, not a suggestion, for three reasons:

1. **The cluster runs demos.** A broken MCP server or UI in the middle of a customer call is embarrassing and hard to recover from quickly. The cluster admin needs to know when changes are landing.
2. **Deploys touch shared state.** The PostgreSQL schema, the oauth_clients table, curation rules, seeded memories — all of these are shared across everyone using the cluster. A bad migration affects everyone, not just you.
3. **Deploy gotchas are non-obvious.** The `/deploy-mcp` slash command invalidates in-session MCP tool access at the transport layer. The image-digest pinning in the UI deployment silently masks rollout failures (#83). File permissions have to be `chmod 644` before building or the container crashes on startup. These are learned-the-hard-way details that live in `memory-hub-mcp/CLAUDE.md`, `memoryhub-ui/CLAUDE.md`, and the retrospectives under `retrospectives/`.

The practical workflow for a new contributor is:

1. Open a PR against `main` with your change.
2. Reviewer (code owner) reviews and merges.
3. Cluster admin (or a designated deployer) runs the deploy separately, on their schedule, after the merge.
4. You verify the deploy worked via the logs you can see with Observer access, or by asking the deployer to confirm.

Do not shortcut this by running `oc apply`, `oc rollout restart`, or starting builds directly — even if your role nominally allows it. Work against your local setup, let PRs mediate changes, and let the cluster admin manage the deploy cadence.

As your contribution history grows and the cluster admin has confidence in your judgment, the no-deploy policy relaxes. There is no formal checklist for that — it's based on trust built through merged PRs.

## Getting a memoryhub-auth client credential

If your work needs to call the MCP server over HTTP (for example, to reproduce an auth-related bug locally, or to run `sdk/tests/test_rbac_live.py` against the live auth server), you need a `memoryhub-auth` OAuth client. **You do not create this yourself.** Ask the cluster admin to provision one.

### What you get

A `client_credentials` OAuth client consists of two values: a `client_id` and a `client_secret`. The `client_id` is a short human-readable identifier (for example, `mh-dev-jdoe-2026` for a personal developer client, or `mh-svc-curator-2026` for a service client). The `client_secret` is an opaque random string starting with `mh-dev-` or `mh-svc-`. Both are secrets: treat them the same way you treat a database password.

Clients are tenant-scoped. Your client can only read and write memories in the tenants it is a member of. New developer clients start in a single `dev-tenant` with limited scopes.

### How clients are provisioned

The cluster admin uses the `memoryhub-auth` admin API to create a client. From their end it looks like:

```bash
# Admin side — reference only. You do not run this.
curl -X POST https://auth-server-memoryhub-auth.apps.<cluster>/admin/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "mh-dev-jdoe-2026",
    "tenant_ids": ["dev-tenant"],
    "scopes": ["memory:read", "memory:write"]
  }'
```

The API returns a JSON document containing the `client_id` and a newly generated `client_secret`. The admin delivers these to you out-of-band (signal, encrypted email, in-person). **The secret is shown once and cannot be re-read** — if you lose it, the admin has to rotate it.

### Where to store your credential

Put the credential at `~/.config/memoryhub/api-key` with mode 0600:

```bash
mkdir -p ~/.config/memoryhub
echo '<your-client-secret>' > ~/.config/memoryhub/api-key
chmod 600 ~/.config/memoryhub/api-key
```

This is the file that `.claude/rules/memoryhub-integration.md` tells Claude Code sessions to read at the start of every conversation. It is intentionally **not** in the repo, is per-operator, and is referenced via environment variables (`MEMORYHUB_TEST_WJACKSON_SECRET`, `MEMORYHUB_TEST_CURATOR_SECRET`) by anything that needs it in tests.

Never commit this file. Never paste the secret into an issue, a PR comment, or a public chat. If you suspect it has been exposed, ask the admin to rotate it immediately.

### Rotation

Credentials are rotated when:

- They are suspected to be leaked
- A contributor leaves the project
- At least annually as hygiene

The rotation process replaces the stored hash in the `oauth_clients` table and in the `memoryhub-users` ConfigMap that the MCP server reads for the api-key shim. See `memory-hub-mcp/deploy/users-configmap.example.yaml` for the ConfigMap shape; the real version is gitignored and generated by the admin.

## When you get stuck

If you cannot reproduce a bug locally and you believe it is cluster-specific:

1. Describe exactly what you tried locally in an issue. Include the local-environment details (Python version, PostgreSQL version, container runtime, OS).
2. Tag `@rdwj` and request a log excerpt, not full access.
3. If it turns out you really do need to run commands in-cluster, ask for a one-off Debugger grant scoped to the namespace in question. The admin may pair with you over a shared screen instead of granting standing access.

Most cluster-specific issues end up being solvable without the contributor ever needing `oc` access — the admin can grab the logs and the contributor fixes the code locally.

## Related documents

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — local development setup, coding conventions, PR flow
- [`docs/auth/openshift-broker.md`](auth/openshift-broker.md) — the **future** OAuth 2.1 authorization-code flow that will replace the current `register_session` api-key shim
- [`docs/governance.md`](governance.md) — the RBAC and JWT architecture that enforces what each client credential can do
- [`memory-hub-mcp/deploy/users-configmap.example.yaml`](../memory-hub-mcp/deploy/users-configmap.example.yaml) — ConfigMap template for the current api-key shim
