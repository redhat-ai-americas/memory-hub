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

# Catch static tool-registration errors before spending time on an image build.
echo "Preflight: tool registration check..."
TOOLS_DIR="$PROJECT_ROOT/src/tools" \
MAIN_PY="$PROJECT_ROOT/src/main.py" \
python3 - <<'PYEOF'
import os
import re
import sys

main_py = os.environ["MAIN_PY"]
tools_dir = os.environ["TOOLS_DIR"]

non_tool_files = {"auth.py", "backfill_entities.py"}
files = {
    f[:-3]
    for f in os.listdir(tools_dir)
    if f.endswith(".py") and not f.startswith("_") and f not in non_tool_files
}

with open(main_py) as f:
    source = f.read()

imports = set(re.findall(r"^from src\.tools\.([a-z_][a-z_0-9]*) import", source, re.M))
loop = re.search(r"for tool_fn in \[(.*?)\]:", source, re.DOTALL)
profile_lists = re.findall(r"_TOOLS_\w+\s*=\s*\[(.*?)\]", source, re.DOTALL)
if not loop and not profile_lists:
    raise SystemExit("ERROR: could not find tool registration list(s) in src/main.py")
registered_text = (loop.group(1) if loop else "") + " ".join(profile_lists)
registered = set(re.findall(r"[a-z_][a-z_0-9]*", registered_text))

errors = []
if files - imports:
    errors.append(f"files NOT imported: {sorted(files - imports)}")
if imports - files:
    errors.append(f"imports without files: {sorted(imports - files)}")
if files - registered:
    errors.append(f"files NOT registered: {sorted(files - registered)}")
if errors:
    print("ERROR: tool registration mismatch in src/main.py")
    print("\n".join(errors))
    raise SystemExit(1)
print(f"OK: {len(files)} tools registered")
PYEOF

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
