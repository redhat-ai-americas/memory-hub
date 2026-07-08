# gateway-template

An OpenAI-compatible HTTP reverse proxy for AI agent backends. It accepts `/v1/chat/completions` requests (synchronous and SSE streaming), proxies them to a configurable backend agent service, and handles the SSE connection lifecycle including heartbeats and flush. Built primarily on the Go standard library; the only third-party dependencies are the JWT/JWKS libraries used by `jwt` auth mode (both stdlib-crypto-only, FIPS-compatible).

## Quick Start

```bash
# Build
make build

# Run (set BACKEND_URL to your agent)
BACKEND_URL=http://localhost:8081 make run

# Test
curl http://localhost:8080/healthz
```

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | Yes | -- | Base URL of the backend agent service |
| `PORT` | No | `8080` | HTTP listen port |
| `AGENT_NAME` | No | `gateway-template` | Agent name in `/.well-known/agent.json` |
| `AGENT_VERSION` | No | `0.1.0` | Agent version in `/.well-known/agent.json` |
| `LOG_REQUESTS` | No | `false` | Enable structured request logging (skips health probes) |
| `GATEWAY_AUTH_MODE` | No | `anonymous` | Inbound auth strategy: `anonymous`, `proxy`, or `jwt` |
| `GATEWAY_AUTH_PROXY_USER_HEADER` | No | `X-Forwarded-User` | (`proxy` mode) header carrying the upstream-validated username |
| `GATEWAY_AUTH_PROXY_EMAIL_HEADER` | No | `X-Forwarded-Email` | (`proxy` mode) header carrying the upstream-validated email; empty disables email projection |
| `GATEWAY_AUTH_JWT_JWKS_URL` | jwt mode | -- | (`jwt` mode) URL of the JWKS endpoint, e.g. `https://kc/realms/x/protocol/openid-connect/certs` |
| `GATEWAY_AUTH_JWT_ISSUER` | jwt mode | -- | (`jwt` mode) expected `iss` claim |
| `GATEWAY_AUTH_JWT_AUDIENCE` | jwt mode | -- | (`jwt` mode) expected `aud` claim |
| `GATEWAY_AUTH_JWT_SUBJECT_CLAIM` | No | `sub` | (`jwt` mode) claim to project onto `X-Auth-Subject` |
| `GATEWAY_AUTH_JWT_USER_CLAIM` | No | `preferred_username` | (`jwt` mode) claim to project onto `X-Auth-User` |
| `GATEWAY_AUTH_JWT_EMAIL_CLAIM` | No | `email` | (`jwt` mode) claim to project onto `X-Auth-Email` |
| `GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT` | No | -- | (`jwt` mode) Go duration capping how often the JWKS client refreshes the key set when a token presents an unknown `kid`. Unset inherits keyfunc's library default (one refresh per 5 minutes). |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL` | exchange | -- | (`jwt` mode, optional) RFC 8693 token endpoint. Setting this together with the next three enables token exchange. |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID` | exchange | -- | (`jwt` mode) confidential client representing the gateway's service account on the exchange request |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET` | exchange | -- | (`jwt` mode) client secret for the exchange request |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE` | exchange | -- | (`jwt` mode) downstream audience the swapped token is issued for |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_SCOPE` | No | -- | (`jwt` mode) optional space-separated scope set requested on the swap |
| `GATEWAY_FILES_MAX_BYTES` | No | `26214400` (25 MiB) | Max accepted size for `POST /v1/files`. Plain bytes or `k`/`m`/`g` suffix (binary). |
| `GATEWAY_FILES_ALLOWED_MIME` | No | -- | Comma-separated MIME allowlist for `POST /v1/files`. Exact (`application/pdf`) or wildcard (`image/*`). Empty defers to the agent. |
| `GATEWAY_FILES_UPLOAD_TIMEOUT` | No | `5m` | Per-request timeout for backend `POST /v1/files`. |

## File uploads

`POST /v1/files` is proxied to the agent as a streaming multipart upload. Two checks run before any byte reaches the agent:

- **Size cap** — `GATEWAY_FILES_MAX_BYTES`. Inbound `Content-Length` over the cap returns 413 immediately. Chunked or unsigned-length bodies are interrupted by `http.MaxBytesReader`.
- **MIME allowlist** — `GATEWAY_FILES_ALLOWED_MIME` (comma-separated, supports `image/*` wildcards). The first multipart file part's declared `Content-Type` is validated *before* the upstream request fires; rejections return 415 without contacting the backend.

The body is never buffered: form fields (e.g. `session_id`) are read into memory because they're tiny by spec, but the file part body is `io.Copy`'d into a re-encoded multipart that streams through a pipe to the backend. Defense in depth on top of the agent's own libmagic-based content sniffing — not a replacement.

`GET /v1/files`, `GET /v1/files/{file_id}`, and `DELETE /v1/files/{file_id}` are opaque pass-throughs to the agent.

## Authentication

The gateway issues a canonical set of trusted headers to the backend agent on every request:

| Header | Description |
|---|---|
| `X-Auth-Subject` | Stable identifier (`anonymous` or the upstream-validated username) |
| `X-Auth-User` | Human-readable username (may be empty in `anonymous` mode) |
| `X-Auth-Email` | Email address (may be empty) |
| `X-Auth-Mode` | `anonymous`, `proxy`, or `jwt` |

Inbound copies of these headers are stripped before the strategy runs, so a client cannot spoof identity by setting them directly. The header names match Kagenti's JWT claim shape, so an AuthBridge token and a fipsagents-issued token resolve onto the same canonical contract.

**Modes** (`GATEWAY_AUTH_MODE`):

- `anonymous` *(default)* — no validation. `X-Auth-Subject` is set to `anonymous`. Use for local dev, smoke tests, or any deployment that does not need user attribution.
- `proxy` — trust an upstream OAuth proxy (e.g. OpenShift `oauth-proxy` sidecar) or service-mesh `outputClaimToHeaders` filter. The gateway reads `X-Forwarded-User` / `X-Forwarded-Email` (header names configurable) and projects them onto the canonical headers. **The gateway pod must be unreachable except via that proxy** — otherwise a client can spoof the upstream headers. If the user header is missing, the gateway returns 503 (fail closed).
- `jwt` — in-process bearer-token validation against a JWKS endpoint. The gateway reads `Authorization: Bearer <token>`, validates the signature against keys fetched from `GATEWAY_AUTH_JWT_JWKS_URL` (cached by `kid`), enforces `iss`, `aud`, `exp`, `nbf`, and projects the configured claims onto the canonical headers. Returns 401 on invalid/expired/wrong-issuer/wrong-audience tokens, 503 if the JWKS endpoint is unreachable AND the cache is cold. Use this when there is no OAuth proxy in front of the gateway (self-contained deployments, or anywhere clients can present tokens directly). Only RSA / ECDSA / RSA-PSS signatures are accepted; HMAC and `alg=none` are rejected by construction.

### Token exchange (`jwt` mode only)

By default the gateway forwards canonical `X-Auth-*` headers to the backend but does **not** forward `Authorization` — the backend has to trust the gateway's header projection. That is fine when the gateway and backend share a trust boundary (same namespace, NetworkPolicy locked down). It is not fine when the call crosses a trust boundary (multi-agent chains, per-user-MCP scopes), where the downstream needs a *signed* assertion of who is calling.

Set the four `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_*` env vars together to opt in. The gateway will then, after validating the inbound JWT:

1. Call `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL` with `grant_type=urn:ietf:params:oauth:grant-type:token-exchange` (RFC 8693) using the configured confidential-client credentials, requesting an audience-narrowed swap of the inbound token.
2. Cache the swapped token in-process (TTL = `min(token-expiry − 30s, 5min)`) keyed by `sha256(inbound-token)`.
3. Forward the swap as `Authorization: Bearer <swapped>` to the backend, alongside the unchanged `X-Auth-*` headers.

The downstream service validates the swapped token against the same JWKS, sees the `aud` it expects, and gets a cryptographic assertion of who is calling. Exchange failures fail closed with 503 — the gateway never silently downgrades to forwarding without the swap. The raw inbound user JWT is **never** forwarded downstream; if exchange is disabled, `Authorization` is stripped entirely.

Partial configuration (some of the four required vars set, others not) is rejected at startup. Either configure all four or none.

**Choosing a mode:**

- Behind an OpenShift `oauth-proxy` sidecar or a service-mesh authn filter → `proxy`.
- Self-contained gateway exposed to clients that already hold a JWT (Keycloak, Auth0, Cognito, Azure AD, etc.) → `jwt`.
- Local development or smoke tests → `anonymous`.

**FIPS:** the JWT/JWKS implementation uses Go stdlib crypto only (no third-party crypto), so it routes through Go's FIPS module when the binary is built with `GOFIPS140=on` (Go ≥1.24) or `GOEXPERIMENT=boringcrypto` (Go ≤1.23).

## Endpoints

| Path | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions (sync + streaming) |
| `/v1/feedback` | POST, GET | User feedback submit/list (pass-through to backend) |
| `/v1/feedback/{feedback_id}` | PATCH | In-place edit of an existing feedback record |
| `/v1/feedback/stats` | GET | Aggregated feedback stats (pass-through to backend) |
| `/healthz` | GET | Liveness probe |
| `/readyz` | GET | Readiness probe (checks backend connectivity) |
| `/v1/agent-info` | GET | Pass-through to backend agent info (UI settings) |
| `/.well-known/agent.json` | GET | Agent discovery card |

All `/v1/*` endpoints forward the canonical `X-Auth-Subject` / `X-Auth-User` / `X-Auth-Email` / `X-Auth-Mode` headers (see Authentication above) so the backend can attribute requests to the resolved identity. Other request headers are dropped.

W3C Trace Context (`Traceparent` / `Tracestate`) is forwarded end-to-end on every backend hop and on the outbound RFC 8693 token-exchange call, so the gateway is a transparent hop in distributed traces. The agent layer's `fipsagents.server.propagation` joins the trace on inbound, and any OTEL backend (Tempo, Honeycomb, Grafana Cloud, etc.) sees a single connected trace per request.

On the response side the gateway propagates a small allowlist back to the client — currently just `X-Trace-Id`, which the agent backend sets on every chat completion response so the UI can submit feedback against a known trace.

## Deployment

Deploy to OpenShift with the included Helm chart:

```bash
helm upgrade --install my-gateway chart/ \
  -n my-namespace \
  --set config.BACKEND_URL=http://my-agent:8080 \
  --set image.repository=<registry>/my-gateway
```

## Scaffolding

This repository is a template used by [fips-agents-cli](https://github.com/fips-agents/fips-agents-cli). To create a new gateway project:

```bash
fips-agents create gateway my-gateway-name
```
