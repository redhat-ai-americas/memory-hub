#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE="${MEMORYHUB_UI_NAMESPACE:-memoryhub-ui}"
oc get namespace "$NAMESPACE" >/dev/null 2>&1 || oc create namespace "$NAMESPACE"
oc apply -n "$NAMESPACE" -f "$ROOT/openshift-build.yaml"
"$ROOT/deploy/build-context.sh"
trap 'rm -rf "$ROOT/.build-context"' EXIT
oc start-build memoryhub-ui -n "$NAMESPACE" --from-dir="$ROOT/.build-context" --follow
