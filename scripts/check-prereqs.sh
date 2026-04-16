#!/bin/bash
# Verify the current environment can successfully install MemoryHub on OpenShift.
# Usage: scripts/check-prereqs.sh [--quiet]
# Exits 0 if all checks pass, non-zero if any failed.

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
QUIET=false

TARGET_NAMESPACES=(memory-hub-mcp memoryhub-auth memoryhub-db memoryhub-ui)

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

info()  { [ "$QUIET" = false ] && echo -e "  ${GREEN}→${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}!${RESET} $*"; }
fail()  { echo -e "  ${RED}✗${RESET} $*" >&2; }
pass()  { [ "$QUIET" = false ] && echo -e "  ${GREEN}✓${RESET} $*"; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=true ;;
        -h|--help)
            echo "Usage: $SCRIPT_NAME [--quiet]"
            echo ""
            echo "  --quiet    Suppress per-check progress output; only print failures and summary"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg (run with --help for usage)" >&2
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
FAILURES=0

banner "MemoryHub Install Prereq Check"
[ "$QUIET" = false ] && echo ""

# 1. oc on PATH
info "Checking for oc..."
if command -v oc &>/dev/null; then
    pass "oc found: $(command -v oc)"
else
    fail "oc not found on PATH. Install the OpenShift CLI: https://docs.openshift.com/container-platform/latest/cli_reference/openshift_cli/getting-started-cli.html"
    (( FAILURES++ ))
fi

# 2. podman on PATH
info "Checking for podman..."
if command -v podman &>/dev/null; then
    pass "podman found: $(command -v podman)"
else
    fail "podman not found on PATH. Install Podman: https://podman.io/getting-started/installation"
    (( FAILURES++ ))
fi

# 3. Logged into a cluster
info "Checking OpenShift login (oc whoami)..."
if oc whoami &>/dev/null; then
    CURRENT_USER="$(oc whoami)"
    CURRENT_SERVER="$(oc whoami --show-server 2>/dev/null || echo 'unknown')"
    pass "Logged in as ${CURRENT_USER} on ${CURRENT_SERVER}"
else
    fail "Not logged into an OpenShift cluster. Run 'oc login <cluster-url>' first."
    (( FAILURES++ ))
    # Remaining checks depend on a working login; skip them with a note.
    echo ""
    warn "Skipping remaining cluster checks — login required."
    echo ""
    if [ "$FAILURES" -eq 1 ]; then
        echo -e "  ${RED}1 check failed — see above${RESET}"
    else
        echo -e "  ${RED}${FAILURES} checks failed — see above${RESET}"
    fi
    exit "$FAILURES"
fi

# 4. Can reach the cluster API
info "Checking cluster API reachability (oc get --raw /version)..."
if oc get --raw /version &>/dev/null; then
    pass "Cluster API reachable"
else
    fail "Could not reach cluster API. Check your network connection and cluster health."
    (( FAILURES++ ))
fi

# 5. Cluster-admin (can create namespaces)
info "Checking cluster-admin privileges (can-i create namespaces)..."
CAN_CREATE_NS="$(oc auth can-i create namespaces 2>/dev/null || echo 'no')"
if [ "$CAN_CREATE_NS" = "yes" ]; then
    pass "cluster-admin confirmed"
else
    fail "Insufficient privileges. 'oc auth can-i create namespaces' returned '${CAN_CREATE_NS}'. cluster-admin (or equivalent) is required to install MemoryHub."
    (( FAILURES++ ))
fi

# 6. RHOAI installed
info "Checking for Red Hat OpenShift AI (namespace redhat-ods-applications)..."
if oc get namespace redhat-ods-applications &>/dev/null; then
    pass "redhat-ods-applications namespace found — RHOAI is installed"
else
    fail "Namespace 'redhat-ods-applications' not found. MemoryHub expects Red Hat OpenShift AI to be installed. See https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed for installation."
    (( FAILURES++ ))
fi

# 7. Default storage class exists
info "Checking for a default StorageClass..."
DEFAULT_SC="$(oc get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null \
    | awk -F'\t' '$2 == "true" {print $1}')"
if [ -n "$DEFAULT_SC" ]; then
    pass "Default StorageClass: ${DEFAULT_SC}"
else
    fail "No default StorageClass found. MemoryHub requires a default StorageClass for persistent volume claims. Set one with: oc patch storageclass <name> -p '{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'"
    (( FAILURES++ ))
fi

# 8. Target namespaces available
[ "$QUIET" = false ] && echo ""
info "Checking target namespaces..."
for NS in "${TARGET_NAMESPACES[@]}"; do
    if oc get namespace "$NS" &>/dev/null; then
        # Namespace exists — check write access
        CAN_WRITE="$(oc auth can-i create deployments -n "$NS" 2>/dev/null || echo 'no')"
        if [ "$CAN_WRITE" = "yes" ]; then
            warn "Namespace '${NS}' already exists (write access confirmed). You may want to uninstall first if doing a fresh install."
        else
            fail "Namespace '${NS}' exists but you cannot create deployments in it. Check RBAC."
            (( FAILURES++ ))
        fi
    else
        pass "Namespace '${NS}' does not exist — will be created on install"
    fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}All prereqs passed${RESET}"
else
    echo -e "  ${RED}${BOLD}${FAILURES} check$([ "$FAILURES" -ne 1 ] && echo 's') failed — see above${RESET}"
fi
echo ""

exit "$FAILURES"
