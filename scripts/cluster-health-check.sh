#!/usr/bin/env bash
# cluster-health-check.sh — verify deployment state at session start
#
# Usage: scripts/cluster-health-check.sh [--full]
#
# Runs a quick health check on the MemoryHub cluster deployment. Designed
# to catch stale assumptions about deployment state (migration drift, dead
# pods, error loops) before they waste session time.
#
# Default mode checks: login, pod status, recent errors, route, tool
# count, image freshness.
# --full adds: migration head comparison (requires port-forward to DB).
#
# Resolves a recurring retro gap: 4 retros flagged stale briefing data
# about cluster state. See retrospectives/2026-04-09_campaign-read-path-
# wiring/RETRO.md for the finding that motivated this script.
#
# Requires: oc. Optional: psql or alembic (for --full migration check).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Args ────────────────────────────────────────────────────────────────────

FULL=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --full) FULL=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--full]"
            echo ""
            echo "Quick health check on MemoryHub cluster deployment."
            echo "  --full    Also check DB migration state (needs port-forward)"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
DIM='\033[0;90m'
RESET='\033[0m'

ok()   { printf "  %-14s ${GREEN}%s${RESET}\n" "$1" "$2"; }
warn() { printf "  %-14s ${YELLOW}%s${RESET}\n" "$1" "$2"; }
bad()  { printf "  %-14s ${RED}%s${RESET}\n" "$1" "$2"; }
dim()  { printf "  %-14s ${DIM}%s${RESET}\n" "$1" "$2"; }

echo "Cluster health check"
echo ""

ISSUES=0

# ── Check 1: oc login ──────────────────────────────────────────────────────

if ! command -v oc &>/dev/null; then
    bad "login:" "oc CLI not found"
    echo ""
    echo "  Install oc or log in before running this check."
    exit 1
fi

if ! OC_USER=$(oc whoami 2>/dev/null); then
    bad "login:" "not logged in"
    echo ""
    if [[ -f "$PROJECT_ROOT/.env" ]] && grep -q OC_SERVER "$PROJECT_ROOT/.env"; then
        echo "  Log in with: source .env && oc login \"\$OC_SERVER\" -u \"\$OC_USER\" -p \"\$OC_PASSWORD\" --insecure-skip-tls-verify"
    else
        echo "  Log in with: oc login <cluster-url>"
    fi
    exit 1
fi

OC_SERVER=$(oc whoami --show-server 2>/dev/null || echo "unknown")
ok "login:" "${OC_USER} @ ${OC_SERVER}"

# ── Check 2: MCP pod status ────────────────────────────────────────────────

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memory-hub-mcp"

POD_JSON=$(oc get pods -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT" \
    -o json 2>/dev/null || echo '{"items":[]}')

POD_COUNT=$(echo "$POD_JSON" | python3 -c "
import json, sys
data = json.load(sys.stdin)
running = [p for p in data['items'] if p['status']['phase'] == 'Running']
print(len(running))
" 2>/dev/null || echo "0")

if [[ "$POD_COUNT" == "0" ]]; then
    bad "mcp pod:" "no running pods in $NAMESPACE"
    ISSUES=$((ISSUES + 1))
elif [[ "$POD_COUNT" != "1" ]]; then
    warn "mcp pod:" "${POD_COUNT} running pods (expected 1)"
    ISSUES=$((ISSUES + 1))
else
    # Get age and restart count
    POD_INFO=$(echo "$POD_JSON" | python3 -c "
import json, sys
from datetime import datetime, timezone
data = json.load(sys.stdin)
for p in data['items']:
    if p['status']['phase'] != 'Running':
        continue
    start = p['status'].get('startTime', '')
    if start:
        dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - dt
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            age = f'{int(delta.total_seconds() // 60)}m'
        elif hours < 48:
            age = f'{hours}h'
        else:
            age = f'{hours // 24}d'
    else:
        age = 'unknown'
    restarts = sum(
        cs.get('restartCount', 0)
        for cs in p['status'].get('containerStatuses', [])
    )
    print(f'Running (age: {age}, restarts: {restarts})')
    break
" 2>/dev/null || echo "Running")
    ok "mcp pod:" "$POD_INFO"
fi

# ── Check 3: DB pod status ─────────────────────────────────────────────────

DB_NAMESPACE="memoryhub-db"
DB_POD_PHASE=$(oc get pods -n "$DB_NAMESPACE" -l app=memoryhub-pg \
    -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "")

if [[ -z "$DB_POD_PHASE" ]]; then
    # Try without label selector
    DB_POD_PHASE=$(oc get pods -n "$DB_NAMESPACE" --no-headers 2>/dev/null \
        | grep -i "pg\|postgres" | awk '{print $3}' | head -1 || echo "")
fi

if [[ "$DB_POD_PHASE" == "Running" ]]; then
    ok "db pod:" "Running in $DB_NAMESPACE"
elif [[ -z "$DB_POD_PHASE" ]]; then
    bad "db pod:" "not found in $DB_NAMESPACE"
    ISSUES=$((ISSUES + 1))
else
    bad "db pod:" "$DB_POD_PHASE"
    ISSUES=$((ISSUES + 1))
fi

# ── Check 4: Recent pod errors ─────────────────────────────────────────────

if [[ "$POD_COUNT" -ge 1 ]]; then
    # Filter for infrastructure errors, not normal MCP ToolErrors.
    # ToolError is a standard MCP response (e.g., auth required) — not a crash.
    # We care about: SQL errors, import failures, tracebacks, crash signals.
    ERROR_PATTERN="(ProgrammingError|ImportError|ModuleNotFoundError|undefined.column|Traceback|CRITICAL|OOMKilled|CrashLoopBack)"

    RECENT_ERRORS=$(oc logs "deployment/$DEPLOYMENT" -n "$NAMESPACE" --tail=100 2>/dev/null \
        | grep -c -E "$ERROR_PATTERN" || echo "0")

    if [[ "$RECENT_ERRORS" == "0" ]]; then
        ok "pod errors:" "none in last 100 log lines"
    else
        ERROR_SAMPLE=$(oc logs "deployment/$DEPLOYMENT" -n "$NAMESPACE" --tail=100 2>/dev/null \
            | grep -E "$ERROR_PATTERN" | tail -1 \
            | head -c 120 || echo "")
        warn "pod errors:" "${RECENT_ERRORS} error lines in last 100 log lines"
        if [[ -n "$ERROR_SAMPLE" ]]; then
            printf "  ${DIM}               %s${RESET}\n" "$ERROR_SAMPLE"
        fi
        ISSUES=$((ISSUES + 1))
    fi
else
    dim "pod errors:" "[skipped — no running pod]"
fi

# ── Check 5: Route ─────────────────────────────────────────────────────────

ROUTE=$(oc get route "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [[ -n "$ROUTE" ]]; then
    ok "route:" "https://${ROUTE}/mcp/"
else
    warn "route:" "not found"
    ISSUES=$((ISSUES + 1))
fi

# ── Check 6: Tool count ───────────────────────────────────────────────────
# Compare deployed tool count against main.py registrations

MAIN_PY="$PROJECT_ROOT/memory-hub-mcp/src/main.py"
EXPECTED_TOOLS=0
if [[ -f "$MAIN_PY" ]]; then
    # Count tool imports — each "from src.tools.<name> import" is one registered tool
    EXPECTED_TOOLS=$(grep -c 'from src\.tools\.' "$MAIN_PY" 2>/dev/null || echo "0")
fi

DEPLOYED_TOOLS=""
if [[ "$POD_COUNT" -ge 1 ]]; then
    DEPLOYED_TOOLS=$(oc logs "deployment/$DEPLOYMENT" -n "$NAMESPACE" --tail=50 2>/dev/null \
        | grep -oE "tools['\"]?: *[0-9]+" | grep -oE '[0-9]+' | head -1 || echo "")
fi

if [[ -n "$DEPLOYED_TOOLS" && "$EXPECTED_TOOLS" -gt 0 ]]; then
    if [[ "$DEPLOYED_TOOLS" == "$EXPECTED_TOOLS" ]]; then
        ok "tools:" "${DEPLOYED_TOOLS} deployed (matches main.py)"
    else
        warn "tools:" "deployed=${DEPLOYED_TOOLS}, main.py=${EXPECTED_TOOLS} (mismatch)"
        ISSUES=$((ISSUES + 1))
    fi
elif [[ "$EXPECTED_TOOLS" -gt 0 ]]; then
    dim "tools:" "${EXPECTED_TOOLS} expected (could not read deployed count from logs)"
else
    dim "tools:" "[could not determine tool counts]"
fi

# ── Check 7: Image freshness ──────────────────────────────────────────────
# Check how old the deployed image is

if [[ "$POD_COUNT" -ge 1 ]]; then
    POD_CREATED=$(oc get pod -l "app.kubernetes.io/name=$DEPLOYMENT" -n "$NAMESPACE" \
        -o jsonpath='{.items[0].metadata.creationTimestamp}' 2>/dev/null || echo "")

    if [[ -n "$POD_CREATED" ]]; then
        AGE_HOURS=$(python3 -c "
from datetime import datetime, timezone
ts = '$POD_CREATED'.replace('Z', '+00:00')
dt = datetime.fromisoformat(ts)
delta = datetime.now(timezone.utc) - dt
print(int(delta.total_seconds() // 3600))
" 2>/dev/null || echo "")

        if [[ -n "$AGE_HOURS" ]]; then
            if [[ "$AGE_HOURS" -lt 24 ]]; then
                ok "image age:" "${AGE_HOURS}h (recent)"
            elif [[ "$AGE_HOURS" -lt 168 ]]; then
                dim "image age:" "$((AGE_HOURS / 24))d"
            else
                warn "image age:" "$((AGE_HOURS / 24))d — image may be stale"
            fi
        else
            dim "image age:" "[could not parse creation timestamp]"
        fi
    else
        dim "image age:" "[could not read pod creation time]"
    fi
else
    dim "image age:" "[skipped — no running pod]"
fi

# ── Check 8 (--full): Migration state ─────────────────────────────────────

if [[ "$FULL" == "true" ]]; then
    echo ""
    dim "migrations:" "checking (port-forwarding to DB)..."

    # Get local alembic head
    LOCAL_HEAD=""
    if [[ -d "$PROJECT_ROOT/alembic/versions" ]]; then
        LOCAL_HEAD=$(ls "$PROJECT_ROOT/alembic/versions/" \
            | grep -E '^[0-9]+_' | sort -n | tail -1 \
            | sed 's/_.*//' || echo "")
    fi

    # Port-forward and check deployed head
    PF_PID=""
    DEPLOYED_HEAD=""

    # Find an available local port
    LOCAL_PORT=15432

    oc port-forward svc/memoryhub-pg "$LOCAL_PORT":5432 -n "$DB_NAMESPACE" &>/dev/null &
    PF_PID=$!
    sleep 2

    if kill -0 "$PF_PID" 2>/dev/null; then
        # Try alembic current
        if [[ -f "$PROJECT_ROOT/alembic.ini" ]] && command -v "$PROJECT_ROOT/.venv/bin/alembic" &>/dev/null; then
            DEPLOYED_HEAD=$(cd "$PROJECT_ROOT" && \
                MEMORYHUB_DB_HOST=localhost \
                MEMORYHUB_DB_PORT=$LOCAL_PORT \
                MEMORYHUB_DB_NAME=memoryhub \
                MEMORYHUB_DB_USER=memoryhub \
                MEMORYHUB_DB_PASSWORD=memoryhub-dev-password \
                .venv/bin/alembic current 2>/dev/null \
                | grep -oE '^[0-9]+' | head -1 || echo "")
        fi

        # Fallback: check alembic_version table directly
        if [[ -z "$DEPLOYED_HEAD" ]] && command -v psql &>/dev/null; then
            DEPLOYED_HEAD=$(PGPASSWORD=memoryhub-dev-password psql \
                -h localhost -p "$LOCAL_PORT" -U memoryhub -d memoryhub \
                -t -A -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null \
                | grep -oE '^[0-9]+' || echo "")
        fi

        kill "$PF_PID" 2>/dev/null
        wait "$PF_PID" 2>/dev/null || true
    else
        dim "migrations:" "[port-forward failed]"
    fi

    # Clear the "checking" line and print result
    if [[ -n "$LOCAL_HEAD" && -n "$DEPLOYED_HEAD" ]]; then
        if [[ "$LOCAL_HEAD" == "$DEPLOYED_HEAD" ]]; then
            printf "\r  %-14s ${GREEN}local=%s, deployed=%s (in sync)${RESET}\n" "migrations:" "$LOCAL_HEAD" "$DEPLOYED_HEAD"
        else
            printf "\r  %-14s ${RED}local=%s, deployed=%s (DRIFT)${RESET}\n" "migrations:" "$LOCAL_HEAD" "$DEPLOYED_HEAD"
            ISSUES=$((ISSUES + 1))
        fi
    elif [[ -n "$LOCAL_HEAD" ]]; then
        printf "\r  %-14s ${YELLOW}local=%s, deployed=unknown${RESET}\n" "migrations:" "$LOCAL_HEAD"
    else
        printf "\r  %-14s ${DIM}[could not determine migration state]${RESET}\n" "migrations:"
    fi
fi

# ── Verdict ─────────────────────────────────────────────────────────────────

echo ""
if [[ $ISSUES -eq 0 ]]; then
    printf "  ${GREEN}VERDICT: Cluster healthy. Safe to proceed.${RESET}\n"
else
    printf "  ${YELLOW}VERDICT: %d issue(s) detected. Review before proceeding.${RESET}\n" "$ISSUES"
fi
