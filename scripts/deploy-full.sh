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
RESTORE_FROM=""

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

# Copy a Secret from one namespace to another, optionally renaming it.
# Idempotent: skips if the target already exists.
copy_secret() {
    local src_name=$1 src_ns=$2 dst_name=$3 dst_ns=$4
    if oc get secret "$dst_name" -n "$dst_ns" &>/dev/null; then
        info "Secret $dst_name already exists in $dst_ns"
        return 0
    fi
    info "Copying Secret $src_name from $src_ns to $dst_ns (as $dst_name)..."
    oc get secret "$src_name" -n "$src_ns" -o json | \
        python3 -c "
import json, sys
s = json.load(sys.stdin)
s['metadata'] = {'name': '$dst_name', 'namespace': '$dst_ns'}
s.pop('status', None)
json.dump(s, sys.stdout)
" | oc apply -f -
}

# Create a Secret with a random hex value if it doesn't already exist.
# Idempotent: skips if the target already exists.
ensure_random_secret() {
    local name=$1 ns=$2 key=$3
    if oc get secret "$name" -n "$ns" &>/dev/null; then
        info "Secret $name already exists in $ns"
        return 0
    fi
    info "Generating Secret $name in $ns..."
    oc create secret generic "$name" --from-literal="$key=$(openssl rand -hex 32)" -n "$ns"
}

elapsed() {
    local end_time
    end_time=$(date +%s)
    echo $(( end_time - START_TIME ))
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-prereqs)    SKIP_PREREQS=true ;;
            --skip-db)         SKIP_DB=true ;;
            --skip-migrations) SKIP_MIGRATIONS=true ;;
            --skip-mcp)        SKIP_MCP=true ;;
            --skip-auth)       SKIP_AUTH=true ;;
            --skip-ui)         SKIP_UI=true ;;
            --skip-tile)       SKIP_TILE=true ;;
            --restore-from)
                shift
                RESTORE_FROM="${1:-}"
                if [[ -z "$RESTORE_FROM" ]]; then
                    die "--restore-from requires a file path argument"
                fi
                if [[ ! -f "$RESTORE_FROM" ]]; then
                    die "Restore file not found: $RESTORE_FROM"
                fi
                ;;
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
                echo "  --restore-from F   Restore database from a pg_dump file after DB deploy"
                exit 0
                ;;
            *)
                die "Unknown argument: $1 (run with --help for usage)"
                ;;
        esac
        shift
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
    echo "    MinIO:       $([ "$SKIP_MCP" = true ] && echo "skip" || echo "deploy")"
    echo "    Valkey:      $([ "$SKIP_MCP" = true ] && echo "skip" || echo "deploy")"
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

    # Ensure namespace exists before creating the Secret
    if ! oc get namespace "$DB_NAMESPACE" &>/dev/null; then
        info "Creating namespace $DB_NAMESPACE..."
        oc create namespace "$DB_NAMESPACE"
    fi

    # Ensure DB credentials Secret exists (generate password on first install,
    # preserve on subsequent runs).  The Secret is NOT in the kustomization so
    # re-applying kustomize never overwrites an existing password.
    if ! oc get secret memoryhub-pg-credentials -n "$DB_NAMESPACE" &>/dev/null; then
        local db_pass
        db_pass=$(openssl rand -hex 16)
        info "Generating DB credentials Secret (first install)..."
        oc create secret generic memoryhub-pg-credentials \
            --from-literal=POSTGRES_USER=memoryhub \
            --from-literal=POSTGRES_PASSWORD="$db_pass" \
            --from-literal=POSTGRES_DB=memoryhub \
            -n "$DB_NAMESPACE"
        oc label secret memoryhub-pg-credentials \
            app.kubernetes.io/name=memoryhub-pg \
            app.kubernetes.io/part-of=memoryhub \
            app.kubernetes.io/component=database \
            -n "$DB_NAMESPACE"
    else
        info "Secret memoryhub-pg-credentials already exists in $DB_NAMESPACE"
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
# Section 2a: Restore from backup (optional)
# ---------------------------------------------------------------------------
restore_from_backup() {
    if [[ -z "$RESTORE_FROM" ]]; then
        return 0
    fi

    banner "2b. Restore from Backup"

    info "Restoring database from: $RESTORE_FROM"
    local restore_script="$REPO_ROOT/scripts/restore-db.sh"
    if [[ ! -f "$restore_script" ]]; then
        die "Restore script not found: $restore_script"
    fi

    if ! bash "$restore_script" --yes "$RESTORE_FROM"; then
        die "Database restore failed. Check output above."
    fi

    echo ""
    echo -e "  ${GREEN}Database restored from backup${RESET}"
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

    # Auto-read DB password from K8s Secret if not already set
    if [ -z "${MEMORYHUB_DB_PASSWORD:-}" ]; then
        info "Reading DB password from K8s Secret in $DB_NAMESPACE..."
        MEMORYHUB_DB_PASSWORD=$(oc get secret memoryhub-pg-credentials -n "$DB_NAMESPACE" \
            -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
        export MEMORYHUB_DB_PASSWORD
    fi

    info "Running $migration_script..."
    if ! bash "$migration_script"; then
        die "Migrations failed. Check output above."
    fi

    echo ""
    echo -e "  ${GREEN}Migrations complete${RESET}"
}

# ---------------------------------------------------------------------------
# Section 3b: MinIO + Valkey infrastructure (MCP dependencies)
# ---------------------------------------------------------------------------
deploy_infra() {
    banner "3b. MinIO + Valkey"

    if [ "$SKIP_MCP" = true ]; then
        skipped "Infrastructure (MCP skipped)"
        return 0
    fi

    # Ensure MCP namespace exists (MCP deploy script also does this, but we
    # need it now for MinIO/Valkey which must be ready before MCP starts)
    if ! oc get namespace "$MCP_PROJECT" &>/dev/null; then
        info "Creating namespace $MCP_PROJECT..."
        oc create namespace "$MCP_PROJECT"
    fi

    info "Deploying MinIO..."
    oc apply -k "$REPO_ROOT/deploy/minio/" -n "$MCP_PROJECT"
    oc adm policy add-scc-to-user anyuid -z memoryhub-minio -n "$MCP_PROJECT"

    info "Deploying Valkey..."
    oc apply -k "$REPO_ROOT/deploy/valkey/" -n "$MCP_PROJECT"
    oc adm policy add-scc-to-user anyuid -z memoryhub-valkey -n "$MCP_PROJECT"

    info "Waiting for MinIO rollout..."
    if ! oc rollout status deployment/memoryhub-minio -n "$MCP_PROJECT" --timeout=120s; then
        die "MinIO did not become ready. Check: oc describe deployment/memoryhub-minio -n $MCP_PROJECT"
    fi

    info "Waiting for Valkey rollout..."
    if ! oc rollout status deployment/memoryhub-valkey -n "$MCP_PROJECT" --timeout=120s; then
        die "Valkey did not become ready. Check: oc describe deployment/memoryhub-valkey -n $MCP_PROJECT"
    fi

    echo ""
    echo -e "  ${GREEN}MinIO + Valkey ready${RESET}"
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
# Section 4b: Auth infrastructure (Secrets required by the auth deployment)
# ---------------------------------------------------------------------------
prepare_auth_infra() {
    if [ "$SKIP_AUTH" = true ]; then return 0; fi

    banner "4b. Auth Infrastructure"

    if ! oc get namespace "$AUTH_PROJECT" &>/dev/null; then
        info "Creating namespace $AUTH_PROJECT..."
        oc create namespace "$AUTH_PROJECT"
    fi

    copy_secret memoryhub-pg-credentials "$DB_NAMESPACE" memoryhub-pg-credentials "$AUTH_PROJECT"
    ensure_random_secret auth-admin-key "$AUTH_PROJECT" AUTH_ADMIN_KEY

    echo -e "  ${GREEN}Auth infrastructure ready${RESET}"
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
    "$REPO_ROOT/scripts/run-seed-oauth-clients.sh"

    info "Building and deploying Auth server (project: $AUTH_PROJECT)..."
    pushd "$REPO_ROOT/memoryhub-auth" > /dev/null
    make deploy PROJECT="$AUTH_PROJECT"
    popd > /dev/null

    echo ""
    echo -e "  ${GREEN}Auth server deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 5b: UI infrastructure (namespace, ServiceAccount, Secrets)
# ---------------------------------------------------------------------------
prepare_ui_infra() {
    if [ "$SKIP_UI" = true ]; then return 0; fi

    banner "5b. UI Infrastructure"

    if ! oc get namespace "$UI_NAMESPACE" &>/dev/null; then
        info "Creating namespace $UI_NAMESPACE..."
        oc create namespace "$UI_NAMESPACE"
    fi

    # ServiceAccount for oauth-proxy sidecar
    info "Applying UI ServiceAccount..."
    oc apply -f "$REPO_ROOT/memoryhub-ui/openshift/oauth-proxy-sa.yaml" -n "$UI_NAMESPACE"

    # DB credentials for the UI BFF — must use MEMORYHUB_DB_* key names
    # (the UI's Pydantic settings uses env_prefix="MEMORYHUB_"). Cannot use
    # copy_secret here because the source Secret has POSTGRES_* keys.
    info "Creating/updating memoryhub-db-credentials in $UI_NAMESPACE..."
    local ui_db_pass
    ui_db_pass=$(oc get secret memoryhub-pg-credentials -n "$DB_NAMESPACE" \
        -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
    oc create secret generic memoryhub-db-credentials \
        --from-literal=MEMORYHUB_DB_HOST=memoryhub-pg.memoryhub-db.svc.cluster.local \
        --from-literal=MEMORYHUB_DB_PORT=5432 \
        --from-literal=MEMORYHUB_DB_NAME=memoryhub \
        --from-literal=MEMORYHUB_DB_USER=memoryhub \
        --from-literal=MEMORYHUB_DB_PASSWORD="$ui_db_pass" \
        --dry-run=client -o json | oc apply -f - -n "$UI_NAMESPACE"

    # OAuth proxy session secret (must be exactly 32 bytes, key must be "session-secret")
    if ! oc get secret memoryhub-ui-proxy -n "$UI_NAMESPACE" &>/dev/null; then
        info "Generating OAuth proxy session secret..."
        oc create secret generic memoryhub-ui-proxy \
            --from-literal="session-secret=$(openssl rand -base64 32 | head -c 32)" \
            -n "$UI_NAMESPACE"
    else
        info "Secret memoryhub-ui-proxy already exists in $UI_NAMESPACE"
    fi

    # Admin key for the UI BFF — copy from auth service's secret, remapping
    # the key name to match the UI's MEMORYHUB_ env prefix.
    if oc get secret auth-admin-key -n "$AUTH_PROJECT" &>/dev/null; then
        info "Creating/updating memoryhub-ui-admin-key in $UI_NAMESPACE..."
        local admin_key_val
        admin_key_val=$(oc get secret auth-admin-key -n "$AUTH_PROJECT" \
            -o jsonpath='{.data.AUTH_ADMIN_KEY}' | base64 -d)
        oc create secret generic memoryhub-ui-admin-key \
            --from-literal=MEMORYHUB_ADMIN_KEY="$admin_key_val" \
            --dry-run=client -o json | oc apply -f - -n "$UI_NAMESPACE"
    else
        warn "auth-admin-key not found in $AUTH_PROJECT — skipping memoryhub-ui-admin-key (deploy auth first or re-run without --skip-auth)"
    fi

    echo -e "  ${GREEN}UI infrastructure ready${RESET}"
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
    restore_from_backup
    run_migrations
    deploy_infra          # MinIO + Valkey before MCP
    deploy_mcp
    prepare_auth_infra    # Secrets before auth
    deploy_auth
    prepare_ui_infra      # SA + Secrets before UI
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
