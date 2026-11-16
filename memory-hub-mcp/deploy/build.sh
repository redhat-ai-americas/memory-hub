#!/usr/bin/env bash
# Build the MemoryHub MCP server image without changing the Deployment.
set -euo pipefail

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memory-hub-mcp"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! oc whoami --context "$CONTEXT" &>/dev/null; then
    echo "Error: Not logged in to OpenShift."
    exit 1
fi

echo "=== Building MemoryHub MCP server ==="

if ! oc get namespace --context "$CONTEXT" "$NAMESPACE" &>/dev/null; then
    oc create namespace --context "$CONTEXT" "$NAMESPACE"
fi
oc apply --context "$CONTEXT" -f "$SCRIPT_DIR/buildconfig.yaml" -n "$NAMESPACE"

"$SCRIPT_DIR/build-context.sh"
BUILD_DIR="$PROJECT_ROOT/.build-context"
trap 'rm -rf "$BUILD_DIR"' EXIT

echo "Starting OpenShift build..."
oc start-build --context "$CONTEXT" "$DEPLOYMENT" \
    --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

echo "MCP image build complete; no deployment was changed."
