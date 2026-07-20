#!/bin/bash
# WARNING: This script is destructive. It removes all MemoryHub
# resources, including the database and all stored memories.
# Use --skip-db to preserve the database.
#
# CREDENTIAL DRIFT: When the DB namespace is deleted and recreated,
# deploy-full.sh generates a new random password for memoryhub-pg-credentials.
# Consumer namespaces (MCP, Auth, UI) that hold cross-namespace copies of the
# DB secret will be stale after reinstall.  Each component's deploy.sh reads
# the password from the DB namespace at deploy time (#192), and deploy-full.sh
# uses copy_secret for auth/UI.  Standalone 'make deploy' in a sub-project
# also reads from the DB namespace, so credentials stay in sync even without
# deploy-full.sh.
#
# Usage: scripts/uninstall-full.sh [--yes] [--skip-db] [--skip-tile] [--skip-models] [--no-backup]
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"

DB_NAMESPACE="memoryhub-db"
MCP_PROJECT="memory-hub-mcp"
AUTH_PROJECT="memoryhub-auth"
UI_NAMESPACE="memoryhub-ui"
RHOAI_NAMESPACE="redhat-ods-applications"
EMBEDDING_MODEL_NAMESPACE="embedding-model"
RERANKER_MODEL_NAMESPACE="reranker-model"

YES=false
SKIP_DB=false
SKIP_TILE=false
SKIP_MODELS=false
NO_BACKUP=false

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --yes)        YES=true ;;
            --skip-db)    SKIP_DB=true ;;
            --skip-tile)  SKIP_TILE=true ;;
            --skip-models) SKIP_MODELS=true ;;
            --no-backup)  NO_BACKUP=true ;;
            -h|--help)
                echo "Usage: $SCRIPT_NAME [--yes] [--skip-db] [--skip-tile] [--skip-models] [--no-backup]"
                echo ""
                echo "  --yes           Skip all confirmation prompts (non-interactive / CI mode)"
                echo "  --skip-db       Preserve the database namespace and its PVC (no memory loss)"
                echo "  --skip-tile     Leave RHOAI tile artifacts in redhat-ods-applications"
                echo "  --skip-models   Preserve embedding + reranker model namespaces"
                echo "  --no-backup     Skip automatic pre-uninstall database backup"
                exit 0
                ;;
            *)
                die "Unknown argument: $arg (run with --help for usage)"
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
preflight() {
    banner "Preflight"

    info "Verifying OpenShift login..."
    if ! oc whoami --context "$CONTEXT" &>/dev/null; then
        die "Not logged in to OpenShift. Run 'oc login' first."
    fi
    echo "     Logged in as: $(oc whoami --context "$CONTEXT")"
    echo "     Server:       $(oc whoami --context "$CONTEXT" --show-server)"
}

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------
confirm() {
    echo ""
    echo -e "  ${RED}${BOLD}DESTRUCTIVE OPERATION${RESET}"
    echo ""
    echo "  The following resources will be removed:"
    echo ""
    if [ "$SKIP_TILE" = false ]; then
        echo "    RHOAI tile artifacts in $RHOAI_NAMESPACE"
        echo "      - OdhApplication/memoryhub"
        echo "      - Route/memoryhub-ui"
        echo "      - Service/memoryhub-ui"
        echo "      - Endpoints/memoryhub-ui"
        echo "      - ConfigMap entry: odh-enabled-applications-config[memoryhub]"
    fi
    echo "    Namespace: $UI_NAMESPACE  (UI — new location)"
    echo "    UI artifacts in $MCP_PROJECT  (UI — legacy location)"
    echo "      - Deployment/memoryhub-ui"
    echo "      - Service/memoryhub-ui"
    echo "      - Route/memoryhub-ui"
    echo "      - ImageStream/memoryhub-ui"
    echo "      - BuildConfig/memoryhub-ui"
    echo "      - ServiceAccount/memoryhub-ui"
    echo "    Namespace: $MCP_PROJECT  (MCP server + MinIO + Valkey)"
    if [ "$SKIP_MODELS" = true ]; then
        echo "    Models: PRESERVED  (--skip-models)"
    else
        echo "    Namespace: $EMBEDDING_MODEL_NAMESPACE  (Embedding model)"
        echo "    Namespace: $RERANKER_MODEL_NAMESPACE  (Reranker model)"
    fi
    echo "    Namespace: $AUTH_PROJECT  (Auth server)"
    if [ "$SKIP_DB" = true ]; then
        echo "    Database: PRESERVED  (--skip-db)"
    else
        echo "    Namespace: $DB_NAMESPACE  (PostgreSQL + ALL STORED MEMORIES — DATA LOSS)"
    fi
    echo ""

    if [ "$YES" = true ]; then
        warn "--yes flag set; skipping confirmation."
        return 0
    fi

    read -r -p "  Type 'y' to proceed, anything else cancels: " answer
    echo ""
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
        echo "  Cancelled. No changes made."
        exit 0
    fi
}

# ---------------------------------------------------------------------------
# Pre-uninstall: Database backup
# ---------------------------------------------------------------------------
backup_before_uninstall() {
    # Skip backup when DB is preserved (no data loss) or explicitly opted out.
    if [ "$SKIP_DB" = true ]; then
        return 0
    fi
    if [ "$NO_BACKUP" = true ]; then
        warn "Skipping pre-uninstall backup (--no-backup)."
        return 0
    fi

    banner "Pre-Uninstall Backup"

    # Check if the DB pod is even running — can't back up a dead pod.
    if ! oc get pod --context "$CONTEXT" -l "app.kubernetes.io/name=memoryhub-pg" \
            -n "$DB_NAMESPACE" &>/dev/null; then
        warn "No PostgreSQL pod found in $DB_NAMESPACE — skipping backup."
        return 0
    fi

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    info "Running database backup before uninstall..."
    if "$script_dir/backup-db.sh"; then
        info "Backup saved. Proceeding with uninstall."
    else
        warn "Backup failed."
        if [ "$YES" = true ]; then
            warn "--yes flag set; continuing despite backup failure."
        else
            read -r -p "  Continue without backup? (y/N): " answer
            if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
                echo "  Cancelled."
                exit 0
            fi
        fi
    fi
}

# ---------------------------------------------------------------------------
# Step 1: RHOAI tile artifacts
# ---------------------------------------------------------------------------
remove_tile() {
    banner "1. RHOAI Tile Artifacts"

    if [ "$SKIP_TILE" = true ]; then
        skipped "RHOAI tile artifacts (--skip-tile)"
        return 0
    fi

    info "Removing OdhApplication/memoryhub..."
    oc delete odhapplication --context "$CONTEXT" memoryhub \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Route/memoryhub-ui..."
    oc delete route --context "$CONTEXT" memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Service/memoryhub-ui..."
    oc delete service --context "$CONTEXT" memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Endpoints/memoryhub-ui..."
    oc delete endpoints --context "$CONTEXT" memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing memoryhub entry from odh-enabled-applications-config..."
    if oc get configmap --context "$CONTEXT" odh-enabled-applications-config \
            -n "$RHOAI_NAMESPACE" &>/dev/null; then
        # Check if the key exists before attempting removal (oc patch fails if key is absent)
        if oc get configmap --context "$CONTEXT" odh-enabled-applications-config \
                -n "$RHOAI_NAMESPACE" \
                -o jsonpath='{.data.memoryhub}' 2>/dev/null | grep -q .; then
            oc patch configmap --context "$CONTEXT" odh-enabled-applications-config \
                -n "$RHOAI_NAMESPACE" \
                --type json \
                -p '[{"op":"remove","path":"/data/memoryhub"}]'
        else
            info "  (key 'memoryhub' not present — nothing to remove)"
        fi
    else
        info "  (ConfigMap not found — skipping)"
    fi

    echo ""
    echo -e "  ${GREEN}RHOAI tile artifacts removed${RESET}"
}

# ---------------------------------------------------------------------------
# Step 2: UI namespace (new, correct location)
# ---------------------------------------------------------------------------
remove_ui_namespace() {
    banner "2. UI Namespace ($UI_NAMESPACE)"

    info "Deleting namespace $UI_NAMESPACE (--wait=false)..."
    oc delete namespace --context "$CONTEXT" "$UI_NAMESPACE" \
        --ignore-not-found \
        --wait=false
    warn "Namespace deletion is async; full teardown may take 30-60s."

    echo ""
    echo -e "  ${GREEN}Namespace $UI_NAMESPACE deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Step 3: Legacy UI artifacts in memory-hub-mcp namespace
# ---------------------------------------------------------------------------
remove_legacy_ui() {
    banner "3. Legacy UI Artifacts in $MCP_PROJECT"

    local ns="-n $MCP_PROJECT --ignore-not-found"

    info "Removing Deployment/memoryhub-ui..."
    oc delete deployment --context "$CONTEXT" memoryhub-ui $ns

    info "Removing Service/memoryhub-ui..."
    oc delete service --context "$CONTEXT" memoryhub-ui $ns

    info "Removing Route/memoryhub-ui..."
    oc delete route --context "$CONTEXT" memoryhub-ui $ns

    info "Removing ImageStream/memoryhub-ui..."
    oc delete imagestream --context "$CONTEXT" memoryhub-ui $ns

    info "Removing BuildConfig/memoryhub-ui..."
    oc delete buildconfig --context "$CONTEXT" memoryhub-ui $ns

    info "Removing ServiceAccount/memoryhub-ui..."
    oc delete serviceaccount --context "$CONTEXT" memoryhub-ui $ns

    echo ""
    echo -e "  ${GREEN}Legacy UI artifacts removed from $MCP_PROJECT${RESET}"
}

# ---------------------------------------------------------------------------
# Step 4: MCP namespace
# ---------------------------------------------------------------------------
remove_mcp_namespace() {
    banner "4. MCP Namespace ($MCP_PROJECT)"

    info "Deleting namespace $MCP_PROJECT (--wait=false)..."
    oc delete namespace --context "$CONTEXT" "$MCP_PROJECT" \
        --ignore-not-found \
        --wait=false
    warn "Namespace deletion is async; full teardown may take 30-60s."

    echo ""
    echo -e "  ${GREEN}Namespace $MCP_PROJECT deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Step 4b: Model namespaces
# ---------------------------------------------------------------------------
remove_model_namespaces() {
    banner "4b. Model Namespaces"

    if [ "$SKIP_MODELS" = true ]; then
        skipped "Model namespaces (--skip-models)"
        return 0
    fi

    for ns in "$EMBEDDING_MODEL_NAMESPACE" "$RERANKER_MODEL_NAMESPACE"; do
        if oc get namespace --context "$CONTEXT" "$ns" &>/dev/null; then
            info "Deleting namespace $ns (--wait=false)..."
            oc delete namespace --context "$CONTEXT" "$ns" --ignore-not-found --wait=false
        else
            info "Namespace $ns does not exist -- skipping"
        fi
    done

    echo ""
    echo -e "  ${GREEN}Model namespaces deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Step 5: Auth namespace
# ---------------------------------------------------------------------------
remove_auth_namespace() {
    banner "5. Auth Namespace ($AUTH_PROJECT)"

    info "Deleting namespace $AUTH_PROJECT (--wait=false)..."
    oc delete namespace --context "$CONTEXT" "$AUTH_PROJECT" \
        --ignore-not-found \
        --wait=false
    warn "Namespace deletion is async; full teardown may take 30-60s."

    echo ""
    echo -e "  ${GREEN}Namespace $AUTH_PROJECT deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Step 6: Database namespace
# ---------------------------------------------------------------------------
remove_db_namespace() {
    banner "6. Database Namespace ($DB_NAMESPACE)"

    if [ "$SKIP_DB" = true ]; then
        skipped "Database namespace (--skip-db). Stored memories preserved."
        return 0
    fi

    warn "Deleting $DB_NAMESPACE — ALL STORED MEMORIES WILL BE LOST."
    oc delete namespace --context "$CONTEXT" "$DB_NAMESPACE" \
        --ignore-not-found \
        --wait=false
    warn "Namespace deletion is async; full teardown may take 30-60s."

    echo ""
    echo -e "  ${GREEN}Namespace $DB_NAMESPACE deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Summary banner
# ---------------------------------------------------------------------------
summary() {
    local secs
    secs=$(elapsed)
    local mins=$(( secs / 60 ))
    local rem=$(( secs % 60 ))

    banner "Uninstall Complete"
    echo ""
    echo "  Resources removed:"
    if [ "$SKIP_TILE" = false ]; then
        echo "    ${GREEN}✓${RESET} RHOAI tile artifacts ($RHOAI_NAMESPACE)"
    else
        echo "    ${YELLOW}-${RESET} RHOAI tile artifacts (skipped)"
    fi
    echo "    ${GREEN}✓${RESET} Namespace $UI_NAMESPACE"
    echo "    ${GREEN}✓${RESET} Legacy UI artifacts in $MCP_PROJECT"
    echo "    ${GREEN}✓${RESET} Namespace $MCP_PROJECT"
    if [ "$SKIP_MODELS" = false ]; then
        echo "    ${GREEN}✓${RESET} Namespace $EMBEDDING_MODEL_NAMESPACE"
        echo "    ${GREEN}✓${RESET} Namespace $RERANKER_MODEL_NAMESPACE"
    else
        echo "    ${YELLOW}-${RESET} Model namespaces (skipped)"
    fi
    echo "    ${GREEN}✓${RESET} Namespace $AUTH_PROJECT"
    if [ "$SKIP_DB" = false ]; then
        echo "    ${GREEN}✓${RESET} Namespace $DB_NAMESPACE (data deleted)"
    else
        echo "    ${YELLOW}-${RESET} Namespace $DB_NAMESPACE (preserved)"
    fi
    echo ""
    warn "Namespace deletions are async. Verify with:"
    echo "       oc get namespaces | grep -E 'memoryhub|memory-hub'"
    echo ""
    echo -e "  ${GREEN}Uninstall initiated${RESET} in ${mins}m ${rem}s"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    echo ""
    echo -e "${BOLD}MemoryHub — Full Stack Uninstall${RESET}"
    echo "  $(date)"

    preflight
    confirm
    backup_before_uninstall
    remove_tile
    remove_ui_namespace
    remove_legacy_ui
    remove_mcp_namespace
    remove_model_namespaces
    remove_auth_namespace
    remove_db_namespace
    summary
}

main "$@"
