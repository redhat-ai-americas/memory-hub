# memoryhub-auth

OAuth 2.1 Authorization Server for MemoryHub.

## Architecture

FastAPI service with three grant types:
- `client_credentials` — agents and SDKs (confidential clients)
- `refresh_token` — token renewal (confidential and public clients)
- `authorization_code` + PKCE — browser-based humans via OpenShift OAuth broker

The broker delegates user authentication to OpenShift's built-in OAuth server and mints MemoryHub JWTs. See `docs/auth/openshift-broker.md` for the full design.

## Database Migrations (Alembic)

This service uses Alembic for schema management. The migration directory is `memoryhub-auth/alembic/`.

**Every model change requires a migration.** After editing `src/models.py`:
```bash
cd memoryhub-auth
.venv/bin/alembic revision --autogenerate -m "description of change"
# Review the generated migration in alembic/versions/
.venv/bin/alembic upgrade head  # apply locally
```

Never use `Base.metadata.create_all()` in production code or deploy scripts. It cannot add columns to existing tables and silently skips schema drift. The test suite uses SQLite with `create_all()` for speed — that's fine because tests start from an empty DB every run.

`deploy.sh` runs `alembic upgrade head` (via port-forward to the DB) before building and rolling out new code.

## Deploy Script

`deploy.sh` is the single entry point for deployment. It handles:
- Project/namespace creation
- RSA signing key generation (if missing)
- OpenShift OAuth client secret generation (if missing)
- OAuthClient CR application (if cluster-admin, with guard)
- Alembic migrations (port-forward to DB)
- Container build via OpenShift BuildConfig
- Rollout with image digest verification

**When adding a new Secret or K8s resource**, add it to deploy.sh following the existing generate-if-missing pattern (see the RSA keys block as the template).

## Admin API

The admin API at `/admin/clients` manages OAuth client registrations. All OAuthClient model fields that are user-configurable must be exposed in the API schemas (`src/schemas.py`). When adding a column to OAuthClient, update:
1. `CreateClientRequest` — if settable at creation time
2. `UpdateClientRequest` — if mutable after creation
3. `ClientResponse` — always (it's what the API returns)
4. `_client_to_response()` in `routes/admin.py` — to map the new field

## Testing

- SQLite in-memory via `tests/conftest.py` (strips PostgreSQL-only server defaults)
- `_ensure_uuid()` hook compensates for missing `uuid_generate_v4()` in SQLite
- Run: `cd memoryhub-auth && .venv/bin/python -m pytest tests/ -x -q`
- OpenShift HTTP calls in callback tests are mocked (patch `_exchange_openshift_code` and `_resolve_openshift_user`)

### E2e tests are mandatory for OpenShift API changes

Any change that touches the OpenShift OAuth redirect chain or calls an OpenShift API (groups, users, tokens) **must** be validated with `tests/integration/test_pkce_e2e.py` against the live cluster before merging. Unit tests with mocked HTTP responses cannot catch encoding conventions, permission models, or response shape surprises from the real APIs. Three bugs were invisible to unit tests but caught by e2e:

1. Wrong user-info URL (returned HTML instead of JSON)
2. IDP selection page not handled (multi-IDP clusters show a picker)
3. b64-encoded usernames in Groups API (`kube:admin` stored as `b64:a3ViZTphZG1pbg==` — the `in` check silently fails)

## Key Files

| File | What |
|------|------|
| `src/models.py` | OAuthClient, RefreshToken, AuthSession models |
| `src/routes/token.py` | POST /token (all three grant types) |
| `src/routes/authorize.py` | GET /authorize (PKCE broker entry) |
| `src/routes/openshift_callback.py` | GET /oauth/openshift/callback |
| `src/routes/admin.py` | Client management CRUD |
| `src/config.py` | AuthSettings (all env vars prefixed AUTH_) |
| `src/tokens.py` | JWT minting and refresh token creation |
| `deploy.sh` | Full deployment script |
| `deploy/oauthclient.yaml` | OpenShift OAuthClient CR |
| `openshift.yaml` | BuildConfig, Deployment, Service, Route |
