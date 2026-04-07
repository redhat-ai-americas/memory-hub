# Authentication

This folder captures the authentication flows MemoryHub speaks: how callers
prove who they are, where the credentials come from, and how the resulting
tokens get to the MCP server.

## Why this is separate from `docs/identity-model/`

The two folders cover adjacent but distinct concerns:

- **`docs/identity-model/`** is about *authorization* — once a request has a
  validated identity, what is that identity allowed to do? Project-membership
  enforcement, the `owner_id`/`actor_id`/`driver_id` triple, scope rules,
  the audit log. It assumes the identity already exists.
- **`docs/auth/`** (this folder) is about *authentication* — how does an
  identity get minted in the first place? OAuth grant flows, the auth server,
  IdP integration, JWT issuance, the token endpoints.

The handoff point is the JWT. Anything that produces one belongs here;
anything that consumes one belongs in `docs/identity-model/`.

## Current state

`memoryhub-auth` is deployed and serves two OAuth 2.1 grant types today:

- `client_credentials` — for agents, SDKs, and any other machine-to-machine
  caller that holds a `client_id` + `client_secret`.
- `refresh_token` — for long sessions, with rotation on every refresh.

It signs RS256 JWTs and exposes JWKS at
`/.well-known/jwks.json`. The MCP server's `JWTVerifier` validates against
that JWKS. RBAC enforcement happens server-side in
`memory-hub-mcp/src/core/authz.py`; see
[`docs/identity-model/authorization.md`](../identity-model/authorization.md)
for the consumer side.

What it does *not* serve today is anything that involves a human in a
browser. There is no `/authorize` endpoint, no PKCE, no login UI. That gap
is what [`openshift-broker.md`](openshift-broker.md) addresses.

## Documents in this folder

- **[openshift-broker.md](openshift-broker.md)** — Design for adding OAuth
  2.1 `authorization_code + PKCE` to `memoryhub-auth` by brokering through
  OpenShift's built-in OAuth server. Motivation, the flow diagram, the
  endpoints to add, the data model, OpenShift `OAuthClient` registration,
  the test surface, and the open questions. Forced by LibreChat MCP
  integration; reusable for the dashboard and any other browser-facing
  consumer.
- **[librechat-integration.md](librechat-integration.md)** — Requirements
  and verification plan for wiring LibreChat as a second MCP client
  alongside Claude Code, proving the multi-client claim. Captures
  LibreChat's OAuth capabilities, the `librechat.yaml` config shape, the
  system prompt sketch, the eight-step end-to-end verification sequence,
  and the open questions. Hard-blocked on the broker tracker.

## Tracking issues

Issues that implement work specified in this folder are linked here so the
folder is a single navigable index.

### OpenShift OAuth broker ([openshift-broker.md](openshift-broker.md))

- **[#74](https://github.com/rdwj/memory-hub/issues/74)** — Tracking issue (design)
- [#75](https://github.com/rdwj/memory-hub/issues/75) — Add `auth_sessions` table and migration
- [#76](https://github.com/rdwj/memory-hub/issues/76) — Implement `/authorize` endpoint with PKCE
- [#77](https://github.com/rdwj/memory-hub/issues/77) — Implement `/oauth/openshift/callback` with user-info resolution
- [#78](https://github.com/rdwj/memory-hub/issues/78) — Extend `/token` with `authorization_code` grant
- [#79](https://github.com/rdwj/memory-hub/issues/79) — Register `memoryhub-auth` as OpenShift `OAuthClient` (infra)
- [#80](https://github.com/rdwj/memory-hub/issues/80) — Advertise `authorization_endpoint` in well-known metadata
- [#81](https://github.com/rdwj/memory-hub/issues/81) — End-to-end PKCE flow integration test

### LibreChat integration ([librechat-integration.md](librechat-integration.md))

- [#82](https://github.com/rdwj/memory-hub/issues/82) — Integrate MemoryHub with LibreChat as second MCP client _(blocked on #74)_
