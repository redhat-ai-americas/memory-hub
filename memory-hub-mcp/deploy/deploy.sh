#!/usr/bin/env bash
# Deploy the MemoryHub MCP server to OpenShift.
#
# This script is the single canonical deploy path for memory-hub-mcp.
# The namespace is hardcoded to "memory-hub-mcp" intentionally — past
# incidents with template-default namespaces ("mcp-demo") created duplicate
# deployments in the wrong place. Do not parameterize this without reading
# docs/admin and the retros first.
#
# Steps:
#   1. Create namespace if needed
#   2. Apply manifests (configmap, secret, deployment, service, route)
#   3. Re-resolve the existing ImageStream tag to a concrete digest
#   4. Force a rollout restart (the selected image has the same :latest tag,
#      so without an explicit restart Kubernetes will not always pick up
#      the new digest — this has bitten us repeatedly)
#   5. Wait for deployment rollout
#   6. Verify exactly one ready pod
#   7. Print the route URL
set -euo pipefail

NAMESPACE="memory-hub-mcp"
DEPLOYMENT="memory-hub-mcp"
CONTEXT="${MEMORYHUB_CONTEXT:-$(oc config current-context 2>/dev/null)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Auth URLs are resolved at deploy time and substituted into the manifest
# (same pattern as memoryhub-auth/deploy.sh).
AUTH_JWKS_URI=""
AUTH_ISSUER=""

apply_manifest() {
    sed "s|__AUTH_JWKS_URI__|${AUTH_JWKS_URI}|g; s|__AUTH_ISSUER__|${AUTH_ISSUER}|g" \
        "$SCRIPT_DIR/openshift.yaml" | oc apply --context "$CONTEXT" -f - -n "$NAMESPACE"
}

echo "=== MemoryHub MCP Server Deployment ==="
echo "Namespace:  $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo ""

# Check OpenShift login
if ! oc whoami --context "$CONTEXT" &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

# Step 1: Create namespace
if oc get namespace --context "$CONTEXT" "$NAMESPACE" &>/dev/null; then
    echo "Using existing namespace: $NAMESPACE"
else
    echo "Creating namespace: $NAMESPACE"
    oc create namespace --context "$CONTEXT" "$NAMESPACE"
fi

# Step 2: Apply manifests
echo ""
echo "Applying manifests..."
# users-configmap.yaml is per-operator and gitignored; it holds real api_keys.
# Refuse to proceed if the operator hasn't copied the example template yet or
# if the copy still contains the placeholder strings.
USERS_CM="$SCRIPT_DIR/users-configmap.yaml"
if [[ ! -f "$USERS_CM" ]]; then
  echo "Generating $USERS_CM from template with random API keys..."
  export CURRENT_USER="${USER:-$(whoami)}"
  python3 -c "
import os, re, secrets, pathlib
src = pathlib.Path('$SCRIPT_DIR/users-configmap.example.yaml').read_text()
user = os.environ.get('CURRENT_USER', 'admin')
out = src.replace('CURRENT_USER_DISPLAY', user.replace('-', ' ').title())
out = out.replace('CURRENT_USER', user)
out = re.sub(
    r'REPLACE-ME-GENERATE-WITH-openssl-rand-hex-16',
    lambda m: 'mh-dev-' + secrets.token_hex(8),
    out,
)
pathlib.Path('$USERS_CM').write_text(out)
print(f'  Generated for user \"{user}\" with {src.count(\"REPLACE-ME\")} unique keys.')
"
fi
if grep -q "REPLACE-ME-" "$USERS_CM"; then
  echo "ERROR: $USERS_CM still contains REPLACE-ME placeholders."
  echo "       Generate real api_keys (e.g. \`openssl rand -hex 16\`) and"
  echo "       replace them before running deploy.sh."
  exit 1
fi
# Apply configmap first — the Deployment mounts it as a volume.
oc apply --context "$CONTEXT" -f "$USERS_CM" -n "$NAMESPACE"

# Resolve auth service URLs for JWT verification.
echo ""
echo "Resolving auth service URLs..."
AUTH_ROUTE_HOST=$(oc get route auth-server --context "$CONTEXT" -n memoryhub-auth -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
if [ -n "$AUTH_ROUTE_HOST" ]; then
    AUTH_JWKS_URI="https://${AUTH_ROUTE_HOST}/.well-known/jwks.json"
    AUTH_ISSUER="https://${AUTH_ROUTE_HOST}"
    echo "  AUTH_JWKS_URI=$AUTH_JWKS_URI"
    echo "  AUTH_ISSUER=$AUTH_ISSUER"
else
    echo "WARNING: auth-server Route not found in memoryhub-auth namespace."
    echo "  JWT verification will not work until auth is deployed and MCP is re-deployed."
    echo "  Run: scripts/deploy-full.sh (deploys auth before MCP)"
fi

# Create the memoryhub-db-credentials Secret from the DB namespace's source of
# truth. This replaces the old pattern of baking a placeholder password into
# openshift.yaml and patching it post-deploy (#192).
DB_SRC_NAMESPACE="memoryhub-db"
DB_SRC_SECRET="memoryhub-pg-credentials"

echo ""
echo "Creating DB credentials Secret from $DB_SRC_NAMESPACE/$DB_SRC_SECRET..."
if ! oc get secret --context "$CONTEXT" "$DB_SRC_SECRET" -n "$DB_SRC_NAMESPACE" &>/dev/null; then
    echo "ERROR: Source Secret $DB_SRC_SECRET not found in namespace $DB_SRC_NAMESPACE."
    echo "       Deploy PostgreSQL first (scripts/deploy-full.sh) or create the Secret manually."
    exit 1
fi

DB_PASSWORD=$(oc get secret --context "$CONTEXT" "$DB_SRC_SECRET" -n "$DB_SRC_NAMESPACE" \
    -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)

echo ""
echo "Resolving embedding and reranker service URLs..."
EMBEDDING_SVC=$(oc get svc --context "$CONTEXT" -n embedding-model -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
RERANKER_SVC=$(oc get svc --context "$CONTEXT" -n reranker-model -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

EMBEDDING_ARGS=""
RERANKER_ARGS=""

if [ -n "$EMBEDDING_SVC" ]; then
    EMBEDDING_URL="http://${EMBEDDING_SVC}.embedding-model.svc.cluster.local:80/embed"
    EMBEDDING_ARGS="--from-literal=MEMORYHUB_EMBEDDING_URL=$EMBEDDING_URL"
    echo "  Embedding: $EMBEDDING_URL"
else
    echo "  WARNING: No embedding service found in embedding-model namespace."
    echo "  Search will use mock embeddings (hash-based, not semantic)."
fi

if [ -n "$RERANKER_SVC" ]; then
    RERANKER_URL="http://${RERANKER_SVC}.reranker-model.svc.cluster.local:80"
    RERANKER_ARGS="--from-literal=MEMORYHUB_RERANKER_URL=$RERANKER_URL"
    echo "  Reranker: $RERANKER_URL"
else
    echo "  Reranker not found -- will use cosine-only ranking (still functional)."
fi

oc create secret generic memoryhub-db-credentials \
    --from-literal=MEMORYHUB_DB_HOST=memoryhub-pg.memoryhub-db.svc.cluster.local \
    --from-literal=MEMORYHUB_DB_PORT=5432 \
    --from-literal=MEMORYHUB_DB_NAME=memoryhub \
    --from-literal=MEMORYHUB_DB_USER=memoryhub \
    --from-literal=MEMORYHUB_DB_PASSWORD="$DB_PASSWORD" \
    $EMBEDDING_ARGS \
    $RERANKER_ARGS \
    --dry-run=client -o json | oc apply --context "$CONTEXT" -f - -n "$NAMESPACE"
echo "OK: memoryhub-db-credentials Secret created/updated in $NAMESPACE"

# Verify MinIO credentials exist (copied cross-namespace by deploy-full.sh)
if ! oc get secret --context "$CONTEXT" memoryhub-minio-credentials -n "$NAMESPACE" &>/dev/null; then
    echo "  WARNING: Secret memoryhub-minio-credentials not found in $NAMESPACE."
    echo "  Run scripts/deploy-full.sh to deploy MinIO and copy credentials,"
    echo "  or see deploy/minio/README.md for manual setup."
    echo "  S3 storage will not work until this secret is present."
fi

apply_manifest

# Step 3: Re-resolve the :latest ImageStream tag.
#
# The Deployment uses `image: memory-hub-mcp:latest` and the
# `alpha.image.policy.openshift.io/resolve-names` annotation. That annotation
# resolves the tag to a concrete digest *at apply time*, not at pod creation
# time. Step 3 applied the manifest before the build, so the Deployment is
# currently pinned to whatever digest :latest pointed at *before* this build.
# Re-applying after the build re-resolves :latest to the digest we just pushed.
#
# Without this step, `oc rollout restart` below will spin up a new pod from
# the OLD digest, even though the build just pushed new code. We hit this
# during the 2026-04-07 Wave 2 deploy (4th retro to flag a deploy/image-cache
# failure family) — the fix is documented in the wave1-4-mcp-fixes retro.
echo ""
echo "Re-applying manifest to re-resolve image digest..."
apply_manifest

# Step 4: Force rollout restart so the selected image digest is picked up
echo ""
echo "Restarting rollout..."
oc rollout restart --context "$CONTEXT" "deployment/$DEPLOYMENT" -n "$NAMESPACE"

# Step 5: Wait for rollout
echo ""
echo "Waiting for rollout..."
oc rollout status --context "$CONTEXT" "deployment/$DEPLOYMENT" -n "$NAMESPACE" --timeout=300s

# Step 6: Verify single Deployment + one available replica.
# Counting Running pods directly is unreliable: terminating pods stay in
# Running phase until they exit, so right after a rollout you briefly see
# 2 Running pods (new + terminating old). Check the Deployment status
# instead — that's the source of truth for "is the desired state met".
#
# These are HARD failures, not warnings (#88). A deploy script that exits
# 0 with a degraded deployment is exactly the failure family this issue
# closes.
echo ""
echo "Verifying deployment state..."
DEPLOY_COUNT=$(oc get deploy --context "$CONTEXT" -n "$NAMESPACE" \
    -l "app.kubernetes.io/name=$DEPLOYMENT" \
    -o name 2>/dev/null | wc -l | tr -d ' ')
if [ "$DEPLOY_COUNT" != "1" ]; then
    echo "ERROR: expected 1 Deployment named $DEPLOYMENT, found $DEPLOY_COUNT"
    oc get deploy --context "$CONTEXT" -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
    exit 1
fi

AVAILABLE=$(oc get deploy --context "$CONTEXT" "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
DESIRED=$(oc get deploy --context "$CONTEXT" "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.replicas}' 2>/dev/null)
if [ "$AVAILABLE" = "$DESIRED" ] && [ "$AVAILABLE" = "1" ]; then
    echo "OK: deployment at desired state (1 available replica)"
else
    echo "ERROR: deployment not at desired state (available=${AVAILABLE:-0}, desired=${DESIRED:-?})"
    oc get pods --context "$CONTEXT" -n "$NAMESPACE" -l "app.kubernetes.io/name=$DEPLOYMENT"
    exit 1
fi

# Step 6.5: Verify the running pod is on the selected digest (#88).
# The Deployment spec carries the resolved digest after re-apply; the
# ImageStream's :latest tag carries the canonical selected image
# digest. They MUST match. If they don't, the build pushed but the
# Deployment is still pinned to an older digest, which is exactly the
# failure family this verification closes.
echo ""
echo "Verifying running digest matches imagestream :latest..."
RUNNING=$(oc get deploy --context "$CONTEXT" "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="mcp-server")].image}' 2>/dev/null || echo "")
LATEST_DIGEST=$(oc get is --context "$CONTEXT" "$DEPLOYMENT" -n "$NAMESPACE" \
    -o jsonpath='{.status.tags[?(@.tag=="latest")].items[0].image}' 2>/dev/null || echo "")
echo "  Running: $RUNNING"
echo "  Latest:  $LATEST_DIGEST"
if [ -z "$RUNNING" ] || [ -z "$LATEST_DIGEST" ]; then
    echo "ERROR: could not resolve running image or imagestream :latest digest"
    exit 1
fi
RUNNING_DIGEST="${RUNNING##*@}"
if [ "$RUNNING_DIGEST" != "$LATEST_DIGEST" ]; then
    echo "ERROR: running digest does not match imagestream :latest"
    echo "  This is the #88 failure family -- the build pushed but the"
    echo "  Deployment is on an older digest. Investigate before retrying."
    exit 1
fi
echo "  OK: running digest matches imagestream :latest"

# Step 7: Print route URL.
#
# Tool-count regression check is performed OUT-OF-BAND by the operator
# via mcp-test-mcp after this script completes. mcp-test-mcp is itself an
# MCP server (not a CLI), so the deploy script can't shell out to it.
# The /deploy-mcp slash command's Step 4 ("Verify deployed tools with
# mcp-test-mcp") is the operator-side equivalent and MUST be run after
# every memory-hub-mcp deploy.
#
# The static preflight at Step 0 above catches the registration silent-
# failure class (file present but not imported / not in mcp.add_tool list)
# before the build runs. Runtime issues that the static check can't see
# (build context missing files, runtime decoration errors, dependency
# import failures) are what the post-deploy mcp-test-mcp check catches.
ROUTE=$(oc get route --context "$CONTEXT" "$DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
echo ""
echo "=== Deployment Complete ==="
if [ -n "$ROUTE" ]; then
    echo "MCP endpoint: https://$ROUTE/mcp/"
    echo ""
    echo "REQUIRED next step -- verify deployed tools with mcp-test-mcp:"
    echo "  connect_to_server name=memory-hub-mcp url=https://$ROUTE/mcp/"
    echo "  list_tools server_name=memory-hub-mcp"
    echo ""
    echo "Without this check, runtime tool-registration failures (build"
    echo "context missing files, decoration errors, etc.) will not be caught."
else
    echo "ERROR: Could not retrieve route URL"
    exit 1
fi
