#!/usr/bin/env bash
# Build the MemoryHub UI image without changing the Deployment.
set -euo pipefail

NAMESPACE="${MEMORYHUB_UI_NAMESPACE:-memoryhub-ui}"
IMAGESTREAM="memoryhub-ui"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! oc whoami --context "$CONTEXT" &>/dev/null; then
    echo "Error: Not logged in to OpenShift."
    exit 1
fi
if ! oc get namespace --context "$CONTEXT" "$NAMESPACE" &>/dev/null; then
    oc create namespace --context "$CONTEXT" "$NAMESPACE"
fi

oc apply --context "$CONTEXT" -f "$PROJECT_ROOT/openshift-build.yaml" -n "$NAMESPACE"
"$SCRIPT_DIR/build-context.sh"
BUILD_DIR="$PROJECT_ROOT/.build-context"
trap 'rm -rf "$BUILD_DIR"' EXIT

latest_ui_build() {
    oc get builds --context "$CONTEXT" -n "$NAMESPACE" -o json \
        | python3 -c '
import json,sys
items=json.load(sys.stdin).get("items", [])
items=[item for item in items if item.get("metadata", {}).get("name", "").startswith("memoryhub-ui-")]
items.sort(key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""))
print(items[-1]["metadata"]["name"] if items else "")
'
}

PREVIOUS_BUILD_NAME=$(latest_ui_build)
echo "Starting OpenShift UI build..."
oc start-build --context "$CONTEXT" "$IMAGESTREAM" \
    --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

# `oc start-build --follow` can return success even when the server-side build
# log contains a failed step. Check the Build resource itself before reporting
# success so the parent build/install workflow stops on a failed UI image.
BUILD_NAME=$(latest_ui_build)
if [[ -z "$BUILD_NAME" ]]; then
    echo "ERROR: could not find the UI Build resource after start-build." >&2
    exit 1
fi
if [[ "$BUILD_NAME" == "$PREVIOUS_BUILD_NAME" ]]; then
    echo "ERROR: start-build did not create a new UI Build resource." >&2
    exit 1
fi

BUILD_PHASE=$(oc get build "$BUILD_NAME" --context "$CONTEXT" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
if [[ "$BUILD_PHASE" != "Complete" ]]; then
    echo "ERROR: UI image build $BUILD_NAME ended in phase '${BUILD_PHASE:-unknown}', not Complete." >&2
    echo "Inspect it with: oc describe build $BUILD_NAME --context $CONTEXT -n $NAMESPACE" >&2
    exit 1
fi
echo "UI image build complete; no deployment was changed."
