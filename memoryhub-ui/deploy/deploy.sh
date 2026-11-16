#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE="${MEMORYHUB_UI_NAMESPACE:-memoryhub-ui}"
oc apply -n "$NAMESPACE" -f "$ROOT/openshift.yaml"
oc rollout restart deployment/memoryhub-ui -n "$NAMESPACE"
oc rollout status deployment/memoryhub-ui -n "$NAMESPACE" --timeout=300s
oc get route memoryhub-ui -n "$NAMESPACE" -o jsonpath='https://{.spec.host}/'
echo
