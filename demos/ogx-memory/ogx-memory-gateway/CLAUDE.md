# CLAUDE.md

## Project Overview

Go HTTP reverse proxy that provides an OpenAI-compatible interface in front of AI agent backends. Accepts `/v1/chat/completions` requests (sync and streaming), proxies them to a configurable backend, and handles SSE lifecycle management.

## Development Commands

```bash
# Build the binary
make build

# Run locally (backend URL required)
BACKEND_URL=http://localhost:8081 make run

# Run tests
make test

# Run linter
make lint

# Build container image
make image-build
```

## Architecture

This is a thin reverse proxy -- minimal external dependencies. The core proxy and auth middleware use the Go standard library only; the `jwt` auth mode adds two stdlib-crypto-only third-party deps (`github.com/golang-jwt/jwt/v5`, `github.com/MicahParks/keyfunc/v3`) to validate inbound bearer tokens against a JWKS endpoint. The optional RFC 8693 token-exchange path on top of `jwt` mode adds no new third-party deps — it speaks plain `application/x-www-form-urlencoded` to the IdP's token endpoint via stdlib `net/http`. Both crypto libraries route through Go's FIPS-certified crypto module when the binary is built with FIPS enabled.

```
Client --> Gateway (:8080) --> Backend Agent
                       \---> Platform (optional, when GATEWAY_PLATFORM_URL set)
             |
             +-- /v1/chat/completions  (POST, sync + SSE streaming, propagates X-Trace-Id)
             +-- /v1/feedback          (POST/GET, pass-through, forwards auth headers; routable to platform)
             +-- /v1/feedback/{id}     (PATCH, in-place edit; routable to platform)
             +-- /v1/feedback/stats    (GET, pass-through; routable to platform)
             +-- /v1/sessions/*        (any method, opaque proxy; routable to platform)
             +-- /v1/sessions/{id}/usage (GET, agent-only — pricing computed in-process)
             +-- /v1/traces/*          (any method, opaque proxy; routable to platform)
             +-- /v1/files             (POST streaming multipart proxy; size cap + MIME allowlist)
             +-- /v1/files             (GET pass-through, list)
             +-- /v1/files/{file_id}   (GET/DELETE pass-through)
             +-- /v1/agent-info        (GET, pass-through to backend)
             +-- /healthz              (GET, liveness)
             +-- /readyz               (GET, checks backend)
             +-- /.well-known/agent.json (GET, agent card)
```

**Platform routing mode (gateway-template#30, chart 0.5.0).** When `GATEWAY_PLATFORM_URL` is set, the three persistence prefixes (`/v1/feedback*`, `/v1/sessions/*`, `/v1/traces/*`) proxy to a deployed [`fipsagents-platform`](https://github.com/fips-agents/fipsagents-platform) service instead of fanning out to per-agent backends. Per-prefix toggles (`GATEWAY_PLATFORM_ROUTE_{FEEDBACK,SESSIONS,TRACES}`) default to `true` when `PLATFORM_URL` is set; flip individual ones to `false` to keep that prefix on the agent. `GET /v1/sessions/{id}/usage` is always agent-routed because it computes USD cost from the agent's `PricingConfig` and is not a platform endpoint. The forwarding handler (`internal/handler/forward.go`, `httputil.ReverseProxy`-based) preserves method, body, query string, `Authorization`, `X-Auth-*`, `X-Tenant`, and `traceparent` headers verbatim — it does not parse request bodies.

Key packages:
- `cmd/server/` -- entry point, wiring, graceful shutdown
- `internal/config/` -- environment variable parsing
- `internal/handler/` -- HTTP handlers for each route
- `internal/middleware/` -- request logging (structured, skips health probes)
- `internal/auth/` -- inbound auth strategies (`anonymous`, `proxy`, `jwt`) + middleware that strips spoofed `X-Auth-*` headers and projects canonical identity onto the request. `jwt` mode validates `Authorization: Bearer <token>` against a configured JWKS endpoint (cached by `kid`), enforces `iss`/`aud`/`exp`/`nbf`, and maps invalid tokens → 401 vs. JWKS-cold-cache failures → 503. Optional RFC 8693 token exchange (`exchange.go`) swaps the inbound user JWT for a downstream-audienced token before the handler runs; `Identity.BearerToken` carries the swapped value, the middleware projects it as `Authorization: Bearer <token>` on the request (or strips Authorization entirely when no swap is configured), and handlers forward it to the backend
- `internal/proxy/` -- SSE relay logic

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | Yes | -- | Backend agent base URL |
| `PORT` | No | `8080` | Listen port |
| `AGENT_NAME` | No | `gateway-template` | Name in agent card |
| `AGENT_VERSION` | No | `0.1.0` | Version in agent card |
| `LOG_REQUESTS` | No | `false` | Enable structured request logging |
| `GATEWAY_AUTH_MODE` | No | `anonymous` | Inbound auth strategy: `anonymous`, `proxy`, or `jwt` |
| `GATEWAY_AUTH_PROXY_USER_HEADER` | No | `X-Forwarded-User` | (`proxy` mode) upstream-validated username header |
| `GATEWAY_AUTH_PROXY_EMAIL_HEADER` | No | `X-Forwarded-Email` | (`proxy` mode) upstream-validated email header |
| `GATEWAY_AUTH_JWT_JWKS_URL` | jwt mode | -- | (`jwt` mode) JWKS endpoint URL |
| `GATEWAY_AUTH_JWT_ISSUER` | jwt mode | -- | (`jwt` mode) expected `iss` claim |
| `GATEWAY_AUTH_JWT_AUDIENCE` | jwt mode | -- | (`jwt` mode) expected `aud` claim |
| `GATEWAY_AUTH_JWT_SUBJECT_CLAIM` | No | `sub` | (`jwt` mode) claim → `X-Auth-Subject` |
| `GATEWAY_AUTH_JWT_USER_CLAIM` | No | `preferred_username` | (`jwt` mode) claim → `X-Auth-User` |
| `GATEWAY_AUTH_JWT_EMAIL_CLAIM` | No | `email` | (`jwt` mode) claim → `X-Auth-Email` |
| `GATEWAY_AUTH_JWT_JWKS_REFRESH_RATE_LIMIT` | No | -- | (`jwt` mode) Go duration capping how often the JWKS client refreshes in response to an unknown `kid`. Unset keeps keyfunc's default of 1 refresh per 5 minutes. Lower for faster post-rotation recovery; higher to harden against forged-kid bursts. |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_URL` | exchange | -- | (`jwt` mode) RFC 8693 token endpoint; setting all four required exchange vars enables the swap |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_ID` | exchange | -- | (`jwt` mode) gateway service-account client ID |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_CLIENT_SECRET` | exchange | -- | (`jwt` mode) gateway service-account client secret |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_AUDIENCE` | exchange | -- | (`jwt` mode) downstream audience the swapped token targets |
| `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_SCOPE` | No | -- | (`jwt` mode) optional space-separated scope set requested on the swap |
| `GATEWAY_PLATFORM_URL` | No | -- | Base URL of a deployed `fipsagents-platform` service. When set, persistence prefixes proxy here; trailing slash trimmed. |
| `GATEWAY_PLATFORM_ROUTE_FEEDBACK` | No | `true` (when `PLATFORM_URL` set) | Route `/v1/feedback*` to platform. Set `false` to keep on agent. No-op when `PLATFORM_URL` unset. |
| `GATEWAY_PLATFORM_ROUTE_SESSIONS` | No | `true` (when `PLATFORM_URL` set) | Route `/v1/sessions/*` to platform (except `/usage`, always agent). Set `false` to keep on agent. |
| `GATEWAY_PLATFORM_ROUTE_TRACES` | No | `true` (when `PLATFORM_URL` set) | Route `/v1/traces/*` to platform. Set `false` to keep on agent. |
| `GATEWAY_FILES_MAX_BYTES` | No | `26214400` (25 MiB) | Cap on multipart upload size. Accepts plain integers or values suffixed with `k`/`m`/`g` (binary). Requests over this size are rejected with 413 before the body is read; chunked clients are interrupted by `http.MaxBytesReader`. |
| `GATEWAY_FILES_ALLOWED_MIME` | No | -- | Comma-separated MIME allowlist for the file part of `/v1/files` uploads. Entries may be exact (`application/pdf`) or wildcard (`image/*`). Empty defers entirely to the agent's own allowlist. |
| `GATEWAY_FILES_UPLOAD_TIMEOUT` | No | `5m` | Per-request timeout for backend `POST /v1/files` calls. Larger than the chat-completion timeout so big uploads on slow links don't trip the gateway-side deadline before the agent finishes parsing. |

## File upload proxy

`POST /v1/files` is a streaming multipart proxy. The handler enforces two checks before forwarding:

- **Size cap.** If the inbound `Content-Length` exceeds `GATEWAY_FILES_MAX_BYTES`, the gateway returns 413 immediately. For chunked or missing-`Content-Length` requests, an `http.MaxBytesReader` interrupts the body once the cap is hit.
- **MIME allowlist.** The first multipart file part's declared `Content-Type` is validated synchronously against `GATEWAY_FILES_ALLOWED_MIME` *before* the upstream request fires. Disallowed types return 415 without ever contacting the backend. The agent runs its own libmagic-based content sniffing in `agent-template/packages/fipsagents/src/fipsagents/server/files.py` — gateway validation is defense in depth, not the authoritative gate.

The body itself is never buffered: the handler reads the inbound multipart, re-encodes parts via `mime/multipart.Writer`, and pipes them into the upstream request body. Form fields encountered before the file part (eg `session_id`) are read into memory because they're tiny by spec; file part bodies stream through `io.Copy`.

`GET /v1/files`, `GET /v1/files/{file_id}`, and `DELETE /v1/files/{file_id}` are opaque pass-throughs handled by the same `httputil.ReverseProxy` used for sessions/traces. Files are always agent-routed — there is no platform-side `/v1/files` surface today.

## Auth contract

The gateway emits canonical `X-Auth-Subject` / `X-Auth-User` / `X-Auth-Email` / `X-Auth-Mode` headers to the backend on every `/v1/*` request. Inbound copies are stripped before the strategy runs so clients cannot spoof identity. Header names match Kagenti's AuthBridge JWT claim shape, so an AuthBridge token and a fipsagents-issued token resolve onto the same canonical contract. `proxy` mode fails closed with 503 when the upstream user header is missing. `jwt` mode validates `Authorization: Bearer <token>` against a JWKS endpoint, returning 401 on bad/expired/wrong-issuer/wrong-audience tokens and 503 only when the JWKS endpoint is unreachable AND the cache is cold.

`Authorization` itself is part of the contract: by default the middleware strips inbound Authorization before the handler runs (so the gateway never forwards a raw user JWT). When the four `GATEWAY_AUTH_JWT_TOKEN_EXCHANGE_*` env vars are set together, the gateway performs an RFC 8693 swap of the inbound token (subject_token) for a downstream-audienced token (the `audience` form parameter), caches it for `min(expires_in − 30s, 5min)` keyed by `sha256(inbound-token)`, and forwards it as `Authorization: Bearer <swapped>` to the backend. Exchange failures fail closed with 503. Partial token-exchange config (some required vars set, others not) is rejected at startup so a typo cannot silently disable the swap.

### Live integration test

`internal/auth/jwt_keycloak_integration_test.go` is build-tagged `integration` and exercises `jwt` mode against a real Keycloak. To run:

```bash
eval "$(scripts/keycloak-test-setup.sh)"   # bootstraps a clean realm/client/user
go test -tags integration -run TestJWTAuth_LiveKeycloak ./internal/auth/...
```

The setup script targets the keycloak operator instance in the `keycloak` namespace of the `mcp-rhoai` cluster (overridable via `KC_CONTEXT` / `KC_NAMESPACE`). Without `KC_INTEGRATION=1` the tests skip, so CI without cluster access stays green.

## Deployment

Deploy to OpenShift using the Helm chart in `chart/`:

```bash
helm upgrade --install my-gateway chart/ \
  -n my-namespace \
  --set config.BACKEND_URL=http://my-agent:8080 \
  --set image.repository=image-registry.openshift-image-registry.svc:5000/my-namespace/gateway-template
```

## Sentinel Values

This is a template repository. The string `gateway-template` appears throughout and is replaced with the actual project name during scaffolding by `fips-agents create gateway <name>`.
