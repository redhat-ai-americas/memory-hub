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
# Usage: scripts/uninstall-full.sh [--yes] [--skip-db] [--skip-tile]
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

DB_NAMESPACE="memoryhub-db"
MCP_PROJECT="memory-hub-mcp"
AUTH_PROJECT="memoryhub-auth"
UI_NAMESPACE="memoryhub-ui"
RHOAI_NAMESPACE="redhat-ods-applications"

YES=false
SKIP_DB=false
SKIP_TILE=false

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
            --yes)       YES=true ;;
            --skip-db)   SKIP_DB=true ;;
            --skip-tile) SKIP_TILE=true ;;
            -h|--help)
                echo "Usage: $SCRIPT_NAME [--yes] [--skip-db] [--skip-tile]"
                echo ""
                echo "  --yes         Skip all confirmation prompts (non-interactive / CI mode)"
                echo "  --skip-db     Preserve the database namespace and its PVC (no memory loss)"
                echo "  --skip-tile   Leave RHOAI tile artifacts in redhat-ods-applications"
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
    if ! oc whoami &>/dev/null; then
        die "Not logged in to OpenShift. Run 'oc login' first."
    fi
    echo "     Logged in as: $(oc whoami)"
    echo "     Server:       $(oc whoami --show-server)"
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
# Step 1: RHOAI tile artifacts
# ---------------------------------------------------------------------------
remove_tile() {
    banner "1. RHOAI Tile Artifacts"

    if [ "$SKIP_TILE" = true ]; then
        skipped "RHOAI tile artifacts (--skip-tile)"
        return 0
    fi

    info "Removing OdhApplication/memoryhub..."
    oc delete odhapplication memoryhub \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Route/memoryhub-ui..."
    oc delete route memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Service/memoryhub-ui..."
    oc delete service memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing Endpoints/memoryhub-ui..."
    oc delete endpoints memoryhub-ui \
        -n "$RHOAI_NAMESPACE" \
        --ignore-not-found

    info "Removing memoryhub entry from odh-enabled-applications-config..."
    if oc get configmap odh-enabled-applications-config \
            -n "$RHOAI_NAMESPACE" &>/dev/null; then
        # Check if the key exists before attempting removal (oc patch fails if key is absent)
        if oc get configmap odh-enabled-applications-config \
                -n "$RHOAI_NAMESPACE" \
                -o jsonpath='{.data.memoryhub}' 2>/dev/null | grep -q .; then
            oc patch configmap odh-enabled-applications-config \
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
    oc delete namespace "$UI_NAMESPACE" \
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
    oc delete deployment memoryhub-ui $ns

    info "Removing Service/memoryhub-ui..."
    oc delete service memoryhub-ui $ns

    info "Removing Route/memoryhub-ui..."
    oc delete route memoryhub-ui $ns

    info "Removing ImageStream/memoryhub-ui..."
    oc delete imagestream memoryhub-ui $ns

    info "Removing BuildConfig/memoryhub-ui..."
    oc delete buildconfig memoryhub-ui $ns

    info "Removing ServiceAccount/memoryhub-ui..."
    oc delete serviceaccount memoryhub-ui $ns

    echo ""
    echo -e "  ${GREEN}Legacy UI artifacts removed from $MCP_PROJECT${RESET}"
}

# ---------------------------------------------------------------------------
# Step 4: MCP namespace
# ---------------------------------------------------------------------------
remove_mcp_namespace() {
    banner "4. MCP Namespace ($MCP_PROJECT)"

    info "Deleting namespace $MCP_PROJECT (--wait=false)..."
    oc delete namespace "$MCP_PROJECT" \
        --ignore-not-found \
        --wait=false
    warn "Namespace deletion is async; full teardown may take 30-60s."

    echo ""
    echo -e "  ${GREEN}Namespace $MCP_PROJECT deletion initiated${RESET}"
}

# ---------------------------------------------------------------------------
# Step 5: Auth namespace
# ---------------------------------------------------------------------------
remove_auth_namespace() {
    banner "5. Auth Namespace ($AUTH_PROJECT)"

    info "Deleting namespace $AUTH_PROJECT (--wait=false)..."
    oc delete namespace "$AUTH_PROJECT" \
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
    oc delete namespace "$DB_NAMESPACE" \
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
    remove_tile
    remove_ui_namespace
    remove_legacy_ui
    remove_mcp_namespace
    remove_auth_namespace
    remove_db_namespace
    summary
}

main "$@"
