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
#   1. Prepare build context (MCP server + memoryhub-core library)
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
# Apply configmap first — the Deployment mounts it as a volume.
oc apply -f "$SCRIPT_DIR/users-configmap.yaml" -n "$NAMESPACE"
oc apply -f "$SCRIPT_DIR/openshift.yaml" -n "$NAMESPACE"

# Step 4: Start binary build
echo ""
echo "Starting build..."
oc start-build "$DEPLOYMENT" --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

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
echo ""
echo "Verifying deployment state..."
DEPLOY_COUNT=$(oc get deploy -n "$NAMESPACE" \
    -l "app.kubernetes.io/name=$DEPLOYMENT" \
    -o name 2>/dev/null | wc -l | tr -d ' ')
if [ "$DEPLOY_COUNT" != "1" ]; then
    echo "WARNING: expected 1 Deployment named $DEPLOYMENT, found $DEPLOY_COUNT"
    oc get deploy -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
fi

AVAILABLE=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
DESIRED=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null)
if [ "$AVAILABLE" = "$DESIRED" ] && [ "$AVAILABLE" = "1" ]; then
    echo "OK: deployment at desired state (1 available replica)"
else
    echo "WARNING: deployment not at desired state (available=${AVAILABLE:-0}, desired=${DESIRED:-?})"
    oc get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
fi

# Step 8: Print route URL
ROUTE=$(oc get route "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "MCP endpoint: https://$ROUTE/mcp/"
    echo ""
    echo "Verify with mcp-test-mcp:"
    echo "  connect_to_server name=memory-hub-mcp url=https://$ROUTE/mcp/"
else
    echo "Warning: Could not retrieve route URL"
fi

# Cleanup build context
rm -rf "$BUILD_DIR"
