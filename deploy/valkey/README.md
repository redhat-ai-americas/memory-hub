# MemoryHub Valkey Deployment

Single-instance Valkey 8.x for MemoryHub session state and append-only focus
history. Deployed into the existing `memory-hub-mcp` namespace so the MCP
server can reach it via plain in-namespace service discovery.

## What This Deploys

- **Namespace**: `memory-hub-mcp` (shared with the MCP server)
- **Deployment**: Single Valkey 8.0 pod (Alpine-based)
- **PVC**: 5Gi persistent volume for append-only file persistence
- **Service**: ClusterIP service on port 6379
- **Config**: `--appendonly yes`, `--save 60 1000`, 512MiB maxmemory,
  `noeviction` policy (we use TTLs, not LRU eviction)

## Image Note

This deployment uses `docker.io/valkey/valkey:8.0-alpine`, which is Alpine-based
(not Red Hat UBI). This is accepted for demo purposes, matching the PostgreSQL
deploy's precedent. A UBI-based Valkey build is a future task for production
readiness.

## Prerequisites

The upstream Valkey image runs as uid 999. OpenShift's default `restricted`
SCC assigns a random UID, which breaks the image. To avoid granting `anyuid`
to the namespace's default ServiceAccount (which would broaden the grant to
every pod in this namespace, including the MCP server), this deploy creates
a dedicated `memoryhub-valkey` ServiceAccount and grants `anyuid` only to
that SA:

```bash
oc adm policy add-scc-to-user anyuid -z memoryhub-valkey -n memory-hub-mcp
```

You need cluster-admin (or equivalent) privileges to run this command. The
MCP server pod continues to run under `restricted-v2` with its own
OpenShift-assigned UID, unaffected by this grant.

## Deploy

```bash
oc apply -k deploy/valkey/
```

Then wait for the pod:

```bash
oc wait --for=condition=ready pod -l app.kubernetes.io/name=memoryhub-valkey \
  -n memory-hub-mcp --timeout=120s
```

## Connect From Within the Cluster

Other pods in `memory-hub-mcp` can connect using:

```
host:     memoryhub-valkey
port:     6379
```

Cross-namespace connection string:

```
redis://memoryhub-valkey.memory-hub-mcp.svc.cluster.local:6379/0
```

The MCP server reads this via the `MEMORYHUB_VALKEY_URL` env var.

## Verify

Quick ping check:

```bash
oc exec -n memory-hub-mcp deployment/memoryhub-valkey -- valkey-cli ping
```

Expected output: `PONG`.

## Key Schema

Two key prefixes are used by MemoryHub:

1. `memoryhub:sessions:<session_id>` — hash with active-session state:
   `focus`, `focus_vector` (base64-encoded float32 array), `user_id`,
   `project`, `created_at`, `expires_at`. Carries a TTL matching the JWT
   lifetime. Used by `#61` (focus history) and `#62` (Pattern E broadcast
   filter).
2. `memoryhub:session_focus_history:<project>:<yyyy-mm-dd>` — list with
   append-only focus declarations per project per day. Each entry is a JSON
   record. Used by `get_focus_history` aggregation.

## Tear Down

```bash
oc delete -k deploy/valkey/
```

The PVC is deleted along with the kustomization, so data is not preserved
across a tear-down. For hardening this, either switch to a `Retain` reclaim
policy on the storage class or externalize the PVC from the kustomization.
