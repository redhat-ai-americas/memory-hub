#!/usr/bin/env bash
# issue-sanity-check.sh — verify an issue's stated problem still matches reality
#
# Usage: scripts/issue-sanity-check.sh <issue-number> [--body-file <path>]
#
# Runs a 30-second sanity check on the issue body against the current state of
# the codebase and (optionally) the cluster. Designed to catch stale issues
# before they waste triage or implementation time.
#
# Resolves a recurring retro gap: #98, #83, #47 were all acted on (or skipped)
# based on stale issue bodies. See retrospectives/2026-04-08_contributor-
# onboarding-cleanup/RETRO.md for the original finding.
#
# Requires: gh, git, grep, awk. Optional: oc (for cluster checks).

set -euo pipefail

# ── Args ────────────────────────────────────────────────────────────────────

ISSUE_NUM=""
BODY_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --body-file) BODY_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 <issue-number> [--body-file <path>]"
            echo ""
            echo "Sanity-check a GitHub issue against current code and cluster state."
            echo "Run this before triaging, labeling, or assigning any issue."
            exit 0
            ;;
        *) ISSUE_NUM="$1"; shift ;;
    esac
done

if [[ -z "$ISSUE_NUM" ]]; then
    echo "Usage: $0 <issue-number> [--body-file <path>]" >&2
    exit 1
fi

# ── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
DIM='\033[0;90m'
RESET='\033[0m'

ok()   { printf "  %-12s ${GREEN}%s${RESET}\n" "$1" "$2"; }
warn() { printf "  %-12s ${YELLOW}%s${RESET}\n" "$1" "$2"; }
bad()  { printf "  %-12s ${RED}%s${RESET}\n" "$1" "$2"; }
dim()  { printf "  %-12s ${DIM}%s${RESET}\n" "$1" "$2"; }

# ── Fetch issue ─────────────────────────────────────────────────────────────

echo "Sanity check for issue #${ISSUE_NUM}"
echo ""

if [[ -n "$BODY_FILE" ]]; then
    if [[ ! -f "$BODY_FILE" ]]; then
        echo "ERROR: --body-file '$BODY_FILE' not found" >&2
        exit 1
    fi
    BODY=$(cat "$BODY_FILE")
    STATE="UNKNOWN (offline mode)"
    UPDATED_AT="unknown"
else
    if ! command -v gh &>/dev/null; then
        echo "ERROR: gh CLI not found. Install it or use --body-file." >&2
        exit 1
    fi

    ISSUE_JSON=$(gh issue view "$ISSUE_NUM" --json state,body,updatedAt 2>&1) || {
        echo "ERROR: Could not fetch issue #${ISSUE_NUM}: ${ISSUE_JSON}" >&2
        exit 1
    }

    STATE=$(echo "$ISSUE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['state'])")
    BODY=$(echo "$ISSUE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['body'])")
    UPDATED_AT=$(echo "$ISSUE_JSON" | python3 -c "
import json,sys
from datetime import datetime, timezone
ts = json.load(sys.stdin)['updatedAt']
dt = datetime.fromisoformat(ts.replace('Z','+00:00'))
days = (datetime.now(timezone.utc) - dt).days
print(f'{days} day(s) ago' if days > 0 else 'today')
")
fi

# ── Check 1: Issue state ───────────────────────────────────────────────────

if [[ "$STATE" == "CLOSED" ]]; then
    bad "state:" "CLOSED (updated ${UPDATED_AT}) — issue already resolved"
    echo ""
    echo "  VERDICT: Issue is already closed. Nothing to triage."
    exit 0
elif [[ "$STATE" == "OPEN" ]]; then
    ok "state:" "OPEN (updated ${UPDATED_AT})"
else
    dim "state:" "$STATE (updated ${UPDATED_AT})"
fi

# ── Check 2: File references ──────────────────────────────────────────────

FILE_REFS=$(echo "$BODY" | grep -oE '`[^`]+\.(py|ts|tsx|sh|md|yaml|yml|json)`' | tr -d '`' | sort -u || true)
# Also catch paths outside backticks that look like file paths
FILE_REFS2=$(echo "$BODY" | grep -oE '[a-zA-Z_][a-zA-Z0-9_/.-]+\.(py|ts|tsx|sh|md|yaml|yml|json)' | grep '/' | sort -u || true)
FILE_REFS=$(echo -e "${FILE_REFS}\n${FILE_REFS2}" | sort -u | grep -v '^$' || true)

if [[ -z "$FILE_REFS" ]]; then
    dim "files:" "[none referenced]"
else
    STALE_FILES=()
    FOUND_FILES=()
    while IFS= read -r fpath; do
        # Skip URLs, globs, and common false positives
        [[ "$fpath" == http* ]] && continue
        [[ "$fpath" == *.example.* ]] && continue
        [[ "$fpath" == *'*'* ]] && continue
        [[ "$fpath" == blob/* ]] && continue
        [[ "$fpath" == ../blob/* ]] && continue

        # Try the path as-is and common prefixes
        if [[ -f "$fpath" ]] || [[ -f "memory-hub-mcp/$fpath" ]] || [[ -f "sdk/$fpath" ]] || [[ -f "memoryhub-ui/$fpath" ]]; then
            FOUND_FILES+=("$fpath")
        else
            STALE_FILES+=("$fpath")
        fi
    done <<< "$FILE_REFS"

    if [[ ${#STALE_FILES[@]} -gt 0 ]]; then
        warn "files:" "STALE — ${#STALE_FILES[@]} referenced file(s) not found:"
        for f in "${STALE_FILES[@]}"; do
            printf "  ${DIM}             %s${RESET}\n" "$f"
        done
    else
        ok "files:" "${#FOUND_FILES[@]} referenced file(s) all exist"
    fi
fi

# ── Check 3: Symbol references ────────────────────────────────────────────

# Extract backtick-wrapped identifiers that look like code symbols
SYMBOLS=$(echo "$BODY" | grep -oE '`[a-zA-Z_][a-zA-Z0-9_]+`' | tr -d '`' | sort -u || true)
# Filter out common non-symbol words and very short identifiers
SYMBOLS=$(echo "$SYMBOLS" | grep -vE '^(True|False|None|error|message|scope|user|project|default|test|main|true|false|null|string|int|float|bool)$' | awk 'length >= 4' || true)

if [[ -z "$SYMBOLS" ]]; then
    dim "symbols:" "[none referenced]"
else
    MISSING_SYMS=()
    FOUND_SYMS=0
    CHECKED=0
    while IFS= read -r sym; do
        # Only check symbols that look like function/class names (not generic words)
        [[ -z "$sym" ]] && continue
        CHECKED=$((CHECKED + 1))
        # Limit to first 10 symbols to keep it fast
        [[ $CHECKED -gt 10 ]] && break

        if grep -rq "$sym" --include='*.py' --include='*.ts' --include='*.tsx' . 2>/dev/null; then
            FOUND_SYMS=$((FOUND_SYMS + 1))
        else
            MISSING_SYMS+=("$sym")
        fi
    done <<< "$SYMBOLS"

    if [[ ${#MISSING_SYMS[@]} -gt 0 ]]; then
        warn "symbols:" "STALE — ${#MISSING_SYMS[@]} symbol(s) not found in codebase:"
        for s in "${MISSING_SYMS[@]}"; do
            printf "  ${DIM}             %s${RESET}\n" "$s"
        done
    else
        ok "symbols:" "${FOUND_SYMS} symbol(s) checked, all found"
    fi
fi

# ── Check 4: Cluster resources ────────────────────────────────────────────

if command -v oc &>/dev/null && oc whoami &>/dev/null 2>&1; then
    CLUSTER=$(oc whoami --show-server 2>/dev/null || echo "unknown")

    # Look for namespace/resource references in the body
    NS_REFS=$(echo "$BODY" | grep -oE '(memory-hub-mcp|memoryhub-auth|memoryhub-db|memoryhub-ui)' | sort -u || true)
    RESOURCE_REFS=$(echo "$BODY" | grep -oE '(deployment|Deployment|pod|Pod|service|Service|route|Route|configmap|ConfigMap|secret|Secret)/[a-zA-Z0-9_-]+' || true)

    if [[ -z "$NS_REFS" && -z "$RESOURCE_REFS" ]]; then
        dim "cluster:" "[no cluster resources referenced] (connected to ${CLUSTER})"
    else
        CLUSTER_ISSUES=()
        CLUSTER_OK=0

        # Check for named resources like "deployment/memory-hub-mcp"
        while IFS= read -r ref; do
            [[ -z "$ref" ]] && continue
            KIND=$(echo "$ref" | cut -d/ -f1 | tr '[:upper:]' '[:lower:]')
            NAME=$(echo "$ref" | cut -d/ -f2)

            # Try each known namespace
            FOUND=false
            for ns in memory-hub-mcp memoryhub-auth memoryhub-db; do
                if oc get "$KIND" "$NAME" -n "$ns" &>/dev/null 2>&1; then
                    FOUND=true
                    CLUSTER_OK=$((CLUSTER_OK + 1))
                    break
                fi
            done
            if [[ "$FOUND" != "true" ]]; then
                CLUSTER_ISSUES+=("${KIND}/${NAME} not found in any namespace")
            fi
        done <<< "$RESOURCE_REFS"

        if [[ ${#CLUSTER_ISSUES[@]} -gt 0 ]]; then
            warn "cluster:" "STALE — ${#CLUSTER_ISSUES[@]} resource(s) not found:"
            for ci in "${CLUSTER_ISSUES[@]}"; do
                printf "  ${DIM}             %s${RESET}\n" "$ci"
            done
        elif [[ $CLUSTER_OK -gt 0 ]]; then
            ok "cluster:" "${CLUSTER_OK} resource(s) verified on ${CLUSTER}"
        else
            dim "cluster:" "namespaces referenced but no specific resources to check"
        fi
    fi
else
    dim "cluster:" "[skipped — oc not available or not logged in]"
fi

# ── Check 5: Commit references ────────────────────────────────────────────

COMMITS=$(echo "$BODY" | grep -oE '\b[0-9a-f]{7,40}\b' | sort -u || true)

if [[ -z "$COMMITS" ]]; then
    dim "commits:" "[none referenced]"
else
    MISSING_COMMITS=()
    FOUND_COMMITS=0
    while IFS= read -r sha; do
        [[ -z "$sha" ]] && continue
        if git log --all --format='%H' | grep -q "^${sha}" 2>/dev/null || git cat-file -t "$sha" &>/dev/null 2>&1; then
            FOUND_COMMITS=$((FOUND_COMMITS + 1))
        else
            MISSING_COMMITS+=("$sha")
        fi
    done <<< "$COMMITS"

    if [[ ${#MISSING_COMMITS[@]} -gt 0 ]]; then
        warn "commits:" "STALE — ${#MISSING_COMMITS[@]} SHA(s) not found in git history:"
        for c in "${MISSING_COMMITS[@]}"; do
            printf "  ${DIM}             %s${RESET}\n" "$c"
        done
    else
        ok "commits:" "${FOUND_COMMITS} SHA(s) all found in git history"
    fi
fi

# ── Verdict ───────────────────────────────────────────────────────────────

echo ""

# Initialize arrays that may not have been set if their check path was skipped
STALE_FILES=("${STALE_FILES[@]+"${STALE_FILES[@]}"}")
MISSING_SYMS=("${MISSING_SYMS[@]+"${MISSING_SYMS[@]}"}")
CLUSTER_ISSUES=("${CLUSTER_ISSUES[@]+"${CLUSTER_ISSUES[@]}"}")
MISSING_COMMITS=("${MISSING_COMMITS[@]+"${MISSING_COMMITS[@]}"}")

# Count warnings
HAS_STALE=false
[[ ${#STALE_FILES[@]} -gt 0 ]] 2>/dev/null && HAS_STALE=true
[[ ${#MISSING_SYMS[@]} -gt 0 ]] 2>/dev/null && HAS_STALE=true
[[ ${#CLUSTER_ISSUES[@]} -gt 0 ]] 2>/dev/null && HAS_STALE=true
[[ ${#MISSING_COMMITS[@]} -gt 0 ]] 2>/dev/null && HAS_STALE=true

if [[ "$HAS_STALE" == "true" ]]; then
    printf "  ${YELLOW}VERDICT: Issue body references state that may no longer match reality.${RESET}\n"
    printf "  ${YELLOW}         Re-read the body before acting on it.${RESET}\n"
else
    printf "  ${GREEN}VERDICT: All referenced state appears current. Safe to triage.${RESET}\n"
fi
