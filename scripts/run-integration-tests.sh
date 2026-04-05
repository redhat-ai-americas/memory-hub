#!/usr/bin/env bash
# Starts PostgreSQL + pgvector, runs integration tests, then stops PostgreSQL.
# Usage: ./scripts/run-integration-tests.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/tests/integration/compose.yaml"
VENV="$REPO_ROOT/.venv"

echo "Starting PostgreSQL + pgvector..."
podman-compose -f "$COMPOSE_FILE" up -d --wait

echo "Running integration tests..."
MEMORYHUB_DB_HOST=localhost \
MEMORYHUB_DB_PORT=15433 \
MEMORYHUB_DB_USER=memoryhub \
MEMORYHUB_DB_PASSWORD=memoryhub-test \
MEMORYHUB_DB_NAME=memoryhub \
  "$VENV/bin/pytest" tests/integration/ -v --tb=short
EXIT_CODE=$?

echo "Stopping PostgreSQL..."
podman-compose -f "$COMPOSE_FILE" down

exit $EXIT_CODE
