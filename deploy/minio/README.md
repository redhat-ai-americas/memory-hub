# MemoryHub MinIO Deployment

Single-instance MinIO for MemoryHub S3-compatible object storage. Stores
memory content that exceeds the 1 KB inline threshold. Deployed into its
own `memoryhub-storage` namespace so that object data survives MCP server
reinstalls (see #395).

## What This Deploys

- **Namespace**: `memoryhub-storage` (dedicated storage namespace)
- **Deployment**: Single MinIO pod (`quay.io/minio/minio:latest`)
- **PVC**: 10Gi persistent volume for object data
- **Service**: ClusterIP service on port 9000 (S3 API)
- **Secret**: Root credentials for dev use (`memoryhub` / `memoryhub-dev-password`)

## Prerequisites

The upstream MinIO image runs as uid 1000. OpenShift's default `restricted`
SCC assigns a random UID, which breaks the image. Grant `anyuid` to the
dedicated `memoryhub-minio` ServiceAccount only:

```bash
oc adm policy add-scc-to-user anyuid -z memoryhub-minio -n memoryhub-storage
```

You need cluster-admin (or equivalent) privileges to run this command.

## Deploy

```bash
oc apply -k deploy/minio/
```

The kustomization sets `namespace: memoryhub-storage` and includes
`namespace.yaml`, so no `-n` flag is needed.

Then wait for the pod:

```bash
oc wait --for=condition=ready pod -l app.kubernetes.io/name=memoryhub-minio \
  -n memoryhub-storage --timeout=120s
```

## Verify

```bash
oc get pods -n memoryhub-storage -l app.kubernetes.io/name=memoryhub-minio
```

## Connect From Within the Cluster

Pods in the `memoryhub-storage` namespace can use the short service name:

```
endpoint: memoryhub-minio:9000
```

Cross-namespace consumers (MCP server, retention cronjob) use the FQDN:

```
memoryhub-minio.memoryhub-storage.svc.cluster.local:9000
```

Cross-namespace consumers also need a copy of the `memoryhub-minio-credentials`
secret in their namespace. `deploy-full.sh` handles this automatically via
`copy_secret`.

## Bucket Creation

The `S3StorageAdapter` calls `ensure_bucket()` on first use, so no manual
bucket creation is needed. The default bucket name is `memoryhub`.

## MCP Server Environment Variables

Configure the MCP server deployment with these env vars to connect to MinIO:

| Variable | Value |
|----------|-------|
| `MEMORYHUB_S3_ENDPOINT` | `memoryhub-minio.memoryhub-storage.svc.cluster.local:9000` |
| `MEMORYHUB_S3_ACCESS_KEY` | `memoryhub` |
| `MEMORYHUB_S3_SECRET_KEY` | `memoryhub-dev-password` |
| `MEMORYHUB_S3_BUCKET` | `memoryhub` |
| `MEMORYHUB_S3_SECURE` | `false` |

## Tear Down

```bash
oc delete -k deploy/minio/
```

The PVC is deleted along with the kustomization. To preserve MinIO data
across reinstalls, use `uninstall-full.sh --skip-data` which skips deletion
of the `memoryhub-storage` namespace entirely (same pattern as `--skip-db`
for PostgreSQL).
