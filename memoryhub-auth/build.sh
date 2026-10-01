#!/usr/bin/env bash
# Build the MemoryHub auth image without changing the Deployment.
set -euo pipefail

PROJECT="${1:-memoryhub-auth}"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! oc whoami --context "$CONTEXT" &>/dev/null; then
    echo "Error: Not logged in to OpenShift."
    exit 1
fi
if ! oc get namespace --context "$CONTEXT" "$PROJECT" &>/dev/null; then
    oc create namespace --context "$CONTEXT" "$PROJECT"
fi

oc apply --context "$CONTEXT" -f "$SCRIPT_DIR/buildconfig.yaml" -n "$PROJECT"

BUILD_DIR=$(mktemp -d)
trap 'rm -rf "$BUILD_DIR"' EXIT
cp "$SCRIPT_DIR/Containerfile" "$SCRIPT_DIR/requirements.txt" "$BUILD_DIR/"
cp "$SCRIPT_DIR/conftest.py" "$BUILD_DIR/" 2>/dev/null || true
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    --exclude='.mypy_cache' "$SCRIPT_DIR/src/" "$BUILD_DIR/src/"

FIXED_COUNT=$(find "$BUILD_DIR" -name '*.py' -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt 0 ]; then
    find "$BUILD_DIR" -name '*.py' -perm 600 -exec chmod 644 {} \;
fi

echo "Starting OpenShift auth build..."
oc start-build --context "$CONTEXT" auth-server \
    --from-dir="$BUILD_DIR" --follow -n "$PROJECT"
echo "Auth image build complete; no deployment was changed."
