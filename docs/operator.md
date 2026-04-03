# Kubernetes Operator

The MemoryHub Operator manages the full lifecycle of a MemoryHub deployment on OpenShift. It watches Custom Resource Definitions (CRDs), reconciles desired state with actual state, and handles provisioning, scaling, upgrades, and teardown of all MemoryHub subsystems.

**Status: skeleton.** CRD names and shapes are preliminary. Significant design work remains before implementation.

## What the Operator Manages

The operator is responsible for deploying and maintaining all MemoryHub components:

- MCP server pods (scaling, configuration, TLS)
- Curator agent (scheduling, configuration, leader election)
- Org ingestion pipeline (source configuration, scheduling)
- PostgreSQL instance (via coordination with the OOTB operator -- MemoryHub's operator doesn't manage PostgreSQL directly but declares what it needs)
- MinIO instance (via coordination with the MinIO operator)
- Prometheus ServiceMonitor and Grafana dashboard ConfigMaps
- RBAC resources (ServiceAccounts, Roles, RoleBindings for inter-component access)

The operator does not replace the OOTB PostgreSQL operator or the MinIO operator. It coordinates with them -- creating the CRs those operators expect and waiting for them to be ready before deploying MemoryHub components that depend on them.

## CRD Concepts

These are preliminary. The names and structures will change as design progresses.

### MemoryHub (top-level)

The primary CR that represents a MemoryHub installation. Applying this CR triggers the operator to deploy all components.

```yaml
apiVersion: memoryhub.openshift.ai/v1alpha1
kind: MemoryHub
metadata:
  name: memoryhub
  namespace: memoryhub
spec:
  storage:
    postgresql:
      # Reference to OOTB PostgreSQL CR or connection details
      size: 50Gi
      replicas: 2
    minio:
      # Reference to MinIO tenant or connection details
      size: 100Gi
      replicas: 4
  mcpServer:
    replicas: 3
    resources:
      requests:
        cpu: 500m
        memory: 512Mi
  curator:
    schedule:
      promotion: "0 2 * * *"    # daily at 2 AM
      pruning: "0 3 * * 0"      # weekly Sunday 3 AM
      secretsScan: "0 */6 * * *" # every 6 hours
  observability:
    grafanaDashboards: true
    serviceMonitor: true
```

### MemoryTier

Declares a memory scope tier with its governance rules. The operator creates the corresponding database partitions, access control rules, and governance policies.

```yaml
apiVersion: memoryhub.openshift.ai/v1alpha1
kind: MemoryTier
metadata:
  name: organizational
spec:
  scope: organizational
  governance:
    writePolicy: curator-only
    readPolicy: all-authenticated
    auditLevel: full
    humanApproval: optional  # vs "required" for enterprise
  injection:
    defaultWeight: 0.8
    stubThreshold: 0.5
  retention:
    maxAge: 365d
    stalenessThreshold: 90d
```

### MemoryPolicy

Declares rules that the governance engine enforces. Multiple policies can coexist; they're evaluated in priority order.

```yaml
apiVersion: memoryhub.openshift.ai/v1alpha1
kind: MemoryPolicy
metadata:
  name: no-secrets-in-memory
spec:
  priority: 100
  scope: all
  rules:
    - type: content-scan
      pattern: secrets
      action: block
      message: "Memory content appears to contain a secret"
    - type: content-scan
      pattern: pii
      action: flag
      message: "Memory content may contain PII"
```

### MemoryStore (maybe)

This one is less certain. It might make sense to have a CR that declares the storage backend configuration separately from the top-level MemoryHub CR, especially if different tiers use different storage characteristics. Or it might be simpler to keep storage configuration inline in the MemoryHub CR.

## Operator Responsibilities

### Lifecycle management

- **Install**: deploy all components in dependency order (storage first, then governance, then MCP server, then curator and ingestion)
- **Upgrade**: rolling updates of MCP server pods, schema migrations for PostgreSQL, configuration propagation
- **Teardown**: clean removal of all resources, with optional data retention (don't delete storage PVCs by default)

### Storage provisioning

The operator creates the PostgreSQL and MinIO CRs that the respective operators manage. It waits for those resources to be ready, then runs schema initialization (creating tables, indexes, pgvector extension, optionally AGE extension).

Schema migrations are versioned. The operator tracks which migration version has been applied and runs pending migrations on upgrade. This is straightforward Flyway/Alembic-style migration management.

### Scaling

MCP server pods scale horizontally based on load. The operator could use an HPA (Horizontal Pod Autoscaler) or manage scaling directly based on queue depth or connection count metrics.

The curator agent does not scale -- it's a singleton by design. The operator ensures exactly one instance is running via leader election.

### Health and readiness

The operator monitors the health of all components and updates the MemoryHub CR's status accordingly. If PostgreSQL is down, the status reflects it. If the curator hasn't run in longer than its schedule, the status flags it.

## Integration with OpenShift AI

MemoryHub deploys alongside OpenShift AI, not inside it. The integration points are:

- Agents running on OpenShift AI connect to MemoryHub's MCP server via a Route or Service
- Authentication shares the cluster's OAuth provider -- agents already have tokens from OpenShift
- The operator runs in its own namespace(s) and manages its own resources
- No modifications to OpenShift AI are required

If MemoryHub is eventually adopted as an OpenShift AI component, the operator would become part of the RHOAI operator's managed set. The CRD design should anticipate this by following RHOAI's conventions for CR structure and status reporting.

## Design Questions

- Should the MemoryHub CR be the single entry point (everything configured in one CR), or should MemoryTier, MemoryPolicy, and MemoryStore be independent CRDs that the operator discovers? The former is simpler to start; the latter is more composable.
- How does the operator coordinate with the OOTB PostgreSQL operator for extension installation? Can it create a PostgreSQL CR that requests pgvector and AGE extensions, or does it need to run post-install scripts against the database?
- What's the operator SDK / framework? Kopf (Python) aligns with the Python tech stack. Operator SDK (Go) is the OpenShift standard. If the goal is upstream contribution to RHOAI, Go might be expected.
- How do we handle CRD versioning? Starting at v1alpha1 is fine, but we need a migration strategy for when the CRD schema changes.
- Should the operator manage backup schedules, or leave that to the PostgreSQL and MinIO operators?
- Namespace topology: single namespace for everything, or separate namespaces for compute (MCP, curator) and storage (PostgreSQL, MinIO)?
- How does the operator handle FIPS validation? Should it check that the cluster is in FIPS mode at install time and warn if not?
