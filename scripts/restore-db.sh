#!/usr/bin/env bash
# Restore a MemoryHub PostgreSQL dump into the running DB pod.
# This is a destructive operation — existing data will be replaced.
#
# Usage: scripts/restore-db.sh [--yes] <dump-file>
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

DB_NAMESPACE="memoryhub-db"
POD_LABEL="app.kubernetes.io/name=memoryhub-pg"
CONTAINER="postgresql"
SECRET_NAME="memoryhub-pg-credentials"

YES=false
DUMP_FILE=""

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

info()  { echo -e "  ${GREEN}→${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET} $*"; }
die()   { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes)
                YES=true
                shift
                ;;
            -h|--help)
                echo "Usage: $SCRIPT_NAME [--yes] <dump-file>"
                echo ""
                echo "  <dump-file>   Path to a pg_dump custom-format (.dump) file"
                echo "  --yes         Skip confirmation prompt (non-interactive / scripted use)"
                echo ""
                echo "Restores the dump into the running MemoryHub PostgreSQL instance via oc exec."
                echo "Uses pg_restore --clean --if-exists, which drops existing objects before"
                echo "recreating them. Existing memories will be replaced."
                exit 0
                ;;
            -*)
                die "Unknown flag: $1 (run with --help for usage)"
                ;;
            *)
                if [[ -n "$DUMP_FILE" ]]; then
                    die "Unexpected argument: $1 (dump file already set to '$DUMP_FILE')"
                fi
                DUMP_FILE="$1"
                shift
                ;;
        esac
    done

    if [[ -z "$DUMP_FILE" ]]; then
        echo "Usage: $SCRIPT_NAME [--yes] <dump-file>" >&2
        die "Dump file path is required."
    fi
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
preflight() {
    banner "Preflight"

    info "Validating dump file..."
    if [[ ! -f "$DUMP_FILE" ]]; then
        die "File not found: $DUMP_FILE"
    fi
    if [[ ! -r "$DUMP_FILE" ]]; then
        die "File is not readable: $DUMP_FILE"
    fi
    echo "     Dump file: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

    info "Verifying OpenShift login..."
    if ! oc whoami &>/dev/null; then
        die "Not logged in to OpenShift. Run 'oc login' first."
    fi
    echo "     Logged in as: $(oc whoami)"
    echo "     Server:       $(oc whoami --show-server)"

    info "Locating PostgreSQL pod..."
    PG_POD="$(oc get pod -n "$DB_NAMESPACE" \
        -l "$POD_LABEL" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    if [[ -z "$PG_POD" ]]; then
        die "No pod found in namespace '$DB_NAMESPACE' with label '$POD_LABEL'. Is the DB deployed?"
    fi
    POD_PHASE="$(oc get pod "$PG_POD" -n "$DB_NAMESPACE" \
        -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    if [[ "$POD_PHASE" != "Running" ]]; then
        die "Pod '$PG_POD' is in phase '$POD_PHASE', expected 'Running'."
    fi
    echo "     Pod: $PG_POD (Running)"

    info "Reading credentials from secret '$SECRET_NAME'..."
    PG_USER="$(oc get secret "$SECRET_NAME" -n "$DB_NAMESPACE" \
        -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)"
    PG_PASSWORD="$(oc get secret "$SECRET_NAME" -n "$DB_NAMESPACE" \
        -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)"
    PG_DB="$(oc get secret "$SECRET_NAME" -n "$DB_NAMESPACE" \
        -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)"

    if [[ -z "$PG_USER" || -z "$PG_PASSWORD" || -z "$PG_DB" ]]; then
        die "One or more credentials are empty in secret '$SECRET_NAME'."
    fi
    echo "     Database: $PG_DB  (user: $PG_USER)"
}

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------
confirm() {
    echo ""
    echo -e "  ${RED}${BOLD}DESTRUCTIVE OPERATION${RESET}"
    echo ""
    echo "  This will overwrite the existing database. Existing memories will be replaced."
    echo ""
    echo "    Target namespace : $DB_NAMESPACE"
    echo "    Target pod       : $PG_POD"
    echo "    Target database  : $PG_DB"
    echo "    Dump file        : $DUMP_FILE"
    echo ""

    if [[ "$YES" = true ]]; then
        warn "--yes flag set; skipping confirmation."
        return 0
    fi

    read -r -p "  Type 'y' to proceed, anything else cancels: " answer
    echo ""
    if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
        echo "  Cancelled. No changes made."
        exit 0
    fi
}

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
restore() {
    banner "Restore"

    info "Streaming dump into pod and running pg_restore..."
    cat "$DUMP_FILE" | oc exec -i "$PG_POD" \
        -n "$DB_NAMESPACE" \
        -c "$CONTAINER" \
        -- env PGPASSWORD="$PG_PASSWORD" \
        pg_restore --clean --if-exists -U "$PG_USER" -d "$PG_DB"

    echo ""
    info "Restore complete."
    echo -e "  ${GREEN}${BOLD}✓ Database '$PG_DB' successfully restored from: $DUMP_FILE${RESET}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
parse_args "$@"
preflight
confirm
restore
