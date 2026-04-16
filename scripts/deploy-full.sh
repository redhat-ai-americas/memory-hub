#!/bin/bash
# Full MemoryHub stack deployment to OpenShift.
# Usage: scripts/deploy-full.sh [--skip-prereqs] [--skip-db] [--skip-migrations]
#                                [--skip-mcp] [--skip-auth] [--skip-ui] [--skip-tile]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

DB_NAMESPACE="memoryhub-db"
MCP_PROJECT="memory-hub-mcp"
AUTH_PROJECT="memoryhub-auth"
UI_NAMESPACE="memoryhub-ui"
RHOAI_NAMESPACE="redhat-ods-applications"
DB_POD_LABEL="app.kubernetes.io/name=memoryhub-pg"

SKIP_PREREQS=false
SKIP_DB=false
SKIP_MIGRATIONS=false
SKIP_MCP=false
SKIP_AUTH=false
SKIP_UI=false
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
            --skip-prereqs)    SKIP_PREREQS=true ;;
            --skip-db)         SKIP_DB=true ;;
            --skip-migrations) SKIP_MIGRATIONS=true ;;
            --skip-mcp)        SKIP_MCP=true ;;
            --skip-auth)       SKIP_AUTH=true ;;
            --skip-ui)         SKIP_UI=true ;;
            --skip-tile)       SKIP_TILE=true ;;
            -h|--help)
                echo "Usage: $SCRIPT_NAME [OPTIONS]"
                echo ""
                echo "  --skip-prereqs     Skip check-prereqs.sh (for known-good environments)"
                echo "  --skip-db          Skip PostgreSQL deployment"
                echo "  --skip-migrations  Skip Alembic migrations"
                echo "  --skip-mcp         Skip MCP server deployment"
                echo "  --skip-auth        Skip Auth server deployment"
                echo "  --skip-ui          Skip UI deployment"
                echo "  --skip-tile        Skip RHOAI OdhApplication tile"
                exit 0
                ;;
            *)
                die "Unknown argument: $arg (run with --help for usage)"
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Section 0a: Prerequisite check (external script)
# ---------------------------------------------------------------------------
check_prereqs() {
    if [ "$SKIP_PREREQS" = true ]; then
        skipped "Prerequisite check (--skip-prereqs)"
        return 0
    fi

    local prereq_script="$REPO_ROOT/scripts/check-prereqs.sh"
    if [ ! -f "$prereq_script" ]; then
        warn "check-prereqs.sh not found at $prereq_script — skipping prereq check."
        return 0
    fi

    banner "0. Prerequisite Check"
    if ! bash "$prereq_script"; then
        die "Prerequisite check failed. Fix the issues above and re-run, or pass --skip-prereqs to bypass."
    fi
    echo ""
    echo -e "  ${GREEN}Prerequisites satisfied${RESET}"
}

# ---------------------------------------------------------------------------
# Section 0b: Preflight checks
# ---------------------------------------------------------------------------
preflight() {
    banner "1. Preflight Checks"

    info "Verifying OpenShift login..."
    if ! oc whoami &>/dev/null; then
        die "Not logged in to OpenShift. Run 'oc login' first."
    fi
    echo "     Logged in as: $(oc whoami)"
    echo "     Server:       $(oc whoami --show-server)"

    info "Verifying .venv and alembic..."
    if [ ! -d "$REPO_ROOT/.venv" ]; then
        die ".venv not found at $REPO_ROOT/.venv — run 'make install' or set up your virtualenv first."
    fi
    if ! "$REPO_ROOT/.venv/bin/alembic" --version &>/dev/null; then
        die "alembic not found in .venv — run 'pip install alembic' in your virtualenv."
    fi
    echo "     $("$REPO_ROOT/.venv/bin/alembic" --version)"

    echo ""
    echo -e "  ${GREEN}Preflight OK${RESET}"
    echo ""
    echo "  Deployment plan:"
    echo "    PostgreSQL:  $([ "$SKIP_DB" = true ] && echo "skip" || echo "deploy")"
    echo "    Migrations:  $([ "$SKIP_MIGRATIONS" = true ] && echo "skip" || echo "run")"
    echo "    MCP server:  $([ "$SKIP_MCP" = true ] && echo "skip" || echo "deploy")"
    echo "    Auth server: $([ "$SKIP_AUTH" = true ] && echo "skip" || echo "deploy")"
    echo "    UI:          $([ "$SKIP_UI" = true ] && echo "skip" || echo "deploy")"
    echo "    RHOAI tile:  $([ "$SKIP_TILE" = true ] && echo "skip" || echo "apply")"
}

# ---------------------------------------------------------------------------
# Section 1: PostgreSQL
# ---------------------------------------------------------------------------
deploy_postgresql() {
    banner "2. PostgreSQL"

    if [ "$SKIP_DB" = true ]; then
        skipped "PostgreSQL (--skip-db)"
        return 0
    fi

    info "Applying kustomize manifests..."
    oc apply -k "$REPO_ROOT/deploy/postgresql/"

    info "Granting anyuid SCC to default service account..."
    # idempotent — oc adm policy exits 0 whether or not the grant was new
    oc adm policy add-scc-to-user anyuid -z default -n "$DB_NAMESPACE"

    # If the pod already existed before the SCC grant, it may be stuck.
    # Check if the pod is in a bad state and delete it so it restarts with the SCC.
    local pod_phase
    pod_phase=$(oc get pod -n "$DB_NAMESPACE" -l "$DB_POD_LABEL" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

    if [ -n "$pod_phase" ] && [ "$pod_phase" != "Running" ]; then
        warn "PostgreSQL pod is in '$pod_phase' state — deleting so it restarts with updated SCC..."
        oc delete pod -n "$DB_NAMESPACE" -l "$DB_POD_LABEL" --ignore-not-found
    fi

    info "Waiting for PostgreSQL pod to be ready (timeout: 120s)..."
    if ! oc wait --for=condition=ready pod -l "$DB_POD_LABEL" \
            -n "$DB_NAMESPACE" --timeout=120s; then
        die "PostgreSQL pod did not become ready within 120s. Check: oc describe pod -l $DB_POD_LABEL -n $DB_NAMESPACE"
    fi

    echo ""
    echo -e "  ${GREEN}PostgreSQL ready${RESET}"
}

# ---------------------------------------------------------------------------
# Section 2: Alembic Migrations
# ---------------------------------------------------------------------------
run_migrations() {
    banner "3. Alembic Migrations"

    if [ "$SKIP_MIGRATIONS" = true ]; then
        skipped "Migrations (--skip-migrations)"
        return 0
    fi

    local migration_script="$REPO_ROOT/scripts/run-migrations.sh"
    if [ ! -f "$migration_script" ]; then
        die "Migration script not found: $migration_script"
    fi

    info "Running $migration_script..."
    if ! bash "$migration_script"; then
        die "Migrations failed. Check output above."
    fi

    echo ""
    echo -e "  ${GREEN}Migrations complete${RESET}"
}

# ---------------------------------------------------------------------------
# Section 3: MCP Server
# ---------------------------------------------------------------------------
deploy_mcp() {
    banner "4. MCP Server"

    if [ "$SKIP_MCP" = true ]; then
        skipped "MCP server (--skip-mcp)"
        return 0
    fi

    info "Building and deploying MCP server (project: $MCP_PROJECT)..."
    pushd "$REPO_ROOT/memory-hub-mcp" > /dev/null
    make deploy PROJECT="$MCP_PROJECT"
    popd > /dev/null

    echo ""
    echo -e "  ${GREEN}MCP server deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 5b: Auth Server (defined after MCP; called after deploy_mcp)
# ---------------------------------------------------------------------------
deploy_auth() {
    banner "5. Auth Server"

    if [ "$SKIP_AUTH" = true ]; then
        skipped "Auth server (--skip-auth)"
        return 0
    fi

    info "Seeding OAuth clients..."
    "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/seed-oauth-clients.py"

    info "Building and deploying Auth server (project: $AUTH_PROJECT)..."
    pushd "$REPO_ROOT/memoryhub-auth" > /dev/null
    make deploy PROJECT="$AUTH_PROJECT"
    popd > /dev/null

    echo ""
    echo -e "  ${GREEN}Auth server deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 6: UI
# ---------------------------------------------------------------------------
deploy_ui() {
    banner "6. UI"

    if [ "$SKIP_UI" = true ]; then
        skipped "UI deployment (--skip-ui)"
        return 0
    fi

    local ui_deploy="$REPO_ROOT/memoryhub-ui/deploy/deploy.sh"
    if [ ! -f "$ui_deploy" ]; then
        die "UI deploy script not found: $ui_deploy"
    fi

    info "Deploying UI (namespace: $UI_NAMESPACE)..."
    if ! bash "$ui_deploy"; then
        die "UI deployment failed. Check output above."
    fi

    echo ""
    echo -e "  ${GREEN}UI deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 7: RHOAI OdhApplication tile
# ---------------------------------------------------------------------------
deploy_tile() {
    banner "7. RHOAI OdhApplication Tile"

    if [ "$SKIP_TILE" = true ]; then
        skipped "OdhApplication tile (--skip-tile)"
        return 0
    fi

    local odh_manifest="$REPO_ROOT/memoryhub-ui/openshift/odh-application.yaml"
    if [ ! -f "$odh_manifest" ]; then
        die "OdhApplication manifest not found: $odh_manifest"
    fi

    info "Applying OdhApplication CR to $RHOAI_NAMESPACE..."
    if ! oc apply -f "$odh_manifest" -n "$RHOAI_NAMESPACE"; then
        die "Failed to apply OdhApplication manifest."
    fi

    echo ""
    echo -e "  ${GREEN}RHOAI tile applied${RESET}"
}

# ---------------------------------------------------------------------------
# Summary banner
# ---------------------------------------------------------------------------
print_summary() {
    banner "Deployment Summary"

    local cluster_url current_user
    cluster_url=$(oc whoami --show-server 2>/dev/null || echo "(unavailable)")
    current_user=$(oc whoami 2>/dev/null || echo "(unavailable)")

    local ui_route mcp_route auth_route rhoai_route
    ui_route=$(oc get route memoryhub-ui -n "$UI_NAMESPACE" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    mcp_route=$(oc get route memory-hub-mcp -n "$MCP_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    auth_route=$(oc get route auth-server -n "$AUTH_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    rhoai_route=$(oc get route rhods-dashboard -n "$RHOAI_NAMESPACE" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

    echo ""
    printf "    %-24s %s\n" "Cluster:" "$cluster_url"
    printf "    %-24s %s\n" "User:" "$current_user"
    echo ""

    if [ -n "$ui_route" ]; then
        printf "    %-24s %s\n" "UI:" "https://${ui_route}"
    else
        printf "    %-24s %s\n" "UI:" "(route not found — check: oc get route memoryhub-ui -n $UI_NAMESPACE)"
    fi

    if [ -n "$mcp_route" ]; then
        printf "    %-24s %s\n" "MCP server:" "https://${mcp_route}/mcp/"
    else
        printf "    %-24s %s\n" "MCP server:" "(route not found — check: oc get route -n $MCP_PROJECT)"
    fi

    if [ -n "$auth_route" ]; then
        printf "    %-24s %s\n" "Auth server:" "https://${auth_route}"
    else
        printf "    %-24s %s\n" "Auth server:" "(route not found — check: oc get route auth-server -n $AUTH_PROJECT)"
    fi

    if [ -n "$rhoai_route" ]; then
        printf "    %-24s %s\n" "RHOAI dashboard:" "https://${rhoai_route}"
    else
        printf "    %-24s %s\n" "RHOAI dashboard:" "(route not found — check: oc get route rhods-dashboard -n $RHOAI_NAMESPACE)"
    fi

    echo ""
    if [ -n "$mcp_route" ]; then
        printf "    %-24s %s\n" "MCP endpoint (agents):" "https://${mcp_route}/mcp/"
    fi
    printf "    %-24s %s\n" "Dev API key:" "~/.config/memoryhub/api-key"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    echo ""
    echo -e "${BOLD}MemoryHub — Full Stack Deployment${RESET}"
    echo "  $(date)"

    check_prereqs
    preflight
    deploy_postgresql
    run_migrations
    deploy_mcp
    deploy_auth
    deploy_ui
    deploy_tile
    print_summary

    local secs
    secs=$(elapsed)
    local mins=$(( secs / 60 ))
    local rem=$(( secs % 60 ))

    banner "Done"
    echo -e "  ${GREEN}Full deployment complete${RESET} in ${mins}m ${rem}s"
    echo ""
}

main "$@"
