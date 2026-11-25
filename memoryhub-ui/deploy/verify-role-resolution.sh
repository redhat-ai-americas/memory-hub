#!/usr/bin/env bash
# Phase 1 cluster verification for human role resolution (#744).
#
# Answers, on a live cluster, the questions the design leaves open
# (docs/auth/human-role-resolution.md):
#   1. Does a token scoped to "user:info user:check-access" (what oauth-proxy
#      and the auth broker request) read users/~ and get an unrestricted
#      SelfSubjectAccessReview answer for memoryhub.io/dashboard?
#   2. What does TokenReview return for that token (user, uid, groups,
#      scopes), and does a SubjectAccessReview need the groups spelled out?
#   3. Does removing a person from an OpenShift Group take effect for a
#      token that already exists (an open session)?
#   4. Does removing a RoleBinding take effect for an existing token?
#   5. Is User.metadata.uid stable and what does it look like?
#
# Everything is created in a scratch namespace and a scratch Group, and is
# removed on exit. A short-lived scoped OAuthAccessToken is minted for the
# test user and deleted on exit. The token is never printed.
#
# Requirements: oc logged in as cluster-admin in the given context, curl,
# openssl, python3. Runs on macOS Bash 3.2.
#
# Usage:
#   memoryhub-ui/deploy/verify-role-resolution.sh --context mcp-rhoai [--user NAME]
#
# --user defaults to `oc whoami`. Results are printed as a table to paste
# into docs/auth/role-resolution-cluster-verification.md.
set -euo pipefail

CONTEXT=""
TEST_USER=""
NS="memoryhub-rbac-verify"
GROUP="memoryhub-rbac-verify-users"
while [ $# -gt 0 ]; do
    case "$1" in
        --context) CONTEXT="$2"; shift ;;
        --user) TEST_USER="$2"; shift ;;
        --namespace) NS="$2"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done
if [ -z "$CONTEXT" ]; then
    echo "--context is required (for this project: --context mcp-rhoai)" >&2
    exit 1
fi

oc_() { oc --context "$CONTEXT" "$@"; }

[ -n "$TEST_USER" ] || TEST_USER="$(oc_ whoami)"
case "$TEST_USER" in system:*) echo "Use a human user, not $TEST_USER" >&2; exit 1 ;; esac

API="$(oc_ whoami --show-server)"
ADMIN_TOKEN="$(oc_ whoami -t)"
TOKEN_NAME=""
RESULTS=""

record() { RESULTS="${RESULTS}| $1 | $2 | $3 |
"; printf '  %-58s %s\n' "$1" "$2"; }

cleanup() {
    set +e
    [ -n "$TOKEN_NAME" ] && oc_ delete oauthaccesstoken "$TOKEN_NAME" --ignore-not-found >/dev/null 2>&1
    oc_ delete group "$GROUP" --ignore-not-found >/dev/null 2>&1
    oc_ delete namespace "$NS" --ignore-not-found --wait=false >/dev/null 2>&1
}
trap cleanup EXIT

api() {
    # api METHOD PATH TOKEN [JSON]: prints "<status> <body>"
    local method="$1" path="$2" token="$3" body="${4:-}"
    if [ -n "$body" ]; then
        curl -sk -o /tmp/mh-verify.$$ -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
            --data "$body" "$API$path"
    else
        curl -sk -o /tmp/mh-verify.$$ -w '%{http_code}' -X "$method" \
            -H "Authorization: Bearer $token" "$API$path"
    fi
    printf ' '
    cat /tmp/mh-verify.$$
    rm -f /tmp/mh-verify.$$
}

json() { python3 -c "import json,sys; d=json.loads(sys.stdin.read().split(' ',1)[1]); print($1)"; }

ssar() {
    # ssar TOKEN VERB -> true|false|error:<status>
    local out status
    out="$(api POST /apis/authorization.k8s.io/v1/selfsubjectaccessreviews "$1" \
        "{\"apiVersion\":\"authorization.k8s.io/v1\",\"kind\":\"SelfSubjectAccessReview\",\"spec\":{\"resourceAttributes\":{\"namespace\":\"$NS\",\"group\":\"memoryhub.io\",\"resource\":\"dashboard\",\"verb\":\"$2\"}}}")"
    status="${out%% *}"
    if [ "$status" != "201" ] && [ "$status" != "200" ]; then echo "error:$status"; return; fi
    printf '%s' "$out" | json "str(d.get('status',{}).get('allowed',False)).lower()"
}

echo "=== Role resolution verification: user=$TEST_USER context=$CONTEXT ==="

# --- scratch RBAC: Roles + group binding (user only via group) -------------
oc_ create namespace "$NS" --dry-run=client -o yaml | oc_ apply -f - >/dev/null
cat <<EOF | oc_ apply -n "$NS" -f - >/dev/null
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: memoryhub-dashboard-user}
rules: [{apiGroups: ["memoryhub.io"], resources: ["dashboard"], verbs: ["use"]}]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: memoryhub-dashboard-admin}
rules: [{apiGroups: ["memoryhub.io"], resources: ["dashboard"], verbs: ["use", "admin"]}]
EOF
oc_ adm groups new "$GROUP" >/dev/null 2>&1 || true
oc_ adm groups add-users "$GROUP" "$TEST_USER" >/dev/null
oc_ create rolebinding verify-users -n "$NS" --role=memoryhub-dashboard-user --group="$GROUP" \
    --dry-run=client -o yaml | oc_ apply -f - >/dev/null

# --- mint a scoped token like the one oauth-proxy holds --------------------
USER_UID="$(oc_ get user "$TEST_USER" -o jsonpath='{.metadata.uid}')"
RAW="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')"
TOKEN_NAME="sha256~$(printf '%s' "$RAW" | openssl dgst -sha256 -binary | base64 | tr '+/' '-_' | tr -d '=\n')"
cat <<EOF | oc_ apply -f - >/dev/null
apiVersion: oauth.openshift.io/v1
kind: OAuthAccessToken
metadata: {name: "$TOKEN_NAME"}
clientName: openshift-challenging-client
userName: "$TEST_USER"
userUID: "$USER_UID"
scopes: ["user:info", "user:check-access"]
expiresIn: 900
redirectURI: https://localhost
EOF
SCOPED="sha256~$RAW"
sleep 2

echo ""
echo "--- 1. scoped token: users/~ and SelfSubjectAccessReview"
OUT="$(api GET /apis/user.openshift.io/v1/users/~ "$SCOPED")"
record "users/~ with scoped token (HTTP)" "${OUT%% *}" "expect 200"
if [ "${OUT%% *}" = "200" ]; then
    record "users/~ metadata.name == test user" \
        "$(printf '%s' "$OUT" | json "d['metadata']['name'] == '$TEST_USER'")" "expect True"
    record "users/~ metadata.uid == User uid" \
        "$(printf '%s' "$OUT" | json "d['metadata']['uid'] == '$USER_UID'")" "expect True"
    record "users/~ identities" "$(printf '%s' "$OUT" | json "','.join(d.get('identities') or [])")" "info"
fi
record "SSAR use (scoped token, via group binding)" "$(ssar "$SCOPED" use)" "expect true -> self mode works"
record "SSAR admin (scoped token, not granted)" "$(ssar "$SCOPED" admin)" "expect false"

echo ""
echo "--- 2. delegated path: TokenReview + SubjectAccessReview"
OUT="$(api POST /apis/authentication.k8s.io/v1/tokenreviews "$ADMIN_TOKEN" \
    "{\"apiVersion\":\"authentication.k8s.io/v1\",\"kind\":\"TokenReview\",\"spec\":{\"token\":\"$SCOPED\"}}")"
record "TokenReview authenticated" "$(printf '%s' "$OUT" | json "d['status'].get('authenticated')")" "expect True"
GROUPS_JSON="$(printf '%s' "$OUT" | json "json.dumps(d['status'].get('user',{}).get('groups',[]))")"
record "TokenReview groups include scratch group" \
    "$(printf '%s' "$OUT" | json "'$GROUP' in d['status'].get('user',{}).get('groups',[])")" "expect True"
record "TokenReview extra scopes" \
    "$(printf '%s' "$OUT" | json "','.join(d['status'].get('user',{}).get('extra',{}).get('scopes.authorization.openshift.io',[]))")" "info"
sar() {
    api POST /apis/authorization.k8s.io/v1/subjectaccessreviews "$ADMIN_TOKEN" \
        "{\"apiVersion\":\"authorization.k8s.io/v1\",\"kind\":\"SubjectAccessReview\",\"spec\":{\"user\":\"$TEST_USER\",\"uid\":\"$USER_UID\",\"groups\":$1,\"resourceAttributes\":{\"namespace\":\"$NS\",\"group\":\"memoryhub.io\",\"resource\":\"dashboard\",\"verb\":\"use\"}}}" \
        | json "str(d['status'].get('allowed',False)).lower()"
}
record "SAR use with TokenReview groups" "$(sar "$GROUPS_JSON")" "expect true"
record "SAR use with user only (no groups)" "$(sar '[]')" "expect false -> groups must be resolved"

echo ""
echo "--- 3. group removal with the token still valid"
oc_ adm groups remove-users "$GROUP" "$TEST_USER" >/dev/null
sleep 3
record "SSAR use after removal from Group (same token)" "$(ssar "$SCOPED" use)" "expect false"
oc_ adm groups add-users "$GROUP" "$TEST_USER" >/dev/null
sleep 3
record "SSAR use after re-adding to Group (same token)" "$(ssar "$SCOPED" use)" "expect true"

echo ""
echo "--- 4. RoleBinding removal with the token still valid"
oc_ delete rolebinding verify-users -n "$NS" >/dev/null
sleep 2
record "SSAR use after RoleBinding deleted (same token)" "$(ssar "$SCOPED" use)" "expect false"

echo ""
echo "--- 5. wildcard: does cluster-admin pass the admin verb?"
OUT="$(api POST /apis/authorization.k8s.io/v1/selfsubjectaccessreviews "$ADMIN_TOKEN" \
    "{\"apiVersion\":\"authorization.k8s.io/v1\",\"kind\":\"SelfSubjectAccessReview\",\"spec\":{\"resourceAttributes\":{\"namespace\":\"$NS\",\"group\":\"memoryhub.io\",\"resource\":\"dashboard\",\"verb\":\"admin\"}}}")"
record "SSAR admin for the operator (cluster-admin)" \
    "$(printf '%s' "$OUT" | json "str(d['status'].get('allowed',False)).lower()")" "expect true (#744)"

echo ""
echo "Paste into docs/auth/role-resolution-cluster-verification.md:"
echo ""
echo "| Check | Result | Expected |"
echo "|---|---|---|"
printf '%s' "$RESULTS"
