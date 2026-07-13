#!/bin/bash
# Deploy EvalHub evaluation infrastructure for MemoryHub benchmarking.
#
# Creates the memoryhub-eval namespace, deploys EvalHub + MLflow CRs,
# and registers the memoryhub-amb BYOF provider via the REST API.
#
# Usage: scripts/deploy-evalhub.sh [--skip-provider] [--skip-wait]
#
# Prerequisites:
#   - TrustyAI operator managed via RHOAI DataScienceCluster
#   - MLflow operator managed via RHOAI DataScienceCluster
#   - evalhub CLI installed (pip install eval-hub-sdk)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
NS="memoryhub-eval"
MANIFEST_DIR="$REPO_ROOT/benchmarks/evalhub-adapter/manifests"
CONFIG_DIR="$REPO_ROOT/benchmarks/evalhub-adapter/config"

SKIP_PROVIDER=false
SKIP_WAIT=false

START_TIME=$(date +%s)

# ---------------------------------------------------------------------------
# Color support
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    BOLD="\033[1m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    RED="\033[0;31m"
    CYAN="\033[0;36m"
    RESET="\033[0m"
else
    BOLD="" GREEN="" YELLOW="" RED="" CYAN="" RESET=""
fi

banner() {
    echo ""
    echo -e "${BOLD}${CYAN}=========================================${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}=========================================${RESET}"
}

info()    { echo -e "  ${GREEN}→${RESET} $*"; }
warn()    { echo -e "  ${YELLOW}!${RESET} $*"; }
die()     { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }
skipped() { echo -e "  ${YELLOW}(skipped)${RESET} $*"; }

elapsed() {
    local end_time
    end_time=$(date +%s)
    echo $(( end_time - START_TIME ))
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-provider)  SKIP_PROVIDER=true ;;
        --skip-wait)      SKIP_WAIT=true ;;
        -h|--help)
            echo "Usage: $SCRIPT_NAME [OPTIONS]"
            echo ""
            echo "  --skip-provider  Skip BYOF provider registration"
            echo "  --skip-wait      Skip waiting for pods to be ready"
            exit 0
            ;;
        *)
            die "Unknown argument: $1 (run with --help for usage)"
            ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
banner "Preflight checks"

info "Checking cluster access..."
oc whoami --context "$CONTEXT" &>/dev/null || die "Cannot authenticate to cluster (context=$CONTEXT)"
info "Authenticated as $(oc whoami --context "$CONTEXT")"

info "Checking TrustyAI operator..."
if ! oc get crd evalhubs.trustyai.opendatahub.io --context "$CONTEXT" &>/dev/null; then
    die "EvalHub CRD not found. TrustyAI must be Managed in the DataScienceCluster."
fi
info "EvalHub CRD available"

info "Checking MLflow operator..."
if ! oc get crd mlflows.mlflow.opendatahub.io --context "$CONTEXT" &>/dev/null; then
    die "MLflow CRD not found. MLflow operator must be Managed in the DataScienceCluster."
fi
info "MLflow CRD available"

# ---------------------------------------------------------------------------
# Namespace
# ---------------------------------------------------------------------------
banner "Namespace: $NS"

if oc get namespace "$NS" --context "$CONTEXT" &>/dev/null; then
    info "Namespace $NS already exists"
else
    info "Creating namespace $NS..."
    oc apply --context "$CONTEXT" -f "$MANIFEST_DIR/namespace.yaml"
fi

# ---------------------------------------------------------------------------
# BuildConfig and ImageStream
# ---------------------------------------------------------------------------
banner "BuildConfig"

if oc get buildconfig memoryhub-evalhub-adapter --context "$CONTEXT" -n "$NS" &>/dev/null; then
    info "BuildConfig memoryhub-evalhub-adapter already exists"
else
    info "Creating BuildConfig and ImageStream..."
    oc apply --context "$CONTEXT" -f "$MANIFEST_DIR/buildconfig.yaml"
fi

# ---------------------------------------------------------------------------
# Model auth Secret (Gemini API key)
# ---------------------------------------------------------------------------
banner "Model auth Secret"

if oc get secret gemini-api-key --context "$CONTEXT" -n "$NS" &>/dev/null; then
    info "Secret gemini-api-key already exists"
else
    if [ -f "$HOME/.secrets" ]; then
        GEMINI_KEY=$(bash -c 'source "$HOME/.secrets" 2>/dev/null; echo "$GEMINI_API_KEY"')
        if [ -n "$GEMINI_KEY" ]; then
            info "Creating Secret gemini-api-key from ~/.secrets..."
            oc create secret generic gemini-api-key \
                --from-literal=api-key="$GEMINI_KEY" \
                --context "$CONTEXT" -n "$NS"
        else
            warn "GEMINI_API_KEY not found in ~/.secrets; skipping Secret creation"
            warn "Create manually: oc create secret generic gemini-api-key --from-literal=api-key=<key> --context $CONTEXT -n $NS"
        fi
    else
        warn "~/.secrets not found; skipping Secret creation"
        warn "Create manually: oc create secret generic gemini-api-key --from-literal=api-key=<key> --context $CONTEXT -n $NS"
    fi
fi

# ---------------------------------------------------------------------------
# EvalHub CR
# ---------------------------------------------------------------------------
banner "EvalHub"

if oc get evalhub memoryhub-evalhub --context "$CONTEXT" -n "$NS" &>/dev/null; then
    info "EvalHub CR memoryhub-evalhub already exists"
else
    info "Creating EvalHub CR..."
    oc apply --context "$CONTEXT" -f "$MANIFEST_DIR/evalhub.yaml"
fi

# ---------------------------------------------------------------------------
# MLflow
# ---------------------------------------------------------------------------
banner "MLflow"

if oc get mlflow mlflow --context "$CONTEXT" -n "$NS" &>/dev/null; then
    info "MLflow CR mlflow already exists"
else
    info "Creating MLflow CR..."
    oc apply --context "$CONTEXT" -f "$MANIFEST_DIR/mlflow.yaml"
fi

# ---------------------------------------------------------------------------
# Wait for pods
# ---------------------------------------------------------------------------
if [ "$SKIP_WAIT" = true ]; then
    skipped "Waiting for pods"
else
    banner "Waiting for pods"

    info "Waiting for EvalHub deployment..."
    if ! oc rollout status deployment/memoryhub-evalhub --context "$CONTEXT" -n "$NS" --timeout=120s 2>/dev/null; then
        warn "EvalHub deployment not ready after 120s. Check: oc get pods --context $CONTEXT -n $NS"
    else
        info "EvalHub deployment ready"
    fi

    info "Waiting for MLflow deployment..."
    MLFLOW_NS=$(oc get mlflow mlflow --context "$CONTEXT" -n "$NS" -o jsonpath='{.status.address.url}' 2>/dev/null | sed 's|.*://mlflow\.\(.*\)\.svc.*|\1|' || echo "redhat-ods-applications")
    if [ -z "$MLFLOW_NS" ]; then
        MLFLOW_NS="redhat-ods-applications"
    fi
    if ! oc rollout status deployment/mlflow --context "$CONTEXT" -n "$MLFLOW_NS" --timeout=120s 2>/dev/null; then
        warn "MLflow deployment not ready after 120s. Check: oc get pods --context $CONTEXT -n $MLFLOW_NS"
    else
        info "MLflow deployment ready (namespace: $MLFLOW_NS)"
    fi
fi

# ---------------------------------------------------------------------------
# BYOF provider registration
# ---------------------------------------------------------------------------
if [ "$SKIP_PROVIDER" = true ]; then
    skipped "Provider registration"
else
    banner "Provider registration"

    EVALHUB_ROUTE=$(oc get route memoryhub-evalhub --context "$CONTEXT" -n "$NS" -o jsonpath='{.spec.host}' 2>/dev/null || true)
    EVALHUB_SVC="http://memoryhub-evalhub.$NS.svc:8080"

    if [ -n "$EVALHUB_ROUTE" ]; then
        EVALHUB_URL="https://$EVALHUB_ROUTE"
        info "Using route: $EVALHUB_URL"
    else
        EVALHUB_URL="$EVALHUB_SVC"
        info "No route found, using service URL: $EVALHUB_URL"
        warn "Provider registration requires port-forward or route access."
        warn "Run: oc port-forward svc/memoryhub-evalhub 8080:8080 --context $CONTEXT -n $NS"
    fi

    TOKEN=$(oc whoami --context "$CONTEXT" -t 2>/dev/null || true)

    info "Configuring evalhub CLI..."
    evalhub config set base_url "$EVALHUB_URL" 2>/dev/null || true
    [ -n "$TOKEN" ] && evalhub config set token "$TOKEN" 2>/dev/null || true
    evalhub config set tenant "$NS" 2>/dev/null || true

    # SQLite file-backed DB loses providers on pod restart; always re-register
    # Generate provider spec with MemoryHub connection env vars
    MEMORYHUB_MCP_URL="http://memory-hub-mcp.memory-hub-mcp.svc:8080/mcp/"
    MEMORYHUB_KEY=$(bash -c 'cat ~/.config/memoryhub/api-key 2>/dev/null' | tr -d '[:space:]')
    MEMORYHUB_DB_PASSWORD=$(oc get secret memoryhub-db-credentials --context "$CONTEXT" -n memory-hub-mcp \
        -o jsonpath='{.data.MEMORYHUB_DB_PASSWORD}' 2>/dev/null | base64 -d || true)

    PROVIDER_SPEC=$(mktemp)
    trap "rm -f $PROVIDER_SPEC" EXIT
    python3 -c "
import yaml, sys
with open('$CONFIG_DIR/provider.yaml') as f:
    spec = yaml.safe_load(f)
spec.setdefault('runtime', {}).setdefault('k8s', {})['env'] = [
    {'name': 'MEMORYHUB_URL', 'value': '$MEMORYHUB_MCP_URL'},
    {'name': 'MEMORYHUB_API_KEY', 'value': '$MEMORYHUB_KEY'},
    {'name': 'MEMORYHUB_DB_HOST', 'value': 'memoryhub-pg.memoryhub-db.svc.cluster.local'},
    {'name': 'MEMORYHUB_DB_PORT', 'value': '5432'},
    {'name': 'MEMORYHUB_DB_USER', 'value': 'memoryhub'},
    {'name': 'MEMORYHUB_DB_PASS', 'value': '$MEMORYHUB_DB_PASSWORD'},
    {'name': 'MEMORYHUB_DB_NAME', 'value': 'memoryhub'},
]
yaml.dump(spec, sys.stdout, default_flow_style=False)
" > "$PROVIDER_SPEC"

    info "Registering provider memoryhub-amb..."
    PROVIDER_OUTPUT=$(evalhub providers create --file "$PROVIDER_SPEC" 2>&1) || true
    PROVIDER_ID=$(echo "$PROVIDER_OUTPUT" | sed -n 's/.*Provider created: \([a-f0-9-]*\).*/\1/p')
    if [ -n "$PROVIDER_ID" ]; then
        info "Provider registered: $PROVIDER_ID"
        # Update all eval configs with current provider ID
        for cfg in "$CONFIG_DIR/smoke-eval.yaml" "$CONFIG_DIR"/matrix/*.yaml; do
            if [ -f "$cfg" ]; then
                sed -i.bak "s|provider_id: .*|provider_id: $PROVIDER_ID|" "$cfg"
                rm -f "${cfg}.bak"
            fi
        done
        info "Updated eval configs with provider ID"
    else
        warn "Provider registration failed (server may not be reachable yet)"
        warn "Re-run after EvalHub is accessible:"
        warn "  evalhub providers create --file $CONFIG_DIR/provider.yaml"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
banner "Deploy complete ($(elapsed)s)"

info "Namespace:  $NS"
info "EvalHub:    memoryhub-evalhub"
info "MLflow:     mlflow"
info ""
info "Next steps:"
info "  1. Build and push adapter container (if not already done)"
info "  2. Register provider (if skipped): evalhub providers create --file $CONFIG_DIR/provider.yaml"
info "  3. Run smoke test: evalhub eval run --config $CONFIG_DIR/smoke-eval.yaml --wait"
