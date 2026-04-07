"""Deployment-topic synthetic memories.

50 memories about OpenShift, container builds, image registries, BuildConfig,
manifests, and platform architecture choices. Phrasing mimics real project
memories: decisions, lessons learned, configuration patterns.
"""

FOCUS_STRING = (
    "OpenShift deployment, container builds, BuildConfig, image registries, "
    "Containerfiles, podman, Red Hat UBI base images, and platform architecture"
)

MEMORIES = [
    {
        "content": "Always use Podman, not Docker, for local container builds. Use Containerfile, not Dockerfile. Targets Red Hat OpenShift with UBI base images.",
        "weight": 0.9,
    },
    {
        "content": "When building on Mac for OpenShift deployment, always specify --platform linux/amd64 to avoid ARM64/x86_64 architecture mismatches that crash pods at runtime.",
        "weight": 0.95,
    },
    {
        "content": "Red Hat UBI base images are the standard for all container builds. Use registry.redhat.io/ubi9/python-311 for Python services, never alpine or debian.",
        "weight": 0.9,
    },
    {
        "content": "Prefer OpenShift BuildConfig over building and pushing containers locally. BuildConfigs run on the cluster, avoid Mac-to-x86_64 architecture issues entirely.",
        "weight": 0.85,
    },
    {
        "content": "Source files written by Claude Code's Write tool have 600 permissions. Run chmod 644 on src/*.py before container builds or non-root pods will fail with PermissionError.",
        "weight": 0.95,
    },
    {
        "content": "memory-hub-mcp deploys to its own OpenShift project to avoid naming collisions. Deploy with: make deploy PROJECT=memory-hub-mcp.",
        "weight": 0.85,
    },
    {
        "content": "FIPS compliance is required for production deployments. Use FIPS-enabled UBI images. Ask the user about FIPS requirements if unclear at project start.",
        "weight": 0.9,
    },
    {
        "content": "Use the -n or --namespace flag with oc/kubectl commands. Never switch projects with 'oc project' — concurrent sessions step on each other's context.",
        "weight": 0.9,
    },
    {
        "content": "Image stream tags resolve at deploy time via alpha.image.policy.openshift.io/resolve-names: '*' annotation. Without it, the deployment uses the last-pinned digest forever.",
        "weight": 0.8,
    },
    {
        "content": "BuildConfig with binary source type requires uploading the build context tar via 'oc start-build --from-dir=.'. The context excludes .venv, __pycache__, and tests.",
        "weight": 0.8,
    },
    {
        "content": "Containerfile USER directive must specify a numeric UID for OpenShift compatibility. USER 1001 works because OpenShift assigns arbitrary UIDs in the project's range.",
        "weight": 0.85,
    },
    {
        "content": "Liveness probe and readiness probe should use different paths or behaviors. Conflating them causes restart loops when the app is briefly unhealthy but still starting.",
        "weight": 0.8,
    },
    {
        "content": "Route TLS termination should be 'edge' for HTTP backends and 'reencrypt' when the pod terminates TLS itself. Passthrough breaks Authorino path-based authz.",
        "weight": 0.75,
    },
    {
        "content": "Set noCache: true on BuildConfig dockerStrategy when iterating on Containerfile. Cached layers from a previous build can mask permission fixes and dependency changes.",
        "weight": 0.85,
    },
    {
        "content": "Build context size matters for binary uploads to OpenShift BuildConfig. Use .dockerignore to exclude .venv, __pycache__, .git, tests/, and benchmarks/.",
        "weight": 0.8,
    },
    {
        "content": "Make deploy targets should validate prerequisites: oc login present, project exists, required secrets created. Fail fast with clear error messages, not midway through.",
        "weight": 0.8,
    },
    {
        "content": "Pod resource limits: start with requests=200m/256Mi, limits=1/1Gi for FastAPI services. Tune based on observed usage in OpenShift's metrics dashboard.",
        "weight": 0.75,
    },
    {
        "content": "Use envFrom with secretRef to bulk-load environment variables from a Secret. Avoids listing each key in the Deployment manifest and lets the secret evolve independently.",
        "weight": 0.8,
    },
    {
        "content": "ConfigMap mounts vs envFrom: prefer envFrom for flat key-value configs, file mounts for structured config (yaml, ini). File mounts hot-reload on ConfigMap update; env vars do not.",
        "weight": 0.8,
    },
    {
        "content": "Init containers run before app containers and share the pod's volumes. Use them for one-time setup like database migrations, never for ongoing work.",
        "weight": 0.75,
    },
    {
        "content": "Database migrations should run as a Kubernetes Job, not an init container, when multiple replicas exist. Init containers run per-pod and would race against each other.",
        "weight": 0.85,
    },
    {
        "content": "OpenShift ServiceAccount tokens auto-mount at /var/run/secrets/kubernetes.io/serviceaccount. Use these for in-cluster API calls instead of static credentials.",
        "weight": 0.8,
    },
    {
        "content": "ImagePullPolicy: Always is required when using image stream tags with mutable tags like :latest. Without it the kubelet caches and never picks up new builds.",
        "weight": 0.85,
    },
    {
        "content": "Use podman-compose for local multi-service development. Translates docker-compose.yml directly. Don't expect 100% compatibility with docker-compose features.",
        "weight": 0.7,
    },
    {
        "content": "memory-hub-mcp Containerfile pins the embedding service URL via env var, not in code. The URL is cluster-specific and changes per environment.",
        "weight": 0.85,
    },
    {
        "content": "Build remote on ec2-dev-2 when on Mac for OpenShift deployment. Use /build-remote slash command. Avoids Mac-to-x86_64 issues entirely and uses the dev cluster's container registry.",
        "weight": 0.85,
    },
    {
        "content": "OpenShift Pipelines (Tekton) is the standard CI/CD path. ArgoCD handles GitOps deployment from the resulting image. Don't use Jenkins for new projects.",
        "weight": 0.85,
    },
    {
        "content": "Pod security context runAsNonRoot: true and readOnlyRootFilesystem: true should be the default. Mount writable scratch dirs as emptyDir if the app needs temp space.",
        "weight": 0.85,
    },
    {
        "content": "OpenShift route hostnames are bounded by the cluster wildcard domain. Don't hardcode the apps.cluster-xxx domain in code; read it from a ConfigMap or env var at runtime.",
        "weight": 0.8,
    },
    {
        "content": "Service of type ClusterIP is the default and the right choice for in-cluster traffic. NodePort and LoadBalancer leak the service to the cluster's host network.",
        "weight": 0.75,
    },
    {
        "content": "PVC access modes: RWO (ReadWriteOnce) for single-pod workloads like databases, RWX (ReadWriteMany) for shared file storage. CephFS supports RWX; AWS EBS does not.",
        "weight": 0.8,
    },
    {
        "content": "OpenShift's built-in monitoring stack (Prometheus + Alertmanager) covers most observability needs. Add ServiceMonitor CRs to scrape custom app metrics.",
        "weight": 0.8,
    },
    {
        "content": "Use OpenShift Secrets for credentials, not ConfigMaps. Secrets are base64-encoded at rest and have different RBAC defaults that prevent accidental exposure.",
        "weight": 0.85,
    },
    {
        "content": "Build args vs env vars in Containerfile: ARG values are baked into image layers and visible in image history. Use ENV for values that should be visible only at runtime.",
        "weight": 0.75,
    },
    {
        "content": "Multi-stage Containerfile builds: use one stage to install build deps and compile, copy artifacts to a slim runtime stage. Cuts final image size dramatically.",
        "weight": 0.8,
    },
    {
        "content": "OpenShift internal image registry is at image-registry.openshift-image-registry.svc:5000. Push there from within the cluster; access from outside via the registry route.",
        "weight": 0.75,
    },
    {
        "content": "When Containerfile RUN commands fail, podman build leaves the failed layer mounted at a podman-id path. Use podman build --target to drop into a shell at the failing step for debugging.",
        "weight": 0.7,
    },
    {
        "content": "Avoid hardcoded paths in container images. Use $HOME, $APP_ROOT, or env vars set in the Containerfile. Hard paths break when the image runs as a different UID.",
        "weight": 0.8,
    },
    {
        "content": "OpenShift pod logs are aggregated by the EFK stack when configured. Use 'oc logs' for ad-hoc debugging, Kibana for historical search.",
        "weight": 0.75,
    },
    {
        "content": "Deployment rolling update strategy: maxSurge=1, maxUnavailable=0 for zero-downtime. The default 25% can briefly drop all replicas if the deployment has fewer than 4.",
        "weight": 0.85,
    },
    {
        "content": "Set explicit livenessProbe initialDelaySeconds high enough that the app can start without being killed. FastAPI with model loading often needs 30+ seconds before it accepts traffic.",
        "weight": 0.85,
    },
    {
        "content": "OpenShift Operator Hub provides validated operators for common services (PostgreSQL, Kafka, Redis). Prefer operators over hand-written StatefulSets for stateful workloads.",
        "weight": 0.8,
    },
    {
        "content": "Pod disruption budgets (PDB) protect against voluntary evictions during node drain. Set minAvailable: 1 for any deployment that should not go to zero replicas.",
        "weight": 0.75,
    },
    {
        "content": "Image pinning by digest (sha256) is more reliable than tag-based references. CI should update the digest in manifests rather than relying on imagePullPolicy.",
        "weight": 0.8,
    },
    {
        "content": "Container images must be rebuilt to pick up base image security updates. Use OpenShift's image change triggers or scheduled BuildConfig runs to rebuild on UBI updates.",
        "weight": 0.8,
    },
    {
        "content": "Use NetworkPolicy to restrict pod-to-pod traffic to only what's needed. Default-deny ingress at the namespace level, then allow specific routes between services.",
        "weight": 0.8,
    },
    {
        "content": "Horizontal Pod Autoscaler (HPA) needs the Vertical Pod Autoscaler's resource requests to be set sensibly. Without realistic requests, the HPA's CPU percentage math is meaningless.",
        "weight": 0.75,
    },
    {
        "content": "Tekton PipelineRuns can take parameters from EventListeners triggered by GitHub webhooks. The full chain: GitHub push → EventListener → TriggerBinding → PipelineRun → Build → Deploy.",
        "weight": 0.75,
    },
    {
        "content": "Don't commit container build artifacts (image tarballs, oci-archive) to git. They're large binaries; fetch from a registry or rebuild from source instead.",
        "weight": 0.75,
    },
    {
        "content": "Helm vs Kustomize for OpenShift: Kustomize integrates more cleanly with the OpenShift CLI and the GitOps ArgoCD pattern. Use Helm only when consuming third-party charts.",
        "weight": 0.8,
    },
]

assert len(MEMORIES) == 50, f"deployment fixture must have 50 memories, has {len(MEMORIES)}"
