#!/bin/bash
# Configure GitHub identity provider on the demo OpenShift cluster and grant
# edit access on the three memory-hub namespaces to anyone who logs in via
# the GitHub IdP (which is restricted to the redhat-ai-americas GitHub org).
#
# Idempotent. Safe to re-run against a freshly-rebuilt OpenTLC sandbox.
#
# Prerequisites before running:
#
#   1. You have cluster-admin access to the target OpenShift cluster
#      (verify with `oc whoami` → should return something with admin).
#
#   2. A GitHub OAuth App exists under the redhat-ai-americas GitHub org.
#      Create one at https://github.com/organizations/redhat-ai-americas/settings/applications
#      (Settings → Developer settings → OAuth Apps → New OAuth App) with:
#
#        Application name:  MemoryHub Demo Cluster (or similar)
#        Homepage URL:      https://github.com/redhat-ai-americas/memory-hub
#        Callback URL:      https://oauth-openshift.apps.<cluster>.<sandbox>.opentlc.com/oauth2callback/github
#
#      Get the callback URL from the cluster's existing OAuth server route:
#        oc get route oauth-openshift -n openshift-authentication \
#          -o jsonpath='https://{.spec.host}/oauth2callback/github'
#
#      After creating the app, GitHub will show the Client ID. Click
#      "Generate a new client secret" to get the secret. You only see the
#      secret once, so copy it immediately.
#
#   3. Export the Client ID and secret before running this script:
#        export GITHUB_CLIENT_ID='<from the OAuth App page>'
#        export GITHUB_CLIENT_SECRET='<the generated secret>'
#
# What this script does (all idempotent):
#
#   - Creates or updates the `github-oauth-secret` Secret in openshift-config
#     holding the client secret.
#   - Patches oauth/cluster to add (or update) a GitHub identity provider
#     named `github`, restricted to the `redhat-ai-americas` GitHub org.
#     Other identity providers (htpasswd, etc.) are preserved.
#   - Creates/updates RoleBindings in memory-hub-mcp, memoryhub-auth, and
#     memoryhub-db that bind `system:authenticated:oauth` to the `edit`
#     cluster role. After this runs, any user who logs in via GitHub (which
#     is restricted to the redhat-ai-americas org at the IdP layer) gets
#     contributor-level access on first login with no per-user admin action.
#   - Waits for the OAuth deployment to roll out so the new config is live.
#
# Usage:
#   export GITHUB_CLIENT_ID='...'
#   export GITHUB_CLIENT_SECRET='...'
#   scripts/cluster-setup-github-idp.sh
#
# Verification after running:
#   1. In a private browser window, visit the OpenShift console login page
#      (any `oc login` target URL).
#   2. Click "Log in with GitHub".
#   3. Authorize the OAuth App the first time.
#   4. You should land on the console logged in as your GitHub username.
#   5. As that user, verify access:
#        oc login --token=... --server=...
#        oc get pods -n memory-hub-mcp       # should succeed
#        oc get pods -n memoryhub-auth       # should succeed
#        oc get pods -n memoryhub-db         # should succeed

set -euo pipefail

SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
IDP_NAME="github"
IDP_SECRET_NAME="github-oauth-secret"
GITHUB_ORG="redhat-ai-americas"
NAMESPACES=(memory-hub-mcp memoryhub-auth memoryhub-db)
ROLE="edit"
SUBJECT_GROUP="system:authenticated:oauth"
ROLEBINDING_NAME="memory-hub-contributors"

log()  { echo "[$SCRIPT_NAME] $*" >&2; }
fail() { log "ERROR: $*"; exit 1; }

# --- preflight -----------------------------------------------------------

if ! command -v oc >/dev/null 2>&1; then
  fail "oc CLI not found in PATH"
fi

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found in PATH (needed for idempotent JSON patching)"
fi

if ! oc whoami >/dev/null 2>&1; then
  fail "Not logged in to OpenShift. Run 'oc login' first."
fi

CURRENT_USER="$(oc whoami)"
log "Logged in as: $CURRENT_USER"

if [ -z "${GITHUB_CLIENT_ID:-}" ]; then
  fail "GITHUB_CLIENT_ID env var is not set. See script header for setup instructions."
fi

if [ -z "${GITHUB_CLIENT_SECRET:-}" ]; then
  fail "GITHUB_CLIENT_SECRET env var is not set. See script header for setup instructions."
fi

# Sanity check: at least 10 chars so we don't silently store an empty string.
if [ "${#GITHUB_CLIENT_SECRET}" -lt 10 ]; then
  fail "GITHUB_CLIENT_SECRET looks too short (${#GITHUB_CLIENT_SECRET} chars). Did you paste it correctly?"
fi

log "All preflight checks passed."

# --- verify target namespaces exist --------------------------------------

for ns in "${NAMESPACES[@]}"; do
  if ! oc get namespace "$ns" >/dev/null 2>&1; then
    fail "Namespace '$ns' does not exist. Deploy memory-hub before configuring IdP access."
  fi
done
log "All target namespaces present: ${NAMESPACES[*]}"

# --- step 1: create/update the OAuth client secret in openshift-config ---

log "Creating/updating Secret $IDP_SECRET_NAME in openshift-config ..."
oc create secret generic "$IDP_SECRET_NAME" \
  --from-literal=clientSecret="$GITHUB_CLIENT_SECRET" \
  -n openshift-config \
  --dry-run=client -o yaml | oc apply -f -

# --- step 2: patch oauth/cluster to add/update the GitHub IdP ------------

log "Patching oauth/cluster to add/update the GitHub identity provider ..."

# Fetch current config, modify the identityProviders list in Python so we
# preserve other IdPs (htpasswd, etc.) while inserting/updating `github`.
NEW_OAUTH_JSON="$(
  oc get oauth cluster -o json \
    | GITHUB_CLIENT_ID="$GITHUB_CLIENT_ID" \
      IDP_NAME="$IDP_NAME" \
      IDP_SECRET_NAME="$IDP_SECRET_NAME" \
      GITHUB_ORG="$GITHUB_ORG" \
      python3 -c '
import json, os, sys

data = json.load(sys.stdin)
spec = data.setdefault("spec", {})
providers = spec.get("identityProviders") or []

# Drop any existing entry with our name so we update cleanly.
providers = [p for p in providers if p.get("name") != os.environ["IDP_NAME"]]

providers.append({
    "name": os.environ["IDP_NAME"],
    "type": "GitHub",
    "mappingMethod": "claim",
    "github": {
        "clientID": os.environ["GITHUB_CLIENT_ID"],
        "clientSecret": {"name": os.environ["IDP_SECRET_NAME"]},
        "organizations": [os.environ["GITHUB_ORG"]],
    },
})

spec["identityProviders"] = providers
print(json.dumps(data))
'
)"

echo "$NEW_OAUTH_JSON" | oc apply -f - >/dev/null
log "oauth/cluster updated."

# --- step 3: create/update RoleBindings in the three namespaces ----------

for ns in "${NAMESPACES[@]}"; do
  log "Applying RoleBinding $ROLEBINDING_NAME in $ns ..."
  cat <<EOF | oc apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: $ROLEBINDING_NAME
  namespace: $ns
  labels:
    app.kubernetes.io/part-of: memory-hub
    app.kubernetes.io/component: contributor-access
  annotations:
    memory-hub/managed-by: cluster-setup-github-idp.sh
    memory-hub/rationale: "Grant edit to any GitHub org member (login-restricted to $GITHUB_ORG at the IdP layer)"
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: $ROLE
subjects:
- kind: Group
  apiGroup: rbac.authorization.k8s.io
  name: $SUBJECT_GROUP
EOF
done

# --- step 4: wait for the OAuth server to roll out -----------------------

log "Waiting for openshift-authentication deployment to roll out ..."
if oc rollout status deployment/oauth-openshift -n openshift-authentication --timeout=300s; then
  log "OAuth server rollout complete."
else
  log "WARNING: rollout status timed out. The config change may still be propagating."
fi

# --- step 5: print verification instructions -----------------------------

OAUTH_HOST="$(oc get route oauth-openshift -n openshift-authentication -o jsonpath='{.spec.host}' 2>/dev/null || echo '<unknown>')"
CONSOLE_HOST="$(oc get route console -n openshift-console -o jsonpath='{.spec.host}' 2>/dev/null || echo '<unknown>')"

cat <<EOF

==========================================================================
GitHub IdP setup complete.
==========================================================================

OAuth callback URL (configure this in the GitHub OAuth App if you haven't):
  https://$OAUTH_HOST/oauth2callback/$IDP_NAME

Console login URL (share with contributors):
  https://$CONSOLE_HOST/

RoleBindings applied:
$(for ns in "${NAMESPACES[@]}"; do echo "  - $ROLEBINDING_NAME in $ns → ClusterRole/$ROLE → Group/$SUBJECT_GROUP"; done)

Verification (do this yourself first, before telling contributors to try):
  1. Open a PRIVATE/incognito browser window.
  2. Visit https://$CONSOLE_HOST/
  3. Choose "github" as the login method.
  4. Log in with a GitHub account that IS a member of the $GITHUB_ORG org.
  5. You should land in the console as that user.
  6. In a terminal:
       oc login --server=https://api.<this-cluster>:6443 -u <your-github-username>
       oc get pods -n memory-hub-mcp       # should succeed
       oc get pods -n memoryhub-auth       # should succeed
       oc get pods -n memoryhub-db         # should succeed

If step 4 fails with "not a member of the allowed organization", the
login restriction is working but the user isn't in the allowed org —
add them to https://github.com/orgs/$GITHUB_ORG/people.

Re-run this script any time:
  - The GitHub OAuth App client secret is rotated
  - The OpenTLC sandbox is rebuilt
  - The RoleBindings are accidentally deleted
EOF
