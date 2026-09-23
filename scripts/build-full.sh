#!/usr/bin/env bash
# Build all MemoryHub application images without changing Deployments.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
export MEMORYHUB_CONTEXT="$CONTEXT"

echo "MemoryHub — Application Image Builds"
echo "Context: $CONTEXT"

bash "$REPO_ROOT/memory-hub-mcp/deploy/build.sh"
bash "$REPO_ROOT/memoryhub-auth/build.sh" memoryhub-auth
bash "$REPO_ROOT/memoryhub-ui/deploy/build.sh"

echo "All application image builds completed. No deployments were changed."
