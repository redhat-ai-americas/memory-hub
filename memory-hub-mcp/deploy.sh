#!/bin/bash
# Simple deployment script for MCP server to OpenShift
# Usage: ./deploy.sh [project-name]

set -e

PROJECT=${1:-mcp-demo}

echo "========================================="
echo "MCP Server Deployment to OpenShift"
echo "========================================="
echo "Project: $PROJECT"
echo ""

# Check if logged in to OpenShift
if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Please run 'oc login' first."
    exit 1
fi

# Create project if it doesn't exist
echo "→ Setting up project..."
if oc project $PROJECT &>/dev/null; then
    echo "  Using existing project: $PROJECT"
else
    echo "  Creating new project: $PROJECT"
    oc new-project $PROJECT
fi

# Apply OpenShift resources
echo "→ Applying OpenShift resources..."
sed "s|image: mcp-server:latest|image: image-registry.openshift-image-registry.svc:5000/$PROJECT/mcp-server:latest|g" openshift.yaml | oc apply -f - -n $PROJECT

# Start build
echo "→ Building container image..."
echo "  Creating filtered build context..."

# Create a temporary directory for the build context
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy only necessary files (exclude __pycache__ and .pyc files)
cp Containerfile requirements.txt pyproject.toml "$BUILD_DIR/"

# Use rsync to copy src/ while excluding cache files
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' --exclude='.mypy_cache' src/ "$BUILD_DIR/src/"

# FIX: Claude Code's Write tool creates files with 600 permissions (owner-only).
# OpenShift containers run as arbitrary non-root UIDs that need at least 644.
# Fix permissions in the build directory before sending to OpenShift.
# Note: Containerfile also has this fix as a backup, but fixing here provides visibility.
FIXED_COUNT=$(find "$BUILD_DIR/src" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "  Fixing $FIXED_COUNT file(s) with 600 permissions (Claude Code Write tool issue)..."
    find "$BUILD_DIR/src" -name "*.py" -perm 600 -exec chmod 644 {} \;
fi

echo "  Starting binary build with filtered context..."
oc start-build mcp-server --from-dir="$BUILD_DIR" --follow -n $PROJECT

# Wait for rollout
echo "→ Deploying application..."
oc rollout restart deployment/mcp-server -n $PROJECT 2>/dev/null || true
oc rollout status deployment/mcp-server -n $PROJECT --timeout=300s

# Get route (host and path)
ROUTE_HOST=$(oc get route mcp-server -n $PROJECT -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
ROUTE_PATH=$(oc get route mcp-server -n $PROJECT -o jsonpath='{.spec.path}' 2>/dev/null || echo "/mcp/")

echo ""
echo "========================================="
echo "✅ Deployment Complete!"
echo "========================================="
if [ -n "$ROUTE_HOST" ]; then
    echo "MCP Server URL: https://${ROUTE_HOST}${ROUTE_PATH}"
    echo ""
    echo "Test with MCP Inspector:"
    echo "  npx @modelcontextprotocol/inspector https://${ROUTE_HOST}${ROUTE_PATH}"
else
    echo "Warning: Could not retrieve route URL"
fi
echo "========================================="