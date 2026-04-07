#!/usr/bin/env bash
# Prepare build context for the MCP server container.
#
# The Containerfile expects a memoryhub_core/ directory alongside the MCP
# server source. This script stages both into a temporary .build-context/
# directory so that `oc start-build --from-dir` has everything it needs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build-context"

echo "Preparing build context..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Copy MCP server files
cp "$PROJECT_ROOT/Containerfile" "$BUILD_DIR/"
cp "$PROJECT_ROOT/requirements.txt" "$BUILD_DIR/"
cp "$PROJECT_ROOT/conftest.py" "$BUILD_DIR/"
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    --exclude='.mypy_cache' "$PROJECT_ROOT/src/" "$BUILD_DIR/src/"

# Copy memoryhub_core library (needed by Containerfile COPY memoryhub_core/)
mkdir -p "$BUILD_DIR/memoryhub_core/src"
cp "$REPO_ROOT/pyproject.toml" "$BUILD_DIR/memoryhub_core/"
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    "$REPO_ROOT/src/memoryhub_core/" "$BUILD_DIR/memoryhub_core/src/memoryhub_core/"

# Fix permissions — Claude Code Write tool creates 600; OpenShift needs 644
FIXED_COUNT=$(find "$BUILD_DIR" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
find "$BUILD_DIR" -name "*.py" -exec chmod 644 {} \;
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "  Fixed $FIXED_COUNT file(s) with 600 permissions"
fi

echo "Build context ready at $BUILD_DIR"
echo "Files:"
find "$BUILD_DIR" -type f | sort | head -40
