#!/bin/bash
# Deployment script for MemoryHub Auth Service to OpenShift
# Usage: ./deploy.sh [project-name]
#
# Conforms to docs/build-deploy-hardening.md (#88).

set -euo pipefail

PROJECT="${1:-memoryhub-auth}"

# Manifest is rewritten through sed to embed the project-qualified registry
# path. Secrets (auth-rsa-keys, auth-admin-key) are managed out-of-band --
# they're documented in openshift.yaml comments and created by this script
# before the apply -- so the manifest itself contains no Secret stanzas and
# the apply pipeline is just sed + oc apply.
apply_manifest() {
    sed "s|image: auth-server:latest|image: image-registry.openshift-image-registry.svc:5000/$PROJECT/auth-server:latest|g" openshift.yaml | \
        oc apply -f - -n "$PROJECT"
}

echo "========================================="
echo "MemoryHub Auth — Deployment to OpenShift"
echo "========================================="
echo "Project: $PROJECT"
echo ""

# Check if logged in to OpenShift
if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Please run 'oc login' first."
    exit 1
fi

# Create project if it doesn't exist
echo "→ Setting up project..."
if oc get project "$PROJECT" &>/dev/null; then
    echo "  Using existing project: $PROJECT"
else
    echo "  Creating new project: $PROJECT"
    oc new-project "$PROJECT"
fi

# Generate RSA keys for JWT signing if the secret doesn't exist or has empty values
echo "→ Checking RSA key secret..."
EXISTING_KEY=$(oc get secret auth-rsa-keys -n "$PROJECT" -o jsonpath='{.data.AUTH_RSA_PRIVATE_KEY_PEM}' 2>/dev/null || echo "")
if [ -z "$EXISTING_KEY" ] || [ "$EXISTING_KEY" = "" ]; then
    echo "  Generating RSA-2048 key pair for JWT signing..."
    TMPKEYS=$(mktemp -d)
    trap "rm -rf $TMPKEYS" EXIT
    openssl genrsa 2048 > "$TMPKEYS/private.pem" 2>/dev/null
    openssl rsa -in "$TMPKEYS/private.pem" -pubout > "$TMPKEYS/public.pem" 2>/dev/null

    # Create/replace the secret with real keys
    oc create secret generic auth-rsa-keys \
        --from-file=AUTH_RSA_PRIVATE_KEY_PEM="$TMPKEYS/private.pem" \
        --from-file=AUTH_RSA_PUBLIC_KEY_PEM="$TMPKEYS/public.pem" \
        --dry-run=client -o yaml | oc apply -f - -n "$PROJECT"
    echo "  RSA key secret created."
else
    echo "  RSA key secret already exists."
fi

# Generate OpenShift OAuth client secret if it doesn't exist
echo "→ Checking OpenShift OAuth client secret..."
EXISTING_OAUTH_SECRET=$(oc get secret openshift-oauth-client-secret -n "$PROJECT" -o jsonpath='{.data.AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET}' 2>/dev/null || echo "")
if [ -z "$EXISTING_OAUTH_SECRET" ]; then
    echo "  Generating OpenShift OAuth client secret..."
    OAUTH_SECRET=$(openssl rand -base64 32 | tr -d '\n')
    oc create secret generic openshift-oauth-client-secret \
        --from-literal=AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET="$OAUTH_SECRET" \
        --dry-run=client -o yaml | oc apply -f - -n "$PROJECT"
    echo "  OpenShift OAuth client secret created."
else
    echo "  OpenShift OAuth client secret already exists."
fi

# Apply OAuthClient CR (cluster-scoped, requires cluster-admin)
echo "→ Checking OAuthClient CR..."
if oc auth can-i create oauthclients 2>/dev/null; then
    if [ -f deploy/oauthclient.yaml ]; then
        # Replace the placeholder secret with the actual value from the K8s Secret.
        OAUTH_SECRET_VALUE=$(oc get secret openshift-oauth-client-secret -n "$PROJECT" \
            -o jsonpath='{.data.AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET}' | base64 -d)
        sed "s|secret: PLACEHOLDER-SEE-COMMENTS-ABOVE|secret: $OAUTH_SECRET_VALUE|" \
            deploy/oauthclient.yaml | oc apply -f - 2>&1
        echo "  OAuthClient CR applied."
    else
        echo "  deploy/oauthclient.yaml not found, skipping."
    fi
else
    echo "  Skipping OAuthClient CR (no cluster-admin permissions)."
    echo "  Ask a cluster-admin to run: oc apply -f deploy/oauthclient.yaml"
fi

# Run Alembic migrations before deploying new code
echo "→ Running database migrations..."
DB_NAMESPACE="memoryhub-db"
oc port-forward -n "$DB_NAMESPACE" svc/memoryhub-pg 15432:5432 &
MIGRATE_PF_PID=$!
WAITED=0
until nc -z localhost 15432 2>/dev/null; do
    if [ $WAITED -ge 10 ]; then
        echo "  ERROR: Port-forward for migrations did not become ready."
        kill "$MIGRATE_PF_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done
DB_PASS=$(oc get secret memoryhub-pg-credentials -n "$DB_NAMESPACE" \
    -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)
AUTH_DB_HOST=localhost \
AUTH_DB_PORT=15432 \
AUTH_DB_USER=memoryhub \
AUTH_DB_PASSWORD="$DB_PASS" \
AUTH_DB_NAME=memoryhub \
    .venv/bin/alembic upgrade head 2>&1
kill "$MIGRATE_PF_PID" 2>/dev/null || true
echo "  Migrations complete."

# Apply OpenShift resources (skip the RSA secret since we handle it above)
echo "→ Applying OpenShift resources..."
apply_manifest

# Build
echo "→ Building container image..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

cp Containerfile requirements.txt "$BUILD_DIR/"
cp conftest.py "$BUILD_DIR/" 2>/dev/null || true
rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' --exclude='.mypy_cache' src/ "$BUILD_DIR/src/"

# Fix permissions
FIXED_COUNT=$(find "$BUILD_DIR" -name "*.py" -perm 600 2>/dev/null | wc -l | tr -d ' ')
if [ "$FIXED_COUNT" -gt "0" ]; then
    echo "  Fixing $FIXED_COUNT file(s) with 600 permissions..."
    find "$BUILD_DIR" -name "*.py" -perm 600 -exec chmod 644 {} \;
fi

oc start-build auth-server --from-dir="$BUILD_DIR" --follow -n "$PROJECT"

# Re-apply manifest to re-resolve the :latest imagestream tag against the
# digest the build just pushed. The Deployment carries
# `alpha.image.policy.openshift.io/resolve-names: '*'`, which rewrites the
# tag to a concrete digest at apply time and never re-resolves on its own.
# Without this re-apply, the next rollout would spin up a pod on the digest
# :latest pointed at *before* the build (#88, manifestation 3/4).
echo "→ Re-applying manifest to re-resolve image digest..."
apply_manifest

# Wait for rollout
echo "→ Deploying application..."
oc rollout restart deployment/auth-server -n "$PROJECT" 2>/dev/null || true
oc rollout status deployment/auth-server -n "$PROJECT" --timeout=300s

# Get route and set issuer
ROUTE_HOST=$(oc get route auth-server -n "$PROJECT" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [ -n "$ROUTE_HOST" ]; then
    ISSUER_URL="https://${ROUTE_HOST}"
    echo "→ Setting AUTH_ISSUER to $ISSUER_URL..."
    oc set env deployment/auth-server AUTH_ISSUER="$ISSUER_URL" -n "$PROJECT"
    # Wait for the rollout triggered by the env change. Both this rollout
    # and the previous one resolve against the post-re-apply digest, so the
    # final running image must equal the imagestream :latest digest.
    oc rollout status deployment/auth-server -n "$PROJECT" --timeout=120s
fi

# Verify the running pod is on the just-pushed digest. This must come AFTER
# both rollouts complete (the initial restart and the env-triggered second
# rollout) so the final running spec is what we compare against. If the
# digests don't match, the build pushed but the Deployment is on an older
# digest -- exactly the failure family #88 closes.
echo "→ Verifying running digest matches imagestream :latest..."
RUNNING=$(oc get deploy auth-server -n "$PROJECT" \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="auth-server")].image}' 2>/dev/null || echo "")
LATEST_DIGEST=$(oc get is auth-server -n "$PROJECT" \
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

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
if [ -n "$ROUTE_HOST" ]; then
    echo "Auth Server URL: https://${ROUTE_HOST}"
    echo ""
    echo "Test with:"
    echo "  curl -s https://${ROUTE_HOST}/healthz"
    echo "  curl -s https://${ROUTE_HOST}/.well-known/oauth-authorization-server | python3 -m json.tool"
    echo "  curl -s https://${ROUTE_HOST}/.well-known/jwks.json | python3 -m json.tool"
else
    echo "Warning: Could not retrieve route URL"
fi
echo "========================================="
