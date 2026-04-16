# MemoryHub MinIO Deployment

Single-instance MinIO for MemoryHub S3-compatible object storage. Stores
memory content that exceeds the 1 KB inline threshold. Deployed into the
existing `memory-hub-mcp` namespace so the MCP server can reach it via
plain in-namespace service discovery.

## What This Deploys

- **Namespace**: `memory-hub-mcp` (shared with the MCP server)
- **Deployment**: Single MinIO pod (`quay.io/minio/minio:latest`)
- **PVC**: 10Gi persistent volume for object data
- **Service**: ClusterIP service on port 9000 (S3 API)
- **Secret**: Root credentials for dev use (`memoryhub` / `memoryhub-dev-password`)

## Prerequisites

The upstream MinIO image runs as uid 1000. OpenShift's default `restricted`
SCC assigns a random UID, which breaks the image. Grant `anyuid` to the
dedicated `memoryhub-minio` ServiceAccount only:

```bash
oc adm policy add-scc-to-user anyuid -z memoryhub-minio -n memory-hub-mcp
```

You need cluster-admin (or equivalent) privileges to run this command.

## Deploy

```bash
oc apply -k deploy/minio/ -n memory-hub-mcp
```

Then wait for the pod:

```bash
oc wait --for=condition=ready pod -l app.kubernetes.io/name=memoryhub-minio \
  -n memory-hub-mcp --timeout=120s
```

## Verify

```bash
oc get pods -n memory-hub-mcp -l app.kubernetes.io/name=memoryhub-minio
```

## Connect From Within the Cluster

Other pods in `memory-hub-mcp` can connect using:

```
endpoint: memoryhub-minio:9000
```

Cross-namespace connection string:

```
memoryhub-minio.memory-hub-mcp.svc.cluster.local:9000
```

## Bucket Creation

The `S3StorageAdapter` calls `ensure_bucket()` on first use, so no manual
bucket creation is needed. The default bucket name is `memoryhub`.

## MCP Server Environment Variables

Configure the MCP server deployment with these env vars to connect to MinIO:

| Variable | Value |
|----------|-------|
| `MEMORYHUB_S3_ENDPOINT` | `memoryhub-minio:9000` |
| `MEMORYHUB_S3_ACCESS_KEY` | `memoryhub` |
| `MEMORYHUB_S3_SECRET_KEY` | `memoryhub-dev-password` |
| `MEMORYHUB_S3_BUCKET` | `memoryhub` |
| `MEMORYHUB_S3_SECURE` | `false` |

## Tear Down

```bash
oc delete -k deploy/minio/ -n memory-hub-mcp
```

The PVC is deleted along with the kustomization, so data is not preserved
across a tear-down. For hardening this, either switch to a `Retain` reclaim
policy on the storage class or externalize the PVC from the kustomization.
