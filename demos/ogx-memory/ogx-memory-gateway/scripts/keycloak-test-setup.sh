#!/usr/bin/env bash
# Bootstrap a Keycloak realm, client, and user for the gateway-template
# JWT-mode integration test.
#
# Idempotent: re-running is safe. The realm is named gateway-template-test
# and is reset on each run so the test gets a clean baseline.
#
# Prereqs:
#   - oc / kubectl access to the cluster running the keycloak operator
#   - kcadm.sh available inside the keycloak pod (it is, by default)
#
# Outputs an `eval`-able snippet of env vars on stdout so the integration
# test can pick them up:
#
#   eval "$(scripts/keycloak-test-setup.sh)"
#   go test -tags integration ./internal/auth/...

set -euo pipefail

CTX="${KC_CONTEXT:-mcp-rhoai}"
NS="${KC_NAMESPACE:-keycloak}"
POD="${KC_POD:-keycloak-0}"
REALM="${KC_TEST_REALM:-gateway-template-test}"
CLIENT_ID="${KC_TEST_CLIENT_ID:-gateway-template}"
TARGET_CLIENT_ID="${KC_TEST_TARGET_CLIENT_ID:-gateway-template-backend}"
USER_NAME="${KC_TEST_USER:-alice}"
USER_PASS="${KC_TEST_USER_PASSWORD:-alicepw}"
USER_EMAIL="${KC_TEST_USER_EMAIL:-alice@example.test}"

ROUTE_HOST=$(oc --context="$CTX" -n "$NS" get route keycloak -o jsonpath='{.spec.host}')
ISSUER="https://${ROUTE_HOST}/realms/${REALM}"
JWKS_URL="${ISSUER}/protocol/openid-connect/certs"
TOKEN_URL="${ISSUER}/protocol/openid-connect/token"

ADMIN_USER=$(oc --context="$CTX" -n "$NS" get secret keycloak-initial-admin -o jsonpath='{.data.username}' | base64 -d)
ADMIN_PASS=$(oc --context="$CTX" -n "$NS" get secret keycloak-initial-admin -o jsonpath='{.data.password}' | base64 -d)

# Run kcadm commands inside the keycloak pod. Connecting via localhost on
# the pod skips TLS issues with the OpenShift route.
KCADM_CONFIG="/tmp/kcadm-${REALM}.config"
# Quiet wrapper for fire-and-forget kcadm calls.
kcq() {
  oc --context="$CTX" -n "$NS" exec "$POD" -- /opt/keycloak/bin/kcadm.sh "$@" --config "$KCADM_CONFIG" >&2
}
# Loud wrapper for calls whose stdout we capture (uses kcadm's -i flag).
kc() {
  oc --context="$CTX" -n "$NS" exec "$POD" -- /opt/keycloak/bin/kcadm.sh "$@" --config "$KCADM_CONFIG"
}

# Authenticate to the master realm.
kcq config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user "$ADMIN_USER" \
  --password "$ADMIN_PASS"

# Wipe the test realm if it exists, then recreate it.
if kc get "realms/${REALM}" >/dev/null 2>&1; then
  kcq delete "realms/${REALM}"
fi

kcq create realms -s "realm=${REALM}" -s enabled=true

# Create a confidential client with direct-grant + client-credentials enabled.
CLIENT_UUID=$(kc create clients -r "$REALM" \
  -s "clientId=${CLIENT_ID}" \
  -s "secret=test-secret" \
  -s "publicClient=false" \
  -s "directAccessGrantsEnabled=true" \
  -s "serviceAccountsEnabled=true" \
  -s 'redirectUris=["*"]' \
  -i 2>/dev/null | tr -d '\r\n')

# Create the test user with a password, email, and first/last name.
# Keycloak's user-profile validation rejects the password grant with
# "Account is not fully set up" if any "required" profile field is missing
# at login time, even when realm `requiredActions` are otherwise clear.
# Providing firstName/lastName up-front sidesteps that resolution path.
USER_UUID=$(kc create users -r "$REALM" \
  -s "username=${USER_NAME}" \
  -s "email=${USER_EMAIL}" \
  -s "firstName=Test" \
  -s "lastName=User" \
  -s "emailVerified=true" \
  -s "enabled=true" \
  -s 'requiredActions=[]' \
  -i 2>/dev/null | tr -d '\r\n')

kcq set-password -r "$REALM" \
  --userid "$USER_UUID" \
  --new-password "$USER_PASS"

# Clear required actions defensively, in case the realm has defaults that
# attached on user creation.
kcq update "users/${USER_UUID}" -r "$REALM" -s 'requiredActions=[]'

# By default Keycloak does not include the client_id in the `aud` claim
# unless the client is in the audience or there is an audience-mapper.
# Add an audience mapper so tokens get aud=${CLIENT_ID}.
kcq create "clients/${CLIENT_UUID}/protocol-mappers/models" -r "$REALM" \
  -s "name=aud-${CLIENT_ID}" \
  -s "protocol=openid-connect" \
  -s "protocolMapper=oidc-audience-mapper" \
  -s 'config."included.client.audience"='"${CLIENT_ID}" \
  -s 'config."access.token.claim"=true' \
  -s 'config."id.token.claim"=false'

# --- RFC 8693 token exchange (auth v2 part 2) ---
#
# Enable Keycloak's "Standard Token Exchange" (token exchange v2) on the
# source client. With this attribute set, the gateway client can call
# /token with grant_type=token-exchange to swap a user-bearing token for
# one audienced at a different client.
#
# Requires Keycloak 26+ on the server. Older Keycloak deployments need
# the legacy fine-grained-permissions model (not configured here).
kcq update "clients/${CLIENT_UUID}" -r "$REALM" \
  -s 'attributes."standard.token.exchange.enabled"=true'

# Create the target client that the swapped token will be audienced at.
# This represents the downstream resource (in the gateway's case: the
# backend agent). It needs no credentials of its own — it only exists so
# the swap has a valid `audience` to point at.
TARGET_UUID=$(kc create clients -r "$REALM" \
  -s "clientId=${TARGET_CLIENT_ID}" \
  -s "publicClient=true" \
  -s "directAccessGrantsEnabled=false" \
  -s "serviceAccountsEnabled=false" \
  -s "standardFlowEnabled=false" \
  -i 2>/dev/null | tr -d '\r\n')

# Add an audience mapper on the source client so the swapped token's
# `aud` claim contains the target client. Without this, the swap returns
# a token with aud=${CLIENT_ID}, defeating the point.
kcq create "clients/${CLIENT_UUID}/protocol-mappers/models" -r "$REALM" \
  -s "name=aud-${TARGET_CLIENT_ID}" \
  -s "protocol=openid-connect" \
  -s "protocolMapper=oidc-audience-mapper" \
  -s 'config."included.client.audience"='"${TARGET_CLIENT_ID}" \
  -s 'config."access.token.claim"=true' \
  -s 'config."id.token.claim"=false'

cat <<EOF
export KC_INTEGRATION=1
export KC_ISSUER="${ISSUER}"
export KC_JWKS_URL="${JWKS_URL}"
export KC_TOKEN_URL="${TOKEN_URL}"
export KC_AUDIENCE="${CLIENT_ID}"
export KC_CLIENT_ID="${CLIENT_ID}"
export KC_CLIENT_SECRET="test-secret"
export KC_USERNAME="${USER_NAME}"
export KC_PASSWORD="${USER_PASS}"
export KC_USER_EMAIL="${USER_EMAIL}"
export KC_EXCHANGE_TOKEN_URL="${TOKEN_URL}"
export KC_EXCHANGE_CLIENT_ID="${CLIENT_ID}"
export KC_EXCHANGE_CLIENT_SECRET="test-secret"
export KC_EXCHANGE_AUDIENCE="${TARGET_CLIENT_ID}"
EOF
