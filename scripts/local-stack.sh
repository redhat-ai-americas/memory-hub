#!/usr/bin/env bash
# Manage the local governed MemoryHub stack.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/compose.yaml"
COMPOSE=( )

die() {
    echo "ERROR: $*" >&2
    exit 1
}

find_compose() {
    if [ -n "${MEMORYHUB_COMPOSE_COMMAND:-}" ]; then
        # shellcheck disable=SC2206
        COMPOSE=( ${MEMORYHUB_COMPOSE_COMMAND} )
        return
    fi
    if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
        COMPOSE=(podman compose)
    elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v podman-compose >/dev/null 2>&1; then
        COMPOSE=(podman-compose)
    else
        die "install Docker Compose or Podman Compose first"
    fi
}

compose() {
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" "$@"
}

prepare_contexts() {
    bash "$REPO_ROOT/memory-hub-mcp/deploy/build-context.sh" >/dev/null
    bash "$REPO_ROOT/memoryhub-ui/deploy/build-context.sh" >/dev/null
}

ensure_python_env() {
    if [ -x "$REPO_ROOT/.venv/bin/alembic" ]; then
        return
    fi
    command -v python3 >/dev/null 2>&1 || die "python3 is required to run migrations"
    echo "Creating the root Python environment for migrations..."
    python3 -m venv "$REPO_ROOT/.venv"
    "$REPO_ROOT/.venv/bin/pip" install --upgrade pip
    "$REPO_ROOT/.venv/bin/pip" install -e "$REPO_ROOT"
}

wait_for_postgres() {
    local attempt
    for attempt in $(seq 1 30); do
        if compose exec -T postgres pg_isready -U memoryhub -d memoryhub >/dev/null 2>&1; then
            return
        fi
        sleep 2
    done
    die "PostgreSQL did not become ready"
}

run_migrations() {
    MEMORYHUB_DB_HOST=localhost \
    MEMORYHUB_DB_PORT=5432 \
    MEMORYHUB_DB_NAME=memoryhub \
    MEMORYHUB_DB_USER=memoryhub \
    MEMORYHUB_DB_PASSWORD=memoryhub-local \
        "$REPO_ROOT/.venv/bin/alembic" -c "$REPO_ROOT/alembic.ini" upgrade head
}

start_stack() {
    prepare_contexts
    compose up -d postgres
    wait_for_postgres
    run_migrations
    compose up -d --build mcp ui
    echo "Local MemoryHub stack is running:"
    echo "  UI:  http://localhost:8080"
    echo "  MCP: http://localhost:18080/mcp/"
}

find_compose
case "${1:-}" in
    install|up)
        ensure_python_env
        start_stack
        ;;
    down)
        compose down
        ;;
    logs)
        shift
        compose logs "$@"
        ;;
    auth-up)
        prepare_contexts
        compose up -d postgres
        wait_for_postgres
        compose --profile auth build auth
        compose --profile auth run --rm auth alembic -c alembic.ini upgrade head
        compose --profile auth up -d auth
        echo "Local auth service is running at http://localhost:18081"
        ;;
    *)
        echo "Usage: $0 {install|up|down|logs|auth-up}" >&2
        exit 2
        ;;
esac
