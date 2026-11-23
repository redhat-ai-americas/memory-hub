#!/usr/bin/env bash
# Provision the dashboard's human access lists (transitional bootstrap, #667).
#
# The dashboard learns who is an Admin and who is a User from two
# comma-separated lists of OpenShift usernames, kept in the Secret
# `memoryhub-ui-human-access` (keys MEMORYHUB_UI_ADMIN_USERS and
# MEMORYHUB_UI_ALLOWED_USERS). This script is the only supported way to
# create or change it, so every change is recorded on the Secret itself
# (who, when, how) besides the cluster's API audit log.
#
# It is a bootstrap until tenant role assignments replace it; see
# docs/ui/human-access.md.
#
# Usage (called by deploy.sh; can be run on its own):
#   human-access.sh [--context CTX] [--namespace NS]
#
# Inputs, all optional:
#   MEMORYHUB_UI_ADMIN_USERS    comma-separated OpenShift usernames (Admins)
#   MEMORYHUB_UI_ALLOWED_USERS  comma-separated OpenShift usernames (Users)
#
# Behaviour:
#   - Either variable set: the Secret is written with exactly these lists.
#   - Neither set, Secret exists: left as it is; its counts are printed.
#   - Neither set, no Secret: the user running the deploy (`oc whoami`)
#     becomes the first Admin, so a clean install can be signed in to.
set -euo pipefail

CONTEXT="${MEMORYHUB_CONTEXT:-$(oc config current-context 2>/dev/null || echo "")}"
NAMESPACE="${MEMORYHUB_UI_NAMESPACE:-memoryhub-ui}"
SECRET="memoryhub-ui-human-access"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --context) CONTEXT="$2"; shift ;;
        --namespace) NAMESPACE="$2"; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
    shift
done

OC=(oc)
[ -n "$CONTEXT" ] && OC+=(--context "$CONTEXT")

normalize() {
    # Trim surrounding spaces, drop empties and duplicates, keep order.
    # No arrays: macOS ships Bash 3.2, where expanding an empty array under
    # `set -u` is an "unbound variable" error.
    local rest="${1:-}" item out="" seen=","
    while [ -n "$rest" ]; do
        case "$rest" in
            *,*) item="${rest%%,*}"; rest="${rest#*,}" ;;
            *) item="$rest"; rest="" ;;
        esac
        item="$(printf '%s' "$item" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [ -z "$item" ] && continue
        if ! printf '%s' "$item" | grep -Eq '^[A-Za-z0-9._@:+-]{1,255}$'; then
            echo "Invalid OpenShift username in human access list: '$item'" >&2
            exit 1
        fi
        case "$seen" in *",$item,"*) continue ;; esac
        seen="$seen$item,"
        out="${out:+$out,}$item"
    done
    printf '%s\n' "$out"
}

count() { [ -z "$1" ] && echo 0 || awk -F',' '{print NF}' <<< "$1"; }

ACTOR="$("${OC[@]}" whoami 2>/dev/null || echo "unknown")"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ -n "${MEMORYHUB_UI_ADMIN_USERS+x}" ] || [ -n "${MEMORYHUB_UI_ALLOWED_USERS+x}" ]; then
    ADMINS="$(normalize "${MEMORYHUB_UI_ADMIN_USERS:-}")"
    USERS="$(normalize "${MEMORYHUB_UI_ALLOWED_USERS:-}")"
    SOURCE="deploy-input"
elif "${OC[@]}" get secret "$SECRET" -n "$NAMESPACE" &>/dev/null; then
    ADMINS="$("${OC[@]}" get secret "$SECRET" -n "$NAMESPACE" -o jsonpath='{.data.MEMORYHUB_UI_ADMIN_USERS}' | base64 --decode 2>/dev/null || true)"
    USERS="$("${OC[@]}" get secret "$SECRET" -n "$NAMESPACE" -o jsonpath='{.data.MEMORYHUB_UI_ALLOWED_USERS}' | base64 --decode 2>/dev/null || true)"
    echo "  Human access: keeping existing $SECRET ($(count "$ADMINS") admin(s), $(count "$USERS") user(s))."
    if [ "$(count "$ADMINS")" = 0 ]; then
        echo "  WARNING: no Admin is listed. Re-run with MEMORYHUB_UI_ADMIN_USERS=<you> to add one."
    fi
    exit 0
else
    if [ "$ACTOR" = "unknown" ] || [[ "$ACTOR" == system:* ]]; then
        echo "ERROR: no $SECRET in $NAMESPACE and no human deployer to make the first Admin."
        echo "  Re-run with MEMORYHUB_UI_ADMIN_USERS=<openshift-username>."
        exit 1
    fi
    ADMINS="$(normalize "$ACTOR")"
    USERS=""
    SOURCE="bootstrap-deployer"
    echo "  Human access: no $SECRET yet; making the deployer '$ACTOR' the first Admin."
fi

if [ -z "$ADMINS" ] && [ -z "$USERS" ]; then
    echo "ERROR: both human access lists are empty; nobody could sign in to the dashboard."
    exit 1
fi

"${OC[@]}" create secret generic "$SECRET" -n "$NAMESPACE" \
    --from-literal=MEMORYHUB_UI_ADMIN_USERS="$ADMINS" \
    --from-literal=MEMORYHUB_UI_ALLOWED_USERS="$USERS" \
    --dry-run=client -o yaml | "${OC[@]}" apply -n "$NAMESPACE" -f - >/dev/null
"${OC[@]}" label secret "$SECRET" -n "$NAMESPACE" --overwrite \
    app.kubernetes.io/part-of=memoryhub memoryhub.io/transitional=true >/dev/null
"${OC[@]}" annotate secret "$SECRET" -n "$NAMESPACE" --overwrite \
    memoryhub.io/human-access-updated-by="$ACTOR" \
    memoryhub.io/human-access-updated-at="$NOW" \
    memoryhub.io/human-access-source="$SOURCE" \
    memoryhub.io/human-access-doc="docs/ui/human-access.md" >/dev/null
echo "  Human access: $SECRET written by $ACTOR ($SOURCE): $(count "$ADMINS") admin(s), $(count "$USERS") user(s)."
