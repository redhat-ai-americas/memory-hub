#!/bin/bash
# Deployment script for MemoryHub Auth Service to OpenShift
# Usage: ./deploy.sh [project-name]

set -euo pipefail

PROJECT="${1:-memoryhub-auth}"

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

# Apply OpenShift resources (skip the RSA secret since we handle it above)
echo "→ Applying OpenShift resources..."
sed "s|image: auth-server:latest|image: image-registry.openshift-image-registry.svc:5000/$PROJECT/auth-server:latest|g" openshift.yaml | \
    grep -v "kind: Secret" | \
    awk 'BEGIN{skip=0} /^---/{skip=0} /name: auth-rsa-keys/{skip=1} skip{next} {print}' | \
    oc apply -f - -n "$PROJECT"

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
    # Wait for the rollout triggered by the env change
    oc rollout status deployment/auth-server -n "$PROJECT" --timeout=120s
fi

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
