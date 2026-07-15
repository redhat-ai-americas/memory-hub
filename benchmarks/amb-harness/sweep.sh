#!/usr/bin/env bash
set -euo pipefail

# Chunking parameter sweep for PersonaMem benchmark.
# Runs 12 configs: 4 chunk sizes x 3 overlap levels.
#
# Usage:
#   ./sweep.sh                  # Run all configs sequentially
#   ./sweep.sh c512-o10-k10     # Run a single config by name
#   ./sweep.sh --baseline       # Run only the baseline (existing corpus)
#
# Prerequisites:
#   - source ~/.secrets (for GEMINI_API_KEY)
#   - MEMORYHUB_API_KEY from ~/.config/memoryhub/api-key
#   - Port-forward to memoryhub-db on 25432
#   - MCP server deployed with chunk param support

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Common env vars for all runs
export MEMORYHUB_API_KEY="${MEMORYHUB_API_KEY:-$(cat ~/.config/memoryhub/api-key)}"
export MEMORYHUB_DB_PASS="${MEMORYHUB_DB_PASS:-$(oc get secret memoryhub-pg-credentials --context mcp-rhoai -n memoryhub-db -o jsonpath='{.data.password}' | base64 -d)}"
export MEMORYHUB_DISABLED_SIGNALS=domain,graph
export MEMORYHUB_FOCUS_MODE=persona
export MEMORYHUB_RETURN_CHUNKS=true
export MEMORYHUB_K=10

# Sweep matrix
CHUNK_SIZES=(32 64 128 256 512 1024 2048)
OVERLAPS=(0 10 25)

log() { echo "[$(date +%H:%M:%S)] $*"; }

run_config() {
    local size=$1 overlap_pct=$2
    local overlap_tokens=$(( size * overlap_pct / 100 ))
    local name="c${size}-o${overlap_pct}-k10"
    local project="amb-${name}"

    log "=== ${name} === (chunk=${size}, overlap=${overlap_pct}% = ${overlap_tokens} tokens)"

    export MEMORYHUB_PROJECT_ID="${project}"
    export MEMORYHUB_CHUNK_TARGET_TOKENS="${size}"
    export MEMORYHUB_CHUNK_OVERLAP_TOKENS="${overlap_tokens}"

    # Skip if output already exists
    if [ -f "outputs/personamem/${name}/rag/32k.json" ] || [ -f "outputs/personamem/${name}/rag/32k.json.gz" ]; then
        log "  SKIP: output already exists for ${name}"
        return 0
    fi

    log "  Ingesting 195 docs into project ${project}..."
    if ! uv run omb run \
        --split 32k --dataset personamem --memory memoryhub --mode rag \
        --name "${name}" \
        --description "Sweep: chunk=${size}, overlap=${overlap_pct}%, k=10" \
        2>&1 | tee "outputs/personamem/${name}.log"; then
        log "  FAILED: ${name}"
        return 1
    fi

    log "  DONE: ${name}"
    # Extract accuracy from the output
    if [ -f "outputs/personamem/${name}/rag/32k.json" ]; then
        local acc
        acc=$(python3 -c "import json; d=json.load(open('outputs/personamem/${name}/rag/32k.json')); print(f\"{d['accuracy']:.1%}\")")
        log "  Accuracy: ${acc}"
    fi
}

run_baseline() {
    local name="c256-o0-k10"
    log "=== BASELINE: ${name} === (existing corpus, no re-ingestion)"

    export MEMORYHUB_PROJECT_ID="amb-benchmark"
    unset MEMORYHUB_CHUNK_TARGET_TOKENS 2>/dev/null || true
    unset MEMORYHUB_CHUNK_OVERLAP_TOKENS 2>/dev/null || true

    if [ -f "outputs/personamem/${name}/rag/32k.json" ] || [ -f "outputs/personamem/${name}/rag/32k.json.gz" ]; then
        log "  SKIP: baseline output already exists"
        return 0
    fi

    log "  Running 589 queries against existing corpus..."
    if ! uv run omb run \
        --split 32k --dataset personamem --memory memoryhub --mode rag \
        --skip-ingestion \
        --name "${name}" \
        --description "Baseline: 256-token chunks, 0% overlap, k=10, chunks-mode" \
        2>&1 | tee "outputs/personamem/${name}.log"; then
        log "  FAILED: baseline"
        return 1
    fi

    log "  DONE: baseline"
    if [ -f "outputs/personamem/${name}/rag/32k.json" ]; then
        local acc
        acc=$(python3 -c "import json; d=json.load(open('outputs/personamem/${name}/rag/32k.json')); print(f\"{d['accuracy']:.1%}\")")
        log "  Baseline accuracy: ${acc}"
    fi
}

show_summary() {
    log "=== SWEEP SUMMARY ==="
    for f in outputs/personamem/c*-o*-k*/rag/32k.json outputs/personamem/c*-o*-k*/rag/32k.json.gz; do
        [ -f "$f" ] || continue
        local name
        name=$(echo "$f" | sed 's|outputs/personamem/||; s|/rag/32k\.json.*||')
        local acc
        if [[ "$f" == *.gz ]]; then
            acc=$(python3 -c "import gzip,json; d=json.load(gzip.open('$f','rt')); print(f\"{d['accuracy']:.1%}\")")
        else
            acc=$(python3 -c "import json; d=json.load(open('$f')); print(f\"{d['accuracy']:.1%}\")")
        fi
        printf "  %-20s %s\n" "$name" "$acc"
    done
}

# Main
if [ "${1:-}" = "--baseline" ]; then
    run_baseline
    exit 0
fi

if [ -n "${1:-}" ] && [ "$1" != "--all" ]; then
    # Run a single named config: e.g., c512-o10-k10
    if [[ "$1" =~ ^c([0-9]+)-o([0-9]+)-k([0-9]+)$ ]]; then
        run_config "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
        exit $?
    else
        echo "Usage: $0 [c<size>-o<overlap>-k<k>] [--baseline] [--all]"
        exit 1
    fi
fi

# Full sweep: baseline first, then all configs
log "Starting full sweep (baseline + 12 configs)"
run_baseline

failed=0
for size in "${CHUNK_SIZES[@]}"; do
    for overlap in "${OVERLAPS[@]}"; do
        # Skip baseline config (already run against existing corpus)
        if [ "$size" = "256" ] && [ "$overlap" = "0" ]; then
            continue
        fi
        if ! run_config "$size" "$overlap"; then
            ((failed++))
        fi
    done
done

show_summary

if [ "$failed" -gt 0 ]; then
    log "WARNING: ${failed} configs failed"
    exit 1
fi
log "All configs complete"
