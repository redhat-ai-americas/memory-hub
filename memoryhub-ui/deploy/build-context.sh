#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/.build-context"
rm -rf "$OUT"
mkdir -p "$OUT/frontend"
cp "$ROOT/Containerfile" "$ROOT/server.mjs" "$OUT/"
cp "$ROOT/frontend/package.json" "$ROOT/frontend/package-lock.json" "$ROOT/frontend/index.html" "$ROOT/frontend/tsconfig.json" "$ROOT/frontend/tsconfig.node.json" "$ROOT/frontend/vite.config.ts" "$OUT/frontend/"
rsync -a --exclude=node_modules --exclude=dist "$ROOT/frontend/src/" "$OUT/frontend/src/"
echo "$OUT"
