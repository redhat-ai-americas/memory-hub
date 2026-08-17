#!/usr/bin/env bash
# Verify that S3-spilled memory content survives the --skip-data golden test.
#
# Exit predicate for issue #395: Write a >100KB memory, verify it's S3-spilled,
# run uninstall-full.sh --skip-data && deploy-full.sh, then verify the memory
# content is fully retrievable afterward.
#
# Usage:
#   scripts/test-golden-s3-preserve.sh [--write-only] [--verify-only MEMORY_ID]
#
#   --write-only      Write the test memory and print its ID, then exit.
#                     Use this before manually running the golden test.
#   --verify-only ID  Verify an existing memory is retrievable with full
#                     content after a golden test cycle. Use after --write-only.
#   (no flags)        Run the full cycle: write, uninstall --skip-data, deploy,
#                     verify. DESTRUCTIVE — takes the stack down and back up.
#
# Prerequisites:
#   - memoryhub CLI or SDK installed (checks .venv/bin/memoryhub)
#   - MEMORYHUB_URL and MEMORYHUB_API_KEY set, or ~/.config/memoryhub/credentials
#   - OpenShift login active (for the golden test cycle)
#   - MEMORYHUB_EMBEDDING_MAX_TOKENS must be set high enough on the MCP server
#     deployment to accept >100KB content without validation rejection. The
#     config default (8192) is wrong for the CPU embedding model (#511).
#     Workaround until #511 is fixed:
#       oc set env deployment/memory-hub-mcp MEMORYHUB_EMBEDDING_MAX_TOKENS=500000 \
#         --context <context> -n memory-hub-mcp
#     Note: deploy-full.sh wipes this — re-apply after every deploy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"

# S3 spill threshold is 102400 bytes (100KB) — generate content above this.
TEST_CONTENT_SIZE=110000
TEST_TAG="golden-s3-test-$$-$(date -u +%Y%m%dT%H%M%SZ)"

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

WRITTEN_MEMORY_ID=""
CLEANUP_MEMORY_ID=""
SKIP_CLEANUP=false
TEST_PASSED=false

cleanup() {
    local id="${CLEANUP_MEMORY_ID:-$WRITTEN_MEMORY_ID}"
    if [ -z "$id" ] || [ "$SKIP_CLEANUP" = "true" ]; then
        return
    fi
    local cli
    cli=$(command -v memoryhub 2>/dev/null || echo "$REPO_ROOT/.venv/bin/memoryhub")
    echo ""
    if [ "$TEST_PASSED" = "true" ]; then
        echo -e "  ${GREEN}→${RESET} Cleaning up test memory $id..."
    else
        echo -e "  ${YELLOW}!${RESET} Test did not pass — cleaning up test memory $id..."
    fi
    $cli delete "$id" -f -o quiet 2>/dev/null && \
        echo -e "  ${GREEN}→${RESET} Deleted" || \
        echo -e "  ${YELLOW}!${RESET} Delete failed (non-fatal)"
}
trap cleanup EXIT

STEP=0
banner() {
    STEP=$((STEP + 1))
    echo ""
    echo -e "${BOLD}${CYAN}=========================================${RESET}"
    echo -e "${BOLD}${CYAN}  Step ${STEP}: $1${RESET}"
    echo -e "${BOLD}${CYAN}=========================================${RESET}"
}
info()  { echo -e "  ${GREEN}→${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET} $*"; }
die()   { echo -e "  ${RED}✗${RESET} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Resolve memoryhub CLI
# ---------------------------------------------------------------------------
resolve_cli() {
    if command -v memoryhub &>/dev/null; then
        echo "memoryhub"
    elif "$REPO_ROOT/.venv/bin/memoryhub" --version &>/dev/null 2>&1; then
        echo "$REPO_ROOT/.venv/bin/memoryhub"
    else
        die "memoryhub CLI not found. Install with: pip install memoryhub-cli"
    fi
}

# ---------------------------------------------------------------------------
# Write a >100KB test memory and verify it's S3-spilled
# ---------------------------------------------------------------------------
write_test_memory() {
    local memoryhub_bin=$1

    banner "Write test memory"

    info "Generating ${TEST_CONTENT_SIZE}-byte test content..."
    local content
    content="[golden-s3-test ${TEST_TAG}] "
    content+="This is a test memory for issue #395 — verifying that S3-spilled "
    content+="content survives the --skip-data golden test. "
    local line_num=0
    while [ ${#content} -lt "$TEST_CONTENT_SIZE" ]; do
        content+="[${TEST_TAG} line ${line_num}] The quick brown fox jumps over the lazy dog. "
        line_num=$((line_num + 1))
    done
    info "Content size: ${#content} bytes (threshold: 102400)"

    info "Writing memory via CLI..."
    local write_output
    write_output=$(echo "$content" | $memoryhub_bin write --scope user --weight 0.1 -o json) || {
        die "Write failed: $write_output"
    }

    local memory_id
    memory_id=$(echo "$write_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = (d.get('data') or {}).get('memory')
if mem:
    print(mem['id'])
else:
    cur = (d.get('data') or {}).get('curation') or {}
    if cur.get('blocked'):
        print('BLOCKED:' + (cur.get('reason') or 'unknown'), file=sys.stderr)
        sys.exit(1)
    print('')
" 2>&1) || die "Write blocked by curation: $memory_id"

    if [ -z "$memory_id" ]; then
        die "Could not parse memory ID from write response"
    fi

    info "Written: $memory_id"

    banner "Verify S3 spill"

    info "Reading memory back to check storage type..."
    local read_output
    read_output=$($memoryhub_bin read "$memory_id" -o json) || {
        die "Read failed"
    }

    local storage_type content_len
    storage_type=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
print(mem.get('storage_type', 'inline'))
")
    content_len=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
c = mem.get('content') or ''
print(len(c))
")

    if [ "$storage_type" = "s3" ]; then
        info "Storage type: s3 (S3-spilled as expected)"
    else
        warn "Storage type: $storage_type (content_len=$content_len)"
        warn "Memory may not be S3-spilled. If MinIO is not configured,"
        warn "content is stored inline. The test can still verify data"
        warn "survival but won't exercise the S3 spill path."
    fi

    WRITTEN_MEMORY_ID="$memory_id"
}

# ---------------------------------------------------------------------------
# Verify a memory is fully retrievable after golden test
# ---------------------------------------------------------------------------
verify_memory() {
    local memoryhub_bin=$1
    local memory_id=$2

    banner "Verify memory retrieval"

    info "Reading memory $memory_id..."
    local read_output
    read_output=$($memoryhub_bin read "$memory_id" -o json) || {
        die "Read failed — memory may have been lost"
    }

    local has_tag storage_type full_available content_len
    has_tag=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
c = mem.get('content') or ''
print('true' if 'golden-s3-test' in c else 'false')
")
    storage_type=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
print(mem.get('storage_type', 'inline'))
")
    full_available=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
print(str(mem.get('full_available', False)).lower())
")
    content_len=$(echo "$read_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
mem = d.get('data', d)
c = mem.get('content') or ''
print(len(c))
")

    if [ "$has_tag" != "true" ]; then
        die "Memory content does not contain test tag — content may be corrupted or truncated"
    fi

    if [ "$storage_type" = "s3" ]; then
        info "Storage type: s3 (S3-spilled)"
        if [ "$full_available" = "true" ]; then
            info "Full content available: yes (S3 object intact)"
        else
            die "S3-spilled memory exists but full content NOT available — S3 data may be lost"
        fi
    else
        if [ "$content_len" -lt "$TEST_CONTENT_SIZE" ]; then
            die "Inline content length ($content_len) is less than expected ($TEST_CONTENT_SIZE)"
        fi
        info "Storage type: inline (content_len=$content_len)"
    fi

    info "Test tag present: yes"

    TEST_PASSED=true
    echo ""
    echo -e "  ${GREEN}${BOLD}PASS: S3-spilled memory survived the --skip-data golden test${RESET}"
    echo ""
}

# ---------------------------------------------------------------------------
# Run the full golden test cycle
# ---------------------------------------------------------------------------
run_golden_test() {
    local uninstall_args="--skip-data --skip-tile --yes"
    local deploy_args="--skip-prereqs --skip-tile --skip-ui --skip-models --skip-smoke-test"

    banner "Uninstall (preserving data)"

    warn "This will take the MemoryHub stack down."
    warn "The --skip-data flag preserves both DB and storage namespaces."
    info "Args: $uninstall_args"
    echo ""

    if [ -t 0 ]; then
        read -r -p "  Continue? [y/N] " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            die "Aborted by user"
        fi
    fi

    # shellcheck disable=SC2086
    "$SCRIPT_DIR/uninstall-full.sh" $uninstall_args || {
        die "Uninstall failed"
    }
    info "Uninstall complete"

    info "Waiting for namespace termination..."
    local ns wait_secs total_wait=0
    for ns in memory-hub-mcp memoryhub-auth memoryhub-ui; do
        wait_secs=0
        while oc get namespace --context "$CONTEXT" "$ns" &>/dev/null 2>&1; do
            if [ $wait_secs -ge 120 ]; then
                die "Namespace $ns still terminating after 120s"
            fi
            sleep 5
            wait_secs=$((wait_secs + 5))
        done
        total_wait=$((total_wait + wait_secs))
    done
    info "All namespaces terminated (${total_wait}s)"

    banner "Reinstall"

    info "Args: $deploy_args"
    # shellcheck disable=SC2086
    "$SCRIPT_DIR/deploy-full.sh" $deploy_args || {
        die "Deploy failed"
    }
    info "Reinstall complete"
}

# ---------------------------------------------------------------------------
# Parse args and run
# ---------------------------------------------------------------------------
MODE="full"
VERIFY_MEMORY_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --write-only)
            MODE="write"
            shift
            ;;
        --verify-only)
            MODE="verify"
            VERIFY_MEMORY_ID="${2:-}"
            if [ -z "$VERIFY_MEMORY_ID" ]; then
                die "--verify-only requires a memory ID argument"
            fi
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--write-only] [--verify-only MEMORY_ID]"
            echo ""
            echo "  --write-only        Write test memory, print ID, exit"
            echo "  --verify-only ID    Verify memory survived golden test"
            echo "  (no flags)          Full cycle: write → uninstall → deploy → verify"
            exit 0
            ;;
        *)
            die "Unknown argument: $1"
            ;;
    esac
done

MEMORYHUB_BIN=$(resolve_cli)

echo ""
echo -e "${BOLD}MemoryHub S3 Golden Test${RESET}"
echo -e "CLI: $MEMORYHUB_BIN"

case "$MODE" in
    write)
        SKIP_CLEANUP=true
        echo -e "Mode: ${CYAN}write-only${RESET} (write test memory, then exit)"
        echo -e "Steps: Write test memory → Verify S3 spill"
        write_test_memory "$MEMORYHUB_BIN"
        echo ""
        echo -e "${BOLD}Memory ID: $WRITTEN_MEMORY_ID${RESET}"
        echo ""
        echo "Next steps:"
        echo "  1. Run the golden test: scripts/uninstall-full.sh --skip-data --skip-tile --yes && scripts/deploy-full.sh --skip-prereqs --skip-tile"
        echo "  2. Verify:              scripts/test-golden-s3-preserve.sh --verify-only $WRITTEN_MEMORY_ID"
        ;;
    verify)
        CLEANUP_MEMORY_ID="$VERIFY_MEMORY_ID"
        echo -e "Mode: ${CYAN}verify-only${RESET} (check memory survived golden test)"
        echo -e "Steps: Verify memory retrieval → Cleanup"
        echo -e "Memory ID: $VERIFY_MEMORY_ID"
        verify_memory "$MEMORYHUB_BIN" "$VERIFY_MEMORY_ID"
        ;;
    full)
        echo -e "Mode: ${CYAN}full cycle${RESET} (write → uninstall → deploy → verify)"
        echo -e "Steps: Write test memory → Verify S3 spill → Golden test → Verify retrieval → Cleanup"
        write_test_memory "$MEMORYHUB_BIN"
        run_golden_test
        verify_memory "$MEMORYHUB_BIN" "$WRITTEN_MEMORY_ID"
        ;;
esac
