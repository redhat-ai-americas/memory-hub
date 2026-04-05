#!/bin/bash
# Full MemoryHub stack deployment to OpenShift.
# Usage: scripts/deploy-full.sh [--skip-db] [--skip-migrations] [--skip-mcp]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

DB_NAMESPACE="memoryhub-db"
MCP_PROJECT="memory-hub-mcp"
AUTH_PROJECT="memoryhub-auth"
DB_POD_LABEL="app.kubernetes.io/name=memoryhub-pg"

SKIP_DB=false
SKIP_MIGRATIONS=false
SKIP_MCP=false
SKIP_AUTH=false

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
            --skip-db)         SKIP_DB=true ;;
            --skip-migrations) SKIP_MIGRATIONS=true ;;
            --skip-mcp)        SKIP_MCP=true ;;
            --skip-auth)       SKIP_AUTH=true ;;
            -h|--help)
                echo "Usage: $SCRIPT_NAME [--skip-db] [--skip-migrations] [--skip-mcp] [--skip-auth]"
                echo ""
                echo "  --skip-db          Skip PostgreSQL deployment"
                echo "  --skip-migrations  Skip Alembic migrations"
                echo "  --skip-mcp         Skip MCP server deployment"
                echo "  --skip-auth        Skip Auth server deployment"
                exit 0
                ;;
            *)
                die "Unknown argument: $arg (run with --help for usage)"
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Section 0: Preflight checks
# ---------------------------------------------------------------------------
preflight() {
    banner "0. Preflight Checks"

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
}

# ---------------------------------------------------------------------------
# Section 1: PostgreSQL
# ---------------------------------------------------------------------------
deploy_postgresql() {
    banner "1. PostgreSQL"

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
    banner "2. Alembic Migrations"

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
    banner "3. MCP Server"

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
# Section 4: Verification
# ---------------------------------------------------------------------------
verify() {
    banner "4. Verification"

    local mcp_route_host mcp_route_path
    mcp_route_host=$(oc get route mcp-server -n "$MCP_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    mcp_route_path=$(oc get route mcp-server -n "$MCP_PROJECT" \
        -o jsonpath='{.spec.path}' 2>/dev/null || echo "/mcp/")

    local db_pod_status
    db_pod_status=$(oc get pod -n "$DB_NAMESPACE" -l "$DB_POD_LABEL" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "unknown")

    echo ""
    echo "  Deployment summary:"
    echo ""
    printf "    %-20s %s\n" "PostgreSQL:" "$db_pod_status  (ns: $DB_NAMESPACE)"
    printf "    %-20s %s\n" "DB connection:" \
        "memoryhub-pg.$DB_NAMESPACE.svc.cluster.local:5432"

    if [ -n "$mcp_route_host" ]; then
        printf "    %-20s %s\n" "MCP server URL:" "https://${mcp_route_host}${mcp_route_path}"
    else
        printf "    %-20s %s\n" "MCP server URL:" "(route not found — check: oc get route -n $MCP_PROJECT)"
    fi

    local auth_route_host
    auth_route_host=$(oc get route auth-server -n "$AUTH_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

    if [ -n "$auth_route_host" ]; then
        printf "    %-20s %s\n" "Auth server URL:" "https://${auth_route_host}"
    else
        printf "    %-20s %s\n" "Auth server URL:" "(route not found — check: oc get route -n $AUTH_PROJECT)"
    fi
}

# ---------------------------------------------------------------------------
# Section 3b: Auth Server
# ---------------------------------------------------------------------------
deploy_auth() {
    banner "3b. Auth Server"

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
# Main
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    echo ""
    echo -e "${BOLD}MemoryHub — Full Stack Deployment${RESET}"
    echo "  $(date)"

    preflight
    deploy_postgresql
    run_migrations
    deploy_mcp
    deploy_auth
    verify

    local secs
    secs=$(elapsed)
    local mins=$(( secs / 60 ))
    local rem=$(( secs % 60 ))

    banner "Done"
    echo -e "  ${GREEN}Full deployment complete${RESET} in ${mins}m ${rem}s"
    echo ""
}

main "$@"
