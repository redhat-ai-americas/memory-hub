#!/usr/bin/env bash
# Backup the MemoryHub PostgreSQL database to a local file.
#
# Usage: scripts/backup-db.sh [OUTPUT_PATH]
#
#   OUTPUT_PATH  Optional. Full path to the output file.
#                Defaults to ./backups/memoryhub-<timestamp>.dump
#
# The dump uses pg_dump --format=custom (compressed; supports selective restore).
set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DB_NAMESPACE="memoryhub-db"
POD_LABEL="app.kubernetes.io/name=memoryhub-pg"
CONTAINER="postgresql"
CREDENTIALS_SECRET="memoryhub-pg-credentials"

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

info() { echo -e "  ${GREEN}→${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
die()  { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Determine output path
# ---------------------------------------------------------------------------
if [[ $# -ge 1 ]]; then
    OUTPUT_FILE="$1"
else
    TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
    BACKUP_DIR="${REPO_ROOT}/backups"
    OUTPUT_FILE="${BACKUP_DIR}/memoryhub-${TIMESTAMP}.dump"
fi

# ---------------------------------------------------------------------------
# Step 1: Verify oc login
# ---------------------------------------------------------------------------
banner "MemoryHub DB Backup"

if ! oc whoami &>/dev/null; then
    die "Not logged in to an OpenShift cluster. Run 'oc login' first."
fi
info "Logged in as: $(oc whoami)"

# ---------------------------------------------------------------------------
# Step 2: Find the PostgreSQL pod
# ---------------------------------------------------------------------------
info "Finding PostgreSQL pod in namespace ${DB_NAMESPACE}..."
PG_POD="$(oc get pod -l "${POD_LABEL}" -n "${DB_NAMESPACE}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)" \
    || die "No pod found matching label '${POD_LABEL}' in namespace '${DB_NAMESPACE}'."

if [[ -z "$PG_POD" ]]; then
    die "No pod found matching label '${POD_LABEL}' in namespace '${DB_NAMESPACE}'."
fi
info "Using pod: ${PG_POD}"

# ---------------------------------------------------------------------------
# Step 3: Read credentials from Secret
# ---------------------------------------------------------------------------
info "Reading credentials from secret '${CREDENTIALS_SECRET}'..."

POSTGRES_USER="$(oc get secret "${CREDENTIALS_SECRET}" -n "${DB_NAMESPACE}" \
    -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)"
POSTGRES_DB="$(oc get secret "${CREDENTIALS_SECRET}" -n "${DB_NAMESPACE}" \
    -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)"
POSTGRES_PASSWORD="$(oc get secret "${CREDENTIALS_SECRET}" -n "${DB_NAMESPACE}" \
    -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)"

if [[ -z "$POSTGRES_USER" || -z "$POSTGRES_DB" || -z "$POSTGRES_PASSWORD" ]]; then
    die "One or more credentials missing from secret '${CREDENTIALS_SECRET}'."
fi
info "Database: ${POSTGRES_DB}  User: ${POSTGRES_USER}"

# ---------------------------------------------------------------------------
# Step 4: Ensure output directory exists
# ---------------------------------------------------------------------------
OUTPUT_DIR="$(dirname "$OUTPUT_FILE")"
if [[ ! -d "$OUTPUT_DIR" ]]; then
    info "Creating output directory: ${OUTPUT_DIR}"
    mkdir -p "$OUTPUT_DIR"
fi

# ---------------------------------------------------------------------------
# Step 5: Run pg_dump
# ---------------------------------------------------------------------------
info "Starting backup → ${OUTPUT_FILE}"

oc exec "${PG_POD}" -n "${DB_NAMESPACE}" -c "${CONTAINER}" \
    -- env PGPASSWORD="${POSTGRES_PASSWORD}" \
    pg_dump --format=custom -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    > "$OUTPUT_FILE"

# ---------------------------------------------------------------------------
# Step 6: Report result
# ---------------------------------------------------------------------------
FILE_SIZE="$(du -sh "$OUTPUT_FILE" | cut -f1)"
echo ""
echo -e "  ${GREEN}✓${RESET} Backup complete"
echo -e "    File : ${BOLD}${OUTPUT_FILE}${RESET}"
echo -e "    Size : ${FILE_SIZE}"
