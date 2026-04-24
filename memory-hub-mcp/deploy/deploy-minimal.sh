#!/usr/bin/env bash
# Deploy the minimal-profile MCP server instance for small model testing.
#
# This creates a SEPARATE deployment alongside the primary memory-hub-mcp.
# Same namespace, shared DB/Valkey/MinIO, but different name and route.
# Sets MEMORYHUB_TOOL_PROFILE=minimal (4 tools: register_session +
# search_memory + write_memory + read_memory).
set -euo pipefail

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memory-hub-mcp-minimal"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== MemoryHub MCP Server (minimal profile) ==="
echo "Namespace:  $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo "Profile:    minimal (4 tools)"
echo ""

if ! oc whoami --context mcp-rhoai &>/dev/null; then
    echo "Error: Not logged in to mcp-rhoai context."
    exit 1
fi

CTX="--context mcp-rhoai"

# Prepare build context (reuses the same script as primary deploy)
"$SCRIPT_DIR/build-context.sh"
BUILD_DIR="$PROJECT_ROOT/.build-context"

# Apply minimal-profile manifests
echo ""
echo "Applying minimal-profile manifests..."
oc apply -f "$SCRIPT_DIR/openshift-minimal.yaml" -n "$NAMESPACE" $CTX

# Build
echo ""
echo "Starting build..."
oc start-build "$DEPLOYMENT" --from-dir="$BUILD_DIR" -n "$NAMESPACE" $CTX --follow

# Re-apply to re-resolve image digest
echo ""
echo "Re-applying manifest to re-resolve image digest..."
oc apply -f "$SCRIPT_DIR/openshift-minimal.yaml" -n "$NAMESPACE" $CTX

# Rollout
echo ""
echo "Restarting rollout..."
oc rollout restart "deployment/$DEPLOYMENT" -n "$NAMESPACE" $CTX

echo ""
echo "Waiting for rollout..."
oc rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE" $CTX --timeout=300s

# Verify
echo ""
echo "Verifying deployment..."
AVAILABLE=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" $CTX \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
if [ "$AVAILABLE" = "1" ]; then
    echo "OK: 1 available replica"
else
    echo "WARNING: available=${AVAILABLE:-0}"
    oc get pods -n "$NAMESPACE" $CTX -l "app.kubernetes.io/name=$DEPLOYMENT"
fi

# Route
ROUTE=$(oc get route "$DEPLOYMENT" -n "$NAMESPACE" $CTX \
    -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "MCP endpoint: https://$ROUTE/mcp/"
    echo ""
    echo "Verify with mcp-test-mcp:"
    echo "  connect_to_server name=mcp-minimal url=https://$ROUTE/mcp/"
    echo "  list_tools server_name=mcp-minimal"
    echo ""
    echo "Expected: 4 tools (register_session, search_memory, write_memory, read_memory)"
else
    echo "ERROR: Could not retrieve route URL"
    exit 1
fi

rm -rf "$BUILD_DIR"
