#!/usr/bin/env bash
# Verify the public Route with TLS validation, using the selected cluster's
# ingress trust bundle or an explicit CA file. Never bypass verification.
set -euo pipefail

CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
ROUTE_HOST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --context) CONTEXT="$2"; shift ;;
        --host) ROUTE_HOST="$2"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done
if [ -z "$CONTEXT" ] || ! [[ "$ROUTE_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
    echo "ERROR: a non-empty context and Route hostname are required." >&2
    exit 1
fi

CA_FILE="${MEMORYHUB_ROUTE_CA_FILE:-}"
TEMP_CA=""
cleanup() { [ -z "$TEMP_CA" ] || rm -f "$TEMP_CA"; }
trap cleanup EXIT

if [ -n "$CA_FILE" ]; then
    if [ ! -r "$CA_FILE" ]; then
        echo "ERROR: MEMORYHUB_ROUTE_CA_FILE is not readable: $CA_FILE" >&2
        exit 1
    fi
else
    # This is the ingress CA for the public Route, not the service CA used by
    # reencrypt between the router and OAuth proxy. Fetch through authenticated
    # oc in the explicit context; do not learn trust from the unverified Route.
    INGRESS_CA=$(oc get configmap default-ingress-cert --context "$CONTEXT" \
        -n openshift-config-managed -o jsonpath='{.data.ca-bundle\.crt}' 2>/dev/null || true)
    if [ -n "$INGRESS_CA" ]; then
        TEMP_CA=$(mktemp "${TMPDIR:-/tmp}/memoryhub-route-ca.XXXXXX")
        printf '%s\n' "$INGRESS_CA" > "$TEMP_CA"
        CA_FILE="$TEMP_CA"
    fi
fi

CURL_ARGS=(-sS -o /dev/null -w '%{http_code}' --max-time 5)
if [ -n "$CA_FILE" ]; then
    CURL_ARGS+=(--cacert "$CA_FILE")
fi
HEALTH_CODE=000
for attempt in $(seq 1 12); do
    if ! HEALTH_CODE=$(curl "${CURL_ARGS[@]}" "https://$ROUTE_HOST/healthz"); then
        HEALTH_CODE=000
    fi
    if [ "$HEALTH_CODE" = "200" ]; then
        echo "  OK: https://$ROUTE_HOST/healthz returned 200 with verified TLS"
        exit 0
    fi
    [ "$attempt" = "12" ] || sleep 5
done
echo "ERROR: https://$ROUTE_HOST/healthz returned $HEALTH_CODE with TLS verification enabled." >&2
echo "  For a custom ingress CA, set MEMORYHUB_ROUTE_CA_FILE to its trusted PEM bundle." >&2
exit 1
