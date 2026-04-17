#!/bin/bash
# Runs seed-oauth-clients.py against the in-cluster PostgreSQL by port-forwarding
# locally. Intended to be called from scripts/deploy-full.sh.
#
# Usage: ./scripts/run-seed-oauth-clients.sh [db-namespace]
#
# The script:
#   1. Verifies the PostgreSQL pod is Ready
#   2. Port-forwards svc/memoryhub-pg to localhost:15432
#   3. Runs seed-oauth-clients.py with MEMORYHUB_DB_* env vars
#   4. Cleans up the port-forward on exit (including errors/signals)
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
# 1. Check PostgreSQL pod is Ready
# ---------------------------------------------------------------------------
echo "Checking PostgreSQL pod in namespace '${DB_NAMESPACE}'..."
POD_STATUS=$(oc get pod -n "$DB_NAMESPACE" \
  -l "app.kubernetes.io/name=memoryhub-pg" \
  -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

if [[ "$POD_STATUS" != "Running" ]]; then
  echo "ERROR: memoryhub-pg pod is not Running in namespace '${DB_NAMESPACE}' (got: '${POD_STATUS}')"
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Start port-forward
# ---------------------------------------------------------------------------
echo "Starting port-forward: localhost:${LOCAL_PORT} -> svc/memoryhub-pg:5432..."
oc port-forward -n "$DB_NAMESPACE" svc/memoryhub-pg "${LOCAL_PORT}:5432" &
PF_PID=$!

# Give port-forward time to start
sleep 1

# ---------------------------------------------------------------------------
# 3. Run seed script with DB env vars
# ---------------------------------------------------------------------------
export MEMORYHUB_DB_HOST=localhost
export MEMORYHUB_DB_PORT=$LOCAL_PORT
export MEMORYHUB_DB_NAME=memoryhub
export MEMORYHUB_DB_USER=memoryhub

# Read password from K8s Secret
echo "Reading DB password from K8s Secret in ${DB_NAMESPACE}..."
export MEMORYHUB_DB_PASSWORD=$(oc get secret memoryhub-pg-credentials -n "$DB_NAMESPACE" \
  -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)

echo "Running seed script..."
"$VENV/bin/python" "$REPO_ROOT/scripts/seed-oauth-clients.py"
