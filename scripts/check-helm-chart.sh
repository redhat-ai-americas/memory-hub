#!/usr/bin/env bash
# Lint, render, and compare the Helm chart with the existing install manifests.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="$REPO_ROOT/charts/memoryhub"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

for command in helm python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "ERROR: required command '$command' is not installed." >&2
        exit 1
    fi
done
if ! command -v kubectl >/dev/null 2>&1 && ! command -v kustomize >/dev/null 2>&1; then
    echo "ERROR: install kubectl with kustomize support, or install kustomize." >&2
    exit 1
fi

echo "Linting Helm chart..."
helm lint "$CHART_DIR" --strict

echo "Rendering default Kubernetes manifests..."
helm template memoryhub "$CHART_DIR" \
    --namespace memory-hub-mcp > "$TEMP_DIR/default.yaml"

echo "Rendering OpenShift manifests (Routes and SCC bindings)..."
helm template memoryhub "$CHART_DIR" \
    --namespace memory-hub-mcp \
    --api-versions route.openshift.io/v1/Route \
    --api-versions security.openshift.io/v1 \
    > "$TEMP_DIR/openshift.yaml"

echo "Rendering GPU model manifests for Kubernetes..."
helm template memoryhub "$CHART_DIR" \
    --namespace memory-hub-mcp \
    --set models.variant=gpu \
    > "$TEMP_DIR/gpu.yaml"

echo "Rendering OpenShift GPU model manifests..."
helm template memoryhub "$CHART_DIR" \
    --namespace memory-hub-mcp \
    --api-versions route.openshift.io/v1/Route \
    --api-versions security.openshift.io/v1 \
    --set models.variant=gpu \
    > "$TEMP_DIR/openshift-gpu.yaml"

echo "Comparing chart resources and workload settings with current manifests..."
python3 "$REPO_ROOT/scripts/check_helm_chart_alignment.py" \
    "$TEMP_DIR/default.yaml" "$TEMP_DIR/openshift.yaml" \
    "$TEMP_DIR/gpu.yaml" "$TEMP_DIR/openshift-gpu.yaml"
