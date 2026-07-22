#!/bin/bash
# Full MemoryHub stack deployment to OpenShift.
# Usage: scripts/deploy-full.sh [--skip-prereqs] [--skip-db] [--skip-migrations]
#                                [--skip-mcp] [--skip-auth] [--skip-ui] [--skip-tile]
#                                [--skip-models] [--gpu-models]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
CONTEXT="${MEMORYHUB_CONTEXT:-$(oc config current-context 2>/dev/null)}"
export MEMORYHUB_CONTEXT="$CONTEXT"

DB_NAMESPACE="memoryhub-db"
MCP_PROJECT="memory-hub-mcp"
AUTH_PROJECT="memoryhub-auth"
UI_NAMESPACE="memoryhub-ui"
RHOAI_NAMESPACE="redhat-ods-applications"
EMBEDDING_MODEL_NAMESPACE="embedding-model"
RERANKER_MODEL_NAMESPACE="reranker-model"
DB_POD_LABEL="app.kubernetes.io/name=memoryhub-pg"

SKIP_PREREQS=false
SKIP_DB=false
SKIP_MIGRATIONS=false
SKIP_MCP=false
SKIP_AUTH=false
SKIP_UI=false
SKIP_TILE=false
SKIP_MODELS=false
GPU_MODELS=false
SKIP_SMOKE_TEST=false
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
    if oc get secret --context "$CONTEXT" "$dst_name" -n "$dst_ns" &>/dev/null; then
        info "Secret $dst_name already exists in $dst_ns"
        return 0
    fi
    info "Copying Secret $src_name from $src_ns to $dst_ns (as $dst_name)..."
    oc get secret --context "$CONTEXT" "$src_name" -n "$src_ns" -o json | \
        python3 -c "
import json, sys
s = json.load(sys.stdin)
s['metadata'] = {'name': '$dst_name', 'namespace': '$dst_ns'}
s.pop('status', None)
json.dump(s, sys.stdout)
" | oc apply --context "$CONTEXT" -f -
}

# Create a Secret with a random hex value if it doesn't already exist.
# Idempotent: skips if the target already exists.
ensure_random_secret() {
    local name=$1 ns=$2 key=$3
    if oc get secret --context "$CONTEXT" "$name" -n "$ns" &>/dev/null; then
        info "Secret $name already exists in $ns"
        return 0
    fi
    info "Generating Secret $name in $ns..."
    oc create secret --context "$CONTEXT" generic "$name" --from-literal="$key=$(openssl rand -hex 32)" -n "$ns"
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
            --skip-models)     SKIP_MODELS=true ;;
            --gpu-models)      GPU_MODELS=true ;;
            --skip-smoke-test) SKIP_SMOKE_TEST=true ;;
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
                echo "  --skip-models      Skip embedding + reranker model deployment"
                echo "  --gpu-models       Use GPU model manifests instead of CPU (default: CPU)"
                echo "  --skip-smoke-test  Skip post-deploy write/search/read verification"
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
    if ! oc whoami --context "$CONTEXT" &>/dev/null; then
        die "Not logged in to OpenShift. Run 'oc login' first."
    fi
    echo "     Logged in as: $(oc whoami --context "$CONTEXT")"
    echo "     Server:       $(oc whoami --context "$CONTEXT" --show-server)"

    info "Verifying .venv and alembic..."
    if [ ! -d "$REPO_ROOT/.venv" ] || ! "$REPO_ROOT/.venv/bin/alembic" --version &>/dev/null; then
        info "Creating .venv (required for migrations)..."
        python3 -m venv "$REPO_ROOT/.venv"
        "$REPO_ROOT/.venv/bin/pip" install --upgrade pip -q
        "$REPO_ROOT/.venv/bin/pip" install -e "$REPO_ROOT" -q
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
    echo "    Models:      $([ "$SKIP_MODELS" = true ] && echo "skip" || ([ "$GPU_MODELS" = true ] && echo "deploy (GPU)" || echo "deploy (CPU)"))"
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
    if ! oc get namespace --context "$CONTEXT" "$DB_NAMESPACE" &>/dev/null; then
        info "Creating namespace $DB_NAMESPACE..."
        oc create namespace --context "$CONTEXT" "$DB_NAMESPACE"
    fi

    # Ensure DB credentials Secret exists (generate password on first install,
    # preserve on subsequent runs).  The Secret is NOT in the kustomization so
    # re-applying kustomize never overwrites an existing password.
    if ! oc get secret --context "$CONTEXT" memoryhub-pg-credentials -n "$DB_NAMESPACE" &>/dev/null; then
        local db_pass
        db_pass=$(openssl rand -hex 16)
        info "Generating DB credentials Secret (first install)..."
        oc create secret --context "$CONTEXT" generic memoryhub-pg-credentials \
            --from-literal=POSTGRES_USER=memoryhub \
            --from-literal=POSTGRES_PASSWORD="$db_pass" \
            --from-literal=POSTGRES_DB=memoryhub \
            -n "$DB_NAMESPACE"
        oc label secret --context "$CONTEXT" memoryhub-pg-credentials \
            app.kubernetes.io/name=memoryhub-pg \
            app.kubernetes.io/part-of=memoryhub \
            app.kubernetes.io/component=database \
            -n "$DB_NAMESPACE"
    else
        info "Secret memoryhub-pg-credentials already exists in $DB_NAMESPACE"
    fi

    info "Applying kustomize manifests..."
    oc apply --context "$CONTEXT" -k "$REPO_ROOT/deploy/postgresql/"

    info "Granting anyuid SCC to default service account..."
    # idempotent — oc adm policy --context "$CONTEXT" exits 0 whether or not the grant was new
    oc adm policy --context "$CONTEXT" add-scc-to-user anyuid -z default -n "$DB_NAMESPACE"

    # If the pod already existed before the SCC grant, it may be stuck.
    # Check if the pod is in a bad state and delete it so it restarts with the SCC.
    local pod_phase
    pod_phase=$(oc get pod --context "$CONTEXT" -n "$DB_NAMESPACE" -l "$DB_POD_LABEL" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

    if [ -n "$pod_phase" ] && [ "$pod_phase" != "Running" ]; then
        warn "PostgreSQL pod is in '$pod_phase' state — deleting so it restarts with updated SCC..."
        oc delete pod --context "$CONTEXT" -n "$DB_NAMESPACE" -l "$DB_POD_LABEL" --ignore-not-found
    fi

    info "Waiting for PostgreSQL pod to be ready (timeout: 120s)..."
    if ! oc wait --context "$CONTEXT" --for=condition=ready pod -l "$DB_POD_LABEL" \
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
        MEMORYHUB_DB_PASSWORD=$(oc get secret --context "$CONTEXT" memoryhub-pg-credentials -n "$DB_NAMESPACE" \
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
    if ! oc get namespace --context "$CONTEXT" "$MCP_PROJECT" &>/dev/null; then
        info "Creating namespace $MCP_PROJECT..."
        oc create namespace --context "$CONTEXT" "$MCP_PROJECT"
    fi

    info "Deploying MinIO..."
    oc apply --context "$CONTEXT" -k "$REPO_ROOT/deploy/minio/" -n "$MCP_PROJECT"
    oc adm policy --context "$CONTEXT" add-scc-to-user anyuid -z memoryhub-minio -n "$MCP_PROJECT"

    info "Deploying Valkey..."
    oc apply --context "$CONTEXT" -k "$REPO_ROOT/deploy/valkey/" -n "$MCP_PROJECT"
    oc adm policy --context "$CONTEXT" add-scc-to-user anyuid -z memoryhub-valkey -n "$MCP_PROJECT"

    info "Waiting for MinIO rollout..."
    if ! oc rollout --context "$CONTEXT" status deployment/memoryhub-minio -n "$MCP_PROJECT" --timeout=120s; then
        die "MinIO did not become ready. Check: oc describe deployment/memoryhub-minio -n $MCP_PROJECT"
    fi

    info "Waiting for Valkey rollout..."
    if ! oc rollout --context "$CONTEXT" status deployment/memoryhub-valkey -n "$MCP_PROJECT" --timeout=120s; then
        die "Valkey did not become ready. Check: oc describe deployment/memoryhub-valkey -n $MCP_PROJECT"
    fi

    echo ""
    echo -e "  ${GREEN}MinIO + Valkey ready${RESET}"
}

# ---------------------------------------------------------------------------
# Section 3d: Embedding + Reranker Models
# ---------------------------------------------------------------------------
deploy_models() {
    banner "3d. Embedding + Reranker Models"

    if [ "$SKIP_MODELS" = true ]; then
        skipped "Models (--skip-models)"
        return 0
    fi

    local embedding_dir="$REPO_ROOT/deploy/embedding"
    local reranker_dir="$REPO_ROOT/deploy/reranker"

    if [ "$GPU_MODELS" = true ]; then
        embedding_dir="$REPO_ROOT/deploy/embedding-gpu"
        reranker_dir="$REPO_ROOT/deploy/reranker-gpu"
        info "Using GPU model manifests"
    else
        info "Using CPU model manifests (default)"
    fi

    # Create namespaces
    for ns in "$EMBEDDING_MODEL_NAMESPACE" "$RERANKER_MODEL_NAMESPACE"; do
        if ! oc get namespace --context "$CONTEXT" "$ns" &>/dev/null; then
            info "Creating namespace $ns..."
            oc create namespace --context "$CONTEXT" "$ns"
        fi
    done

    info "Deploying embedding model..."
    oc apply --context "$CONTEXT" -k "$embedding_dir"

    info "Deploying reranker model..."
    oc apply --context "$CONTEXT" -k "$reranker_dir"

    info "Waiting for embedding model rollout (model download may take 2-3 min)..."
    local embedding_deploy
    embedding_deploy=$(oc get deploy --context "$CONTEXT" -n "$EMBEDDING_MODEL_NAMESPACE" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$embedding_deploy" ]; then
        if ! oc rollout status --context "$CONTEXT" "deployment/$embedding_deploy" \
                -n "$EMBEDDING_MODEL_NAMESPACE" --timeout=300s; then
            die "Embedding model did not become ready within 300s."
        fi
    fi

    info "Waiting for reranker model rollout..."
    local reranker_deploy
    reranker_deploy=$(oc get deploy --context "$CONTEXT" -n "$RERANKER_MODEL_NAMESPACE" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
    if [ -n "$reranker_deploy" ]; then
        if ! oc rollout status --context "$CONTEXT" "deployment/$reranker_deploy" \
                -n "$RERANKER_MODEL_NAMESPACE" --timeout=300s; then
            die "Reranker model did not become ready within 300s."
        fi
    fi

    echo ""
    echo -e "  ${GREEN}Models deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 3c: Retention Enforcement CronJob
# ---------------------------------------------------------------------------
deploy_retention_cronjob() {
    banner "3c. Retention Enforcement CronJob"

    if [ "$SKIP_DB" = true ]; then
        skipped "Retention CronJob (DB skipped)"
        return 0
    fi

    info "Deploying retention sweep CronJob..."
    oc apply --context "$CONTEXT" -f "$REPO_ROOT/deploy/retention/cronjob.yaml" -n "$MCP_PROJECT"
    echo ""
    echo -e "  ${GREEN}Retention CronJob deployed${RESET}"
}

# ---------------------------------------------------------------------------
# Section 4: MCP Server
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

    if ! oc get namespace --context "$CONTEXT" "$AUTH_PROJECT" &>/dev/null; then
        info "Creating namespace $AUTH_PROJECT..."
        oc create namespace --context "$CONTEXT" "$AUTH_PROJECT"
    fi

    copy_secret memoryhub-pg-credentials "$DB_NAMESPACE" memoryhub-pg-credentials "$AUTH_PROJECT"
    ensure_random_secret auth-admin-key "$AUTH_PROJECT" AUTH_ADMIN_KEY
    ensure_random_secret auth-internal-service-key "$AUTH_PROJECT" AUTH_INTERNAL_SERVICE_KEY

    # Copy the internal service key to MCP namespace so the MCP server can
    # call the auth service's /internal/validate-api-key endpoint.
    copy_secret auth-internal-service-key "$AUTH_PROJECT" auth-internal-service-key "$MCP_PROJECT"

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
    # Auto-generate seed-clients.json from the users ConfigMap if it doesn't exist.
    local seed_json="$REPO_ROOT/scripts/seed-clients.json"
    if [ ! -f "$seed_json" ]; then
        local users_cm="$REPO_ROOT/memory-hub-mcp/deploy/users-configmap.yaml"
        if [ -f "$users_cm" ]; then
            info "Generating $seed_json from users ConfigMap..."
            "$REPO_ROOT/.venv/bin/python" -c "
import json, sys, yaml, pathlib
with open(sys.argv[1]) as f:
    cm = yaml.safe_load(f)
users = json.loads(cm['data']['users.json'])['users']
clients = []
for u in users:
    identity_type = u.get('identity_type', 'user')
    scopes = ['memory:read', 'memory:write:user']
    if 'organizational' in u.get('scopes', []):
        scopes.append('memory:write:organizational')
    if 'enterprise' in u.get('scopes', []):
        scopes.append('memory:write:enterprise')
    clients.append({
        'client_id': u['user_id'],
        'client_secret': u['api_key'],
        'client_name': u.get('name', u['user_id']),
        'identity_type': identity_type,
        'tenant_id': u.get('tenant_id', 'default'),
        'default_scopes': scopes,
    })
pathlib.Path(sys.argv[2]).write_text(json.dumps(clients, indent=2))
print(f'  Generated {len(clients)} OAuth clients from users ConfigMap.')
" "$users_cm" "$seed_json"
        fi
    fi
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

    if ! oc get namespace --context "$CONTEXT" "$UI_NAMESPACE" &>/dev/null; then
        info "Creating namespace $UI_NAMESPACE..."
        oc create namespace --context "$CONTEXT" "$UI_NAMESPACE"
    fi

    # ServiceAccount for oauth-proxy sidecar
    info "Applying UI ServiceAccount..."
    oc apply --context "$CONTEXT" -f "$REPO_ROOT/memoryhub-ui/openshift/oauth-proxy-sa.yaml" -n "$UI_NAMESPACE"

    # DB credentials for the UI BFF — must use MEMORYHUB_DB_* key names
    # (the UI's Pydantic settings uses env_prefix="MEMORYHUB_"). Cannot use
    # copy_secret here because the source Secret has POSTGRES_* keys.
    info "Creating/updating memoryhub-db-credentials in $UI_NAMESPACE..."
    local ui_db_pass
    ui_db_pass=$(oc get secret --context "$CONTEXT" memoryhub-pg-credentials -n "$DB_NAMESPACE" \
        -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
    oc create secret --context "$CONTEXT" generic memoryhub-db-credentials \
        --from-literal=MEMORYHUB_DB_HOST=memoryhub-pg.memoryhub-db.svc.cluster.local \
        --from-literal=MEMORYHUB_DB_PORT=5432 \
        --from-literal=MEMORYHUB_DB_NAME=memoryhub \
        --from-literal=MEMORYHUB_DB_USER=memoryhub \
        --from-literal=MEMORYHUB_DB_PASSWORD="$ui_db_pass" \
        --dry-run=client -o json | oc apply --context "$CONTEXT" -f - -n "$UI_NAMESPACE"

    # OAuth proxy session secret (must be exactly 32 bytes, key must be "session-secret")
    if ! oc get secret --context "$CONTEXT" memoryhub-ui-proxy -n "$UI_NAMESPACE" &>/dev/null; then
        info "Generating OAuth proxy session secret..."
        oc create secret --context "$CONTEXT" generic memoryhub-ui-proxy \
            --from-literal="session-secret=$(openssl rand -base64 32 | head -c 32)" \
            -n "$UI_NAMESPACE"
    else
        info "Secret memoryhub-ui-proxy already exists in $UI_NAMESPACE"
    fi

    # Admin key for the UI BFF — copy from auth service's secret, remapping
    # the key name to match the UI's MEMORYHUB_ env prefix.
    if oc get secret --context "$CONTEXT" auth-admin-key -n "$AUTH_PROJECT" &>/dev/null; then
        info "Creating/updating memoryhub-ui-admin-key in $UI_NAMESPACE..."
        local admin_key_val
        admin_key_val=$(oc get secret --context "$CONTEXT" auth-admin-key -n "$AUTH_PROJECT" \
            -o jsonpath='{.data.AUTH_ADMIN_KEY}' | base64 -d)
        oc create secret --context "$CONTEXT" generic memoryhub-ui-admin-key \
            --from-literal=MEMORYHUB_ADMIN_KEY="$admin_key_val" \
            --dry-run=client -o json | oc apply --context "$CONTEXT" -f - -n "$UI_NAMESPACE"
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

    if oc get crd odhapplications.dashboard.opendatahub.io --context "$CONTEXT" &>/dev/null; then
        info "Applying OdhApplication CR to $RHOAI_NAMESPACE..."
        if ! oc apply --context "$CONTEXT" -f "$odh_manifest" -n "$RHOAI_NAMESPACE"; then
            die "Failed to apply OdhApplication manifest."
        fi
        echo ""
        echo -e "  ${GREEN}RHOAI tile applied${RESET}"
    else
        warn "OdhApplication CRD not found — skipping dashboard tile (non-blocking)"
        echo ""
        echo -e "  ${YELLOW}RHOAI tile skipped (CRD not available)${RESET}"
    fi
}

# ---------------------------------------------------------------------------
# Section 7b: Configure local client (API key for CLI/SDK)
# ---------------------------------------------------------------------------
configure_local_client() {
    local api_key_file="$HOME/.config/memoryhub/api-key"
    if [ -f "$api_key_file" ]; then
        info "API key already exists at $api_key_file"
        return 0
    fi

    local users_cm="$REPO_ROOT/memory-hub-mcp/deploy/users-configmap.yaml"
    if [ ! -f "$users_cm" ]; then return 0; fi

    local key user_id
    key=$("$REPO_ROOT/.venv/bin/python" -c "
import json, sys, yaml
with open(sys.argv[1]) as f:
    cm = yaml.safe_load(f)
users = json.loads(cm['data']['users.json'])
print(users['users'][0]['api_key'])
" "$users_cm" 2>/dev/null || echo "")

    if [ -n "$key" ] && [[ "$key" != REPLACE-ME* ]]; then
        user_id=$("$REPO_ROOT/.venv/bin/python" -c "
import json, sys, yaml
with open(sys.argv[1]) as f:
    cm = yaml.safe_load(f)
users = json.loads(cm['data']['users.json'])
print(users['users'][0]['user_id'])
" "$users_cm" 2>/dev/null || echo "unknown")
        mkdir -p "$HOME/.config/memoryhub"
        echo -n "$key" > "$api_key_file"
        chmod 600 "$api_key_file"
        info "Wrote API key to $api_key_file (user: $user_id)"
    fi
}

# ---------------------------------------------------------------------------
# Section 8: Smoke Test
# ---------------------------------------------------------------------------
smoke_test() {
    banner "8. Smoke Test"

    if [ "$SKIP_SMOKE_TEST" = true ]; then
        skipped "Smoke test (--skip-smoke-test)"
        return 0
    fi

    local mcp_route
    mcp_route=$(oc get route --context "$CONTEXT" memory-hub-mcp -n "$MCP_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    if [ -z "$mcp_route" ]; then
        warn "MCP route not found -- skipping smoke test"
        return 0
    fi
    local mcp_url="https://${mcp_route}/mcp/"

    local api_key_file="$HOME/.config/memoryhub/api-key"
    if [ ! -f "$api_key_file" ]; then
        warn "No API key at $api_key_file -- skipping smoke test"
        return 0
    fi
    local api_key
    api_key=$(cat "$api_key_file")

    if ! command -v memoryhub &>/dev/null; then
        warn "memoryhub CLI not installed -- skipping smoke test"
        warn "Install with: pip install memoryhub-cli"
        return 0
    fi

    export MEMORYHUB_URL="$mcp_url"
    export MEMORYHUB_API_KEY="$api_key"

    info "Writing test memory..."
    local write_output memory_id
    write_output=$(memoryhub write "MemoryHub smoke test $(date -u +%Y%m%dT%H%M%SZ)" \
        --scope user --weight 0.5 -o json 2>&1) || {
        warn "Write failed: $write_output"
        return 0
    }
    memory_id=$(echo "$write_output" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
    if [ -z "$memory_id" ]; then
        warn "Could not parse write response"
        return 0
    fi
    info "  Written: $memory_id"

    info "Searching..."
    local search_output search_count
    search_output=$(memoryhub search "smoke test" --max-results 3 -o json 2>&1) || true
    search_count=$(echo "$search_output" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('results',[])))" 2>/dev/null || echo "0")
    info "  Search returned $search_count results"

    info "Reading back..."
    memoryhub read "$memory_id" -o quiet 2>/dev/null || warn "Read failed"
    info "  Read OK"

    info "Cleaning up..."
    memoryhub delete "$memory_id" -o quiet 2>/dev/null || true
    info "  Deleted test memory"

    echo ""
    echo -e "  ${GREEN}Smoke test passed${RESET}"
}

# ---------------------------------------------------------------------------
# Summary banner
# ---------------------------------------------------------------------------
print_summary() {
    banner "Deployment Summary"

    local cluster_url current_user
    cluster_url=$(oc whoami --context "$CONTEXT" --show-server 2>/dev/null || echo "(unavailable)")
    current_user=$(oc whoami --context "$CONTEXT" 2>/dev/null || echo "(unavailable)")

    local ui_route mcp_route auth_route rhoai_route
    ui_route=$(oc get route --context "$CONTEXT" memoryhub-ui -n "$UI_NAMESPACE" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    mcp_route=$(oc get route --context "$CONTEXT" memory-hub-mcp -n "$MCP_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    auth_route=$(oc get route --context "$CONTEXT" auth-server -n "$AUTH_PROJECT" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    rhoai_route=$(oc get route --context "$CONTEXT" rhods-dashboard -n "$RHOAI_NAMESPACE" \
        -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

    echo ""
    printf "    %-24s %s\n" "Cluster:" "$cluster_url"
    printf "    %-24s %s\n" "User:" "$current_user"
    echo ""

    if [ -n "$ui_route" ]; then
        printf "    %-24s %s\n" "UI:" "https://${ui_route}"
    else
        printf "    %-24s %s\n" "UI:" "(route not found — check: oc get route --context "$CONTEXT" memoryhub-ui -n $UI_NAMESPACE)"
    fi

    if [ -n "$mcp_route" ]; then
        printf "    %-24s %s\n" "MCP server:" "https://${mcp_route}/mcp/"
    else
        printf "    %-24s %s\n" "MCP server:" "(route not found — check: oc get route --context "$CONTEXT" -n $MCP_PROJECT)"
    fi

    if [ -n "$auth_route" ]; then
        printf "    %-24s %s\n" "Auth server:" "https://${auth_route}"
    else
        printf "    %-24s %s\n" "Auth server:" "(route not found — check: oc get route --context "$CONTEXT" auth-server -n $AUTH_PROJECT)"
    fi

    if [ -n "$rhoai_route" ]; then
        printf "    %-24s %s\n" "RHOAI dashboard:" "https://${rhoai_route}"
    else
        printf "    %-24s %s\n" "RHOAI dashboard:" "(route not found — check: oc get route --context "$CONTEXT" rhods-dashboard -n $RHOAI_NAMESPACE)"
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
    deploy_infra              # MinIO + Valkey before MCP
    deploy_models             # Embedding + Reranker before MCP
    deploy_retention_cronjob  # Retention sweep after DB
    prepare_auth_infra        # Secrets before auth
    deploy_auth               # Auth BEFORE MCP (so auth route exists)
    deploy_mcp                # MCP (auth route now available for JWKS URL)
    configure_local_client    # Write API key for CLI/SDK
    prepare_ui_infra          # SA + Secrets before UI
    deploy_ui
    deploy_tile
    print_summary
    smoke_test

    local secs
    secs=$(elapsed)
    local mins=$(( secs / 60 ))
    local rem=$(( secs % 60 ))

    banner "Done"
    echo -e "  ${GREEN}Full deployment complete${RESET} in ${mins}m ${rem}s"
    echo ""
}

main "$@"
