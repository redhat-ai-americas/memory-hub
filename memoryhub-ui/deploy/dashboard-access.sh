#!/usr/bin/env bash
# Manage who may use the MemoryHub dashboard, through OpenShift RBAC (#744).
#
# Access is a RoleBinding to one of two Roles in the dashboard namespace:
#   memoryhub-dashboard-user   verbs: use          -> dashboard User
#   memoryhub-dashboard-admin  verbs: use, admin   -> dashboard Admin
# on the virtual resource memoryhub.io/dashboard. Bind corporate groups
# where possible, individual people where needed. MemoryHub only manages its
# own RoleBindings; group membership belongs to the platform and the IdP.
# Every change is a RoleBinding change, so the cluster audit log records it.
# See docs/auth/human-role-resolution.md and docs/ui/human-access.md.
#
# Usage:
#   dashboard-access.sh [--context CTX] [--namespace NS] COMMAND [ARGS]
#
# Commands:
#   apply-roles   create or update the Roles, and the dashboard's read access
#                 to its own RoleBindings
#   bootstrap     apply-roles, bind the configured groups, and make the first
#                 Admin exactly once (deploy.sh runs this)
#   grant  --admin|--user --group NAME|--person NAME
#   revoke --admin|--user --group NAME|--person NAME
#   list          show the bindings to the two Roles (assignments, not the
#                 expanded list of effective users)
#   migrate       turn the transitional username lists (#667 Secret) into
#                 RoleBindings; the Secret is kept and marked as migrated
#
# Environment:
#   MEMORYHUB_UI_ADMIN_GROUPS, MEMORYHUB_UI_USER_GROUPS
#       comma-separated groups bound on every bootstrap
#   MEMORYHUB_UI_INITIAL_ADMIN_GROUP, MEMORYHUB_UI_INITIAL_ADMIN_USER
#       the first Admin; CI and GitOps must set one of them (or ADMIN_GROUPS)
#   MEMORYHUB_UI_BOOTSTRAP_DEPLOYER=1
#       make `oc whoami` the first Admin without a terminal
#   MEMORYHUB_UI_RBAC_CHECK=delegated
#       also bind system:auth-delegator for the dashboard service account
set -euo pipefail

CONTEXT="${MEMORYHUB_CONTEXT:-}"
NAMESPACE="${MEMORYHUB_UI_NAMESPACE:-memoryhub-ui}"
SA="memoryhub-ui"
USER_ROLE="memoryhub-dashboard-user"
ADMIN_ROLE="memoryhub-dashboard-admin"
LEGACY_SECRET="memoryhub-ui-human-access"
NAME_RE='^[A-Za-z0-9._@:+-]{1,255}$'
GROUP_RE='^[A-Za-z0-9._@:+= -]{1,255}$'

while [ $# -gt 0 ]; do
    case "$1" in
        --context) CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        *) break ;;
    esac
done
[ -n "$CONTEXT" ] || CONTEXT="$(oc config current-context 2>/dev/null || echo "")"
COMMAND="${1:-}"
[ $# -gt 0 ] && shift

oc_() {
    if [ -n "$CONTEXT" ]; then oc --context "$CONTEXT" "$@"; else oc "$@"; fi
}

die() { echo "ERROR: $*" >&2; exit 1; }

ACTOR="$(oc_ whoami 2>/dev/null || echo "unknown")"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

role_for() {
    case "$1" in
        admin) echo "$ADMIN_ROLE" ;;
        user) echo "$USER_ROLE" ;;
        *) die "unknown role '$1'" ;;
    esac
}

validate() {
    # validate KIND NAME
    if [ "$1" = "Group" ]; then
        printf '%s' "$2" | grep -Eq "$GROUP_RE" || die "Invalid OpenShift group name: '$2'"
    else
        printf '%s' "$2" | grep -Eq "$NAME_RE" || die "Invalid OpenShift username: '$2'"
    fi
}

binding_name() {
    # binding_name ROLE KIND NAME -> stable, DNS-safe and collision-free
    local slug sum
    slug="$(printf '%s' "$3" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9-]/-/g; s/--*/-/g; s/^-//; s/-$//' | cut -c1-40)"
    sum="$(printf '%s' "$2:$3" | cksum | awk '{print $1}')"
    printf 'mh-%s-%s-%s-%s' "$1" "$(printf '%s' "$2" | tr 'A-Z' 'a-z')" "${slug:-x}" "$sum"
}

apply_roles() {
    cat <<EOF | oc_ apply -n "$NAMESPACE" -f - >/dev/null
{"apiVersion": "v1", "kind": "List", "items": [
 {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
  "metadata": {"name": "$USER_ROLE", "labels": {"app.kubernetes.io/part-of": "memoryhub", "memoryhub.io/dashboard-access": "role"}},
  "rules": [{"apiGroups": ["memoryhub.io"], "resources": ["dashboard"], "verbs": ["use"]}]},
 {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
  "metadata": {"name": "$ADMIN_ROLE", "labels": {"app.kubernetes.io/part-of": "memoryhub", "memoryhub.io/dashboard-access": "role"}},
  "rules": [{"apiGroups": ["memoryhub.io"], "resources": ["dashboard"], "verbs": ["use", "admin"]}]},
 {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
  "metadata": {"name": "memoryhub-ui-access-reader", "labels": {"app.kubernetes.io/part-of": "memoryhub"}},
  "rules": [{"apiGroups": ["rbac.authorization.k8s.io"], "resources": ["rolebindings"], "verbs": ["get", "list"]}]},
 {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
  "metadata": {"name": "memoryhub-ui-access-reader", "labels": {"app.kubernetes.io/part-of": "memoryhub"}},
  "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "memoryhub-ui-access-reader"},
  "subjects": [{"kind": "ServiceAccount", "name": "$SA", "namespace": "$NAMESPACE"}]}
]}
EOF
    local crb="memoryhub-ui-auth-delegator-$NAMESPACE"
    if [ "${MEMORYHUB_UI_RBAC_CHECK:-self}" = "delegated" ]; then
        oc_ create clusterrolebinding "$crb" --clusterrole=system:auth-delegator \
            --serviceaccount="$NAMESPACE:$SA" --dry-run=client -o yaml | oc_ apply -f - >/dev/null
        echo "  Dashboard access: delegated checks; $SA may review tokens (system:auth-delegator)."
    else
        oc_ delete clusterrolebinding "$crb" --ignore-not-found >/dev/null 2>&1 || true
    fi
    echo "  Dashboard access: Roles $USER_ROLE and $ADMIN_ROLE applied in $NAMESPACE."
}

grant() {
    # grant admin|user Group|User NAME
    local role kind="$2" name="$3" rb
    role="$(role_for "$1")"
    validate "$kind" "$name"
    rb="$(binding_name "$1" "$kind" "$name")"
    if oc_ get rolebinding "$rb" -n "$NAMESPACE" >/dev/null 2>&1; then
        echo "  Dashboard access: $kind '$name' already has $1 ($rb)."
        return 0
    fi
    cat <<EOF | oc_ apply -n "$NAMESPACE" -f - >/dev/null
{"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
 "metadata": {"name": "$rb",
  "labels": {"app.kubernetes.io/part-of": "memoryhub", "memoryhub.io/dashboard-access": "$1"},
  "annotations": {"memoryhub.io/granted-by": "$ACTOR", "memoryhub.io/granted-at": "$NOW"}},
 "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "$role"},
 "subjects": [{"apiGroup": "rbac.authorization.k8s.io", "kind": "$kind", "name": "$name"}]}
EOF
    echo "  Dashboard access: granted $1 to $kind '$name' ($rb)."
}

revoke() {
    local kind="$2" name="$3" rb
    role_for "$1" >/dev/null
    validate "$kind" "$name"
    rb="$(binding_name "$1" "$kind" "$name")"
    if ! oc_ get rolebinding "$rb" -n "$NAMESPACE" >/dev/null 2>&1; then
        die "no $1 binding for $kind '$name' made by this script; see '$0 list' for bindings made otherwise"
    fi
    oc_ delete rolebinding "$rb" -n "$NAMESPACE" >/dev/null
    echo "  Dashboard access: revoked $1 from $kind '$name' ($rb)."
    if [ "$1" = "admin" ] && [ "$(bindings "$ADMIN_ROLE" | wc -l | tr -d ' ')" = 0 ]; then
        echo "  WARNING: no Admin binding is left in $NAMESPACE."
    fi
}

bindings() {
    # bindings [ROLE]: "role<TAB>binding<TAB>Kind:name ..." for our Roles
    oc_ get rolebindings -n "$NAMESPACE" -o \
        jsonpath='{range .items[*]}{.roleRef.name}{"\t"}{.metadata.name}{"\t"}{range .subjects[*]}{.kind}:{.name}{" "}{end}{"\n"}{end}' \
        | awk -F'\t' -v only="${1:-}" -v a="$ADMIN_ROLE" -v u="$USER_ROLE" \
            '($1 == a || $1 == u) && (only == "" || $1 == only)'
}

each() {
    # each "a,b,c" FUNCTION ARGS...: call FUNCTION ARGS... ITEM per trimmed item
    local rest="$1" item
    shift
    while [ -n "$rest" ]; do
        case "$rest" in
            *,*) item="${rest%%,*}"; rest="${rest#*,}" ;;
            *) item="$rest"; rest="" ;;
        esac
        item="$(printf '%s' "$item" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        [ -z "$item" ] && continue
        "$@" "$item"
    done
}

migration_state() {
    # Prints "none", "done:<when>" or "pending".
    if ! oc_ get secret "$LEGACY_SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
        echo none; return
    fi
    local done_at
    done_at="$(oc_ get secret "$LEGACY_SECRET" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.memoryhub\.io/migrated-to-rbac-at}' 2>/dev/null || true)"
    if [ -n "$done_at" ]; then echo "done:$done_at"; else echo pending; fi
}

migrate() {
    local state admins users
    state="$(migration_state)"
    case "$state" in
        none) echo "  Dashboard access: no $LEGACY_SECRET to migrate."; return 0 ;;
        done:*) echo "  Dashboard access: $LEGACY_SECRET was already migrated at ${state#done:}."; return 0 ;;
    esac
    admins="$(oc_ get secret "$LEGACY_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.MEMORYHUB_UI_ADMIN_USERS}' \
        | base64 --decode 2>/dev/null || true)"
    users="$(oc_ get secret "$LEGACY_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.MEMORYHUB_UI_ALLOWED_USERS}' \
        | base64 --decode 2>/dev/null || true)"
    # Validate everything before writing anything.
    each "$admins" validate User
    each "$users" validate User
    each "$admins" grant admin User
    each "$users" grant user User
    oc_ annotate secret "$LEGACY_SECRET" -n "$NAMESPACE" --overwrite \
        memoryhub.io/migrated-to-rbac-at="$NOW" memoryhub.io/migrated-to-rbac-by="$ACTOR" >/dev/null
    echo "  Dashboard access: migrated $LEGACY_SECRET to RoleBindings. Delete the Secret after verifying sign-in."
}

bootstrap() {
    apply_roles
    each "${MEMORYHUB_UI_ADMIN_GROUPS:-}" grant admin Group
    each "${MEMORYHUB_UI_USER_GROUPS:-}" grant user Group

    local booted source=""
    booted="$(oc_ get role "$ADMIN_ROLE" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.memoryhub\.io/bootstrapped-at}' 2>/dev/null || true)"
    if [ -n "$booted" ]; then
        # Bootstrap happened once. Missing bindings now are a decision, not a gap.
        if [ "$(bindings | wc -l | tr -d ' ')" = 0 ]; then
            echo "  WARNING: no dashboard bindings in $NAMESPACE (bootstrapped $booted); nobody can sign in."
            echo "  Not re-bootstrapping: removing every binding may be a deliberate revocation."
            echo "  To restore access: $0 --namespace $NAMESPACE grant --admin --person <name>"
        fi
        return 0
    fi

    if [ -n "${MEMORYHUB_UI_INITIAL_ADMIN_GROUP:-}" ]; then
        grant admin Group "$MEMORYHUB_UI_INITIAL_ADMIN_GROUP"; source="initial-admin-group"
    elif [ -n "${MEMORYHUB_UI_INITIAL_ADMIN_USER:-}" ]; then
        grant admin User "$MEMORYHUB_UI_INITIAL_ADMIN_USER"; source="initial-admin-user"
    elif [ "$(migration_state)" = pending ]; then
        migrate; source="migrated-lists"
    elif [ -n "${MEMORYHUB_UI_ADMIN_GROUPS:-}" ]; then
        source="admin-groups"
    elif [ "${MEMORYHUB_UI_BOOTSTRAP_DEPLOYER:-}" = 1 ] || { [ -t 0 ] && [ -z "${CI:-}" ]; }; then
        case "$ACTOR" in
            unknown|system:*)
                die "no human deployer to make the first Admin; set MEMORYHUB_UI_INITIAL_ADMIN_GROUP or MEMORYHUB_UI_INITIAL_ADMIN_USER" ;;
        esac
        grant admin User "$ACTOR"; source="bootstrap-deployer"
    else
        die "first install without a terminal: set MEMORYHUB_UI_INITIAL_ADMIN_GROUP or MEMORYHUB_UI_INITIAL_ADMIN_USER"
    fi
    oc_ annotate role "$ADMIN_ROLE" -n "$NAMESPACE" --overwrite \
        memoryhub.io/bootstrapped-at="$NOW" memoryhub.io/bootstrapped-by="$ACTOR" \
        memoryhub.io/bootstrap-source="$source" >/dev/null
    echo "  Dashboard access: bootstrapped by $ACTOR ($source)."
}

subject_args() {
    # subject_args ARGS... -> "role kind name" or exit
    local role="" kind="" name=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --admin) role="admin"; shift ;;
            --user) role="user"; shift ;;
            --group) kind="Group"; name="${2:-}"; shift 2 ;;
            --person) kind="User"; name="${2:-}"; shift 2 ;;
            *) die "unknown argument: $1" ;;
        esac
    done
    [ -n "$role" ] && [ -n "$kind" ] && [ -n "$name" ] || die "need --admin|--user and --group NAME|--person NAME"
    printf '%s\t%s\t%s\n' "$role" "$kind" "$name"
}

case "$COMMAND" in
    apply-roles) apply_roles ;;
    bootstrap) bootstrap ;;
    grant|revoke)
        ARGS="$(subject_args "$@")"
        ROLE="$(printf '%s' "$ARGS" | cut -f1)"
        KIND="$(printf '%s' "$ARGS" | cut -f2)"
        NAME="$(printf '%s' "$ARGS" | cut -f3)"
        "$COMMAND" "$ROLE" "$KIND" "$NAME"
        ;;
    list)
        echo "Bindings to $ADMIN_ROLE and $USER_ROLE in $NAMESPACE (assignments; group members and"
        echo "cluster-wide grants such as cluster-admin are not expanded):"
        bindings | awk -F'\t' '{ role = ($1 ~ /admin$/) ? "admin" : "user"; printf "  %-6s %-50s %s\n", role, $2, $3 }'
        ;;
    migrate) migrate ;;
    *) sed -n '2,38p' "$0"; [ -z "$COMMAND" ] && exit 1; die "unknown command: $COMMAND" ;;
esac
