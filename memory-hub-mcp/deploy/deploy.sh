#!/usr/bin/env bash
# Deploy the MemoryHub MCP server to OpenShift.
#
# This script is the single canonical deploy path for memory-hub-mcp.
# The namespace is hardcoded to "memory-hub-mcp" intentionally — past
# incidents with template-default namespaces ("mcp-demo") created duplicate
# deployments in the wrong place. Do not parameterize this without reading
# docs/admin and the retros first.
#
# Steps:
#   1. Prepare build context (MCP server + memoryhub_core library)
#   2. Create namespace if needed
#   3. Apply manifests (configmap, secret, imagestream, buildconfig,
#      deployment, service, route)
#   4. Run a binary build from the staged context
#   5. Force a rollout restart (the new image has the same :latest tag,
#      so without an explicit restart Kubernetes will not always pick up
#      the new digest — this has bitten us repeatedly)
#   6. Wait for deployment rollout
#   7. Verify exactly one ready pod
#   8. Print the route URL
set -euo pipefail

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memory-hub-mcp"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== MemoryHub MCP Server Deployment ==="
echo "Namespace:  $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo ""

# Check OpenShift login
if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

# Step 0: Preflight — tool registration sanity check.
#
# main.py uses static tool registration (the dynamic loader is not used —
# see memory-hub-mcp/CLAUDE.md for the history). Every tool file in
# src/tools/ must be both imported AND added to the mcp.add_tool list.
# Forgetting either is a silent failure: the file deploys but the tool
# does not appear in list_tools, with no error in the pod logs. This
# bit us during the delete_memory work (see retrospectives/
# 2026-04-06_memory-deletion-cli-client/RETRO.md).
#
# Catch it before building, not after deploying.
echo ""
echo "Preflight: tool registration check..."
TOOLS_DIR="$PROJECT_ROOT/src/tools" \
MAIN_PY="$PROJECT_ROOT/src/main.py" \
python3 - <<'PYEOF' || exit 1
import os, re, sys

main_py = os.environ["MAIN_PY"]
tools_dir = os.environ["TOOLS_DIR"]

with open(main_py) as f:
    src = f.read()

# Files in src/tools/ that are tool implementations (exclude __init__,
# private/dunder modules, and the known auth helper utility module).
NON_TOOL_FILES = {"auth.py"}
files = {
    f[:-3]
    for f in os.listdir(tools_dir)
    if f.endswith(".py") and not f.startswith("_") and f not in NON_TOOL_FILES
}

# Tools imported into main.py via `from src.tools.NAME import NAME`.
imports = set(re.findall(r"^from src\.tools\.([a-z_][a-z_0-9]*) import", src, re.M))

# Tools actually registered via the `for tool_fn in [...]:` loop.
loop = re.search(r"for tool_fn in \[(.*?)\]:", src, re.DOTALL)
if not loop:
    sys.exit("ERROR: could not find `for tool_fn in [...]:` loop in src/main.py")
registered = set(re.findall(r"[a-z_][a-z_0-9]*", loop.group(1)))

errors = []
missing_imports = files - imports
if missing_imports:
    errors.append(f"  files NOT imported in main.py: {sorted(missing_imports)}")
extra_imports = imports - files
if extra_imports:
    errors.append(f"  imports without a corresponding file: {sorted(extra_imports)}")
missing_reg = files - registered
if missing_reg:
    errors.append(f"  files NOT in the mcp.add_tool list: {sorted(missing_reg)}")

if errors:
    print("ERROR: tool registration mismatch in src/main.py")
    for line in errors:
        print(line)
    print()
    print("The MCP server uses static tool registration. Every file in")
    print("src/tools/ must be imported AND added to the mcp.add_tool list")
    print("in src/main.py. See memory-hub-mcp/CLAUDE.md (Adding a new tool).")
    sys.exit(1)

print(f"OK: {len(files)} tools registered")
PYEOF

# Step 1: Prepare build context
"$SCRIPT_DIR/build-context.sh"
BUILD_DIR="$PROJECT_ROOT/.build-context"

# Step 2: Create namespace
if oc get namespace "$NAMESPACE" &>/dev/null; then
    echo "Using existing namespace: $NAMESPACE"
else
    echo "Creating namespace: $NAMESPACE"
    oc create namespace "$NAMESPACE"
fi

# Step 3: Apply manifests
echo ""
echo "Applying manifests..."
# users-configmap.yaml is per-operator and gitignored; it holds real api_keys.
# Refuse to proceed if the operator hasn't copied the example template yet or
# if the copy still contains the placeholder strings.
USERS_CM="$SCRIPT_DIR/users-configmap.yaml"
if [[ ! -f "$USERS_CM" ]]; then
  echo "ERROR: $USERS_CM not found."
  echo "       Copy the template and replace the placeholder api_keys:"
  echo "         cp $SCRIPT_DIR/users-configmap.example.yaml $USERS_CM"
  echo "         \$EDITOR $USERS_CM"
  exit 1
fi
if grep -q "REPLACE-ME-" "$USERS_CM"; then
  echo "ERROR: $USERS_CM still contains REPLACE-ME placeholders."
  echo "       Generate real api_keys (e.g. \`openssl rand -hex 16\`) and"
  echo "       replace them before running deploy.sh."
  exit 1
fi
# Apply configmap first — the Deployment mounts it as a volume.
oc apply -f "$USERS_CM" -n "$NAMESPACE"

# openshift.yaml has a placeholder PG password. Refuse to apply it verbatim;
# the operator must have replaced REPLACE-ME-match-the-postgres-secret with
# the real PG password (or use a separate Secret and edit this file).
if grep -q "REPLACE-ME-match-the-postgres-secret" "$SCRIPT_DIR/openshift.yaml"; then
  echo "ERROR: $SCRIPT_DIR/openshift.yaml still contains the REPLACE-ME"
  echo "       PG password placeholder. Replace it with the actual value"
  echo "       from deploy/postgresql/secret.yaml before running deploy.sh."
  exit 1
fi
oc apply -f "$SCRIPT_DIR/openshift.yaml" -n "$NAMESPACE"

# Step 4: Start binary build
echo ""
echo "Starting build..."
oc start-build "$DEPLOYMENT" --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

# Step 4.5: Re-resolve the :latest ImageStream tag.
#
# The Deployment uses `image: memory-hub-mcp:latest` and the
# `alpha.image.policy.openshift.io/resolve-names` annotation. That annotation
# resolves the tag to a concrete digest *at apply time*, not at pod creation
# time. Step 3 applied the manifest before the build, so the Deployment is
# currently pinned to whatever digest :latest pointed at *before* this build.
# Re-applying after the build re-resolves :latest to the digest we just pushed.
#
# Without this step, `oc rollout restart` below will spin up a new pod from
# the OLD digest, even though the build just pushed new code. We hit this
# during the 2026-04-07 Wave 2 deploy (4th retro to flag a deploy/image-cache
# failure family) — the fix is documented in the wave1-4-mcp-fixes retro.
echo ""
echo "Re-applying manifest to re-resolve image digest..."
oc apply -f "$SCRIPT_DIR/openshift.yaml" -n "$NAMESPACE"

# Step 5: Force rollout restart so the new image digest is picked up
echo ""
echo "Restarting rollout..."
oc rollout restart "deployment/$DEPLOYMENT" -n "$NAMESPACE"

# Step 6: Wait for rollout
echo ""
echo "Waiting for rollout..."
oc rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE" --timeout=300s

# Step 7: Verify single Deployment + one available replica.
# Counting Running pods directly is unreliable: terminating pods stay in
# Running phase until they exit, so right after a rollout you briefly see
# 2 Running pods (new + terminating old). Check the Deployment status
# instead — that's the source of truth for "is the desired state met".
#
# These are HARD failures, not warnings (#88). A deploy script that exits
# 0 with a degraded deployment is exactly the failure family this issue
# closes.
echo ""
echo "Verifying deployment state..."
DEPLOY_COUNT=$(oc get deploy -n "$NAMESPACE" \
    -l "app.kubernetes.io/name=$DEPLOYMENT" \
    -o name 2>/dev/null | wc -l | tr -d ' ')
if [ "$DEPLOY_COUNT" != "1" ]; then
    echo "ERROR: expected 1 Deployment named $DEPLOYMENT, found $DEPLOY_COUNT"
    oc get deploy -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
    exit 1
fi

AVAILABLE=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
DESIRED=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null)
if [ "$AVAILABLE" = "$DESIRED" ] && [ "$AVAILABLE" = "1" ]; then
    echo "OK: deployment at desired state (1 available replica)"
else
    echo "ERROR: deployment not at desired state (available=${AVAILABLE:-0}, desired=${DESIRED:-?})"
    oc get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
    exit 1
fi

# Step 7.5: Verify the running pod is on the just-pushed digest (#88).
# The Deployment spec carries the resolved digest after re-apply; the
# imagestream's :latest tag carries the canonical "what was just pushed"
# digest. They MUST match. If they don't, the build pushed but the
# Deployment is still pinned to an older digest, which is exactly the
# failure family this verification closes.
echo ""
echo "Verifying running digest matches imagestream :latest..."
RUNNING=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="mcp-server")].image}' 2>/dev/null || echo "")
LATEST_DIGEST=$(oc get is "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.tags[?(@.tag=="latest")].items[0].image}' 2>/dev/null || echo "")
echo "  Running: $RUNNING"
echo "  Latest:  $LATEST_DIGEST"
if [ -z "$RUNNING" ] || [ -z "$LATEST_DIGEST" ]; then
    echo "ERROR: could not resolve running image or imagestream :latest digest"
    exit 1
fi
RUNNING_DIGEST="${RUNNING##*@}"
if [ "$RUNNING_DIGEST" != "$LATEST_DIGEST" ]; then
    echo "ERROR: running digest does not match imagestream :latest"
    echo "  This is the #88 failure family -- the build pushed but the"
    echo "  Deployment is on an older digest. Investigate before retrying."
    exit 1
fi
echo "  OK: running digest matches imagestream :latest"

# Step 8: Print route URL.
#
# Tool-count regression check is performed OUT-OF-BAND by the operator
# via mcp-test-mcp after this script completes. mcp-test-mcp is itself an
# MCP server (not a CLI), so the deploy script can't shell out to it.
# The /deploy-mcp slash command's Step 4 ("Verify deployed tools with
# mcp-test-mcp") is the operator-side equivalent and MUST be run after
# every memory-hub-mcp deploy.
#
# The static preflight at Step 0 above catches the registration silent-
# failure class (file present but not imported / not in mcp.add_tool list)
# before the build runs. Runtime issues that the static check can't see
# (build context missing files, runtime decoration errors, dependency
# import failures) are what the post-deploy mcp-test-mcp check catches.
ROUTE=$(oc get route "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "MCP endpoint: https://$ROUTE/mcp/"
    echo ""
    echo "REQUIRED next step -- verify deployed tools with mcp-test-mcp:"
    echo "  connect_to_server name=memory-hub-mcp url=https://$ROUTE/mcp/"
    echo "  list_tools server_name=memory-hub-mcp"
    echo ""
    echo "Without this check, runtime tool-registration failures (build"
    echo "context missing files, decoration errors, etc.) will not be caught."
else
    echo "ERROR: Could not retrieve route URL"
    exit 1
fi

# Cleanup build context
rm -rf "$BUILD_DIR"
