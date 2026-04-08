# OpenShift OAuth Broker

## Why this exists

`memoryhub-auth` today implements two OAuth 2.1 grants: `client_credentials`
(for agents and SDKs) and `refresh_token`. That covers every machine-to-machine
caller MemoryHub has. It does **not** cover anything that runs in a browser:
LibreChat, the MemoryHub Dashboard, MCP Inspector, Claude Desktop, or any
future agent UI a customer might build.

The forcing function is LibreChat. LibreChat's MCP integration supports
authorization_code + PKCE on streamable-http servers, with per-user encrypted
token storage. To plug MemoryHub into LibreChat with real per-user identity,
the auth server has to speak that flow. It currently does not. Verified in:

- `memoryhub-auth/src/routes/token.py:77-82` rejects every grant other than
  `client_credentials` and `refresh_token` with `unsupported_grant_type`.
- `memoryhub-auth/src/routes/well_known.py:17` advertises only those two grant
  types in the RFC 8414 metadata, and there is no `authorization_endpoint`
  field, so client auto-discovery cannot find one.

This work is the Phase 2 OAuth that the original auth architecture decision
(2026-04-05) called out as `authorization_code+PKCE for browser humans`. It was
deferred at the time because there was no concrete browser consumer. There is
one now.

## Decision: broker, don't reinvent

The constraint is that we need an authorization-code endpoint that humans can
log in through. There are three ways to satisfy that constraint:

1. **Build a full login UI in `memoryhub-auth`.** Username/password tables,
   password reset, MFA, account recovery, the whole identity-provider surface.
   This is months of work, none of it differentiated, and it duplicates
   identity backends that the cluster already has.
2. **Deploy Keycloak (or another OIDC provider) and front MemoryHub with it.**
   Real per-user identity, mature UI, claim mappers — but it's another piece
   of stateful infrastructure to operate, back up, secure, and pay for. The
   cluster does not currently run Keycloak (verified: no routes, pods,
   projects, CRDs, or operators matching keycloak/sso/rh-sso).
3. **Broker through OpenShift's built-in OAuth server.** Every OpenShift
   cluster ships with an OAuth server already wired into whatever identity
   providers the cluster admin configured (htpasswd, LDAP, GitHub, OIDC, etc).
   `memoryhub-auth` becomes a thin OAuth 2.1 authorization server in front of
   it: it owns the OAuth dance with the client (LibreChat), but delegates the
   actual user-authentication step to OpenShift, then mints its own JWT with
   MemoryHub-shaped claims.

Option 3 is the right answer for our constraints. It deploys zero new
infrastructure, requires zero changes to the MCP server, requires no login UI,
and gives us full control over the JWT claims that downstream code already
depends on (`sub`, `identity_type`, `tenant_id`, `scopes`).

The non-obvious constraint that rules out using OpenShift OAuth *directly* is
that OpenShift issues opaque tokens, not JWTs. The MCP server's `JWTVerifier`
validates signed JWTs against `memoryhub-auth`'s JWKS. Pointing it at
OpenShift would require swapping the verifier for an introspection-based one
and losing claim control. The broker approach sidesteps this entirely:
LibreChat sees a `memoryhub-auth` JWT, the MCP server sees a `memoryhub-auth`
JWT, and the OpenShift opaque token never leaves the broker.

## The flow

```
LibreChat                memoryhub-auth                OpenShift OAuth
   |                          |                              |
   |  GET /authorize          |                              |
   |  ?response_type=code     |                              |
   |  &client_id=librechat    |                              |
   |  &redirect_uri=...       |                              |
   |  &code_challenge=...     |                              |
   |  &code_challenge_method  |                              |
   |  &state=...              |                              |
   |------------------------->|                              |
   |                          | validate client + PKCE       |
   |                          | mint internal session id     |
   |                          | persist {session_id, PKCE,   |
   |                          |   client redirect, state}    |
   |                          |                              |
   |                          |  GET /oauth/authorize        |
   |                          |  ?response_type=code         |
   |                          |  &client_id=memoryhub-auth   |
   |                          |  &redirect_uri=$BROKER/cb    |
   |                          |  &state=$session_id          |
   |  302 to OpenShift  <-----|----------------------------->|
   |---------- user logs in via OpenShift web console -------|
   |                          |  302 to broker callback      |
   |                          |  ?code=$ocp_code             |
   |                          |  &state=$session_id          |
   |                          |<-----------------------------|
   |                          | look up session_id           |
   |                          | POST /oauth/token            |
   |                          |   grant=authorization_code   |
   |                          |   code=$ocp_code             |
   |                          |----------------------------->|
   |                          |  {access_token: opaque}      |
   |                          |<-----------------------------|
   |                          | GET /apis/user.openshift.io  |
   |                          |   /v1/users/~                |
   |                          |   Authorization: Bearer ...  |
   |                          |----------------------------->|
   |                          |  {metadata.name: "alice"}    |
   |                          |<-----------------------------|
   |                          | resolve or JIT-provision     |
   |                          |   memoryhub user "alice"     |
   |                          | mint our own auth code,      |
   |                          |   bind to subject + scopes   |
   |  302 to client redirect  |                              |
   |  ?code=$mh_code          |                              |
   |  &state=$client_state    |                              |
   |<-------------------------|                              |
   |                          |                              |
   |  POST /token             |                              |
   |  grant=authorization_code|                              |
   |  code=$mh_code           |                              |
   |  code_verifier=...       |                              |
   |------------------------->|                              |
   |                          | validate PKCE, mint JWT      |
   |  {access_token: JWT,     |                              |
   |   refresh_token: ...}    |                              |
   |<-------------------------|                              |
   |                          |                              |
   |  MCP request             |                              |
   |  Authorization: Bearer JWT                              |
   |--------------> memory-hub-mcp                           |
   |                JWTVerifier validates against            |
   |                memoryhub-auth JWKS (no change)          |
```

The OpenShift opaque token is held only inside the broker and only long
enough to call the user-info endpoint. It is never persisted and never
returned to LibreChat.

## Endpoints to add

### `GET /authorize`

Standard OAuth 2.1 authorization endpoint. Required query params:
`response_type=code`, `client_id`, `redirect_uri`, `code_challenge`,
`code_challenge_method=S256`, `state`. Optional: `scope`.

Validates:

- `client_id` exists and is active in `oauth_clients`.
- `redirect_uri` matches one of the client's registered URIs exactly. No
  prefix matching, no wildcards. (LibreChat's callback is
  `https://librechat.example.com/api/mcp/{serverName}/oauth/callback` —
  the broker stores this verbatim per client.)
- `code_challenge_method` is `S256`. Plain is rejected.
- `code_challenge` is a non-empty string of valid base64url.

On success, the broker generates an internal `session_id` (random 256-bit),
stores a row in a new `auth_sessions` table with the PKCE challenge, the
client's `redirect_uri`, the client's `state`, and an expiry of ~5 minutes,
then 302s the user to OpenShift OAuth's `/oauth/authorize` with our own
callback URL and `state=$session_id`.

### `GET /oauth/openshift/callback`

The broker's own callback for the OpenShift leg. Receives `code` and
`state=$session_id` from OpenShift. Looks up the session row; rejects if
missing or expired.

Exchanges the OpenShift code for an opaque token at OpenShift's `/oauth/token`
using the broker's own client credentials (the OpenShift `OAuthClient` CR;
see "OpenShift client registration" below).

Calls `GET /apis/user.openshift.io/v1/users/~` with the opaque token to get
`metadata.name` (the OpenShift username). Discards the opaque token after this
call — it is never persisted.

Resolves the username to a MemoryHub identity:

- If a row exists in `users` (or whatever the broker's identity store ends up
  being — see open questions), use it.
- If not, JIT-provision (subject to allowlist gate; see open questions).

Mints a fresh authorization code (random 256-bit, hashed in storage), updates
the session row with `subject`, `identity_type`, `tenant_id`, `scopes`,
marks it `ready`, and 302s the user back to the LibreChat `redirect_uri` with
`code=$mh_code` and the original client `state`.

### `POST /token` — extend with `authorization_code` grant

Add a third branch alongside the existing `client_credentials` and
`refresh_token` handlers. Required form params: `grant_type=authorization_code`,
`code`, `redirect_uri`, `code_verifier`, `client_id`. (`client_secret` is
optional for public clients.)

Validates:

- The code exists in `auth_sessions`, is in `ready` state, and has not
  expired.
- The `client_id` matches the row.
- The `redirect_uri` matches the row exactly.
- `SHA256(code_verifier)` base64url-encoded equals the stored
  `code_challenge`.
- The code has not been used before. On success, mark used in the same
  transaction that issues the tokens, so a replay fails.

On success, mint an access token via `create_access_token()` with the
session's `subject`, `identity_type`, `tenant_id`, `scopes`, and a refresh
token via the existing path. Return the standard OAuth response.

## Data model

New table `auth_sessions` (single table covers both PKCE state and
authorization codes — they have the same lifecycle):

```sql
CREATE TABLE auth_sessions (
  session_id          VARCHAR(64)  PRIMARY KEY,
  client_id           VARCHAR(255) NOT NULL,
  client_redirect_uri TEXT         NOT NULL,
  client_state        TEXT         NOT NULL,
  code_challenge      TEXT         NOT NULL,
  code_challenge_method VARCHAR(8) NOT NULL DEFAULT 'S256',
  code_hash           VARCHAR(64),                -- SHA256 of issued code
  subject             VARCHAR(255),
  identity_type       VARCHAR(32),
  tenant_id           VARCHAR(255),
  scopes              TEXT[],
  status              VARCHAR(16)  NOT NULL DEFAULT 'pending',
                                                 -- pending → ready → used
  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
  expires_at          TIMESTAMPTZ  NOT NULL,
  used_at             TIMESTAMPTZ
);
CREATE INDEX ix_auth_sessions_code_hash ON auth_sessions (code_hash);
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);
```

Lifecycle:

- `pending` after `/authorize`, before the OpenShift round-trip resolves.
- `ready` after `/oauth/openshift/callback` resolves the user and mints the
  client-facing code.
- `used` after `/token` consumes the code. Replay attempts after this fail.

A periodic cleanup deletes rows past `expires_at`. Five-minute TTL on
`pending`, ten-minute TTL on `ready`, hard-delete `used` rows after 24 hours
(retained briefly for forensics).

## OpenShift client registration

The broker needs to be a registered OAuth client *of OpenShift* so that
OpenShift accepts the redirect to its callback. This is a one-time admin
action — an `OAuthClient` cluster-scoped resource:

```yaml
apiVersion: oauth.openshift.io/v1
kind: OAuthClient
metadata:
  name: memoryhub-auth-broker
secret: <generated, stored in memoryhub-auth Secret>
redirectURIs:
  - https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/oauth/openshift/callback
grantMethod: prompt
accessTokenMaxAgeSeconds: 600
```

The `secret` lives in a Kubernetes Secret in the `memoryhub-auth` namespace
and is read by the broker at startup as `OPENSHIFT_OAUTH_CLIENT_SECRET`. The
broker also needs `OPENSHIFT_OAUTH_AUTHORIZE_URL`, `OPENSHIFT_OAUTH_TOKEN_URL`,
and `OPENSHIFT_USER_INFO_URL` env vars. These can be discovered from the
cluster at startup via `oc get .well-known/oauth-authorization-server` on the
cluster API endpoint, but for the demo a static config is fine.

`grantMethod: prompt` shows users a "do you authorize memoryhub-auth-broker"
consent screen the first time. `auto` would skip it; `prompt` is the
appropriate default for any client that asks for user identity.

## Well-known metadata updates

`memoryhub-auth/src/routes/well_known.py` needs:

```python
"authorization_endpoint": f"{base}/authorize",
"grant_types_supported": [
    "client_credentials",
    "refresh_token",
    "authorization_code",
],
"response_types_supported": ["code"],
"code_challenge_methods_supported": ["S256"],
"token_endpoint_auth_methods_supported": [
    "client_secret_post",
    "none",                # public clients (LibreChat)
],
```

The `none` auth method matters: LibreChat may register as a public client
without a secret, relying on PKCE alone. The broker has to accept that for
public clients while still requiring `client_secret` for confidential ones.
This is a per-client flag in `oauth_clients` (new column `public bool`).

## Test surface

The PKCE happy path is the easy one. The interesting tests are the negative
cases:

- Mismatched `code_verifier` at `/token` rejects with `invalid_grant`.
- Replayed code (same code submitted twice) rejects the second attempt.
- Expired session at `/oauth/openshift/callback` rejects without calling
  OpenShift.
- Missing `state` at the OpenShift callback rejects without trusting the
  request.
- `redirect_uri` at `/token` not matching the one stored in the session
  rejects.
- `code_challenge_method=plain` at `/authorize` rejects.
- `client_id` mismatch between `/authorize` and `/token` rejects.
- OpenShift user-info call failing (network, 401, malformed) returns a clean
  error to the client without leaking details.
- JIT user provisioning gated by allowlist: an OpenShift user not in the
  allowlist gets a clean denial, not a 500.

End-to-end test: a Python script that simulates LibreChat's flow against a
deployed broker, drives the OpenShift consent step via headless browser, and
verifies the resulting JWT can call MCP `search_memory` successfully.

## Open questions

These are decisions to make during implementation, not blockers for filing
issues.

1. **Where does the MemoryHub identity for an OpenShift user live?** Options:
   (a) a new `users` table in `memoryhub-auth` populated by JIT on first
   login; (b) the existing `users-configmap.yaml` consumed by the MCP server,
   read by the broker via the K8s API; (c) no persistence at all — the
   broker mints a JWT with the OpenShift username as `sub` and lets the MCP
   server handle whatever it needs from there. (c) is simplest and matches
   the current MCP-server posture, which already trusts whatever `sub` the
   JWT carries. Recommendation: **start with (c)**, add (a) only if a real
   need emerges (e.g., per-user scope grants).

2. **Tenant assignment for human users.** OpenShift does not know about
   MemoryHub tenants. Options: (i) single-tenant, hardcode `tenant_id =
   "default"` in the broker; (ii) read tenant from an OpenShift group claim
   (`memoryhub-tenant-{name}`); (iii) read tenant from a per-cluster env
   var on the broker. For the demo, **(i) is sufficient**. The broker
   should expose tenant via env var so different broker deployments can
   serve different tenants if that becomes needed.

3. **Default scopes for human users.** Recommendation: `memory:read:user`
   and `memory:write:user`. Anything broader (`organizational`, `enterprise`,
   admin-tier) requires an out-of-band grant. The broker should not silently
   give human users elevated scopes.

4. **Allowlist gate.** Should the broker accept *any* authenticated
   OpenShift user, or only users in a specific OpenShift group? For
   production this matters; for the demo cluster (single-user OpenShift
   sandbox), it does not. Recommendation: **gate on an OpenShift group
   name configured via env var, default unset = allow-all**. Production
   deployments set the env var; demo deployments leave it unset.

5. **Refresh token behavior for browser clients.** LibreChat's reconnection
   manager refreshes automatically. The current refresh-token implementation
   in `routes/token.py:128` requires `client_id` + `client_secret`. For
   public clients (PKCE-only) this would break. The refresh handler needs
   the same `public` flag check as the new authorization-code handler.

## Out of scope

These are *not* part of this work, even though they're tangentially related:

- **kagenti SPIFFE-based token exchange (RFC 8693).** Tracked separately in
  `../../planning/kagenti-integration/`. That work concerns service identities being
  exchanged across trust boundaries, not human users in browsers.
- **Per-user RBAC grants.** The broker mints JWTs with default scopes. A
  separate mechanism for granting elevated scopes to specific users (admin
  panel, CLI, GitOps) is its own design question.
- **Audit log of broker authentications.** The broker should log
  authentications somewhere durable, but the audit-log story belongs to
  `docs/governance.md` and the identity-model audit stub, not here.
- **Multi-issuer support in the MCP server.** The MCP server keeps trusting
  only `memoryhub-auth` JWTs. Federating with external IdPs that issue their
  own JWTs is a different design.
- **Logout / token revocation UI.** OAuth 2.1 token revocation
  (RFC 7009) is a follow-up, not part of this work.

## Status

Design draft. Implementation has not started. Issues filed against this
document:

- Tracker: [#74](https://github.com/rdwj/memory-hub/issues/74)
- Children: [#75](https://github.com/rdwj/memory-hub/issues/75),
  [#76](https://github.com/rdwj/memory-hub/issues/76),
  [#77](https://github.com/rdwj/memory-hub/issues/77),
  [#78](https://github.com/rdwj/memory-hub/issues/78),
  [#79](https://github.com/rdwj/memory-hub/issues/79),
  [#80](https://github.com/rdwj/memory-hub/issues/80),
  [#81](https://github.com/rdwj/memory-hub/issues/81)

See the [tracking section of the README](README.md#tracking-issues) for the
canonical list.
