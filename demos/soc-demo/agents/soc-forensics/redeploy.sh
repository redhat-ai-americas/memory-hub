#!/usr/bin/env bash
# =============================================================================
# redeploy.sh — Force-redeploy the agent to OpenShift with a fresh image pull
# =============================================================================
# Usage: ./redeploy.sh <project-namespace> [image-tag]
#
# Prerequisites:
#   - oc CLI installed and logged in
#   - Container image already pushed to the registry before running this script
#   - Helm chart in chart/ directory
#
# This script is useful when OpenShift has cached an old image under the same
# tag (e.g. :latest). It sets imagePullPolicy=Always on the helm release and
# triggers a rollout restart so new pods pull the latest image from the registry.
# =============================================================================
set -euo pipefail

PROJECT="${1:?Usage: ./redeploy.sh <project-namespace> [image-tag]}"
IMAGE_TAG="${2:-latest}"

OC_CTX=""
HELM_CTX=""
if [ -n "${CONTEXT:-}" ]; then
    OC_CTX="--context=$CONTEXT"
    HELM_CTX="--kube-context=$CONTEXT"
fi

APP_NAME="$(basename "$(pwd)")"
CHART_DIR="chart"

# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

echo "NOTE: This script does not build or push images."
echo "  Ensure your image is already pushed before running:"
echo "    podman push \${IMAGE_NAME}:${IMAGE_TAG} quay.io/your-org/\${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if ! command -v oc &>/dev/null; then
    echo "Error: oc CLI not found. Install it from https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"
    exit 1
fi

if ! oc whoami $OC_CTX &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

if ! command -v helm &>/dev/null; then
    echo "Error: helm CLI not found. Install it from https://helm.sh/docs/intro/install/"
    exit 1
fi

if [ ! -f "$CHART_DIR/Chart.yaml" ]; then
    echo "Error: $CHART_DIR/Chart.yaml not found. Run this script from the agent project root."
    exit 1
fi

# Ensure the namespace exists (create if missing and user has permission)
if ! oc get namespace "$PROJECT" $OC_CTX &>/dev/null; then
    echo "Namespace '$PROJECT' not found. Creating..."
    oc new-project "$PROJECT" $OC_CTX || {
        echo "Error: Could not create namespace '$PROJECT'."
        exit 1
    }
fi

# ---------------------------------------------------------------------------
# Deploy with imagePullPolicy=Always
# ---------------------------------------------------------------------------

echo "Deploying '$APP_NAME' to namespace '$PROJECT' (image tag: $IMAGE_TAG)..."
helm upgrade --install "$APP_NAME" "$CHART_DIR" \
    -n "$PROJECT" $HELM_CTX \
    --set image.pullPolicy=Always \
    --set image.tag="$IMAGE_TAG" \
    --wait

# ---------------------------------------------------------------------------
# Force rollout restart so pods pull the fresh image
# ---------------------------------------------------------------------------

echo ""
echo "Triggering rollout restart to force fresh image pull..."
oc rollout restart deployment/"$APP_NAME" -n "$PROJECT" $OC_CTX

echo "Waiting for rollout to complete (timeout: 120s)..."
oc rollout status deployment/"$APP_NAME" -n "$PROJECT" $OC_CTX --timeout=120s

# ---------------------------------------------------------------------------
# Status summary
# ---------------------------------------------------------------------------

echo ""
echo "Pod status in '$PROJECT':"
oc get pods -n "$PROJECT" $OC_CTX

echo ""
echo "Recent logs from '$APP_NAME':"
oc logs deployment/"$APP_NAME" -n "$PROJECT" $OC_CTX --tail=20

echo ""
echo "Redeployment complete. Namespace: $PROJECT | Image tag: $IMAGE_TAG"
