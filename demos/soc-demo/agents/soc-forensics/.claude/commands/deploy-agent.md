# Deploy Agent

Build the container image and deploy the agent to OpenShift. This command handles the full path from source code to a running pod.

**Prerequisites: The agent must be implemented and tested. Run `/create-agent` and ideally `/exercise-agent` first. You also need `oc` CLI access and a target OpenShift cluster.**

## Process

### Step 1: Pre-flight Checks

Before building anything, verify the project is ready:

1. **Tests pass**: Run `make test`. If tests fail, stop and fix them. Do not deploy broken code.
2. **No uncommitted changes**: Run `git status`. Warn the developer if there are uncommitted changes — the image should correspond to a known git state.
3. **Configuration review**: Read `agent.yaml` and confirm:
   - The model endpoint is set via env var (`${MODEL_ENDPOINT:-...}`) — not hardcoded to a local URL
   - Any MCP server URLs use env var substitution
   - Secrets (API keys, tokens) are not embedded in any file
4. **Containerfile exists**: Verify `Containerfile` is present at the project root.
5. **Helm chart exists**: Verify `chart/Chart.yaml` and `chart/values.yaml` exist.

Report the pre-flight status to the developer. If anything is wrong, explain what needs fixing and do not proceed until it is resolved.

### Step 2: Determine Build Strategy

Ask the developer which build approach to use:

**Option A: Remote build (recommended on Mac)**
Building on macOS produces ARM64 images by default, which will not run on OpenShift (x86_64). If the developer is on a Mac, recommend a remote build. Ask: "Should I build this container remotely on ec2-dev-2 to ensure x86_64 compatibility?" If yes, delegate to the `remote-builder` agent.

**Option B: Local build with platform override**
If the developer prefers a local build, use:
```
podman build --platform linux/amd64 -t <image-name>:<tag> -f Containerfile . --no-cache
```

**Option C: OpenShift BuildConfig**
If the cluster has a BuildConfig set up, trigger the build there. This avoids the architecture mismatch entirely.

Wait for the developer to choose before proceeding.

### Step 3: Prepare for Build

Before building, ensure source files have correct permissions. The container runs as a non-root user (UID 1001), so all Python source files must be readable:

```bash
chmod 644 src/*.py src/base_agent/*.py tools/*.py
chmod 644 prompts/*.md rules/*.md agent.yaml
find skills/ -name "*.md" -exec chmod 644 {} +
```

The Containerfile handles group permissions internally, but the source files need to be readable at COPY time.

### Step 4: Build the Image

Execute the chosen build strategy. The image name and tag come from the `Makefile` defaults or developer override:

- `IMAGE_NAME` defaults to `agent-template` — the developer should override this with their agent's name
- `IMAGE_TAG` defaults to `latest` — recommend using a git short hash or semantic version instead

For a local build: `make build IMAGE_NAME=<name> IMAGE_TAG=<tag>`

Verify the build succeeds. If it fails, read the build output carefully and fix the issue. Common problems:
- Missing Python dependencies in `pyproject.toml`
- Files referenced in Containerfile that do not exist
- Syntax errors in Python source files that only surface during `pip install`

### Step 5: Push the Image

The image needs to reach a registry accessible by the OpenShift cluster. Ask the developer which registry to use:

- `quay.io/your-org/<image>` — public or organization registry
- `image-registry.openshift-image-registry.svc:5000/<namespace>/<image>` — internal OpenShift registry
- Another registry the developer specifies

Push the image:
```bash
podman push <image-name>:<tag> <registry>/<image-name>:<tag>
```

### Step 6: Configure the Deployment

Review and update `chart/values.yaml` with deployment-specific settings:

- Container image reference (registry, name, tag)
- Resource requests and limits (CPU, memory)
- Environment variables for `agent.yaml` overrides (MODEL_ENDPOINT, MODEL_NAME, etc.)
- Secret references for credentials
- Replica count (typically 1 for an agent loop, unless the agent is designed for parallel instances)

If the agent uses MemoryHub, ensure the MemoryHub server URL and API key are configured as environment variables or secrets.

### Step 7: Deploy

Use the project's deploy script or Helm directly:

**With deploy.sh**: `./deploy.sh <namespace>`

**With Helm**: `helm upgrade --install <release-name> chart/ -n <namespace> --wait`

**With make**: `make deploy PROJECT=<namespace>`

The namespace should already exist. If it does not, confirm with the developer before creating it — they may have specific naming conventions or quotas.

### Step 8: Verify Deployment

After deployment, check that the agent is running:

```bash
# Pod is running
oc get pods -n <namespace> -l app=<image-name>

# No crash loops or restart cycles
oc describe pod <pod-name> -n <namespace>

# Agent startup logs look correct (should see "Agent setup complete")
oc logs <pod-name> -n <namespace> --tail=50
```

Look for these indicators of a healthy start:
- "Setting up agent" with the correct model name and endpoint
- Tool discovery messages showing the expected number of tools
- Prompt loading messages
- "Agent setup complete"

Look for these problems:
- `ImportError` — missing dependency in `pyproject.toml`
- `ConfigError` — bad `agent.yaml` or missing env vars
- `ConnectionRefused` — model endpoint not reachable from the cluster
- `PermissionError` — file permissions issue in the container
- Crash loop with `OOMKilled` — increase memory limits in `values.yaml`

### Step 9: Report

Present the deployment status:

- Namespace and pod name
- Image tag deployed
- Whether the agent started successfully
- Any warnings or issues observed in logs
- How to check logs going forward: `oc logs -f <pod-name> -n <namespace>`
- How to redeploy after changes: rebuild image, push, restart pod or upgrade Helm release
