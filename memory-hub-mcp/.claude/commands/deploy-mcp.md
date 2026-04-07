---
description: Deploy memory-hub-mcp to OpenShift via the project-canonical deploy/deploy.sh
---

# Deploy memory-hub-mcp

Deploy the MemoryHub MCP server to OpenShift. This command is **specific to memory-hub-mcp** — the namespace, deployment name, and script paths are all hardcoded for this project. Do NOT use the generic fips-agents template flow.

## No arguments

The OpenShift namespace (`memory-hub-mcp`) and deployment name (`memory-hub-mcp`) are hardcoded in `deploy/deploy.sh` on purpose. Past incidents with template-default namespaces (`mcp-demo`) and parameterized scripts created duplicate deployments and lost work. Do not parameterize without reading the retros first.

## Prerequisites

- Tools are implemented and tested
- Local pytest suite passes
- `mcp-test-mcp` is available in the calling agent's tool list (verify before starting; if not, STOP and ask)
- Logged in to the right OpenShift cluster (`oc whoami`)

## Step 1: Pre-deployment checks (in main context)

Run these in the main conversation, not delegated:

### A. File permissions

```bash
find memory-hub-mcp/src -name "*.py" -perm 600 -exec chmod 644 {} \;
```

### B. Test suite

```bash
cd memory-hub-mcp && .venv/bin/pytest tests/ -v --ignore=tests/examples/
```

If tests fail, STOP. Do not deploy broken code.

### C. Baseline cluster state

Capture exactly what's deployed before you change anything:

```bash
oc get deploy memory-hub-mcp -n memory-hub-mcp -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
oc get pods -n memory-hub-mcp -l app.kubernetes.io/name=memory-hub-mcp
```

You should see exactly one running pod and one image. Save the pod name — you will compare against it post-deploy to confirm a fresh rollout actually happened.

If you see more than one `memory-hub-mcp` deployment or more than one running pod, STOP and investigate before deploying. Do not run `make deploy` until the baseline is clean.

### D. Secret scan

```bash
gitleaks detect --source=memory-hub-mcp/ --no-banner --no-git
```

If secrets are flagged, STOP and warn the user.

## Step 2: Delegate the build to terminal-worker

The `make deploy` step runs a long, verbose `oc start-build` and a rollout. Delegate this single step to a `terminal-worker` subagent — but with a project-specific prompt that does NOT introduce parameters or rename anything. Use this exact delegation prompt:

```
Run the memory-hub-mcp deploy script and report the result.

Working directory: /Users/wjackson/Developer/memory-hub/memory-hub-mcp

Command:
  make deploy

The script (deploy/deploy.sh) will:
  1. Prepare a build context via deploy/build-context.sh (this stages
     ../src/memoryhub/ as memoryhub-core/ for the Containerfile)
  2. Apply deploy/users-configmap.yaml
  3. Apply deploy/openshift.yaml
  4. Run `oc start-build memory-hub-mcp --from-dir=<staged> -n memory-hub-mcp --follow`
  5. Run `oc rollout restart deployment/memory-hub-mcp -n memory-hub-mcp`
  6. Wait up to 300s for rollout
  7. Verify exactly one ready pod
  8. Print the route URL

Do NOT modify the script. Do NOT pass extra arguments. Do NOT change
namespaces or deployment names. The hardcoding is intentional.

Report:
  - Whether the build succeeded
  - Whether the rollout completed
  - The number of ready pods after rollout
  - The route URL
  - Any errors or warnings (especially the "expected 1 ready pod" check)
  - The final ~50 lines of build output if anything failed
```

## Step 3: Verify the rollout actually happened (in main context)

Compare the post-deploy state against the baseline you captured in Step 1.C:

```bash
oc get pods -n memory-hub-mcp -l app.kubernetes.io/name=memory-hub-mcp
oc get deploy memory-hub-mcp -n memory-hub-mcp -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

The pod name MUST be different from the baseline pod name. If it is the same, the rollout did not pick up the new image — investigate before declaring success. The deploy script's `oc rollout restart` should prevent this, but verify.

If the rollout is sticky (same pod name, but you know the build succeeded), it is acceptable to delete the pod manually:

```bash
oc delete pod <old-pod-name> -n memory-hub-mcp
```

The Deployment will spin up a fresh one from the latest image. **Never delete the Deployment itself** without explicit user approval — there are several other services in the `memory-hub-mcp` namespace (notably `memoryhub-ui`) that must not be touched.

## Step 4: Verify deployed tools with mcp-test-mcp

```
connect_to_server name=memory-hub-mcp url=https://<route-host>/mcp/
list_tools server_name=memory-hub-mcp
```

Spot-check at least one tool that this deploy was supposed to fix. For full ergonomics verification, follow `memory-hub-mcp/.claude/commands/exercise-tools.md` rather than running ad-hoc tests here.

## Step 5: Report

Brief summary to the user:

- Whether deploy succeeded
- Old pod → new pod (proves fresh rollout)
- Route URL
- Which tools were spot-checked and the result
- Pointer to the next step (e.g. "ready for /exercise-tools" or "Wave 2 fixes verified")

## Important guidelines

- The namespace is `memory-hub-mcp` and the deployment is `memory-hub-mcp`. Both are hardcoded in `deploy/deploy.sh`. Do not override.
- There are other services in the `memory-hub-mcp` namespace (e.g. `memoryhub-ui`). Never use cluster-wide delete operations. Always scope to `app.kubernetes.io/name=memory-hub-mcp`.
- The `memoryhub` server-side package source lives at the **repo root** (`src/memoryhub/`), NOT in `sdk/src/memoryhub/`. The build context script copies the root one. See `docs/package-layout.md`.
- If the build fails because of import errors involving `memoryhub.services` or `memoryhub.storage`, you are probably editing `sdk/src/memoryhub/` instead of `src/memoryhub/`. See `docs/package-layout.md`.
- If `mcp-test-mcp` is not available, STOP and ask the user to enable it. Do not declare success without verifying the deployed tools.
