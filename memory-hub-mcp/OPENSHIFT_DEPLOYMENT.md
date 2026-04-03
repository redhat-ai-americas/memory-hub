# Deploying MCP Servers to OpenShift

When building MCP servers destined for OpenShift, several design decisions make the difference between a smooth deployment and hours of debugging.

## Hard Requirements

These will cause deployment failures if not addressed.

### Non-Root Container Execution

OpenShift runs containers as arbitrary non-root user IDs for security. This catches many developers off guard. Your Containerfile must explicitly set ownership and user:

```dockerfile
COPY --chown=1001:0 src/ ./src/
USER 1001
```

A subtle gotcha: if your development tooling creates files with 600 permissions (owner-only), the arbitrary UID won't be able to read them. Fix this in the Containerfile:

```dockerfile
RUN find ./src -name "*.py" -exec chmod 644 {} \;
```

Without this, your container starts but crashes with `PermissionError` when loading Python modules.

### File Permissions

Claude Code's Write tool (and some other dev tools) create files with 600 permissions as a security measure. OpenShift's arbitrary UIDs need at least 644 (world-readable). The `chmod 644` step in your Containerfile is mandatory, not optional.

### Environment-Driven Transport

The same codebase must run locally (STDIO for testing) and in OpenShift (HTTP for remote access). Environment variables control the switch:

```dockerfile
ENV MCP_TRANSPORT=http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8080
```

Without `MCP_TRANSPORT=http`, the server defaults to STDIO mode and won't accept network connections—your pod runs but nothing can connect to it.

## Best Practices

Recommended for production-ready deployments.

### Red Hat UBI Base Images

Start with `registry.redhat.io/ubi9/python-311:latest`. UBI (Universal Base Image) provides enterprise support, security updates, and compatibility with OpenShift's security model. Required if your environment has FIPS compliance requirements.

### OpenShift-Native Builds

Rather than pushing containers from your laptop, use OpenShift's BuildConfig with binary builds:

1. Creates a filtered build context (excluding `__pycache__`, `.pyc` files)
2. Fixes any permission issues before upload
3. Triggers `oc start-build --from-dir` to build server-side

This ensures the image is built on x86_64 (avoiding Mac ARM architecture mismatches) and lands directly in the internal registry.

### Health Checks and Resource Limits

Production deployments need probes for OpenShift to manage pod lifecycle, and resource constraints to prevent runaway consumption:

```yaml
livenessProbe:
  tcpSocket:
    port: 8080
  initialDelaySeconds: 10
readinessProbe:
  tcpSocket:
    port: 8080
  initialDelaySeconds: 5
resources:
  limits:
    memory: "512Mi"
    cpu: "500m"
```

Without health checks, OpenShift can't detect unresponsive pods or perform proper rolling updates.

### TLS Termination at the Route

Let OpenShift Routes handle TLS at the edge. Your container speaks plain HTTP internally:

```yaml
tls:
  termination: edge
  insecureEdgeTerminationPolicy: Redirect
```

This simplifies certificate management and leverages OpenShift's built-in TLS infrastructure.

## One-Command Deployment

Everything wraps up in a Makefile target:

```bash
make deploy PROJECT=my-mcp-server
```

This creates the project if needed, applies manifests, builds the image, and waits for rollout. The output includes the URL ready for testing.

---

**The takeaway**: Non-root execution and correct file permissions are non-negotiable. Environment-driven transport configuration is essential. Everything else improves reliability and maintainability but won't block your initial deployment.
