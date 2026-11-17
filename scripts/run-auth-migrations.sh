#!/usr/bin/env bash
# Run the auth service's Alembic migrations against the chart's PostgreSQL.
# This intentionally runs outside Helm so the migration command does not need
# to be embedded in the MCP or auth runtime image.
#
# Usage: ./scripts/run-auth-migrations.sh [db-namespace] [db-secret]
set -euo pipefail

DB_NAMESPACE="${1:-memoryhub-db}"
DB_SECRET_NAME="${2:-${MEMORYHUB_DB_SECRET_NAME:-memoryhub-pg-credentials}}"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
LOCAL_PORT="${MEMORYHUB_MIGRATION_LOCAL_PORT:-15432}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUTH_ROOT="$REPO_ROOT/memoryhub-auth"
VENV="$AUTH_ROOT/.venv"
PF_PID=""

cleanup() {
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "$VENV/bin/alembic" ]]; then
  echo "ERROR: Auth Alembic is not installed in $VENV."
  echo "       Run: make -C memoryhub-auth install"
  exit 1
fi

echo "Checking PostgreSQL pod in namespace '$DB_NAMESPACE'..."
POD_STATUS=$(oc get pod --context "$CONTEXT" -n "$DB_NAMESPACE" \
  -l app.kubernetes.io/name=memoryhub-pg \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)
if [[ "$POD_STATUS" != "Running" ]]; then
  echo "ERROR: memoryhub-pg is not Running in namespace '$DB_NAMESPACE' (got '$POD_STATUS')."
  exit 1
fi

if nc -z localhost "$LOCAL_PORT" 2>/dev/null; then
  echo "ERROR: Local port $LOCAL_PORT is already in use. Set MEMORYHUB_MIGRATION_LOCAL_PORT to another port."
  exit 1
fi

echo "Starting PostgreSQL port-forward on localhost:$LOCAL_PORT..."
oc port-forward --context "$CONTEXT" -n "$DB_NAMESPACE" \
  svc/memoryhub-pg "$LOCAL_PORT:5432" &
PF_PID=$!

WAITED=0
until nc -z localhost "$LOCAL_PORT" 2>/dev/null; do
  if ! kill -0 "$PF_PID" 2>/dev/null || [[ $WAITED -ge 15 ]]; then
    echo "ERROR: PostgreSQL port-forward did not become ready."
    exit 1
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done

DB_USER="${AUTH_DB_USER:-${MEMORYHUB_DB_USER:-$(oc get secret "$DB_SECRET_NAME" --context "$CONTEXT" -n "$DB_NAMESPACE" -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)}}"
DB_NAME="${AUTH_DB_NAME:-${MEMORYHUB_DB_NAME:-$(oc get secret "$DB_SECRET_NAME" --context "$CONTEXT" -n "$DB_NAMESPACE" -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)}}"
DB_PASSWORD="${AUTH_DB_PASSWORD:-${MEMORYHUB_DB_PASSWORD:-$(oc get secret "$DB_SECRET_NAME" --context "$CONTEXT" -n "$DB_NAMESPACE" -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)}}"
: "${DB_USER:?Could not read POSTGRES_USER from Secret ${DB_NAMESPACE}/${DB_SECRET_NAME}}"
: "${DB_NAME:?Could not read POSTGRES_DB from Secret ${DB_NAMESPACE}/${DB_SECRET_NAME}}"
: "${DB_PASSWORD:?Could not read POSTGRES_PASSWORD from Secret ${DB_NAMESPACE}/${DB_SECRET_NAME}}"

echo "Running auth database migrations..."
cd "$AUTH_ROOT"
AUTH_DB_HOST=localhost \
AUTH_DB_PORT="$LOCAL_PORT" \
AUTH_DB_USER="$DB_USER" \
AUTH_DB_PASSWORD="$DB_PASSWORD" \
AUTH_DB_NAME="$DB_NAME" \
  "$VENV/bin/alembic" -c "$AUTH_ROOT/alembic.ini" upgrade head

echo "Auth database migrations complete."
