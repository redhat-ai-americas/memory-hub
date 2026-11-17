# MemoryHub Helm chart

This umbrella chart describes the current MemoryHub deployment in one Helm
release. Workloads retain the existing multi-namespace layout. The existing
`scripts/deploy-full.sh` and Kubernetes/OpenShift manifests remain supported.
The documented Helm path is a fresh MemoryHub installation: it does not adopt
existing workloads or data claims. For an OpenShift fresh install, use
`make helm-install`; it coordinates setup and applies this chart without
applying the Kustomize workload manifests. Direct `helm upgrade --install`
remains available when images, migrations, Secrets, ConfigMaps, and the
OpenShift OAuthClient are managed separately.

## One-command OpenShift install

The Make target provides a full-stack install experience like `make install`:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install
```

It creates the standard namespaces with a namespace-only chart pass, generates
the database, MinIO, auth, and UI Secrets, creates `memoryhub-users`, installs
the database, object store, and cache, runs core and auth database migrations,
builds MCP, auth, and UI images using the existing OpenShift build scripts, registers the
OpenShift OAuthClient, and enables the complete Helm release. It also stores
the first user's generated API key in `~/.config/memoryhub/credentials` under
the selected context. Re-running after an interrupted install reuses existing
Secrets and user configuration. After installation, use Helm's normal
`upgrade` workflow for configuration changes. The target expects the standard
namespace names and does not deploy the optional RHOAI dashboard tile.

To avoid running application image builds during installation, publish the
MCP, auth, and UI images first, set their full registry paths and tags in a
values file, then pass `--prebuilt-images`:

```bash
cp charts/memoryhub/values-openshift.prebuilt.example.yaml values-openshift.yaml
# Replace the three example image references with images available to the cluster.
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install \
  ARGS="--prebuilt-images --values values-openshift.yaml"
```

This skips only the MCP/auth/UI image builds. Namespace setup, credentials,
migrations, OAuthClient registration, and Helm installation still run. The
chart does not publish application images, and this repository currently has
no CI workflow that publishes them; a usable registry image must exist before
using this mode. For a private registry, create the referenced pull Secret in
every namespace where a workload pulls one of those images.

If a previous Kustomize installation left the chart's auth ClusterRole or
ClusterRoleBindings behind, the installer checks that each object's rules and
ServiceAccount subject match the chart before adding Helm ownership metadata.
It stops instead of adopting a mismatched or differently owned RBAC object.

To customize chart settings, create a values file and pass it to the target:

```bash
cp charts/memoryhub/values-openshift.example.yaml values-openshift.yaml
# Tune resource, storage, probe, model, or other supported settings.
MEMORYHUB_CONTEXT=mcp-rhoai make helm-install ARGS="--values values-openshift.yaml"
```

The one-command installer always uses the standard namespace names and
resolves the OpenShift Route hosts and OAuth URL from the cluster, overriding
those fields in an optional values file. It keeps the standard namespace,
ServiceAccount, OAuth client, and Secret names so they match the resources it
creates. In the default mode it builds the three application images and uses
the chart's standard OpenShift ImageStream names. In `--prebuilt-images` mode,
the three application image values are taken from your values file and checked
for registry-qualified paths. Other values can tune resources, storage,
probes, and model selection. Use direct Helm installation for custom
namespaces or externally managed Secrets.

The installer needs `oc`, Helm 3, Python 3, and OpenSSL locally, plus cluster
permissions to create namespaces, namespaced resources, SCC bindings, auth
ClusterRoleBindings, and the cluster-scoped OpenShift OAuthClient. The default
mode builds the three application images on OpenShift, so the installer also
needs permission to create and run the repository BuildConfigs. Prebuilt mode
does not need those build permissions. It waits for the
database and workloads to become ready. The optional RHOAI dashboard tile
remains on its existing integration path.

## Chart layout

```text
charts/memoryhub/
├── Chart.yaml
├── values.yaml
├── values.schema.json
└── templates/
    ├── _helpers.tpl
    ├── namespaces/
    ├── postgresql/
    ├── minio/
    ├── valkey/
    ├── mcp/
    ├── auth/
    ├── ui/
    ├── models/
    └── maintenance/
```

Most resource templates have one file per Kubernetes resource. Values and
helpers provide shared image references, labels, namespace names, and settings.

## Namespaces

Helm's `--create-namespace` creates only the release namespace. MemoryHub uses
that namespace for MCP, Valkey, and the retention job; the chart creates the
other six namespaces when they do not exist:

| Setting | Default | Workloads |
|---|---|---|
| `--namespace` | `memory-hub-mcp` | MCP, Valkey, retention job |
| `namespaces.database` | `memoryhub-db` | PostgreSQL |
| `namespaces.storage` | `memoryhub-storage` | MinIO |
| `namespaces.auth` | `memoryhub-auth` | Auth service |
| `namespaces.ui` | `memoryhub-ui` | UI |
| `namespaces.embeddingModel` | `embedding-model` | Embedding model |
| `namespaces.rerankerModel` | `reranker-model` | Reranker model |

This is the same seven-namespace layout used by `scripts/deploy-full.sh`. The
dashboard is in `memoryhub-ui`; older architecture text that grouped it under
`memory-hub-mcp` described an earlier deployment. `memoryhub-agents` is a
separate optional install and is not managed by this chart or
`scripts/deploy-full.sh`. The optional RHOAI proxy uses the platform-owned
`redhat-ods-applications` namespace and remains outside the chart. See the
corrected [deployment topology](../../docs/SYSTEMS.md#deployment-topology) and
[architecture](../../docs/ARCHITECTURE.md#deployment-topology).

The chart describes one MemoryHub installation per cluster. In particular,
the default auth `ClusterRole` and `ClusterRoleBinding` names are cluster-wide;
installing a second release with the default OpenShift RBAC settings would
collide with the first. Multi-install support would require release-specific
cluster-scoped RBAC names and is not part of this chart.

The chart builds internal Service URLs as
`<service>.<namespace>.svc.<clusterDomain>`. The default
`clusterDomain: cluster.local` matches the current deployment; override it if
the cluster uses a different DNS domain.

Namespace values must be distinct, including from the release namespace.
Existing empty namespaces are reused and are not adopted by Helm. Namespaces
created by this release remain in the release manifest on upgrades, while
pre-existing namespaces are omitted from it. Set
`namespaces.create=false` when another process creates the component
namespaces. With `namespaces.create=true`, the installer needs permission to
read Namespace resources because the chart uses Helm's `lookup` function to
avoid emitting already-existing namespaces, and permission to create missing
Namespace resources. Helm fails template rendering if the API denies a lookup.

## Prerequisites and current limits

Use Helm 3. The chart uses the v2 chart format and Kubernetes API discovery to
select OpenShift Routes and SCC bindings.

### Secret handling contract

The chart uses externally managed Kubernetes Secrets in each workload's own
namespace. Kubernetes does not let a pod read a Secret from another namespace.
The chart therefore takes configurable Secret **names** only; it does not take
passwords, keys, certificate material, or other credentials in `values.yaml`,
`--set`, or rendered Secret resources. Secret references in the table are
local to the namespace in the first column.

| Namespace | Secret and required keys | Provisioning expectation |
|---|---|---|
| `memoryhub-db` | `memoryhub-pg-credentials`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Create the database source Secret through the platform's secret workflow. The current `scripts/deploy-full.sh` generates it on first install and preserves it on later runs. |
| `memoryhub-storage` | `memoryhub-minio-credentials`: `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Provision in the storage namespace. The current deployment workflow creates it for MinIO. |
| `memory-hub-mcp` (Helm release namespace) | `memoryhub-db-credentials`: `MEMORYHUB_DB_PORT`, `MEMORYHUB_DB_NAME`, `MEMORYHUB_DB_USER`, `MEMORYHUB_DB_PASSWORD`; `memoryhub-minio-credentials`: `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`; `auth-internal-service-key`: `AUTH_INTERNAL_SERVICE_KEY` | Create the DB Secret by remapping the DB source credentials; copy MinIO credentials from `memoryhub-storage`; copy the internal auth key from `memoryhub-auth`. `MEMORYHUB_DB_HOST` is set by the chart to the database Service DNS name. |
| `memoryhub-auth` | `memoryhub-pg-credentials`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`; `auth-rsa-keys`: `AUTH_RSA_PRIVATE_KEY_PEM`, `AUTH_RSA_PUBLIC_KEY_PEM`; `auth-admin-key`: `AUTH_ADMIN_KEY`; `auth-internal-service-key`: `AUTH_INTERNAL_SERVICE_KEY`; `openshift-oauth-client-secret`: `AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET` | Copy DB credentials from `memoryhub-db`; securely generate and provision the RSA keys, admin key, internal key, and OAuth client secret. The OAuth client Secret value must match the separately created OpenShift OAuthClient. The current auth/full deployment scripts document these generation and copy steps. |
| `memoryhub-ui` | `memoryhub-db-credentials`: `MEMORYHUB_DB_PORT`, `MEMORYHUB_DB_NAME`, `MEMORYHUB_DB_USER`, `MEMORYHUB_DB_PASSWORD`; `memoryhub-ui-admin-key`: `MEMORYHUB_ADMIN_KEY`; `memoryhub-ui-proxy`: `session-secret` (32 bytes) | Create the DB Secret by remapping the DB source credentials; copy/remap the auth admin key from `memoryhub-auth`; generate the proxy session secret securely. `MEMORYHUB_DB_HOST` is set by the chart. On OpenShift, the Service CA fills `memoryhub-ui-tls` from the Service annotation; on Kubernetes, provision a TLS Secret named by `ui.secrets.tls` with `tls.crt` and `tls.key`. |

The `POSTGRES_USER` and `POSTGRES_DB` values in the database Secret must match
`postgresql.username` and `postgresql.database`; the auth service uses the chart
values while PostgreSQL initializes from the Secret. The copied MCP and UI
database Secrets must use matching `MEMORYHUB_DB_USER` and `MEMORYHUB_DB_NAME`
values as well.

`memoryhub-users` is a ConfigMap in the MCP release namespace, not a Secret. It
must also be provisioned before MCP starts. The current deployment scripts show
how these resources are generated and copied, but they also deploy the
non-Helm manifests. Do not run them alongside Helm as a secret-only step.
Instead, use the platform's approved secret manager or a controlled process to
create each target-namespace Secret before enabling workloads. Secret
distribution is an operator/platform responsibility; this chart does not add
an external-secret controller or copy credentials between namespaces.

Secret object names can be changed without changing their data: use
`postgresql.secretName` and `minio.secretName` for the database and storage
namespaces, and the `mcp.secrets.*`, `auth.secrets.*`, and `ui.secrets.*` values
for the corresponding workload namespaces. Each value still refers to a
Secret created in that workload's own namespace.

For additional sensitive environment variables, use a Secret reference in a
component's `extraEnv` value. Do not put the credential itself in `values.yaml`
or `--set`. For example, `mcp.extraEnv` can refer to a Secret already created
in the MCP release namespace:

```yaml
mcp:
  extraEnv:
    - name: EXTERNAL_TOKEN
      valueFrom:
        secretKeyRef:
          name: external-api-credentials
          key: token
```

Do not put credentials in Helm values or pass them with `--set`: Helm records
release values. If you customize namespace names, keep the target-namespace
Secrets in sync; the chart derives database, auth, MCP, MinIO, Valkey, and model
Service DNS URLs from the namespace values. The auth service also needs a valid
`auth.issuer`, the cluster's OAuth authorize URL, and its OpenShift OAuthClient
created separately. Images for MCP, auth, and UI must already be available in
the cluster registry or another accessible registry.
Configure the OAuthClient callback to match
`<auth.issuer>/oauth/openshift/callback`.

The chart includes PostgreSQL, MinIO, Valkey, MCP, auth, UI, both model
endpoints, the retention sweep, and an opt-in test-data cleanup job. The
cleanup job is disabled by default, matching `scripts/deploy-full.sh`; when
enabled, it soft-deletes rows matching the test prefixes and owner IDs in
`deploy/cleanup/cronjob.yaml`. The chart does not create the OpenShift
OAuthClient, install the optional RHOAI dashboard integration, or deploy
`memoryhub-agents`. The RHOAI deploy script creates a proxy Service and
Endpoints after reading the UI Service's allocated ClusterIP, then applies the
tile only when the RHOAI API is present; that runtime-generated integration
remains with the existing script. The agent manifests are not part of
`deploy-full.sh`. Auth and the OAuth proxy use OpenShift OAuth APIs, so those
components are OpenShift-specific even though the chart can render Ingress
resources for Kubernetes.

## Image builds and database migrations

Helm renders and installs Kubernetes resources. It does not run the
repository's local build scripts or Alembic migrations.

### Build or publish the application images

The default MCP, auth, and UI image names (`memory-hub-mcp:latest`,
`auth-server:latest`, and `memoryhub-ui:latest`) match the OpenShift
ImageStreams used by the existing deployment. Their pod templates retain
OpenShift's short-name resolution annotation. For a fresh OpenShift install,
the build scripts create the corresponding BuildConfig and ImageStream, then
build the image without changing the Deployment:

```bash
MEMORYHUB_CONTEXT=mcp-rhoai scripts/build-full.sh
```

Run this after the target namespaces exist and before enabling MCP, auth, or
the UI. The script builds only those three application images; it does not
build PostgreSQL, MinIO, Valkey, or the model-server images. It currently
targets the default MCP, auth, and UI namespace names. If you customize those
names, build and publish the images to a registry accessible from the cluster,
then configure the chart with the corresponding full repository and tag.

For Kubernetes clusters, or when promoting a release between OpenShift
clusters, publish the application images to an accessible registry and use
explicit image references. Prefer immutable tags or digests for production.
Registry pull Secrets can be configured once in chart values, but Kubernetes
requires a copy of each referenced Secret in every namespace where a chart
workload runs:

```yaml
imagePullSecrets:
  - name: memoryhub-registry
mcp:
  image:
    repository: quay.io/example/memory-hub-mcp
    tag: "1.2.3"
auth:
  image:
    repository: quay.io/example/memoryhub-auth
    tag: "1.2.3"
ui:
  image:
    repository: quay.io/example/memoryhub-ui
    tag: "1.2.3"
```

Create `memoryhub-registry` in the release namespace and each namespace running
the configured images. A Helm values entry only references the Secret; it does
not create or copy registry credentials. Model images use the `models.image`
CPU/GPU settings, while PostgreSQL, MinIO, Valkey, the UI OAuth proxy, and the
optional cleanup job have their own image values. The retention job follows
`mcp.image` by default; set fields under `maintenance.retention.image` to
override only the repository, tag/digest, or pull policy that needs to differ.

The one-command OpenShift installer can use pre-published images with
`--prebuilt-images`; it validates the rendered MCP, auth, and UI image paths
before making cluster changes. The default mode continues to build these
images with the existing OpenShift build scripts.

### Run database migrations before enabling services

The current MCP container does not contain the repository-root `alembic/`
directory or `alembic.ini`, so it cannot run the core database migrations.
The chart deliberately does not create a migration Job that would fail at
runtime. Instead, run both migration sets from a local repository checkout
after PostgreSQL is ready and before enabling MCP/auth/UI. The scripts
port-forward PostgreSQL and read credentials from the configured database
Secret. They require `oc` access to the cluster and locally installed Python
dependencies:

```bash
# In the repository root, install the core migration dependencies once.
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# Install the auth service's migration dependencies once.
make -C memoryhub-auth install

# Use the cluster context and database namespace for this Helm release.
MEMORYHUB_CONTEXT=mcp-rhoai scripts/run-migrations.sh memoryhub-db memoryhub-pg-credentials
MEMORYHUB_CONTEXT=mcp-rhoai scripts/run-auth-migrations.sh memoryhub-db memoryhub-pg-credentials
```

Run the core migration first, then the auth migration. If the chart uses a
custom database namespace or source Secret name, replace the two script
arguments accordingly. Both scripts accept local environment overrides for
database connection fields; never put passwords into chart values or command
line `--set` arguments.

## OpenShift installation

The defaults use OpenShift Routes when the cluster advertises the Route API.
PostgreSQL, MinIO, and Valkey each run under a dedicated ServiceAccount. The
chart grants the `anyuid` SCC only to these ServiceAccounts with namespaced
RoleBindings; it never grants SCC access to a namespace's default
ServiceAccount. These three existing images use fixed UIDs. The global switch
`openshift.sccBindings=false` disables all three chart-created bindings. To
manage them individually, set `openshift.scc.postgresql=false`,
`openshift.scc.minio=false`, or `openshift.scc.valkey=false`; in that case an
administrator must grant the matching ServiceAccount SCC access separately.
For example, this keeps PostgreSQL and Valkey bindings chart-managed while an
administrator manages MinIO's grant:

```yaml
openshift:
  scc:
    minio: false
```

The auth ServiceAccount has two cluster-level grants: a ClusterRole and
ClusterRoleBinding that allow it to read Namespace objects, and (when the
OpenShift Route API is available) a ClusterRoleBinding to
`system:auth-delegator`. These grants are configurable through
`auth.rbac.enabled`, `auth.rbac.namespaceReader`, and
`auth.rbac.authDelegator`. Disable an individual grant or all chart-created
auth RBAC when an administrator pre-provisions the needed grant for the auth
ServiceAccount. The auth component will not have the corresponding OpenShift
functionality if a required grant is missing.

For example, disable all auth RBAC objects when the grants are managed outside
Helm:

```yaml
auth:
  rbac:
    enabled: false
```

### Installer permissions

The identity running Helm needs permission to manage the namespaced resources
in every target namespace. If `namespaces.create=true`, it needs permission to
read Namespace resources for the chart's `lookup` checks and to create missing
component Namespace resources. The SCC bindings require permission
to manage RoleBindings in the PostgreSQL, MinIO, and Valkey namespaces and to
bind the OpenShift `anyuid` SCC ClusterRole. The auth RBAC resources require
permission to manage the chart's ClusterRole and ClusterRoleBindings, including
permission to bind `system:auth-delegator` and the chart-created namespace
reader role. Because Kubernetes prevents privilege escalation through RBAC,
creating the namespace-reader ClusterRole also requires the installer to have
the `get namespaces` permission itself or delegated `escalate` permission on
ClusterRoles.

These permissions can be delegated to the Helm installer without granting
cluster-admin. If an administrator chooses to create the SCC bindings or auth
RBAC separately, disable the corresponding chart values above and ensure those
grants exist before starting the workloads. The chart does not grant extra
permissions to workload ServiceAccounts beyond the auth grants and the three
SCC bindings described here.

The RHOAI dashboard integration remains optional and outside this chart. The
existing deployment script can skip it with `--skip-tile` and checks that the
RHOAI API is available before applying it. Core MemoryHub installation does
not require `redhat-ods-applications` access or RHOAI resources.

PVCs use the current deployment's storage requests. PostgreSQL and MinIO PVCs
and chart-created namespaces are retained by default; Valkey and model-cache
PVCs are removed on uninstall. See [Default retention](#default-retention) for
data reuse, cleanup, and the explicit deletion workflow.

For direct chart management, use this command after completing the Secret,
image, migration, OAuthClient, and URL setup described above:

```bash
helm upgrade --install memoryhub ./charts/memoryhub \
  --kube-context mcp-rhoai \
  -n memory-hub-mcp --create-namespace \
  -f values-openshift.yaml
```

The Helm release owns MCP, Valkey, PostgreSQL, MinIO, auth, UI, the two model
deployments, and the retention CronJob across those namespaces. `--create-namespace`
creates only `memory-hub-mcp`; the chart templates create the other six. Keep
RHOAI and `memoryhub-agents` on their separate installation paths.

### Fresh-install boundary

The supported Helm path starts with no existing MemoryHub workloads or data
claims that need to be adopted. With direct Helm usage, required Secrets and
the `memoryhub-users` ConfigMap must be provisioned separately. The
chart can create the namespaces or reuse empty namespaces, but does not adopt
resources created by `scripts/deploy-full.sh` or `kubectl apply -k`. Helm will
reject same-named resources that lack this release's ownership metadata. Switching a running
Kustomize installation to Helm is outside this fresh-install workflow.

## Configuration examples

Change a namespace, image, resource requests, PVC size, a probe setting, and
the model variant:

```bash
helm upgrade --install memoryhub ./charts/memoryhub \
  --kube-context mcp-rhoai \
  -n memory-hub-mcp --create-namespace \
  --set namespaces.storage=memoryhub-object-store \
  --set minio.image.repository=registry.example.com/minio \
  --set minio.image.tag=RELEASE.2026-09-22T19-25-18Z \
  --set minio.image.digest= \
  --set postgresql.storage=20Gi \
  --set mcp.resources.requests.memory=512Mi \
  --set mcp.probes.readiness.initialDelaySeconds=10 \
  --set models.variant=gpu
```

The default model variant is `cpu`, matching `scripts/deploy-full.sh`. Set
`models.variant=gpu` to select the existing Granite GPU model manifests; GPU
nodes and the NVIDIA device plugin must be available. Set image repositories,
tags, pull policies, replica counts, resources, storage, Route hosts, or
environment variables through `values.yaml` or Helm `--set` overrides.

Probe objects are configurable under each component's `probes` value.
PostgreSQL, MinIO, and Valkey expose `replicas: 1` but reject other replica
counts because their current single-volume standalone configurations do not
support scaling. Model replicas can be increased, but their cache PVCs default
to `ReadWriteOnce`; select a storage class and `storageAccessMode: ReadWriteMany`
that support shared read/write mounts before running multiple model replicas.

The UI deployment derives `MEMORYHUB_EMBEDDING_URL` from the selected model and
namespace, as the UI deploy script does. Override it with `ui.embeddingUrl` or
set `models.enabled=false` to omit the variable when models are not installed.
The MCP server derives its JWKS endpoint from `auth.issuer`; override it with
`mcp.authJwksUri` if the endpoint is hosted elsewhere.

The CPU and GPU model manifests use the same PVC names. Before changing
`models.variant`, first run `helm upgrade` with `models.enabled=false` and wait
for the model pods to stop; then upgrade again with `models.enabled=true` and
the new variant. This releases the ReadWriteOnce claims before the other model
deployment starts.

On Kubernetes, set `ingress.enabled=true` and enable the per-component
`mcp.ingress.enabled`, `auth.ingress.enabled`, `ui.ingress.enabled`, or model
Ingress values as needed. Provide an Ingress class and host; model endpoints
use separate hosts configured under `models.embedding.ingress.host` and
`models.reranker.ingress.host`. The UI OAuth proxy and auth service still
depend on OpenShift OAuth and are not portable Kubernetes replacements.

## Upgrade and uninstall

Apply a chart or values change with:

```bash
helm upgrade memoryhub ./charts/memoryhub --kube-context mcp-rhoai \
  -n memory-hub-mcp -f values-openshift.yaml
```

Uninstall workloads with the provided script (recommended — it also removes
the OpenShift OAuthClient and optional RHOAI tile that Helm does not manage):

```bash
make helm-uninstall
```

By default this retains all data PVCs and namespaces. To also delete all
MemoryHub namespaces and their contents (including PostgreSQL and MinIO data):

```bash
make helm-uninstall ARGS="--delete-namespaces --yes"
```

Or, to uninstall without the script:

```bash
helm uninstall memoryhub --kube-context mcp-rhoai -n memory-hub-mcp
```

### Default retention

PostgreSQL and MinIO PVCs have `helm.sh/resource-policy: keep` by default.
Their PVCs and any chart-created component namespaces remain after
`helm uninstall`; the release namespace created with `--create-namespace` also
remains. This protects database and object data and avoids deleting namespace
contents managed outside Helm. Kept PVCs and namespaces are orphaned: Helm no
longer upgrades or removes them. External Secrets and the `memoryhub-users`
ConfigMap in those namespaces also remain. Namespaces that existed before the
chart install are never adopted or deleted by this chart.

Valkey and model-cache PVCs are disposable and are removed by Helm during
uninstall. PostgreSQL and MinIO are the chart's durable data stores. If
upgrading a previous Helm chart release, upgrade to this chart version before
relying on the new cache-PVC or data-deletion behavior; uninstalling without
that upgrade still uses the previous release manifest.

### Optional: reuse retained PostgreSQL or MinIO data

This is not needed for a fresh install. If you intentionally reinstall after a
Helm uninstall that retained data, configure the existing claim names. This
prevents Helm from trying to create PVC objects that were kept by the previous
release; the chart will mount the claims but will not manage or resize them.
Keep the same target namespaces unless you have moved the storage yourself.

```yaml
postgresql:
  existingClaim: memoryhub-pg-data
minio:
  existingClaim: memoryhub-minio-data
```

Pass that file to `helm upgrade --install` along with the normal non-secret
configuration. Confirm the retained claims and the target namespaces before
starting workloads. Helm's `keep` annotation leaves resources unmanaged after
uninstall, as described in the [Helm resource-retention guidance](https://helm.sh/docs/howto/charts_tips_and_tricks/).

### Delete PostgreSQL or MinIO data

To delete one store, set its `retainPvcOnUninstall` value to `false` with
`helm upgrade` before uninstalling. To delete both PVCs:

```bash
helm upgrade memoryhub ./charts/memoryhub --kube-context mcp-rhoai \
  -n memory-hub-mcp \
  --set postgresql.retainPvcOnUninstall=false \
  --set minio.retainPvcOnUninstall=false
helm uninstall memoryhub --kube-context mcp-rhoai -n memory-hub-mcp
```

The upgrade removes the `keep` annotation from those PVCs; the later uninstall
deletes the claims. The chart still retains the component namespaces, and the
release namespace remains, so externally managed Secrets or other resources
there may need separate cleanup. If you intend to remove a retained namespace,
first verify it contains no resources used by another installation. Deleting a
namespace removes every object inside it, including external Secrets and any
other workloads. For namespaces created only for this release, an administrator
can remove the component namespaces and release namespace explicitly after
reviewing their contents. Replace the context with the one for your cluster:

```bash
oc delete namespace memoryhub-db memoryhub-storage memoryhub-auth memoryhub-ui \
  embedding-model reranker-model memory-hub-mcp --context mcp-rhoai
```

If the release is already uninstalled and you now want to delete a retained
PVC, delete its claim directly instead of trying to change the old release's
values. Replace namespace or claim names if you customized them:

```bash
oc delete pvc memoryhub-pg-data --context mcp-rhoai -n memoryhub-db
oc delete pvc memoryhub-minio-data --context mcp-rhoai -n memoryhub-storage
```

Deleting a PVC does not always erase the underlying storage. Check the
PersistentVolume's reclaim policy and your storage provider's backup/snapshot
retention: `Delete` removes the backing asset only when the volume plugin
supports it, while `Retain` leaves the PV and data for manual cleanup. See the
[Kubernetes PersistentVolume reclaim-policy documentation](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).

## Validation status

Local validation completed for this chart change:

- `bash scripts/check-helm-chart.sh` runs `helm lint --strict`, renders the
  default Kubernetes and OpenShift configurations for both CPU and GPU model
  selections, then compares rendered resources and settings with the current
  Kustomize and OpenShift manifests. The comparison covers workloads, Services,
  PVCs, ConfigMaps, Routes, and RBAC.
- `kubectl kustomize` built all seven current storage and model deployment
  directories, including both CPU and GPU model variants.
- `helm template` with registry pull Secrets, a published MCP image override,
  GPU model selection, and the optional cleanup job enabled
- OpenShift-specific rendering with Route API and SCC API discovery, including
  five Routes and the three dedicated-ServiceAccount SCC RoleBindings
- YAML parsing of both rendered outputs, including confirmation that every
  rendered PodSpec receives the pull Secret and the retention job follows the
  MCP image override
- JSON schema parsing, shell syntax checks for both migration helpers, and
  `git diff --check`

GitHub Actions runs the same chart lint, render, and alignment script when the
chart or its deployment sources change. Local Helm was v4.2.3; CI pins Helm
3.18.4 to exercise the supported Helm 3 runtime.

No live cluster install was performed. A fresh install still needs the
namespace-local Secret provisioning, application image builds or publishing,
local database migrations, and OpenShift OAuthClient setup described above.
