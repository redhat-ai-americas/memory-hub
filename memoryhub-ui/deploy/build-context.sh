#!/usr/bin/env bash
# Prepare build context for the MemoryHub UI container.
#
# The Containerfile expects:
#   - frontend/          (React app source for the Node build stage)
#   - backend/           (FastAPI BFF source)
#   - memoryhub_core/    (shared SQLAlchemy models library)
#
# This script stages everything into .build-context/ for `oc start-build --from-dir`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PROJECT_ROOT/.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/.build-context"

echo "Preparing build context..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Copy Containerfile
cp "$PROJECT_ROOT/Containerfile" "$BUILD_DIR/"
cp "$PROJECT_ROOT/.dockerignore" "$BUILD_DIR/" 2>/dev/null || true

# Copy frontend source
mkdir -p "$BUILD_DIR/frontend/src"
cp "$PROJECT_ROOT/frontend/package.json" "$BUILD_DIR/frontend/"
cp "$PROJECT_ROOT/frontend/package-lock.json" "$BUILD_DIR/frontend/" 2>/dev/null || true
cp "$PROJECT_ROOT/frontend/tsconfig.json" "$BUILD_DIR/frontend/"
cp "$PROJECT_ROOT/frontend/tsconfig.node.json" "$BUILD_DIR/frontend/" 2>/dev/null || true
cp "$PROJECT_ROOT/frontend/vite.config.ts" "$BUILD_DIR/frontend/"
cp "$PROJECT_ROOT/frontend/index.html" "$BUILD_DIR/frontend/"
rsync -a --exclude='__pycache__' --exclude='node_modules' --exclude='dist' \
    "$PROJECT_ROOT/frontend/src/" "$BUILD_DIR/frontend/src/"
[ -d "$PROJECT_ROOT/frontend/public" ] && rsync -a "$PROJECT_ROOT/frontend/public/" "$BUILD_DIR/frontend/public/"

# Copy backend source
mkdir -p "$BUILD_DIR/backend"
cp "$PROJECT_ROOT/backend/requirements.txt" "$BUILD_DIR/backend/"
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' \
    --exclude='.mypy_cache' "$PROJECT_ROOT/backend/src/" "$BUILD_DIR/backend/src/"

# Copy memoryhub_core library (same pattern as MCP server). Previously
# this script staged to memoryhub-core/ while the Containerfile read from
# memoryhub/ -- a real bug fixed during the #55 rename.
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
find "$BUILD_DIR" -type f | sort | head -60
