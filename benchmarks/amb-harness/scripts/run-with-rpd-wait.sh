#!/usr/bin/env bash
# Run AMB benchmark with RPD-aware retry. Probes the Gemini API before
# starting the harness, backs off if rate-limited.
set -euo pipefail

GEMINI_KEY=$(grep GEMINI_API_KEY ~/.secrets | cut -d'=' -f2)
PROBE_URL="https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key=$GEMINI_KEY"
PROBE_BODY='{"contents":[{"parts":[{"text":"Say ok"}]}]}'

probe() {
    local status
    status=$(curl -s -o /dev/null -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -d "$PROBE_BODY" "$PROBE_URL")
    echo "$status"
}

echo "[$(date)] Probing Gemini API..."
while true; do
    status=$(probe)
    if [ "$status" = "200" ]; then
        echo "[$(date)] API responsive (HTTP $status). Starting run."
        break
    elif [ "$status" = "429" ]; then
        echo "[$(date)] Rate limited (HTTP 429). Waiting 10 minutes..."
        sleep 600
    else
        echo "[$(date)] Unexpected status $status. Waiting 60s..."
        sleep 60
    fi
done

cd "$(dirname "$0")/.."

# Ensure port-forward is up
if ! lsof -i:25432 >/dev/null 2>&1; then
    echo "[$(date)] Starting port-forward..."
    oc port-forward statefulset/memoryhub-pg 25432:5432 --context mcp-rhoai -n memoryhub-db &>/dev/null &
    sleep 2
fi

MEMORYHUB_URL="https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/" \
MEMORYHUB_API_KEY=$(cat ~/.config/memoryhub/api-key) \
MEMORYHUB_DB_PASS=$(oc get secret memoryhub-db-credentials --context mcp-rhoai -n memoryhub-db -o jsonpath='{.data.password}' | base64 -d) \
GOOGLE_API_KEY=$GEMINI_KEY \
OMB_ANSWER_LLM=gemini \
OMB_JUDGE_LLM=gemini \
OMB_ANSWER_MODEL=gemini-3.1-pro-preview \
uv run omb run --dataset personamem --split 32k --memory memoryhub \
  --skip-ingestion -o ../../benchmarks/amb-outputs
