#!/usr/bin/env bash
# Deploy the MemoryHub UI to OpenShift.
#
# Conforms to docs/build-deploy-hardening.md (#88).
#
# Steps:
#   1. Prepare build context (frontend + backend + memoryhub_core)
#   2. Ensure namespace exists
#   3. Apply manifests (imagestream, buildconfig, deployment, service, route)
#   4. Run binary build from the staged context
#   5. Re-apply manifest to re-resolve the imagestream tag against the
#      just-pushed digest (resolve-names rewrites at apply time, not pod
#      creation time -- see retro #18)
#   6. Force rollout restart so the new digest takes effect even when the
#      manifest is byte-identical
#   7. Wait for rollout
#   8. Verify the running pod is on the just-pushed digest (fail if not)
#   9. Print the route URL
set -euo pipefail

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memoryhub-ui"
IMAGESTREAM="memoryhub-ui"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== MemoryHub UI Deployment ==="
echo "Namespace: $NAMESPACE"
echo ""

# Check OpenShift login
if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

# Step 1: Prepare build context
"$SCRIPT_DIR/build-context.sh"
BUILD_DIR="$PROJECT_ROOT/.build-context"

# Step 2: Ensure namespace exists
if oc get namespace "$NAMESPACE" &>/dev/null; then
    echo "Using existing namespace: $NAMESPACE"
else
    echo "Creating namespace: $NAMESPACE"
    oc create namespace "$NAMESPACE"
fi

# Step 3: Apply manifests
echo ""
echo "Applying manifests..."
oc apply -f "$PROJECT_ROOT/openshift.yaml" -n "$NAMESPACE"

# Step 4: Start binary build
echo ""
echo "Starting build..."
oc start-build "$IMAGESTREAM" --from-dir="$BUILD_DIR" -n "$NAMESPACE" --follow

# Step 5: Re-apply manifest to re-resolve the :latest imagestream tag
# against the digest the build just pushed. The Deployment carries
# `alpha.image.policy.openshift.io/resolve-names: '*'`, which rewrites the
# tag to a concrete digest at apply time and never re-resolves on its own.
# Without this re-apply, the next rollout restart would spin up a pod on
# the digest :latest pointed at *before* the build (retro #18 / #83 / #88).
echo ""
echo "Re-applying manifest to re-resolve image digest..."
oc apply -f "$PROJECT_ROOT/openshift.yaml" -n "$NAMESPACE"

# Step 5b: Populate the public-facing route URLs used by the Client
# Management welcome-email renderer. The openshift.yaml manifest ships
# with example.com placeholders so the UI renders an obviously wrong URL
# if this step is skipped; real values come from the actual cluster Routes.
# Idempotent — re-running the deploy against a rebuilt sandbox updates the
# env vars to the new Route hostnames automatically.
echo ""
echo "Populating public Route URLs for the welcome-email feature..."
MCP_ROUTE_HOST=$(oc get route memory-hub-mcp -n memory-hub-mcp -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
AUTH_ROUTE_HOST=$(oc get route auth-server -n memoryhub-auth -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
EMBEDDING_SVC_HOST=$(oc get svc all-minilm-l6-v2 -n embedding-model -o jsonpath='{.metadata.name}.{.metadata.namespace}.svc.cluster.local' 2>/dev/null || echo "")
if [ -n "$MCP_ROUTE_HOST" ] && [ -n "$AUTH_ROUTE_HOST" ]; then
    MCP_PUBLIC_URL="https://$MCP_ROUTE_HOST/mcp/"
    AUTH_PUBLIC_URL="https://$AUTH_ROUTE_HOST"
    echo "  MEMORYHUB_PUBLIC_MCP_URL=$MCP_PUBLIC_URL"
    echo "  MEMORYHUB_PUBLIC_AUTH_URL=$AUTH_PUBLIC_URL"
    ENV_ARGS=(
        "MEMORYHUB_PUBLIC_MCP_URL=$MCP_PUBLIC_URL"
        "MEMORYHUB_PUBLIC_AUTH_URL=$AUTH_PUBLIC_URL"
    )
    if [ -n "$EMBEDDING_SVC_HOST" ]; then
        EMBEDDING_URL="http://$EMBEDDING_SVC_HOST:80"
        echo "  MEMORYHUB_EMBEDDING_URL=$EMBEDDING_URL"
        ENV_ARGS+=("MEMORYHUB_EMBEDDING_URL=$EMBEDDING_URL")
    else
        echo "  WARNING: embedding service not found in embedding-model namespace"
        echo "  Search will fall back to text matching until the service is deployed."
    fi
    oc set env "deployment/$DEPLOYMENT" -n "$NAMESPACE" \
        "${ENV_ARGS[@]}" \
        --containers="$DEPLOYMENT" >/dev/null
    echo "  Env vars applied to deployment/$DEPLOYMENT."
else
    echo "  WARNING: could not resolve mcp-server or auth-server Route host."
    echo "  MCP:  ${MCP_ROUTE_HOST:-<missing>}"
    echo "  Auth: ${AUTH_ROUTE_HOST:-<missing>}"
    echo "  The welcome-email feature will render example.com placeholder URLs"
    echo "  until the routes exist. Re-run this script after mcp-server and"
    echo "  auth-server are deployed."
fi

# Step 6: Force rollout restart so the new image digest is picked up.
echo ""
echo "Restarting rollout..."
oc rollout restart "deployment/$DEPLOYMENT" -n "$NAMESPACE"

# Step 7: Wait for rollout
echo ""
echo "Waiting for rollout..."
oc rollout status "deployment/$DEPLOYMENT" -n "$NAMESPACE" --timeout=300s

# Step 8: Verify the running pod is on the just-pushed digest.
# The Deployment spec carries the resolved digest after re-apply; the
# imagestream's :latest tag carries the canonical "what was just pushed"
# digest. They MUST match. If they don't, the build pushed but the
# Deployment is still pinned to an older digest, which is exactly the
# failure family #88 closes.
echo ""
echo "Verifying running digest matches imagestream :latest..."
RUNNING=$(oc get deploy "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="memoryhub-ui")].image}' 2>/dev/null || echo "")
LATEST_DIGEST=$(oc get is "$IMAGESTREAM" -n "$NAMESPACE" \
    -o jsonpath='{.status.tags[?(@.tag=="latest")].items[0].image}' 2>/dev/null || echo "")
echo "  Running: $RUNNING"
echo "  Latest:  $LATEST_DIGEST"
if [ -z "$RUNNING" ] || [ -z "$LATEST_DIGEST" ]; then
    echo "ERROR: could not resolve running image or imagestream :latest digest"
    exit 1
fi
# RUNNING is `<registry>/<ns>/<is>@sha256:...` after resolve-names; extract
# the sha256 and compare to LATEST_DIGEST (which is the bare sha256:... id).
RUNNING_DIGEST="${RUNNING##*@}"
if [ "$RUNNING_DIGEST" != "$LATEST_DIGEST" ]; then
    echo "ERROR: running digest does not match imagestream :latest"
    echo "  This is the #88 failure family -- the build pushed but the"
    echo "  Deployment is on an older digest. Investigate before retrying."
    exit 1
fi
echo "  OK: running digest matches imagestream :latest"

# Step 9: Print route URL
ROUTE=$(oc get route "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "Dashboard URL: https://$ROUTE/"
    echo ""
    echo "To register the RHOAI tile:"
    echo "  oc apply -f $PROJECT_ROOT/openshift/odh-application.yaml"
else
    echo "Warning: Could not retrieve route URL"
fi

# Cleanup build context
rm -rf "$BUILD_DIR"
