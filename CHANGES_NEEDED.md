# Changes Needed -- Install Test Findings

Test cluster: `memory-hub-install-test` (dl92l, sandbox2953)
Date: 2026-07-20

## Finding 1: RHOAI prereq check is a hard gate but not a real dependency

`check-prereqs.sh` hard-fails when `redhat-ods-applications` namespace doesn't exist.
MemoryHub core (DB, MCP, Auth, embedding, reranker) does not actually require RHOAI
to be installed. RHOAI is only needed for:
- The `deploy_tile` step (OdhApplication CR in redhat-ods-applications)
- The `deploy_ui` step (if it uses the RHOAI dashboard cross-namespace proxy)

**Proposed fix:** Downgrade the RHOAI check from FAIL to WARN in `check-prereqs.sh`.
The UI tile and RHOAI integration steps already have their own guards (CRD existence
check, `--skip-tile`). A missing RHOAI shouldn't prevent the core stack from deploying.

## Finding 2: Makefile doesn't forward arguments to deploy-full.sh

`make install -- --skip-prereqs` doesn't pass `--skip-prereqs` to the script.
The Makefile target is just `scripts/deploy-full.sh` with no `$(MAKEFLAGS)` or
argument forwarding.

The README documents `make install -- --gpu-models` and similar but this syntax
does not actually work.

**Proposed fix:** Change `install` and `uninstall` targets to forward args:
```makefile
install:
	scripts/deploy-full.sh $(INSTALL_ARGS)

uninstall:
	scripts/uninstall-full.sh $(UNINSTALL_ARGS)
```
Or simply document using the script directly for flag options.

## Finding 3: Auto-created venv missing bcrypt (seed-oauth-clients fails)

The preflight auto-venv step runs `pip install -e "$REPO_ROOT"` (no `[dev]` extra).
But `scripts/seed-oauth-clients.py` imports `bcrypt`, which is in the `[dev]` extras.
The deploy fails at the "Seeding OAuth clients" step with `ModuleNotFoundError: No module named 'bcrypt'`.

**Root cause:** `bcrypt` is declared in `memoryhub-auth/pyproject.toml` but the seed
script (`scripts/seed-oauth-clients.py`) runs from the root `.venv` which only has
`memoryhub-core` deps. It worked on the dev machine because bcrypt was manually
installed in the root venv at some point.

**Proposed fix:** Add `bcrypt>=4.0` to the root `pyproject.toml` dependencies (not
just dev -- it's needed by a deploy script, not just tests). Alternatively, add it
to the `[dev]` extra AND change the auto-venv to install `[dev]`.

## Finding 4: seed-clients.json is gitignored -- auth seeding fails on fresh clone

`scripts/seed-clients.json` is gitignored. `scripts/seed-clients.example.json` exists
but the seed script doesn't fall back to it. On a fresh clone, the auth seeding step
fails with "No client data found."

Same pattern as the users-configmap: the script should auto-generate from the example
if the real file doesn't exist, or the `run-seed-oauth-clients.sh` wrapper should
copy the example template with generated secrets.

**Proposed fix:** In `scripts/run-seed-oauth-clients.sh`, if `seed-clients.json`
doesn't exist, generate it from `seed-clients.example.json` with random secrets
(same `secrets.token_hex(16)` pattern used for users-configmap).

## Finding 5: Two auth systems are confusing -- needs clear documentation

There are TWO auth paths that a fresh installer encounters:

1. **`memory-hub-mcp/deploy/users-configmap.yaml`** -- API key auth. Each entry is
   a user/agent with an `api_key` (bearer token) and `scopes` (memory-level scopes
   like `user`, `project`, `organizational`). This is the simpler path used by Claude
   Code, the CLI, and scripts. The ConfigMap is mounted into the MCP server pod.

2. **`scripts/seed-clients.json`** -- OAuth 2.1 client registration. Each entry is
   an OAuth client with `client_id`, `client_secret`, `identity_type`, and
   `default_scopes` (OAuth scopes like `memory:read`, `memory:write:user`,
   `memory:admin`). This is the more complex path used by the auth service for
   token-based flows, browser-based PKCE, and service-to-service auth.

A fresh installer sees both and doesn't know which to use or how they relate. The
example files use different scope formats (`scopes` vs `default_scopes`), different
key formats (`api_key` vs `client_secret`), and different field names.

**Proposed fix:**
- Add clear comments in both example files explaining which auth path they serve
- The auto-generate logic for seed-clients.json should produce working admin +
  regular client examples. Suggested entries:

Admin/operator client (seed-clients.json):
```json
{
  "client_id": "admin",
  "client_secret": "<generated>",
  "client_name": "Cluster Admin",
  "identity_type": "user",
  "tenant_id": "default",
  "default_scopes": ["memory:read", "memory:write:user", "memory:write:organizational", "memory:admin"]
}
```

Regular agent client (seed-clients.json):
```json
{
  "client_id": "my-agent",
  "client_secret": "<generated>",
  "client_name": "My Agent",
  "identity_type": "service",
  "tenant_id": "default",
  "default_scopes": ["memory:read", "memory:write:user"]
}
```

Users-configmap admin entry:
```json
{
  "user_id": "admin",
  "name": "Cluster Admin",
  "api_key": "<generated>",
  "tenant_id": "default",
  "scopes": ["user", "project", "role", "organizational", "enterprise"]
}
```

Users-configmap regular agent entry:
```json
{
  "user_id": "my-agent",
  "name": "My Agent",
  "api_key": "<generated>",
  "identity_type": "service",
  "tenant_id": "default",
  "scopes": ["user", "project"]
}
```

- Ideally the seed-clients.json and users-configmap.yaml should be generated from the
  same source (one user definition, two representations) to avoid config drift. But
  that's a larger refactor -- for now, clear examples and auto-generation are the fix.

## Finding 7: Auto-generated API keys don't follow mh-dev-<hex> format

The users-configmap auto-generator uses `secrets.token_hex(16)` which produces
plain hex like `624c6d3079ade62d`. The example template placeholder is
`REPLACE-ME-GENERATE-WITH-openssl-rand-hex-16`. But the MCP server's
register_session error messages and documentation reference `mh-dev-<hex>` format.

The format itself is not validated in code (the key is just matched against the
ConfigMap), but the inconsistency confuses users.

**Proposed fix:** Generate keys with the `mh-dev-` prefix:
`f"mh-dev-{secrets.token_hex(16)}"` instead of `secrets.token_hex(16)`.
Update the example template placeholder to match.

## Finding 8: configure_local_client skips when api-key file exists (wrong cluster)

`configure_local_client()` checks `if [ -f "$api_key_file" ]` and returns early.
But the existing key may be from a different cluster (as happened here: key from
memory-hub-fips was present when deploying to memory-hub-install-test).

The smoke test then fails because the local API key doesn't match the new cluster's
ConfigMap.

**Proposed fix:** Either:
(a) Always overwrite the API key file (since you're deploying to a new cluster), OR
(b) Compare the existing key against the current cluster's ConfigMap and warn if
    they don't match, offering to overwrite

Option (a) is simpler but could surprise a user with multiple clusters. Option (b)
is safer. Either way, the smoke test should use the key from the just-deployed
ConfigMap, not the file on disk.

## Finding 9: Smoke test uses wrong CLI flag (--max-results vs --max)

`smoke_test()` in deploy-full.sh uses `memoryhub search "smoke test" --max-results 3`
but the CLI's actual flag is `--max` / `-n`.

**Proposed fix:** Change `--max-results 3` to `--max 3` in the smoke test.

## Finding 10: greenlet missing from main dependencies

`seed-oauth-clients.py` uses SQLAlchemy async (which requires greenlet).
`greenlet` is in `[dev]` extra only. The auto-venv installs just the main deps.

**Proposed fix:** Move `greenlet` from `[dev]` to main dependencies in pyproject.toml.
It's required by any async SQLAlchemy usage, which includes the deploy scripts.

## Finding 6: Auth deploy.sh expects its own .venv (not auto-created)

`memoryhub-auth/deploy.sh` line 167 runs `.venv/bin/alembic upgrade head` but this
is the auth service's local `.venv`, not the root one. On a fresh clone,
`memoryhub-auth/.venv` doesn't exist. The auth deploy will fail with
"alembic: command not found" or similar.

The root deploy-full.sh auto-creates the root `.venv` but the auth deploy.sh has no
equivalent auto-setup for its own venv.

**Proposed fix:** Either:
(a) Have `memoryhub-auth/deploy.sh` auto-create its `.venv` (same pattern as root
    deploy-full.sh preflight), OR
(b) Have `memoryhub-auth/deploy.sh` use the root `.venv` for migrations (it's the
    same DB, same alembic, and memoryhub_core already has all the model deps)

Option (b) is simpler since deploy-full.sh already creates the root venv.
