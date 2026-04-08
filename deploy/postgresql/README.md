# MemoryHub PostgreSQL + pgvector Deployment

Single-instance PostgreSQL 16 with pgvector 0.8.2 for MemoryHub development and demo use.

## What This Deploys

- **Namespace**: `memoryhub-db`
- **StatefulSet**: Single PostgreSQL 16 pod with pgvector extension
- **PVC**: 10Gi persistent volume for data
- **Service**: ClusterIP service on port 5432
- **Extensions**: `vector` (pgvector) and `uuid-ossp`, auto-created on first boot

## Image Note

This deployment uses `pgvector/pgvector:0.8.2-pg16`, which is Debian-based
(not Red Hat UBI). This is accepted for demo purposes. A UBI-based build is a
future task for production readiness.

## Prerequisites

The official postgres image runs as uid 999. OpenShift's default `restricted`
SCC assigns a random UID, which breaks the image. Grant the `anyuid` SCC to the
default service account in the namespace:

```bash
oc adm policy add-scc-to-user anyuid -z default -n memoryhub-db
```

You need cluster-admin (or equivalent) privileges to run this command.

## Deploy

```bash
oc apply -k deploy/postgresql/
```

Then grant the SCC (if not already done) and wait for the pod:

```bash
oc adm policy add-scc-to-user anyuid -z default -n memoryhub-db

# Restart the pod if it was already created before the SCC grant
oc delete pod -l app.kubernetes.io/name=memoryhub-pg -n memoryhub-db

oc wait --for=condition=ready pod -l app.kubernetes.io/name=memoryhub-pg \
  -n memoryhub-db --timeout=120s
```

## Connect From Within the Cluster

Other pods in the cluster can connect using:

```
host:     memoryhub-pg.memoryhub-db.svc.cluster.local
port:     5432
user:     memoryhub
password: <the POSTGRES_PASSWORD you set in deploy/postgresql/secret.yaml>
database: memoryhub
```

Connection string:

```
postgresql://memoryhub:<your-password>@memoryhub-pg.memoryhub-db.svc.cluster.local:5432/memoryhub
```

## Verify pgvector Works

Quick check via oc exec:

```bash
oc exec -n memoryhub-db statefulset/memoryhub-pg -- \
  psql -U memoryhub -d memoryhub -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

For a full validation (creates a test table, inserts vectors, runs a similarity
search, then cleans up):

```bash
./scripts/validate-postgresql.sh
```

## Credentials Warning

The credentials in `secret.yaml` are **demo-only defaults**. For any
environment beyond local development, replace them with properly generated
secrets managed through OpenShift Secrets or HashiCorp Vault.

## Tear Down

```bash
oc delete -k deploy/postgresql/
```

Note: deleting the namespace removes all resources, but the PV reclaim policy
determines whether data is retained. Check your storage class configuration.
