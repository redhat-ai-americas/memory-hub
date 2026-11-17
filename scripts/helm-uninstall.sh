#!/usr/bin/env bash
# Remove a MemoryHub Helm installation from an OpenShift cluster.
# PostgreSQL and MinIO PVCs are retained by default (retainPvcOnUninstall=true
# in the chart). External resources created by helm-install.sh — the
# OpenShift OAuthClient and the optional RHOAI tile proxy — are removed here
# because Helm does not manage them.
set -euo pipefail

CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
RELEASE="${MEMORYHUB_HELM_RELEASE:-memoryhub}"
NAMESPACE="${MEMORYHUB_HELM_NAMESPACE:-memory-hub-mcp}"
YES=false
DELETE_NAMESPACES=false

usage() {
    cat <<'EOF'
Usage: make helm-uninstall [ARGS="--yes"] [ARGS="--delete-namespaces --yes"]

Options:
  --context <ctx>      OpenShift context (default: mcp-rhoai)
  --release <name>     Helm release name (default: memoryhub)
  --namespace <ns>     Release namespace (default: memory-hub-mcp)
  --yes, -y            Skip confirmation prompt
  --delete-namespaces  Also delete all MemoryHub namespaces and their PVCs (see below)

Environment (overridden by flags):
  MEMORYHUB_CONTEXT        OpenShift context
  MEMORYHUB_HELM_RELEASE   Helm release name
  MEMORYHUB_HELM_NAMESPACE Release namespace

Removes the MemoryHub Helm release and cleans up the OpenShift OAuthClient
and optional RHOAI dashboard tile that helm-install.sh created outside Helm.
PostgreSQL and MinIO data PVCs are retained by default.

--delete-namespaces  Also delete all MemoryHub namespaces and their PVCs.
                     WARNING: this destroys all stored data permanently.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --context)
            CONTEXT="${2:?--context requires a value}"
            shift 2
            ;;
        --release)
            RELEASE="${2:?--release requires a value}"
            shift 2
            ;;
        --yes|-y)
            YES=true
            shift
            ;;
        --namespace|-n)
            NAMESPACE="${2:?--namespace requires a value}"
            shift 2
            ;;
        --delete-namespaces)
            DELETE_NAMESPACES=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

oc_context=(oc --context "$CONTEXT")

if ! oc whoami --context "$CONTEXT" >/dev/null 2>&1; then
    echo "Not logged in to OpenShift context '$CONTEXT'. Log in first, then retry." >&2
    exit 1
fi

if ! helm status "$RELEASE" --kube-context "$CONTEXT" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "No Helm release '$RELEASE' found in namespace '$NAMESPACE' on context '$CONTEXT' — nothing to do."
    exit 0
fi

if [[ "$YES" != true ]]; then
    echo "This will remove the '$RELEASE' Helm release from context '$CONTEXT'."
    if [[ "$DELETE_NAMESPACES" == true ]]; then
        echo "WARNING: --delete-namespaces is set. All MemoryHub namespaces and their"
        echo "         data (PostgreSQL, MinIO PVCs) will be PERMANENTLY DELETED."
    else
        echo "PostgreSQL and MinIO data PVCs will be RETAINED."
    fi
    echo "External resources (OpenShift OAuthClient, RHOAI tile) will also be removed."
    echo ""
    read -r -p "Continue? [y/N] " reply
    [[ "$(echo "$reply" | tr '[:upper:]' '[:lower:]')" == y ]] || { echo "Aborted."; exit 0; }
fi

echo "==> Reading Helm values before uninstall"
_HELM_VALUES=$(helm get values "$RELEASE" --kube-context "$CONTEXT" -n "$NAMESPACE" -o json 2>/dev/null || echo '{}')
read -r OAUTH_CLIENT_ID _NS_DB _NS_STORAGE _NS_AUTH _NS_UI _NS_EMBED _NS_RERANK < <(
    echo "$_HELM_VALUES" | python3 - <<'PY'
import json, sys
d = sys.stdin.read()
v = json.loads(d) if d.strip() else {}
ns = v.get("namespaces", {})
print(
    v.get("auth", {}).get("oauthClientId", "memoryhub-auth-broker"),
    ns.get("database",      "memoryhub-db"),
    ns.get("storage",       "memoryhub-storage"),
    ns.get("auth",          "memoryhub-auth"),
    ns.get("ui",            "memoryhub-ui"),
    ns.get("embeddingModel","embedding-model"),
    ns.get("rerankerModel", "reranker-model"),
)
PY
)
OAUTH_CLIENT_ID="${OAUTH_CLIENT_ID:-memoryhub-auth-broker}"
_NS_DB="${_NS_DB:-memoryhub-db}"
_NS_STORAGE="${_NS_STORAGE:-memoryhub-storage}"
_NS_AUTH="${_NS_AUTH:-memoryhub-auth}"
_NS_UI="${_NS_UI:-memoryhub-ui}"
_NS_EMBED="${_NS_EMBED:-embedding-model}"
_NS_RERANK="${_NS_RERANK:-reranker-model}"

echo "==> Removing Helm release '$RELEASE'"
helm uninstall "$RELEASE" --kube-context "$CONTEXT" -n "$NAMESPACE" --wait

echo "==> Removing OpenShift OAuthClient"
"${oc_context[@]}" delete oauthclient "$OAUTH_CLIENT_ID" --ignore-not-found >/dev/null

RHOAI_NS="redhat-ods-applications"
if "${oc_context[@]}" get namespace "$RHOAI_NS" >/dev/null 2>&1; then
    echo "==> Removing RHOAI tile and proxy resources"
    "${oc_context[@]}" delete service   memoryhub-ui -n "$RHOAI_NS" --ignore-not-found >/dev/null
    "${oc_context[@]}" delete endpoints memoryhub-ui -n "$RHOAI_NS" --ignore-not-found >/dev/null
    "${oc_context[@]}" delete route     memoryhub-ui -n "$RHOAI_NS" --ignore-not-found >/dev/null
    if "${oc_context[@]}" api-versions | grep -q 'dashboard.opendatahub.io'; then
        "${oc_context[@]}" delete odhapplication memoryhub -n "$RHOAI_NS" --ignore-not-found >/dev/null
    fi
else
    echo "==> RHOAI not installed — skipping tile cleanup"
fi

if [[ "$DELETE_NAMESPACES" == true ]]; then
    echo "==> Deleting MemoryHub namespaces (and all PVCs within them)"
    for ns in "$NAMESPACE" "$_NS_DB" "$_NS_STORAGE" "$_NS_AUTH" "$_NS_UI" "$_NS_EMBED" "$_NS_RERANK"; do
        if "${oc_context[@]}" get namespace "$ns" >/dev/null 2>&1; then
            echo "    Deleting namespace $ns"
            "${oc_context[@]}" delete namespace "$ns" --timeout=5m || \
                echo "    WARNING: namespace $ns may be stuck Terminating — check with: oc get namespace $ns --context $CONTEXT"
        fi
    done
fi

echo ""
echo "MemoryHub Helm release '$RELEASE' removed."
if [[ "$DELETE_NAMESPACES" == true ]]; then
    echo "All MemoryHub namespaces and data have been deleted."
else
    echo "Data PVCs are retained in their namespaces. To delete them:"
    echo "  oc delete pvc --all -n memoryhub-db      --context $CONTEXT"
    echo "  oc delete pvc --all -n memoryhub-storage  --context $CONTEXT"
fi
