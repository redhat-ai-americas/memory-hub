#!/usr/bin/env bash
# Deploy the MemoryHub MCP server to OpenShift.
#
# Steps:
#   1. Prepare build context (MCP server + memoryhub-core library)
#   2. Create namespace if needed
#   3. Apply manifests (secret, imagestream, buildconfig, deployment, service, route)
#   4. Run a binary build from the staged context
#   5. Wait for deployment rollout
#   6. Print the route URL
set -euo pipefail

NAMESPACE="memory-hub-mcp"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== MemoryHub MCP Server Deployment ==="
echo "Namespace: $NAMESPACE"
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
oc apply -f "$SCRIPT_DIR/openshift.yaml" -n "$NAMESPACE"

# Step 4: Start binary build
echo ""
echo "Starting build..."
oc start-build memory-hub-mcp --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

# Step 5: Wait for deployment rollout
echo ""
echo "Waiting for rollout..."
oc rollout status deployment/memory-hub-mcp -n "$NAMESPACE" --timeout=120s

# Step 6: Print route URL
ROUTE=$(oc get route memory-hub-mcp -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "MCP endpoint: https://$ROUTE/mcp/"
    echo ""
    echo "Test with:"
    echo "  mcp-test-mcp connect https://$ROUTE/mcp/"
else
    echo "Warning: Could not retrieve route URL"
fi

# Cleanup build context
rm -rf "$BUILD_DIR"
