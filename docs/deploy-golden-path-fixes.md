# Deploy Golden Path Fixes (2026-07-20)

A colleague attempting a fresh MemoryHub install on a new OpenShift AI cluster hit multiple failures. This document captures what was broken, why, and what we did to fix it.

## What was broken

Seven issues prevented `deploy-full.sh` from producing a working MemoryHub on any cluster other than the original development sandbox (cluster-n7pd5).

### 1. Hardcoded cluster URLs everywhere

The MCP server deployment manifest (`openshift.yaml`) had the auth service's JWKS and issuer URLs baked in as string literals pointing to `apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com`. The MCP deploy script (`deploy.sh`) hardcoded embedding and reranker model URLs to the same domain. The OAuthClient redirect URI was similarly pinned. On any other cluster, JWT verification would fail, embedding calls would error out, and OAuth login would redirect to a nonexistent host.

**Files affected:** `memory-hub-mcp/deploy/openshift.yaml`, `memory-hub-mcp/deploy/openshift-minimal.yaml`, `memory-hub-mcp/deploy/deploy.sh`, `memoryhub-auth/deploy/oauthclient.yaml`

### 2. Embedding and reranker models never deployed

`deploy-full.sh` had no step to deploy the embedding or reranker models. Manifests existed in `deploy/embedding/` and `deploy/reranker/` but were never applied. The MCP deploy script set the embedding URL to a route that didn't exist, causing the `HttpEmbeddingService` to fail with connection errors. The fallback to `MockEmbeddingService` only activates when `MEMORYHUB_EMBEDDING_URL` is *unset*, but deploy.sh *did* set it (to a broken URL).

Additionally, the existing manifests required GPU nodes (`nvidia.com/gpu: "1"` with L40S tolerations), making them unusable on clusters without GPUs.

### 3. Retention CronJob broken in three ways

`deploy/retention/cronjob.yaml` had:
- **Wrong secret key names:** Referenced `host`, `port`, `database`, `username`, `password` but the actual `memoryhub-db-credentials` secret uses `MEMORYHUB_DB_HOST`, `MEMORYHUB_DB_PORT`, etc.
- **Wrong S3 secret:** Referenced `memoryhub-s3-credentials` (which doesn't exist) instead of `memoryhub-minio-credentials`, with mismatched key names.
- **Non-existent container image:** Referenced `memoryhub/memoryhub-core:latest` but no such ImageStream or BuildConfig exists anywhere in the deploy pipeline.

Result: CronJob pods would fail with `CreateContainerConfigError` on every scheduled run.

### 4. OAuthClient redirect URI hardcoded

`memoryhub-auth/deploy/oauthclient.yaml` had the redirect URI hardcoded to the development cluster's domain. The auth deploy script (`deploy.sh`) substituted the OAuth secret at deploy time but did not touch the redirect URI. On a different cluster, the OpenShift OAuth flow would fail because the callback URL wouldn't match the registered client.

### 5. UI deploy searched for stale embedding model name

`memoryhub-ui/deploy/deploy.sh` hardcoded `all-minilm-l6-v2` as the embedding service name to look up. The embedding model had been switched to `granite-embedding` in July 2026, so the lookup always failed. The UI would fall back to text-only search.

### 6. Deploy order prevented auth URL resolution

`deploy-full.sh` deployed the MCP server (step 4) *before* the auth server (step 5). Since the MCP server needed the auth route to configure its JWKS endpoint, and the auth route didn't exist yet on a fresh cluster, JWT verification couldn't be configured. The auth deploy script handled its own URLs dynamically, but the MCP deploy had no equivalent logic.

### 7. Uninstall didn't clean up model namespaces

`uninstall-full.sh` had no awareness of the `embedding-model` or `reranker-model` namespaces. A teardown followed by a fresh deploy could leave stale model deployments behind.

## What we fixed

### Dynamic URL resolution (issues 1, 4, 6)

Replaced all hardcoded cluster URLs with runtime resolution:

- **MCP `openshift.yaml`:** Auth URLs replaced with `__AUTH_JWKS_URI__` and `__AUTH_ISSUER__` sed placeholders, substituted at deploy time from the actual auth route.
- **MCP `deploy.sh`:** Added `apply_manifest()` function (matching the pattern auth `deploy.sh` already uses). Embedding and reranker URLs resolved dynamically by querying services in the `embedding-model` and `reranker-model` namespaces. When a service isn't found, the env var is omitted and the MCP server falls back to its mock/noop implementation gracefully.
- **OAuthClient:** Redirect URI replaced with `__REDIRECT_URI__` placeholder. Auth `deploy.sh` now resolves the cluster's apps domain via `oc get ingress.config.openshift.io cluster` and constructs the correct callback URL.
- **Deploy order:** Reordered `deploy-full.sh` so auth deploys before MCP, ensuring the auth route exists when MCP resolves its JWKS endpoint.

### CPU-default model deployment (issue 2)

- Replaced `deploy/embedding/` with CPU-based `all-MiniLM-L6-v2` manifests (HuggingFace TEI `cpu-1.6` image, no GPU required, 384-dim output matching the existing pgvector schema).
- Replaced `deploy/reranker/` with CPU-based `ms-marco-MiniLM-L12-v2` manifests (same TEI image).
- Preserved the original GPU granite manifests in `deploy/embedding-gpu/` and `deploy/reranker-gpu/` as optional overlays.
- Added `deploy_models()` step to `deploy-full.sh` with `--skip-models` and `--gpu-models` flags.

### Retention CronJob fix (issue 3)

- Changed secret key references to match the actual keys: `MEMORYHUB_DB_HOST`, `MEMORYHUB_DB_PORT`, `MEMORYHUB_DB_NAME`, `MEMORYHUB_DB_USER`, `MEMORYHUB_DB_PASSWORD`.
- Changed S3 config to use `memoryhub-minio-credentials` with `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` keys, and an inline `value` for the endpoint hostname.
- Changed image to the MCP server imagestream (`memory-hub-mcp/memory-hub-mcp:latest`) which contains the `memoryhub_core` library.

### UI deploy fix (issue 5)

Changed the hardcoded service name lookup to a dynamic discovery: `oc get svc -n embedding-model` finds whatever embedding service exists, regardless of model name.

### Uninstall lifecycle (issue 7)

Added `remove_model_namespaces()` to `uninstall-full.sh` with `--skip-models` flag, cleaning up `embedding-model` and `reranker-model` namespaces.

## Validation

Full teardown and fresh deploy on the `memory-hub-fips` cluster (zks6c, sandbox417):

- `uninstall-full.sh --yes --no-backup` completed cleanly
- `deploy-full.sh --skip-prereqs --skip-ui --skip-tile` completed in 8 minutes
- All 7 pods running: PostgreSQL, MinIO, Valkey, embedding (all-MiniLM-L6-v2), reranker (ms-marco-MiniLM-L12-v2), auth server, MCP server
- 26 Alembic migrations applied from empty database
- Auth health check: `{"status":"ok"}`
- MCP endpoint responding (406 on GET = correct for streamable-http)
- Embedding URL resolved to `http://all-minilm-l6-v2.embedding-model.svc.cluster.local:80/embed`
- Reranker URL resolved to `http://ms-marco-minilm-l12-v2.reranker-model.svc.cluster.local:80`
- Retention CronJob secret references validated against actual secrets
- `grep` confirms zero hardcoded cluster URLs remain in deploy files
