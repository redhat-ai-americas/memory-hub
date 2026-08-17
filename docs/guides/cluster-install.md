# Cluster Install Guide

MemoryHub installs to any OpenShift cluster with Red Hat OpenShift AI (RHOAI). The full stack is seven services across six namespaces, all deployed by a single `make install`. For the personal edition (no infrastructure needed), see the [root README](../../README.md#get-started).

## Prerequisites

- `oc` logged in with cluster-admin on a cluster with RHOAI installed
- `podman` on your PATH (checked but not required for server-side builds)
- A default StorageClass (most clusters have one)
- Python 3.11+ on your PATH (the deploy script creates `.venv` automatically)

Run `make check-prereqs` to verify all of these non-destructively. GPUs are not required; the default install uses CPU-based embedding and reranker models.

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the "new contributor no-deploy" rule: if you're onboarding to this codebase, work against a local SQLite or Podman PostgreSQL instead of deploying to a cluster.

## Quick start

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
oc login <cluster-api-url>      # cluster-admin required
make install                    # full stack deploy (~10 min)
```

That's it. The deploy script auto-creates the Python virtualenv (for Alembic migrations), generates API keys for the users ConfigMap if it doesn't exist, writes the first key to `~/.config/memoryhub/api-key` for CLI/SDK use, and runs a write/search/read smoke test at the end.

To bring your own API keys instead, copy the template before running install:

```bash
cp memory-hub-mcp/deploy/users-configmap.example.yaml \
   memory-hub-mcp/deploy/users-configmap.yaml
# Replace REPLACE-ME placeholders with: openssl rand -hex 16
make install
```

## What gets deployed

| Service | Namespace | What |
|---------|-----------|------|
| PostgreSQL + pgvector | `memoryhub-db` | Database (memories, threads, graph, auth tables) |
| MinIO | `memory-hub-mcp` | S3-compatible object storage for oversized content |
| Valkey | `memory-hub-mcp` | Session focus state and compilation epoch cache |
| Embedding model | `embedding-model` | all-MiniLM-L6-v2 via HuggingFace TEI (CPU, 384-dim) |
| Reranker model | `reranker-model` | ms-marco-MiniLM-L12-v2 cross-encoder via TEI (CPU) |
| Auth service | `memoryhub-auth` | OAuth 2.1 authorization server (JWT, PKCE, API keys) |
| MCP server | `memory-hub-mcp` | FastMCP 3 server exposing memory operations |
| Dashboard UI | `memoryhub-ui` | React + PatternFly 6 frontend with FastAPI BFF |

All service URLs (auth JWKS, embedding, reranker) are resolved dynamically from cluster state at deploy time. No hardcoded cluster domains.

Expect 8-15 minutes on a first install. The MCP server, auth service, and UI each go through an OpenShift BuildConfig, and the embedding/reranker models need to download weights on first run.

## Targeting a specific cluster

If you have multiple clusters configured in your kubeconfig, set `MEMORYHUB_CONTEXT` to target a specific one without switching your active context:

```bash
MEMORYHUB_CONTEXT=my-cluster make install
MEMORYHUB_CONTEXT=my-cluster make uninstall
```

This passes `--context` on every `oc` command and never mutates your kubeconfig.

## Deploy options

```bash
make install                                       # full stack (CPU models, default)
make install ARGS="--gpu-models"                   # use GPU embedding/reranker models instead
make install ARGS="--skip-models"                  # skip embedding/reranker (mock search)
make install ARGS="--skip-ui --skip-tile"          # headless (no dashboard)
```

## Uninstall

```bash
make uninstall                                     # prompts for confirmation
make uninstall ARGS="--yes"                        # non-interactive (CI)
make uninstall ARGS="--skip-data"                   # preserve database + storage across reinstall
make uninstall ARGS="--skip-models"                # keep embedding/reranker models running
```

## Troubleshooting

**Image digest mismatch.** If the MCP deploy fails with `running digest does not match imagestream :latest`, the OpenShift deployment cached a stale image. Re-run the install and it will pick up the correct digest:

```bash
make install ARGS="--skip-data --skip-migrations --skip-auth"
```

**Reranker timeout with `--gpu-models`.** On single-GPU clusters, the embedding model takes the GPU. The reranker runs on CPU (with a GPU node toleration for scheduling). If the reranker times out, check for PVC contention -- the CPU model variant may still be running and holding the shared PVC. The deploy script scales down CPU models automatically, but leftover deployments from a prior install can interfere. Delete them manually: `oc delete deployment <cpu-model-name> -n reranker-model`.

## Partial deploys

`make deploy-db`, `make deploy-mcp`, `make deploy-auth`, `make deploy-ui`, `make deploy-tile` each deploy a single service and skip the others. `make help` lists everything.

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
oc get configmap memoryhub-users -n memory-hub-mcp \
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

**5. Open the dashboard from RHOAI.** The install adds a MemoryHub tile to the Red Hat OpenShift AI application catalog:

1. Open the RHOAI dashboard (the URL printed in the install summary, or find it at `https://rhods-dashboard-redhat-ods-applications.apps.<your-cluster>/`)
2. Click **Applications** in the left sidebar, then **Explore**
3. Find the **MemoryHub** tile and click it
4. Click **Open application** to launch the admin dashboard

The dashboard has six panels: Memory Graph (visual node/edge view of memories and relationships), Status Overview (system health), Users & Agents (active sessions), Client Management (OAuth clients), Curation Rules (content filtering), and Contradiction Log (conflicting memories). If you ran `seed-sample-data.py` in step 3, the Memory Graph will show the seeded memories and their relationships.
