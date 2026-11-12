# Cluster Install Guide

MemoryHub installs to an OpenShift cluster with Red Hat OpenShift AI (RHOAI). The standard install deploys the application across seven namespaces. `make install` builds and deploys the full stack; Helm is an additional install path using the same namespace layout. For the personal edition (no infrastructure needed), see the [root README](../../README.md#get-started).

## Prerequisites

- `oc` logged in with cluster-admin on a cluster with RHOAI installed
- `podman` on your PATH (checked but not required for server-side builds)
- A default StorageClass (most clusters have one)
- Python 3.11+ on your PATH (the deploy script creates `.venv` automatically)
- Helm 3 and OpenSSL when using `make helm-install`

Run `make check-prereqs` to verify all of these non-destructively. GPUs are not required; the default install uses CPU-based embedding and reranker models.

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the "new contributor no-deploy" rule: if you're onboarding to this codebase, work against a local SQLite or Podman PostgreSQL instead of deploying to a cluster.

## Quick start

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
oc whoami --context mcp-rhoai   # verify the configured project cluster context
MEMORYHUB_CONTEXT=mcp-rhoai make install  # full stack deploy (~10 min)
```

That's it. The deploy script auto-creates the Python virtualenv (for Alembic migrations), generates API keys for the users ConfigMap if it doesn't exist, writes the first key to `~/.config/memoryhub/api-key` for CLI/SDK use, and runs a write/search/read smoke test at the end.

To bring your own API keys instead, copy the template before running install:

```bash
cp memory-hub-mcp/deploy/users-configmap.example.yaml \
   memory-hub-mcp/deploy/users-configmap.yaml
# Replace REPLACE-ME placeholders with: openssl rand -hex 16
MEMORYHUB_CONTEXT=mcp-rhoai make install
```

## What gets deployed

| Service | Namespace | What |
|---------|-----------|------|
| PostgreSQL + pgvector | `memoryhub-db` | Database (memories, threads, graph, auth tables) |
| MinIO | `memoryhub-storage` | S3-compatible object storage for oversized content |
| Valkey | `memory-hub-mcp` | Session focus state and compilation epoch cache |
| Embedding model | `embedding-model` | all-MiniLM-L6-v2 via HuggingFace TEI (CPU, 384-dim) |
| Reranker model | `reranker-model` | ms-marco-MiniLM-L12-v2 cross-encoder via TEI (CPU) |
| Auth service | `memoryhub-auth` | OAuth 2.1 authorization server (JWT, PKCE, API keys) |
| MCP server | `memory-hub-mcp` | FastMCP 3 server exposing memory operations |
| Dashboard UI | `memoryhub-ui` | React + PatternFly 6 frontend with FastAPI BFF |

The standard install uses seven namespaces: `memory-hub-mcp`, `memoryhub-db`,
`memoryhub-storage`, `memoryhub-auth`, `memoryhub-ui`, `embedding-model`, and
`reranker-model`. The `memoryhub-agents` manifests are a separate install path
and are not included in `make install` or Helm. If RHOAI is available,
`make install` also applies the optional dashboard tile in the platform-owned
`redhat-ods-applications` namespace; use `--skip-tile` to omit it. The Helm
chart does not manage that platform integration. The deploy script discovers
internal service endpoints at deploy time. Helm derives internal service DNS
names from the configured namespaces and `clusterDomain`; set the public auth
issuer and OAuth authorize URL in the Helm values file.

Expect 8-15 minutes on a first install. The MCP server, auth service, and UI each go through an OpenShift BuildConfig, and the embedding/reranker models need to download weights on first run.

## Targeting a specific cluster

The project cluster context is `mcp-rhoai`. Set it explicitly for install and
uninstall so the scripts do not depend on the active kubeconfig context:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make install
MEMORYHUB_CONTEXT=mcp-rhoai make uninstall
```

This passes `--context mcp-rhoai` on every `oc` command and does not change the
active kubeconfig context.

## Helm installation

For the same one-command experience as `make install`, run:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install
```

The installer creates the component namespaces, securely generates and copies
the required Secrets, runs both database migration sets, builds the MCP/auth/UI
images with the existing OpenShift build scripts, creates the OpenShift
OAuthClient, and then installs the chart. It uses the standard seven namespace
names and CPU models by default. To customize chart values, supply a YAML file:

```bash
cp charts/memoryhub/values-openshift.example.yaml values-openshift.yaml
# Tune resources, storage, probes, model selection, and other supported values.
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install ARGS="--values values-openshift.yaml"
```

To avoid building application images during installation, publish the images
to a registry the cluster can access, set the `mcp.image`, `auth.image`, and
`ui.image` repository/tag values in the file, then use:

```bash
cp charts/memoryhub/values-openshift.prebuilt.example.yaml values-openshift.yaml
# Replace the three image paths and tags with published images.
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install \
  ARGS="--prebuilt-images --values values-openshift.yaml"
```

This mode validates that the three application images use registry-qualified
paths, then skips the MCP/auth/UI builds. It still creates Secrets, runs
migrations, registers the OAuthClient, and installs the Helm release. This
repository does not currently publish those images in CI, so they must already
exist in a registry before using this mode. For custom namespaces, Route hosts,
or Secret names, use the direct chart workflow described in the chart guide.

The installer still requires the cluster permissions listed in the [Helm
chart guide](../../charts/memoryhub/README.md), including permission to create
namespaces, SCC bindings, the auth ClusterRoleBindings, and the cluster-scoped
OpenShift OAuthClient. It does not install the optional RHOAI dashboard tile;
that platform integration remains separate. The Helm path assumes a fresh
MemoryHub install with no existing workloads or data claims to adopt. Helm and
`make install` manage the same core resources, so use only one method in those
namespaces. The chart does not migrate a running Kustomize installation.

## Helm uninstall

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make helm-uninstall        # prompts for confirmation
MEMORYHUB_CONTEXT=mcp-rhoai make helm-uninstall ARGS="--yes"  # non-interactive
```

This removes the Helm release and cleans up two external resources that the
installer created outside Helm: the OpenShift OAuthClient and the optional
RHOAI dashboard tile and proxy. RHOAI cleanup is skipped automatically when
the `redhat-ods-applications` namespace is not present.

By default, PostgreSQL and MinIO data PVCs and all MemoryHub namespaces are
**retained** after uninstall. To also delete the namespaces and all data:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make helm-uninstall ARGS="--delete-namespaces --yes"
```

**Warning:** `--delete-namespaces` permanently deletes all stored memories,
PostgreSQL data, and MinIO objects. This cannot be undone.

To delete only the PVCs without touching the namespaces, set
`retainPvcOnUninstall: false` in your values file and re-run
`make helm-install` to apply the change before uninstalling. Or delete the
PVCs manually afterwards:

```bash
oc delete pvc --all -n memoryhub-db      --context mcp-rhoai
oc delete pvc --all -n memoryhub-storage  --context mcp-rhoai
```

## Deploy options

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make install                      # full stack (CPU models, default)
MEMORYHUB_CONTEXT=mcp-rhoai make install ARGS="--gpu-models"  # use GPU models instead
MEMORYHUB_CONTEXT=mcp-rhoai make install ARGS="--skip-models" # skip embedding/reranker
MEMORYHUB_CONTEXT=mcp-rhoai make install ARGS="--skip-ui --skip-tile" # headless
```

## Uninstall

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make uninstall                    # prompts for confirmation
MEMORYHUB_CONTEXT=mcp-rhoai make uninstall ARGS="--yes"       # non-interactive (CI)
MEMORYHUB_CONTEXT=mcp-rhoai make uninstall ARGS="--skip-data" # preserve database + storage
MEMORYHUB_CONTEXT=mcp-rhoai make uninstall ARGS="--skip-models" # keep model deployments
```

## Troubleshooting

**Image digest mismatch.** If the MCP deploy fails with `running digest does not match imagestream :latest`, the OpenShift deployment cached a stale image. Re-run the install and it will pick up the correct digest:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make install ARGS="--skip-data --skip-migrations --skip-auth"
```

**Reranker timeout with `--gpu-models`.** On single-GPU clusters, the embedding model takes the GPU. The reranker runs on CPU (with a GPU node toleration for scheduling). If the reranker times out, check for PVC contention -- the CPU model variant may still be running and holding the shared PVC. The deploy script scales down CPU models automatically, but leftover deployments from a prior install can interfere. Delete them manually with `oc delete deployment <cpu-model-name> --context mcp-rhoai -n reranker-model`.

## Partial deploys

The `deploy-db`, `deploy-mcp`, `deploy-auth`, `deploy-ui`, and `deploy-tile`
Make targets deploy one service at a time. Prefix each command with
`MEMORYHUB_CONTEXT=mcp-rhoai`; `make help` lists all targets.

## Post-install verification

The deploy script prints a summary banner with all Route URLs. Verify the MCP endpoint with:

```bash
# Health check (406 = correct for streamable-HTTP MCP)
curl -s -o /dev/null -w "%{http_code}" \
  https://memory-hub-mcp-memory-hub-mcp.apps.<cluster>/mcp/

# Auth health
curl -s https://auth-server-memoryhub-auth.apps.<cluster>/healthz
```

For full tool verification, use `mcp-test-mcp` to connect to the deployed MCP server and list its tools.

## After install

The install summary banner prints the routes for each service. Follow these steps to verify the deployment and connect your first agent.

**1. Get an API key.** The install creates a `memoryhub-users` ConfigMap in the `memory-hub-mcp` namespace with pre-seeded users and API keys. To view the available keys:

```bash
oc get configmap memoryhub-users --context mcp-rhoai -n memory-hub-mcp \
  -o jsonpath='{.data.users\.json}' | python3 -m json.tool
```

Copy a key (format: `mh-dev-<hex>`) and store it locally:

```bash
mkdir -p ~/.config/memoryhub
echo "mh-dev-<your-key>" > ~/.config/memoryhub/api-key
```

To add new users or rotate keys, see the [API key provisioning runbook](../runbooks/add-mcp-api-user.md).

**2. Install the CLI and SDK.**

```bash
pip install memoryhub-cli    # terminal client
pip install memoryhub        # Python SDK (optional, for scripting)
```

**3. Verify the deployment.** Use the CLI to test the connection:

```bash
memoryhub login              # configures endpoint + API key
memoryhub search "test"      # should return empty results on a fresh install
```

Or use the SDK directly:

```bash
python scripts/seed-sample-data.py \
  --url https://<your-mcp-route>/mcp/
```

This writes sample memories across multiple scopes so the dashboard has content to display.

**4. Connect Claude Code.** Add the MCP server to Claude Code (the server name `memoryhub` is required as the first positional argument):

```bash
claude mcp add memoryhub \
  --transport http \
  -s user \
  https://<your-mcp-route>/mcp/
```

Then set up the agent rule file so Claude Code knows how to use the tools:

```bash
memoryhub config init        # interactive wizard -- generates .memoryhub.yaml + .claude/rules/
```

**5. Open the dashboard from RHOAI.** When RHOAI is available and the install was not run with `--skip-tile`, it adds a MemoryHub tile to the Red Hat OpenShift AI application catalog:

1. Open the RHOAI dashboard (the URL printed in the install summary, or find it at `https://rhods-dashboard-redhat-ods-applications.apps.<your-cluster>/`)
2. Click **Applications** in the left sidebar, then **Explore**
3. Find the **MemoryHub** tile and click it
4. Click **Open application** to launch the admin dashboard

The dashboard has six panels: Memory Graph (visual node/edge view of memories and relationships), Status Overview (system health), Users & Agents (active sessions), Client Management (OAuth clients), Curation Rules (content filtering), and Contradiction Log (conflicting memories). If you ran `seed-sample-data.py` in step 3, the Memory Graph will show the seeded memories and their relationships.
