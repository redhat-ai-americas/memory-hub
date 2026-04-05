#!/usr/bin/env bash
# Runs Alembic migrations against the in-cluster PostgreSQL by port-forwarding
# locally. Intended to be called from scripts/deploy-full.sh or manually.
#
# Usage: ./scripts/run-migrations.sh [db-namespace]
#
# The script:
#   1. Verifies the local venv has alembic installed
#   2. Checks the PostgreSQL pod is Ready
#   3. Port-forwards svc/memoryhub-pg to localhost:15432
#   4. Runs `alembic upgrade head` with MEMORYHUB_DB_* env vars
#   5. Cleans up the port-forward on exit (including errors/signals)
set -euo pipefail

DB_NAMESPACE="${1:-memoryhub-db}"
LOCAL_PORT=15432
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_ROOT}/.venv"
PF_PID=""

# ---------------------------------------------------------------------------
# Cleanup — always kill the port-forward if we started one
# ---------------------------------------------------------------------------
cleanup() {
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    echo "Stopping port-forward (pid $PF_PID)..."
    kill "$PF_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# 1. Check venv + alembic
# ---------------------------------------------------------------------------
if [[ ! -f "${VENV}/bin/alembic" ]]; then
  echo "ERROR: alembic not found in ${VENV}/bin/alembic"
  echo "       Run: python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Check PostgreSQL pod is Ready
# ---------------------------------------------------------------------------
echo "Checking PostgreSQL pod in namespace '${DB_NAMESPACE}'..."
POD_STATUS=$(oc get pod -n "$DB_NAMESPACE" \
  -l "app.kubernetes.io/name=memoryhub-pg" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

if [[ "$POD_STATUS" != "Running" ]]; then
  echo "ERROR: memoryhub-pg pod is not Running in namespace '${DB_NAMESPACE}' (got: '${POD_STATUS}')"
  echo "       Deploy PostgreSQL first: oc apply -k deploy/postgresql -n ${DB_NAMESPACE}"
  exit 1
fi
echo "  PostgreSQL pod is Running."

# ---------------------------------------------------------------------------
# 3. Start port-forward
# ---------------------------------------------------------------------------
echo "Starting port-forward: localhost:${LOCAL_PORT} -> svc/memoryhub-pg:5432..."
oc port-forward -n "$DB_NAMESPACE" svc/memoryhub-pg "${LOCAL_PORT}:5432" &
PF_PID=$!

# Wait up to 10s for the port to be available
WAITED=0
until nc -z localhost "$LOCAL_PORT" 2>/dev/null; do
  if [[ $WAITED -ge 10 ]]; then
    echo "ERROR: Port-forward did not become ready within 10 seconds."
    exit 1
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done
echo "  Port-forward ready (waited ${WAITED}s)."

# ---------------------------------------------------------------------------
# 4. Run migrations
# ---------------------------------------------------------------------------
echo "Running: alembic upgrade head"
cd "$REPO_ROOT"

MEMORYHUB_DB_HOST=localhost \
MEMORYHUB_DB_PORT=$LOCAL_PORT \
MEMORYHUB_DB_USER=memoryhub \
MEMORYHUB_DB_PASSWORD=memoryhub-dev-password \
MEMORYHUB_DB_NAME=memoryhub \
  "${VENV}/bin/alembic" upgrade head

echo ""
echo "Migrations complete."
