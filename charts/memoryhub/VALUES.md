# Helm chart values reference

This reference lists every default in [`values.yaml`](values.yaml), plus optional image digest overrides accepted by the chart. Set values with a YAML file or Helm `--set` flags. `""` means unset; `{}` and `[]` are empty objects and lists. The chart references Secret names only; create the actual Secrets separately in the listed namespaces.

### `namespaces`

| Value | Default | Description |
|---|---|---|
| `namespaces.create` | `true` | Create chart-managed component namespaces that do not already exist. |
| `namespaces.database` | `"memoryhub-db"` | Namespace for PostgreSQL and its Secret and PVC. |
| `namespaces.storage` | `"memoryhub-storage"` | Namespace for MinIO and its Secret and PVC. |
| `namespaces.auth` | `"memoryhub-auth"` | Namespace for the auth service and its Secrets. |
| `namespaces.ui` | `"memoryhub-ui"` | Namespace for the dashboard and its Secrets. |
| `namespaces.embeddingModel` | `"embedding-model"` | Namespace for the embedding model workload and cache. |
| `namespaces.rerankerModel` | `"reranker-model"` | Namespace for the reranker workload and cache. |

### `clusterDomain`

| Value | Default | Description |
|---|---|---|
| `clusterDomain` | `"cluster.local"` | DNS suffix used to build in-cluster service URLs. |

### `imagePullSecrets`

| Value | Default | Description |
|---|---|---|
| `imagePullSecrets` | `[]` | Namespace-local image pull Secret references added to chart workloads. |
| `imagePullSecrets[].name` | `required per entry` | Name of a pre-created image pull Secret; create it in each workload namespace. |

### `openshift`

| Value | Default | Description |
|---|---|---|
| `openshift.enabled` | `true` | Enable OpenShift-specific resources and behavior. |
| `openshift.sccBindings` | `true` | Create chart-managed anyuid SCC RoleBindings where required. |
| `openshift.scc.postgresql` | `true` | Create the anyuid SCC binding for PostgreSQL. |
| `openshift.scc.minio` | `true` | Create the anyuid SCC binding for MinIO. |
| `openshift.scc.valkey` | `true` | Create the anyuid SCC binding for Valkey. |
| `openshift.routes` | `true` | Create OpenShift Routes for enabled services. |

### `ingress`

| Value | Default | Description |
|---|---|---|
| `ingress.enabled` | `false` | Enable Kubernetes Ingress resources in addition to any OpenShift Routes. |
| `ingress.className` | `""` | Ingress controller class applied to generated Ingress resources. |
| `ingress.host` | `""` | Fallback host used when a component ingress host is empty. |
| `ingress.tls` | `[]` | TLS entries added to generated Ingress resources; empty creates no TLS entries. |
| `ingress.annotations` | `{}` | Annotations applied to generated Kubernetes Ingress resources. |

### `postgresql`

| Value | Default | Description |
|---|---|---|
| `postgresql.enabled` | `true` | Deploy the PostgreSQL database resources. |
| `postgresql.image.repository` | `"pgvector/pgvector"` | Container image repository for the PostgreSQL workload. |
| `postgresql.image.tag` | `"0.8.2-pg16"` | Image tag for the PostgreSQL workload when no digest is set. |
| `postgresql.image.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy for the PostgreSQL workload. |
| `postgresql.replicas` | `1` | Desired number of PostgreSQL pods. |
| `postgresql.serviceAccountName` | `"memoryhub-postgresql"` | ServiceAccount assigned to the PostgreSQL workload. |
| `postgresql.secretName` | `"memoryhub-pg-credentials"` | Name of the pre-created database Secret in the database namespace. |
| `postgresql.retainPvcOnUninstall` | `true` | Keep the PostgreSQL PVC when the Helm release is uninstalled. |
| `postgresql.existingClaim` | `""` | Existing PostgreSQL PVC to mount; empty lets the chart create one. |
| `postgresql.database` | `"memoryhub"` | Database name initialized for MemoryHub. |
| `postgresql.username` | `"memoryhub"` | Database user used by PostgreSQL health checks and application configuration. |
| `postgresql.storage` | `"10Gi"` | Requested capacity for the PostgreSQL data PVC. |
| `postgresql.storageClassName` | `""` | StorageClass for the PostgreSQL PVC; empty uses the cluster default. |
| `postgresql.initSql` | `multiline SQL block below` | SQL run during database initialization to enable and check required extensions. |
| `postgresql.resources.requests.cpu` | `"250m"` | Cpu request used for scheduling the PostgreSQL workload. |
| `postgresql.resources.requests.memory` | `"256Mi"` | Memory request used for scheduling the PostgreSQL workload. |
| `postgresql.resources.limits.cpu` | `"1"` | Maximum cpu allowed for the PostgreSQL workload. |
| `postgresql.resources.limits.memory` | `"1Gi"` | Maximum memory allowed for the PostgreSQL workload. |
| `postgresql.probes.liveness.exec.command` | `["pg_isready","-U","{{ .Values.postgresql.username }}","-d","{{ .Values.postgresql.database }}"]` | Command run by the liveness probe for the PostgreSQL workload. |
| `postgresql.probes.liveness.initialDelaySeconds` | `30` | Delay before the liveness probe starts for the PostgreSQL workload. |
| `postgresql.probes.liveness.periodSeconds` | `10` | Interval between liveness probe checks for the PostgreSQL workload. |
| `postgresql.probes.liveness.timeoutSeconds` | `5` | Time limit for each liveness probe check for the PostgreSQL workload. |
| `postgresql.probes.liveness.failureThreshold` | `6` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `postgresql.probes.readiness.exec.command` | `["pg_isready","-U","{{ .Values.postgresql.username }}","-d","{{ .Values.postgresql.database }}"]` | Command run by the readiness probe for the PostgreSQL workload. |
| `postgresql.probes.readiness.initialDelaySeconds` | `5` | Delay before the readiness probe starts for the PostgreSQL workload. |
| `postgresql.probes.readiness.periodSeconds` | `5` | Interval between readiness probe checks for the PostgreSQL workload. |
| `postgresql.probes.readiness.timeoutSeconds` | `3` | Time limit for each readiness probe check for the PostgreSQL workload. |
| `postgresql.probes.readiness.failureThreshold` | `3` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `postgresql.extraEnv` | `[]` | Additional environment-variable entries for the PostgreSQL container. |
| `postgresql.image.digest` | `unset` | Optional immutable image digest for PostgreSQL; when set it overrides the tag. |

### `minio`

| Value | Default | Description |
|---|---|---|
| `minio.enabled` | `true` | Deploy the MinIO object-storage resources. |
| `minio.replicas` | `1` | Desired number of MinIO pods. |
| `minio.image.repository` | `"cgr.dev/chainguard/minio"` | Container image repository for the MinIO workload. |
| `minio.image.tag` | `""` | Image tag for the MinIO workload when no digest is set. |
| `minio.image.digest` | `"sha256:dc455cdd4db6e390b1b26514f15ff37681a777bf8dab41aac445a0259f751e56"` | Immutable image digest for MinIO; when set it overrides the tag. |
| `minio.image.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy for the MinIO workload. |
| `minio.serviceAccountName` | `"memoryhub-minio"` | ServiceAccount assigned to the MinIO workload. |
| `minio.secretName` | `"memoryhub-minio-credentials"` | Name of the pre-created MinIO credentials Secret in the storage namespace. |
| `minio.retainPvcOnUninstall` | `true` | Keep the MinIO data PVC when the Helm release is uninstalled. |
| `minio.existingClaim` | `""` | Existing MinIO PVC to mount; empty lets the chart create one. |
| `minio.storage` | `"10Gi"` | Requested capacity for the MinIO data PVC. |
| `minio.storageClassName` | `""` | StorageClass for the MinIO PVC; empty uses the cluster default. |
| `minio.resources.requests.cpu` | `"100m"` | Cpu request used for scheduling the MinIO workload. |
| `minio.resources.requests.memory` | `"128Mi"` | Memory request used for scheduling the MinIO workload. |
| `minio.resources.limits.cpu` | `"1"` | Maximum cpu allowed for the MinIO workload. |
| `minio.resources.limits.memory` | `"1Gi"` | Maximum memory allowed for the MinIO workload. |
| `minio.probes.liveness.httpGet.path` | `"/minio/health/live"` | HTTP path checked by the liveness probe for the MinIO workload. |
| `minio.probes.liveness.httpGet.port` | `9000` | Port checked by the liveness probe for the MinIO workload. |
| `minio.probes.liveness.initialDelaySeconds` | `15` | Delay before the liveness probe starts for the MinIO workload. |
| `minio.probes.liveness.periodSeconds` | `10` | Interval between liveness probe checks for the MinIO workload. |
| `minio.probes.liveness.timeoutSeconds` | `3` | Time limit for each liveness probe check for the MinIO workload. |
| `minio.probes.liveness.failureThreshold` | `6` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `minio.probes.readiness.httpGet.path` | `"/minio/health/live"` | HTTP path checked by the readiness probe for the MinIO workload. |
| `minio.probes.readiness.httpGet.port` | `9000` | Port checked by the readiness probe for the MinIO workload. |
| `minio.probes.readiness.initialDelaySeconds` | `5` | Delay before the readiness probe starts for the MinIO workload. |
| `minio.probes.readiness.periodSeconds` | `5` | Interval between readiness probe checks for the MinIO workload. |
| `minio.probes.readiness.timeoutSeconds` | `3` | Time limit for each readiness probe check for the MinIO workload. |
| `minio.probes.readiness.failureThreshold` | `3` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `minio.extraEnv` | `[]` | Additional environment-variable entries for the MinIO container. |

### `valkey`

| Value | Default | Description |
|---|---|---|
| `valkey.enabled` | `true` | Deploy the Valkey cache resources. |
| `valkey.replicas` | `1` | Desired number of Valkey pods. |
| `valkey.image.repository` | `"docker.io/valkey/valkey"` | Container image repository for the Valkey workload. |
| `valkey.image.tag` | `"8.0-alpine"` | Image tag for the Valkey workload when no digest is set. |
| `valkey.image.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy for the Valkey workload. |
| `valkey.serviceAccountName` | `"memoryhub-valkey"` | ServiceAccount assigned to the Valkey workload. |
| `valkey.storage` | `"5Gi"` | Requested capacity for the Valkey data PVC. |
| `valkey.storageClassName` | `""` | StorageClass for the Valkey PVC; empty uses the cluster default. |
| `valkey.maxMemory` | `"512mb"` | Valkey maxmemory setting; the default is below its container memory limit. |
| `valkey.resources.requests.cpu` | `"100m"` | Cpu request used for scheduling the Valkey workload. |
| `valkey.resources.requests.memory` | `"128Mi"` | Memory request used for scheduling the Valkey workload. |
| `valkey.resources.limits.cpu` | `"1"` | Maximum cpu allowed for the Valkey workload. |
| `valkey.resources.limits.memory` | `"768Mi"` | Maximum memory allowed for the Valkey workload. |
| `valkey.probes.liveness.exec.command` | `["valkey-cli","ping"]` | Command run by the liveness probe for the Valkey workload. |
| `valkey.probes.liveness.initialDelaySeconds` | `10` | Delay before the liveness probe starts for the Valkey workload. |
| `valkey.probes.liveness.periodSeconds` | `10` | Interval between liveness probe checks for the Valkey workload. |
| `valkey.probes.liveness.timeoutSeconds` | `3` | Time limit for each liveness probe check for the Valkey workload. |
| `valkey.probes.liveness.failureThreshold` | `6` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `valkey.probes.readiness.exec.command` | `["valkey-cli","ping"]` | Command run by the readiness probe for the Valkey workload. |
| `valkey.probes.readiness.initialDelaySeconds` | `3` | Delay before the readiness probe starts for the Valkey workload. |
| `valkey.probes.readiness.periodSeconds` | `5` | Interval between readiness probe checks for the Valkey workload. |
| `valkey.probes.readiness.timeoutSeconds` | `3` | Time limit for each readiness probe check for the Valkey workload. |
| `valkey.probes.readiness.failureThreshold` | `3` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `valkey.extraEnv` | `[]` | Additional environment-variable entries for the Valkey container. |
| `valkey.image.digest` | `unset` | Optional immutable image digest for Valkey; when set it overrides the tag. |

### `mcp`

| Value | Default | Description |
|---|---|---|
| `mcp.enabled` | `true` | Deploy the MemoryHub MCP server. |
| `mcp.image.repository` | `"memory-hub-mcp"` | Container image repository for the MCP workload. |
| `mcp.image.tag` | `"latest"` | Image tag for the MCP workload when no digest is set. |
| `mcp.image.pullPolicy` | `"Always"` | Kubernetes image pull policy for the MCP workload. |
| `mcp.replicas` | `1` | Desired number of MCP pods. |
| `mcp.resources.requests.cpu` | `"250m"` | Cpu request used for scheduling the MCP workload. |
| `mcp.resources.requests.memory` | `"256Mi"` | Memory request used for scheduling the MCP workload. |
| `mcp.resources.limits.cpu` | `"500m"` | Maximum cpu allowed for the MCP workload. |
| `mcp.resources.limits.memory` | `"512Mi"` | Maximum memory allowed for the MCP workload. |
| `mcp.probes.liveness.tcpSocket.port` | `8080` | Port checked by the liveness probe for the MCP workload. |
| `mcp.probes.liveness.initialDelaySeconds` | `10` | Delay before the liveness probe starts for the MCP workload. |
| `mcp.probes.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the MCP workload. |
| `mcp.probes.readiness.tcpSocket.port` | `8080` | Port checked by the readiness probe for the MCP workload. |
| `mcp.probes.readiness.initialDelaySeconds` | `5` | Delay before the readiness probe starts for the MCP workload. |
| `mcp.probes.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the MCP workload. |
| `mcp.secrets.database` | `"memoryhub-db-credentials"` | Name of the pre-created database Secret referenced by the MCP workload. |
| `mcp.secrets.minio` | `"memoryhub-minio-credentials"` | Name of the pre-created minio Secret referenced by the MCP workload. |
| `mcp.secrets.authInternal` | `"auth-internal-service-key"` | Name of the pre-created authInternal Secret referenced by the MCP workload. |
| `mcp.usersConfigMap` | `"memoryhub-users"` | Name of the ConfigMap containing MCP user configuration. |
| `mcp.authJwksUri` | `""` | JWKS URL used by MCP to validate auth-service tokens; empty uses chart-derived configuration. |
| `mcp.authApiKeyValidateUrl` | `""` | Auth API URL used to validate API keys; empty uses chart-derived configuration. |
| `mcp.embeddingUrl` | `""` | Embedding service URL; empty derives it from the model variant and namespace. |
| `mcp.rerankerUrl` | `""` | Reranker service URL; empty derives it from the model variant and namespace. |
| `mcp.valkeyUrl` | `""` | Valkey connection URL; empty uses the chart service address. |
| `mcp.s3Endpoint` | `""` | S3-compatible object-storage endpoint; empty uses the chart MinIO service. |
| `mcp.route.enabled` | `true` | Create an OpenShift Route for the MCP service. |
| `mcp.route.host` | `""` | Host name for the MCP OpenShift Route; empty lets OpenShift assign one. |
| `mcp.route.path` | `"/mcp/"` | Path served by the MCP OpenShift Route. |
| `mcp.route.tlsTermination` | `"edge"` | OpenShift Route TLS termination mode for the MCP service. |
| `mcp.route.insecurePolicy` | `"Redirect"` | How the MCP Route handles insecure HTTP requests. |
| `mcp.ingress.enabled` | `false` | Create a Kubernetes Ingress for the MCP service. |
| `mcp.ingress.host` | `""` | Host name for the MCP Ingress. |
| `mcp.ingress.path` | `"/mcp/"` | Path served by the MCP Ingress. |
| `mcp.env.MCP_TRANSPORT` | `"http"` | Value passed to the MCP container as the MCP_TRANSPORT environment variable. |
| `mcp.env.MCP_HTTP_HOST` | `"0.0.0.0"` | Value passed to the MCP container as the MCP_HTTP_HOST environment variable. |
| `mcp.env.MCP_HTTP_PORT` | `"8080"` | Value passed to the MCP container as the MCP_HTTP_PORT environment variable. |
| `mcp.env.MCP_HTTP_PATH` | `"/mcp/"` | Value passed to the MCP container as the MCP_HTTP_PATH environment variable. |
| `mcp.env.MCP_LOG_LEVEL` | `"INFO"` | Value passed to the MCP container as the MCP_LOG_LEVEL environment variable. |
| `mcp.env.AUTH_AUDIENCE` | `"memoryhub"` | Value passed to the MCP container as the AUTH_AUDIENCE environment variable. |
| `mcp.env.MEMORYHUB_S3_BUCKET` | `"memoryhub"` | Value passed to the MCP container as the MEMORYHUB_S3_BUCKET environment variable. |
| `mcp.env.MEMORYHUB_S3_SECURE` | `"false"` | Value passed to the MCP container as the MEMORYHUB_S3_SECURE environment variable. |
| `mcp.extraEnv` | `[]` | Additional environment-variable entries for the MCP container. |
| `mcp.image.digest` | `unset` | Optional immutable image digest for the MCP server; when set it overrides the tag. |

### `auth`

| Value | Default | Description |
|---|---|---|
| `auth.enabled` | `true` | Deploy the authentication service. |
| `auth.image.repository` | `"auth-server"` | Container image repository for the auth workload. |
| `auth.image.tag` | `"latest"` | Image tag for the auth workload when no digest is set. |
| `auth.image.pullPolicy` | `"Always"` | Kubernetes image pull policy for the auth workload. |
| `auth.replicas` | `1` | Desired number of auth pods. |
| `auth.serviceAccountName` | `"auth-server"` | ServiceAccount used by the auth workload and its OpenShift RBAC bindings. |
| `auth.rbac.enabled` | `true` | Create the auth service ClusterRole and ClusterRoleBindings. |
| `auth.rbac.authDelegator` | `true` | Create the auth-delegator ClusterRoleBinding when auth RBAC is enabled. |
| `auth.rbac.namespaceReader` | `true` | Allow the auth service to read Namespace objects when auth RBAC is enabled. |
| `auth.resources.requests.cpu` | `"100m"` | Cpu request used for scheduling the auth workload. |
| `auth.resources.requests.memory` | `"128Mi"` | Memory request used for scheduling the auth workload. |
| `auth.resources.limits.cpu` | `"250m"` | Maximum cpu allowed for the auth workload. |
| `auth.resources.limits.memory` | `"256Mi"` | Maximum memory allowed for the auth workload. |
| `auth.probes.liveness.httpGet.path` | `"/healthz"` | HTTP path checked by the liveness probe for the auth workload. |
| `auth.probes.liveness.httpGet.port` | `8081` | Port checked by the liveness probe for the auth workload. |
| `auth.probes.liveness.initialDelaySeconds` | `10` | Delay before the liveness probe starts for the auth workload. |
| `auth.probes.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the auth workload. |
| `auth.probes.readiness.httpGet.path` | `"/healthz"` | HTTP path checked by the readiness probe for the auth workload. |
| `auth.probes.readiness.httpGet.port` | `8081` | Port checked by the readiness probe for the auth workload. |
| `auth.probes.readiness.initialDelaySeconds` | `5` | Delay before the readiness probe starts for the auth workload. |
| `auth.probes.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the auth workload. |
| `auth.secrets.database` | `"memoryhub-pg-credentials"` | Name of the pre-created database credentials Secret in the auth namespace. |
| `auth.secrets.rsaKeys` | `"auth-rsa-keys"` | Name of the pre-created RSA key Secret in the auth namespace. |
| `auth.secrets.adminKey` | `"auth-admin-key"` | Name of the pre-created auth admin-key Secret. |
| `auth.secrets.internalServiceKey` | `"auth-internal-service-key"` | Name of the pre-created internal-service-key Secret. |
| `auth.secrets.oauthClient` | `"openshift-oauth-client-secret"` | Name of the pre-created OAuth client Secret. |
| `auth.extraEnv` | `[]` | Additional environment-variable entries for the auth container. |
| `auth.issuer` | `""` | Token issuer URL advertised by the auth service; empty uses the chart-derived URL. |
| `auth.oauthAuthorizeUrl` | `""` | OpenShift OAuth authorize URL; empty uses the chart-derived URL. |
| `auth.allowedGroup` | `"memoryhub-users"` | OpenShift group allowed to use the auth service. |
| `auth.oauthClientId` | `"memoryhub-auth-broker"` | OpenShift OAuthClient identifier registered for the auth service. |
| `auth.route.enabled` | `true` | Create an OpenShift Route for the auth service. |
| `auth.route.host` | `""` | Host name for the auth OpenShift Route; empty lets OpenShift assign one. |
| `auth.route.tlsTermination` | `"edge"` | OpenShift Route TLS termination mode for the auth service. |
| `auth.route.insecurePolicy` | `"Redirect"` | How the auth Route handles insecure HTTP requests. |
| `auth.ingress.enabled` | `false` | Create a Kubernetes Ingress for the auth service. |
| `auth.ingress.host` | `""` | Host name for the auth Ingress. |
| `auth.image.digest` | `unset` | Optional immutable image digest for the auth service; when set it overrides the tag. |

### `ui`

| Value | Default | Description |
|---|---|---|
| `ui.enabled` | `true` | Deploy the dashboard and OAuth proxy. |
| `ui.image.repository` | `"memoryhub-ui"` | Container image repository for the dashboard workload. |
| `ui.image.tag` | `"latest"` | Image tag for the dashboard workload when no digest is set. |
| `ui.image.pullPolicy` | `"Always"` | Kubernetes image pull policy for the dashboard workload. |
| `ui.oauthProxyImage.repository` | `"registry.redhat.io/openshift4/ose-oauth-proxy"` | Container image repository for the dashboard workload. |
| `ui.oauthProxyImage.tag` | `"v4.14"` | Image tag for the dashboard workload when no digest is set. |
| `ui.oauthProxyImage.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy for the dashboard workload. |
| `ui.replicas` | `1` | Desired number of dashboard pods. |
| `ui.serviceAccountName` | `"memoryhub-ui"` | ServiceAccount used by the dashboard and OAuth proxy. |
| `ui.resources.requests.cpu` | `"250m"` | Cpu request used for scheduling the dashboard workload. |
| `ui.resources.requests.memory` | `"256Mi"` | Memory request used for scheduling the dashboard workload. |
| `ui.resources.limits.cpu` | `"500m"` | Maximum cpu allowed for the dashboard workload. |
| `ui.resources.limits.memory` | `"512Mi"` | Maximum memory allowed for the dashboard workload. |
| `ui.probes.liveness.httpGet.path` | `"/healthz"` | HTTP path checked by the liveness probe for the dashboard workload. |
| `ui.probes.liveness.httpGet.port` | `8080` | Port checked by the liveness probe for the dashboard workload. |
| `ui.probes.liveness.initialDelaySeconds` | `10` | Delay before the liveness probe starts for the dashboard workload. |
| `ui.probes.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the dashboard workload. |
| `ui.probes.readiness.httpGet.path` | `"/healthz"` | HTTP path checked by the readiness probe for the dashboard workload. |
| `ui.probes.readiness.httpGet.port` | `8080` | Port checked by the readiness probe for the dashboard workload. |
| `ui.probes.readiness.initialDelaySeconds` | `5` | Delay before the readiness probe starts for the dashboard workload. |
| `ui.probes.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the dashboard workload. |
| `ui.proxyResources.requests.cpu` | `"50m"` | Cpu request used for scheduling the dashboard OAuth proxy. |
| `ui.proxyResources.requests.memory` | `"64Mi"` | Memory request used for scheduling the dashboard OAuth proxy. |
| `ui.proxyResources.limits.cpu` | `"100m"` | Maximum cpu allowed for the dashboard OAuth proxy. |
| `ui.proxyResources.limits.memory` | `"128Mi"` | Maximum memory allowed for the dashboard OAuth proxy. |
| `ui.secrets.database` | `"memoryhub-db-credentials"` | Name of the pre-created database credentials Secret in the UI namespace. |
| `ui.secrets.adminKey` | `"memoryhub-ui-admin-key"` | Name of the pre-created UI admin-key Secret. |
| `ui.secrets.proxy` | `"memoryhub-ui-proxy"` | Name of the pre-created OAuth proxy session Secret. |
| `ui.secrets.tls` | `"memoryhub-ui-tls"` | Name of the TLS Secret used by the dashboard service. |
| `ui.extraEnv` | `[]` | Additional environment-variable entries for the dashboard container. |
| `ui.mcpServerUrl` | `""` | Internal MCP URL used by the dashboard; empty uses the chart-derived URL. |
| `ui.authServiceUrl` | `""` | Internal auth URL used by the dashboard; empty uses the chart-derived URL. |
| `ui.publicMcpUrl` | `"https://mcp-server.example.com/mcp/"` | Public MCP URL shown to dashboard clients. |
| `ui.publicAuthUrl` | `"https://auth-server.example.com"` | Public auth URL used by dashboard clients. |
| `ui.embeddingUrl` | `""` | Embedding service URL used by the dashboard; empty derives it from the model settings. |
| `ui.route.enabled` | `true` | Create an OpenShift Route for the dashboard. |
| `ui.route.host` | `""` | Host name for the dashboard OpenShift Route; empty lets OpenShift assign one. |
| `ui.route.tlsTermination` | `"reencrypt"` | OpenShift Route TLS termination mode for the dashboard service. |
| `ui.route.insecurePolicy` | `"Redirect"` | How the dashboard Route handles insecure HTTP requests. |
| `ui.ingress.enabled` | `false` | Create a Kubernetes Ingress for the dashboard. |
| `ui.ingress.host` | `""` | Host name for the dashboard Ingress. |
| `ui.ingress.servicePort` | `8443` | Service port targeted by the dashboard Ingress. |
| `ui.image.digest` | `unset` | Optional immutable image digest for the dashboard; when set it overrides the tag. |
| `ui.oauthProxyImage.digest` | `unset` | Optional immutable image digest for the OAuth proxy; when set it overrides the tag. |

### `models`

| Value | Default | Description |
|---|---|---|
| `models.enabled` | `true` | Deploy the embedding and reranker model services. |
| `models.variant` | `"cpu"` | Select the CPU or GPU image, model ID, resources, probes, and service names. |
| `models.image.cpu.repository` | `"ghcr.io/huggingface/text-embeddings-inference"` | Container image repository used for CPU model workloads. |
| `models.image.cpu.tag` | `"cpu-1.6"` | Container image tag used for CPU model workloads when no digest is set. |
| `models.image.cpu.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy used for CPU model workloads. |
| `models.image.gpu.repository` | `"ghcr.io/huggingface/text-embeddings-inference"` | Container image repository used for GPU model workloads. |
| `models.image.gpu.tag` | `"1.9"` | Container image tag used for GPU model workloads when no digest is set. |
| `models.image.gpu.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy used for GPU model workloads. |
| `models.embedding.replicas` | `1` | Number of embedding-service pods. |
| `models.embedding.modelId.cpu` | `"sentence-transformers/all-MiniLM-L6-v2"` | Embedding model ID loaded for the CPU variant. |
| `models.embedding.modelId.gpu` | `"ibm-granite/granite-embedding-small-english-r2"` | Embedding model ID loaded for the GPU variant. |
| `models.embedding.storage` | `"10Gi"` | Requested capacity for the embedding model cache PVC. |
| `models.embedding.storageClassName` | `""` | StorageClass for the embedding cache PVC; empty uses the cluster default. |
| `models.embedding.storageAccessMode` | `"ReadWriteOnce"` | Access mode for the embedding cache PVC. |
| `models.embedding.resources.requests.cpu` | `"1"` | Cpu request used for scheduling the embedding workload. |
| `models.embedding.resources.requests.memory` | `"2Gi"` | Memory request used for scheduling the embedding workload. |
| `models.embedding.resources.limits.cpu` | `"2"` | Maximum cpu allowed for the embedding workload. |
| `models.embedding.resources.limits.memory` | `"4Gi"` | Maximum memory allowed for the embedding workload. |
| `models.embedding.probes.cpu.liveness.httpGet.path` | `"/health"` | HTTP path checked by the liveness probe for the embedding workload. |
| `models.embedding.probes.cpu.liveness.httpGet.port` | `8080` | Port checked by the liveness probe for the embedding workload. |
| `models.embedding.probes.cpu.liveness.initialDelaySeconds` | `120` | Delay before the liveness probe starts for the embedding workload. |
| `models.embedding.probes.cpu.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the embedding workload. |
| `models.embedding.probes.cpu.liveness.failureThreshold` | `3` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `models.embedding.probes.cpu.readiness.httpGet.path` | `"/health"` | HTTP path checked by the readiness probe for the embedding workload. |
| `models.embedding.probes.cpu.readiness.httpGet.port` | `8080` | Port checked by the readiness probe for the embedding workload. |
| `models.embedding.probes.cpu.readiness.initialDelaySeconds` | `120` | Delay before the readiness probe starts for the embedding workload. |
| `models.embedding.probes.cpu.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the embedding workload. |
| `models.embedding.probes.cpu.readiness.failureThreshold` | `10` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `models.embedding.probes.gpu.liveness.httpGet.path` | `"/health"` | HTTP path checked by the liveness probe for the embedding workload. |
| `models.embedding.probes.gpu.liveness.httpGet.port` | `8080` | Port checked by the liveness probe for the embedding workload. |
| `models.embedding.probes.gpu.liveness.initialDelaySeconds` | `300` | Delay before the liveness probe starts for the embedding workload. |
| `models.embedding.probes.gpu.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the embedding workload. |
| `models.embedding.probes.gpu.liveness.failureThreshold` | `3` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `models.embedding.probes.gpu.readiness.httpGet.path` | `"/health"` | HTTP path checked by the readiness probe for the embedding workload. |
| `models.embedding.probes.gpu.readiness.httpGet.port` | `8080` | Port checked by the readiness probe for the embedding workload. |
| `models.embedding.probes.gpu.readiness.initialDelaySeconds` | `180` | Delay before the readiness probe starts for the embedding workload. |
| `models.embedding.probes.gpu.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the embedding workload. |
| `models.embedding.probes.gpu.readiness.failureThreshold` | `60` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `models.embedding.extraEnv` | `[]` | Additional environment-variable entries for the embedding container. |
| `models.embedding.gpuResources.requests.cpu` | `"1"` | cpu request for the GPU embedding workload. |
| `models.embedding.gpuResources.requests.memory` | `"4Gi"` | memory request for the GPU embedding workload. |
| `models.embedding.gpuResources.requests.nvidia.com/gpu` | `"1"` | Number of NVIDIA GPUs requested for the embedding workload; schedules it on a GPU node. |
| `models.embedding.gpuResources.limits.cpu` | `"4"` | Maximum cpu for the GPU embedding workload. |
| `models.embedding.gpuResources.limits.memory` | `"8Gi"` | Maximum memory for the GPU embedding workload. |
| `models.embedding.gpuResources.limits.nvidia.com/gpu` | `"1"` | Maximum number of NVIDIA GPUs assigned to the embedding workload. |
| `models.embedding.route.enabled` | `true` | Create an OpenShift Route for the embedding service. |
| `models.embedding.route.host` | `""` | Host name for the embedding OpenShift Route; empty lets OpenShift assign one. |
| `models.embedding.route.timeout` | `""` | OpenShift Route timeout override; an empty GPU value defaults to 120s. |
| `models.embedding.ingress.enabled` | `false` | Create a Kubernetes Ingress for the embedding service. |
| `models.embedding.ingress.host` | `""` | Host name for the embedding-service Ingress. |
| `models.reranker.replicas` | `1` | Number of reranker-service pods. |
| `models.reranker.modelId.cpu` | `"cross-encoder/ms-marco-MiniLM-L12-v2"` | Reranker model ID loaded for the CPU variant. |
| `models.reranker.modelId.gpu` | `"ibm-granite/granite-embedding-reranker-english-r2"` | Reranker model ID loaded for the GPU variant. |
| `models.reranker.storage` | `"10Gi"` | Requested capacity for the reranker model cache PVC. |
| `models.reranker.storageClassName` | `""` | StorageClass for the reranker cache PVC; empty uses the cluster default. |
| `models.reranker.storageAccessMode` | `"ReadWriteOnce"` | Access mode for the reranker cache PVC. |
| `models.reranker.resources.requests.cpu` | `"1"` | Cpu request used for scheduling the reranker workload. |
| `models.reranker.resources.requests.memory` | `"2Gi"` | Memory request used for scheduling the reranker workload. |
| `models.reranker.resources.limits.cpu` | `"2"` | Maximum cpu allowed for the reranker workload. |
| `models.reranker.resources.limits.memory` | `"4Gi"` | Maximum memory allowed for the reranker workload. |
| `models.reranker.probes.cpu.liveness.httpGet.path` | `"/health"` | HTTP path checked by the liveness probe for the reranker workload. |
| `models.reranker.probes.cpu.liveness.httpGet.port` | `8080` | Port checked by the liveness probe for the reranker workload. |
| `models.reranker.probes.cpu.liveness.initialDelaySeconds` | `120` | Delay before the liveness probe starts for the reranker workload. |
| `models.reranker.probes.cpu.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the reranker workload. |
| `models.reranker.probes.cpu.liveness.failureThreshold` | `3` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `models.reranker.probes.cpu.readiness.httpGet.path` | `"/health"` | HTTP path checked by the readiness probe for the reranker workload. |
| `models.reranker.probes.cpu.readiness.httpGet.port` | `8080` | Port checked by the readiness probe for the reranker workload. |
| `models.reranker.probes.cpu.readiness.initialDelaySeconds` | `120` | Delay before the readiness probe starts for the reranker workload. |
| `models.reranker.probes.cpu.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the reranker workload. |
| `models.reranker.probes.cpu.readiness.failureThreshold` | `10` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `models.reranker.probes.gpu.liveness.httpGet.path` | `"/health"` | HTTP path checked by the liveness probe for the reranker workload. |
| `models.reranker.probes.gpu.liveness.httpGet.port` | `8080` | Port checked by the liveness probe for the reranker workload. |
| `models.reranker.probes.gpu.liveness.initialDelaySeconds` | `300` | Delay before the liveness probe starts for the reranker workload. |
| `models.reranker.probes.gpu.liveness.periodSeconds` | `30` | Interval between liveness probe checks for the reranker workload. |
| `models.reranker.probes.gpu.liveness.failureThreshold` | `3` | Consecutive liveness probe failures before the workload is marked unhealthy. |
| `models.reranker.probes.gpu.readiness.httpGet.path` | `"/health"` | HTTP path checked by the readiness probe for the reranker workload. |
| `models.reranker.probes.gpu.readiness.httpGet.port` | `8080` | Port checked by the readiness probe for the reranker workload. |
| `models.reranker.probes.gpu.readiness.initialDelaySeconds` | `300` | Delay before the readiness probe starts for the reranker workload. |
| `models.reranker.probes.gpu.readiness.periodSeconds` | `10` | Interval between readiness probe checks for the reranker workload. |
| `models.reranker.probes.gpu.readiness.failureThreshold` | `10` | Consecutive readiness probe failures before the workload is marked unhealthy. |
| `models.reranker.extraEnv` | `[]` | Additional environment-variable entries for the reranker container. |
| `models.reranker.gpuResources.requests.cpu` | `"1"` | cpu request for the GPU reranker workload. |
| `models.reranker.gpuResources.requests.memory` | `"4Gi"` | memory request for the GPU reranker workload. |
| `models.reranker.gpuResources.requests.nvidia.com/gpu` | `"1"` | Number of NVIDIA GPUs requested for the reranker workload; schedules it on a GPU node. |
| `models.reranker.gpuResources.limits.cpu` | `"4"` | Maximum cpu for the GPU reranker workload. |
| `models.reranker.gpuResources.limits.memory` | `"8Gi"` | Maximum memory for the GPU reranker workload. |
| `models.reranker.gpuResources.limits.nvidia.com/gpu` | `"1"` | Maximum number of NVIDIA GPUs assigned to the reranker workload. |
| `models.reranker.route.enabled` | `true` | Create an OpenShift Route for the reranker service. |
| `models.reranker.route.host` | `""` | Host name for the reranker OpenShift Route; empty lets OpenShift assign one. |
| `models.reranker.route.timeout` | `""` | OpenShift Route timeout override; an empty GPU value defaults to 120s. |
| `models.reranker.ingress.enabled` | `false` | Create a Kubernetes Ingress for the reranker service. |
| `models.reranker.ingress.host` | `""` | Host name for the reranker-service Ingress. |
| `models.image.cpu.digest` | `unset` | Optional immutable image digest for CPU model workloads; when set it overrides the tag. |
| `models.image.gpu.digest` | `unset` | Optional immutable image digest for GPU model workloads; when set it overrides the tag. |

### `maintenance`

| Value | Default | Description |
|---|---|---|
| `maintenance.retention.enabled` | `true` | Enable the scheduled retention-policy job. |
| `maintenance.retention.schedule` | `"0 2 * * *"` | Cron schedule for the retention job. |
| `maintenance.retention.resources.requests.cpu` | `"100m"` | Cpu request used for scheduling the retention job workload. |
| `maintenance.retention.resources.requests.memory` | `"128Mi"` | Memory request used for scheduling the retention job workload. |
| `maintenance.retention.resources.limits.cpu` | `"200m"` | Maximum cpu allowed for the retention job workload. |
| `maintenance.retention.resources.limits.memory` | `"256Mi"` | Maximum memory allowed for the retention job workload. |
| `maintenance.cleanup.enabled` | `false` | Enable the optional test-data cleanup CronJob; disabled by default. |
| `maintenance.cleanup.schedule` | `"0 3 * * 0"` | Cron schedule for the test-data cleanup job. |
| `maintenance.cleanup.image.repository` | `"registry.redhat.io/rhel9/postgresql-16"` | Container image repository for the cleanup job. |
| `maintenance.cleanup.image.tag` | `"latest"` | Image tag used when no digest is set for the cleanup job. |
| `maintenance.cleanup.image.pullPolicy` | `"IfNotPresent"` | Kubernetes image pull policy for the cleanup job. |
| `maintenance.cleanup.resources.requests.cpu` | `"50m"` | Cpu request used for scheduling the cleanup job workload. |
| `maintenance.cleanup.resources.requests.memory` | `"64Mi"` | Memory request used for scheduling the cleanup job workload. |
| `maintenance.cleanup.resources.limits.cpu` | `"100m"` | Maximum cpu allowed for the cleanup job workload. |
| `maintenance.cleanup.resources.limits.memory` | `"128Mi"` | Maximum memory allowed for the cleanup job workload. |
| `maintenance.cleanup.image.digest` | `unset` | Optional immutable image digest for the cleanup job; when set it overrides the tag. |
| `maintenance.retention.image` | `{}` | Optional retention-job image override; an empty map uses the MCP image settings. |
| `maintenance.retention.image.repository` | `"memory-hub-mcp"` | Image repository inherited from `mcp.image.repository` unless overridden. |
| `maintenance.retention.image.tag` | `"latest"` | Image tag inherited from `mcp.image.tag` unless overridden or a digest is set. |
| `maintenance.retention.image.digest` | `unset` | Optional image digest inherited from `mcp.image.digest`; when set it overrides the tag. |
| `maintenance.retention.image.pullPolicy` | `"Always"` | Image pull policy inherited from `mcp.image.pullPolicy` unless overridden. |

#### `postgresql.initSql` default

```sql
-- Enable required extensions for MemoryHub
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify extensions loaded
DO $$
DECLARE
  vec_version text;
BEGIN
  SELECT extversion INTO vec_version FROM pg_extension WHERE extname = 'vector';
  RAISE NOTICE 'pgvector version: %', vec_version;
  RAISE NOTICE 'uuid-ossp loaded: %', EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'uuid-ossp');
END $$;
```
