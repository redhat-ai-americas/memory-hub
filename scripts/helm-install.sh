#!/usr/bin/env bash
# One-command fresh OpenShift installation of the full MemoryHub Helm chart.
# This orchestrates optional image builds, secret setup, migrations, and Helm upgrades;
# it never applies the Kustomize workload manifests.
set -euo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="$REPO_ROOT/charts/memoryhub"
CONTEXT="${MEMORYHUB_CONTEXT:-mcp-rhoai}"
RELEASE="${MEMORYHUB_HELM_RELEASE:-memoryhub}"
NAMESPACE="${MEMORYHUB_HELM_NAMESPACE:-memory-hub-mcp}"
VALUES_FILE="${MEMORYHUB_HELM_VALUES:-}"
PREBUILT_IMAGES=false
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

usage() {
    cat <<'EOF'
Usage: make helm-install [ARGS="--values path/to/values.yaml"]
       make helm-install ARGS="--prebuilt-images --values values-openshift.yaml"

Environment:
  MEMORYHUB_CONTEXT       OpenShift context (default: mcp-rhoai)
  MEMORYHUB_HELM_RELEASE  Helm release name (default: memoryhub)
  MEMORYHUB_HELM_NAMESPACE Release namespace (default: memory-hub-mcp, currently fixed)
  MEMORYHUB_HELM_VALUES   Optional values file for chart configuration

The one-command installer uses the repository's standard seven namespaces.
The release namespace is currently fixed to memory-hub-mcp; use the chart
directly for a custom namespace layout.
By default it builds MCP, auth, and UI images with the repository's OpenShift
build scripts. --prebuilt-images skips those builds and requires registry-
qualified mcp.image, auth.image, and ui.image values in the values file.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --context)
            CONTEXT="${2:?--context requires a value}"
            shift 2
            ;;
        --release)
            RELEASE="${2:?--release requires a value}"
            shift 2
            ;;
        --namespace)
            NAMESPACE="${2:?--namespace requires a value}"
            shift 2
            ;;
        --values|-f)
            VALUES_FILE="${2:?--values requires a file path}"
            shift 2
            ;;
        --prebuilt-images)
            PREBUILT_IMAGES=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$NAMESPACE" != "memory-hub-mcp" ]]; then
    echo "The one-command installer currently expects release namespace memory-hub-mcp." >&2
    echo "Use the chart directly for a custom namespace layout." >&2
    exit 2
fi
if [[ -n "$VALUES_FILE" && ! -f "$VALUES_FILE" ]]; then
    echo "Values file not found: $VALUES_FILE" >&2
    exit 2
fi
if [[ "$PREBUILT_IMAGES" == true && -z "$VALUES_FILE" ]]; then
    echo "--prebuilt-images requires a values file with mcp.image, auth.image, and ui.image references." >&2
    exit 2
fi

for command in oc helm openssl python3; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Required command not found: $command" >&2
        exit 1
    }
done

validate_prebuilt_image() {
    local component="$1" template="$2" container="$3"
    local rendered="$TEMP_DIR/prebuilt-${component}.yaml" image

    helm template "$RELEASE" "$CHART_DIR" -n "$NAMESPACE" \
        -f "$VALUES_FILE" --show-only "$template" > "$rendered"
    image=$(python3 - "$rendered" "$container" <<'PY'
import pathlib, re, sys

path, target = sys.argv[1:]
in_container = False
for line in pathlib.Path(path).read_text().splitlines():
    match = re.match(r"^\s*-\s+name:\s*(\S+)\s*$", line)
    if match:
        in_container = match.group(1) == target
        continue
    if in_container and line.lstrip().startswith("image:"):
        print(line.split(":", 1)[1].strip().strip('"'))
        break
PY
)
    if [[ -z "$image" || "$image" != */* || "$image" == *registry.example.com* || "$image" == *replace-with-published-tag* ]]; then
        echo "Prebuilt mode needs a registry-qualified image for ${component}.image in $VALUES_FILE; rendered image was '${image:-missing}'." >&2
        echo "Use a full image path such as registry.example.com/team/${component}:tag." >&2
        exit 2
    fi
    echo "  Using prebuilt ${component} image: $image"
}

if [[ "$PREBUILT_IMAGES" == true ]]; then
    validate_prebuilt_image mcp templates/mcp/deployment.yaml mcp-server
    validate_prebuilt_image auth templates/auth/deployment.yaml auth-server
    validate_prebuilt_image ui templates/ui/deployment.yaml memoryhub-ui
fi

if ! oc whoami --context "$CONTEXT" >/dev/null 2>&1; then
    echo "Not logged in to OpenShift context '$CONTEXT'. Log in first, then retry." >&2
    exit 1
fi

for permission in "create namespaces" "get namespaces" "create oauthclients"; do
    read -r verb resource <<<"$permission"
    if ! oc auth can-i "$verb" "$resource" --context "$CONTEXT" 2>/dev/null | grep -qx yes; then
        echo "The installer identity needs permission to $permission." >&2
        exit 1
    fi
done
if ! oc get storageclass --context "$CONTEXT" -o json \
    | python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; sys.exit(0 if any(x.get("metadata",{}).get("annotations",{}).get("storageclass.kubernetes.io/is-default-class") == "true" or x.get("metadata",{}).get("annotations",{}).get("storageclass.beta.kubernetes.io/is-default-class") == "true" for x in items) else 1)'; then
    echo "WARNING: no default StorageClass is configured. Set storageClassName values in your values file before installing."
fi
if ! oc api-versions --context "$CONTEXT" | grep -qx 'route.openshift.io/v1'; then
    echo "The selected cluster does not advertise the OpenShift Route API." >&2
    exit 1
fi

echo "==> Resolving OpenShift route and OAuth URLs"
APPS_DOMAIN=$(oc get ingress.config.openshift.io cluster --context "$CONTEXT" -o jsonpath='{.spec.domain}')
if [[ -z "$APPS_DOMAIN" ]]; then
    echo "Could not determine the OpenShift apps domain." >&2
    exit 1
fi
OAUTH_HOST=$(oc get route oauth-openshift -n openshift-authentication --context "$CONTEXT" -o jsonpath='{.spec.host}' 2>/dev/null || true)
if [[ -n "$OAUTH_HOST" ]]; then
    OAUTH_AUTHORIZE_URL="https://${OAUTH_HOST}/oauth/authorize"
else
    OAUTH_AUTHORIZE_URL=$(oc get --context "$CONTEXT" --raw '/.well-known/oauth-authorization-server' \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("authorization_endpoint", ""))')
fi
if [[ -z "$OAUTH_AUTHORIZE_URL" ]]; then
    echo "Could not resolve the OpenShift OAuth authorization endpoint." >&2
    exit 1
fi
AUTH_HOST="auth-server-memoryhub-auth.${APPS_DOMAIN}"
MCP_HOST="memory-hub-mcp-memory-hub-mcp.${APPS_DOMAIN}"
UI_HOST="memoryhub-ui-memoryhub-ui.${APPS_DOMAIN}"
python3 - "$TEMP_DIR/runtime-values.yaml" "$AUTH_HOST" "$MCP_HOST" "$UI_HOST" "$OAUTH_AUTHORIZE_URL" <<'PY'
import json, pathlib, sys

target, auth_host, mcp_host, ui_host, oauth_url = sys.argv[1:]
values = {
    "openshift": {
        "enabled": True,
        "routes": True,
        "sccBindings": True,
        "scc": {"postgresql": True, "minio": True, "valkey": True},
    },
    "postgresql": {
        "database": "memoryhub", "username": "memoryhub",
        "secretName": "memoryhub-pg-credentials",
        "serviceAccountName": "memoryhub-postgresql",
    },
    "minio": {
        "secretName": "memoryhub-minio-credentials",
        "serviceAccountName": "memoryhub-minio",
    },
    "valkey": {"serviceAccountName": "memoryhub-valkey"},
    "mcp": {
        "usersConfigMap": "memoryhub-users",
        "secrets": {
            "database": "memoryhub-db-credentials",
            "minio": "memoryhub-minio-credentials",
            "authInternal": "auth-internal-service-key",
        },
        "route": {"host": mcp_host},
    },
    "auth": {
        "serviceAccountName": "auth-server",
        "oauthClientId": "memoryhub-auth-broker",
        "rbac": {"enabled": True, "authDelegator": True, "namespaceReader": True},
        "secrets": {
            "database": "memoryhub-pg-credentials",
            "rsaKeys": "auth-rsa-keys",
            "adminKey": "auth-admin-key",
            "internalServiceKey": "auth-internal-service-key",
            "oauthClient": "openshift-oauth-client-secret",
        },
        "issuer": f"https://{auth_host}",
        "oauthAuthorizeUrl": oauth_url,
        "route": {"host": auth_host},
    },
    "ui": {
        "serviceAccountName": "memoryhub-ui",
        "secrets": {
            "database": "memoryhub-db-credentials",
            "adminKey": "memoryhub-ui-admin-key",
            "proxy": "memoryhub-ui-proxy",
            "tls": "memoryhub-ui-tls",
        },
        "route": {"host": ui_host},
        "publicMcpUrl": f"https://{mcp_host}/mcp/",
        "publicAuthUrl": f"https://{auth_host}",
    },
}
pathlib.Path(target).write_text(json.dumps(values, indent=2) + "\n")
PY

oc_context=(oc --context "$CONTEXT")
helm_args=(upgrade --install "$RELEASE" "$CHART_DIR" --kube-context "$CONTEXT" -n "$NAMESPACE" --create-namespace --wait --timeout 15m)
RELEASE_EXISTS=false
if helm status "$RELEASE" --kube-context "$CONTEXT" -n "$NAMESPACE" >/dev/null 2>&1; then
    RELEASE_EXISTS=true
fi

adopt_legacy_auth_rbac() {
    local kind="$1" name="$2" expected="$3"
    local object_file="$TEMP_DIR/${kind}-${name}.json"
    if ! oc get "$kind" "$name" --context "$CONTEXT" -o json > "$object_file" 2>/dev/null; then
        return 0
    fi

    # Older Kustomize installs created these cluster-scoped RBAC objects with
    # the same names and specs but without Helm ownership metadata. Adopt only
    # exact matches; never take over an object owned by another Helm release
    # or with broader permissions/subjects.
    python3 - "$object_file" "$kind" "$name" "$expected" "$RELEASE" "$NAMESPACE" <<'PY'
import json, pathlib, sys

path, kind, name, expected, release, release_namespace = sys.argv[1:]
obj = json.loads(pathlib.Path(path).read_text())
metadata = obj.get("metadata", {})
annotations = metadata.get("annotations", {})
labels = metadata.get("labels", {})
ownership = (
    labels.get("app.kubernetes.io/managed-by", ""),
    annotations.get("meta.helm.sh/release-name", ""),
    annotations.get("meta.helm.sh/release-namespace", ""),
)
if any(ownership) and ownership != ("Helm", release, release_namespace):
    raise SystemExit(f"Refusing to adopt {kind} {name}: it has different or incomplete ownership metadata.")

spec = obj.get("rules", []) if kind == "clusterrole" else obj.get("roleRef", {})
if kind == "clusterrolebinding":
    subjects = sorted(
        (subject.get("kind", ""), subject.get("name", ""), subject.get("namespace", ""))
        for subject in obj.get("subjects", [])
    )
    expected_subject = ("ServiceAccount", "auth-server", "memoryhub-auth")
    if subjects != [expected_subject]:
        raise SystemExit(f"Refusing to adopt {kind} {name}: its subjects do not match the chart.")

if kind == "clusterrole":
    expected_rules = [{"apiGroups": [""], "resources": ["namespaces"], "verbs": ["get"]}]
    if spec != expected_rules:
        raise SystemExit(f"Refusing to adopt {kind} {name}: its rules do not match the chart.")
elif expected == "namespace-reader":
    if spec != {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "memoryhub-auth-ns-reader"}:
        raise SystemExit(f"Refusing to adopt {kind} {name}: its role reference does not match the chart.")
elif spec != {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "system:auth-delegator"}:
    raise SystemExit(f"Refusing to adopt {kind} {name}: its role reference does not match the chart.")
PY

    if [[ -z "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("metadata",{}).get("annotations",{}).get("meta.helm.sh/release-name", ""))' "$object_file")" ]]; then
        oc label "$kind" "$name" app.kubernetes.io/managed-by=Helm --overwrite --context "$CONTEXT" >/dev/null
        oc annotate "$kind" "$name" \
            "meta.helm.sh/release-name=$RELEASE" \
            "meta.helm.sh/release-namespace=$NAMESPACE" \
            --overwrite --context "$CONTEXT" >/dev/null
        echo "Adopted matching legacy $kind/$name into Helm release '$RELEASE'."
    fi
}

adopt_legacy_auth_rbac clusterrole memoryhub-auth-ns-reader namespace-reader
adopt_legacy_auth_rbac clusterrolebinding memoryhub-auth-ns-reader namespace-reader
adopt_legacy_auth_rbac clusterrolebinding memoryhub-auth-delegator auth-delegator

check_resource_ownership() {
    local resource="$1" namespace="$2" object_json owner
    if ! object_json=$(oc get "$resource" -n "$namespace" --context "$CONTEXT" -o json 2>/dev/null); then
        return 0
    fi
    owner=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("metadata",{}).get("labels",{}).get("app.kubernetes.io/instance", ""))' <<<"$object_json")
    if [[ "$RELEASE_EXISTS" == true && "$owner" == "$RELEASE" ]]; then
        return 0
    fi
    echo "Found existing $resource in namespace '$namespace' that is not owned by Helm release '$RELEASE'." >&2
    echo "The Helm installer supports fresh installs only; remove or separately migrate existing MemoryHub resources first." >&2
    exit 1
}

while read -r resource namespace; do
    check_resource_ownership "$resource" "$namespace"
done <<EOF
statefulset/memoryhub-pg memoryhub-db
service/memoryhub-pg memoryhub-db
configmap/memoryhub-pg-init memoryhub-db
deployment/memoryhub-minio memoryhub-storage
service/memoryhub-minio memoryhub-storage
deployment/memoryhub-valkey $NAMESPACE
service/memoryhub-valkey $NAMESPACE
deployment/memory-hub-mcp $NAMESPACE
service/memory-hub-mcp $NAMESPACE
deployment/auth-server memoryhub-auth
service/auth-server memoryhub-auth
deployment/memoryhub-ui memoryhub-ui
service/memoryhub-ui memoryhub-ui
deployment/all-minilm-l6-v2 embedding-model
deployment/granite-embedding embedding-model
service/all-minilm-l6-v2 embedding-model
service/granite-embedding embedding-model
deployment/ms-marco-minilm-l12-v2 reranker-model
deployment/granite-reranker reranker-model
service/ms-marco-minilm-l12-v2 reranker-model
service/granite-reranker reranker-model
persistentvolumeclaim/memoryhub-pg-data memoryhub-db
persistentvolumeclaim/memoryhub-minio-data memoryhub-storage
persistentvolumeclaim/embedding-model-cache embedding-model
persistentvolumeclaim/reranker-model-cache reranker-model
EOF

if [[ "$RELEASE_EXISTS" == true ]] \
    && oc get deployment/memory-hub-mcp -n "$NAMESPACE" --context "$CONTEXT" >/dev/null 2>&1; then
    echo "The Helm release already has MCP workloads installed." >&2
    echo "Use 'helm upgrade' for changes; helm-install is for the initial fresh install." >&2
    exit 2
fi

helm_stage() {
    local stage_values="$1"
    shift
    echo "==> Helm: $stage_values"
    local args=("${helm_args[@]}")
    if [[ -n "$VALUES_FILE" ]]; then
        args+=(-f "$VALUES_FILE")
    fi
    # Cluster-derived URLs are authoritative for this one-command workflow.
    # Direct Helm users can set custom hosts themselves.
    if [[ -f "$TEMP_DIR/runtime-values.yaml" ]]; then
        args+=(-f "$TEMP_DIR/runtime-values.yaml")
    fi
    args+=(-f "$stage_values")
    helm "${args[@]}" --set namespaces.create=true "$@"
}

echo "MemoryHub Helm install"
echo "  OpenShift context: $CONTEXT"
echo "  Release:           $RELEASE"
echo "  Release namespace: $NAMESPACE"

# Stage 1 creates the release and component namespaces without starting
# workloads. This lets the installer provision credentials before pods start.
cat > "$TEMP_DIR/namespaces.yaml" <<'EOF'
postgresql:
  enabled: false
minio:
  enabled: false
valkey:
  enabled: false
mcp:
  enabled: false
auth:
  enabled: false
ui:
  enabled: false
models:
  enabled: false
maintenance:
  retention:
    enabled: false
  cleanup:
    enabled: false
EOF
NAMESPACE_STAGE_NEEDED=true
if [[ "$RELEASE_EXISTS" == true ]]; then
    NAMESPACE_STAGE_NEEDED=false
    for namespace in "$NAMESPACE" memoryhub-db memoryhub-storage memoryhub-auth memoryhub-ui embedding-model reranker-model; do
        if ! oc get namespace "$namespace" --context "$CONTEXT" >/dev/null 2>&1; then
            NAMESPACE_STAGE_NEEDED=true
            break
        fi
    done
fi
if [[ "$NAMESPACE_STAGE_NEEDED" == true ]]; then
    helm_stage "$TEMP_DIR/namespaces.yaml"
else
    echo "==> Component namespaces already exist; continuing the current Helm release"
fi

ensure_secret() {
    local secret_name="$1" secret_namespace="$2"
    shift 2
    if "${oc_context[@]}" get secret "$secret_name" -n "$secret_namespace" >/dev/null 2>&1; then
        echo "  Reusing Secret $secret_namespace/$secret_name"
    else
        echo "  Creating Secret $secret_namespace/$secret_name"
        "${oc_context[@]}" create secret generic "$secret_name" -n "$secret_namespace" "$@" >/dev/null
    fi
}

write_secret_file() {
    local file="$TEMP_DIR/$1" value="$2"
    printf '%s' "$value" > "$file"
    printf '%s' "$file"
}

copy_secret() {
    local source_name="$1" source_namespace="$2" target_name="$3" target_namespace="$4"
    if "${oc_context[@]}" get secret "$target_name" -n "$target_namespace" >/dev/null 2>&1; then
        return
    fi
    "${oc_context[@]}" get secret "$source_name" -n "$source_namespace" -o json \
        | python3 -c 'import json,sys; s=json.load(sys.stdin); s["metadata"]={"name":sys.argv[1],"namespace":sys.argv[2]}; s.pop("status",None); json.dump(s,sys.stdout)' \
            "$target_name" "$target_namespace" \
        | "${oc_context[@]}" apply -f - >/dev/null
}

read_secret() {
    local name="$1" namespace="$2" key="$3"
    "${oc_context[@]}" get secret "$name" -n "$namespace" -o json \
        | python3 -c 'import base64,json,sys; print(base64.b64decode(json.load(sys.stdin)["data"][sys.argv[1]]).decode(),end="")' "$key"
}

remap_db_secret() {
    local target_namespace="$1" target_name="$2" target_prefix="$3"
    local db_user db_name db_password db_user_file db_name_file db_password_file db_host_file db_port_file
    db_user=$(read_secret memoryhub-pg-credentials memoryhub-db POSTGRES_USER)
    db_name=$(read_secret memoryhub-pg-credentials memoryhub-db POSTGRES_DB)
    db_password=$(read_secret memoryhub-pg-credentials memoryhub-db POSTGRES_PASSWORD)
    db_user_file=$(write_secret_file "${target_name}-user" "$db_user")
    db_name_file=$(write_secret_file "${target_name}-name" "$db_name")
    db_password_file=$(write_secret_file "${target_name}-password" "$db_password")
    db_host_file=$(write_secret_file "${target_name}-host" "memoryhub-pg.memoryhub-db.svc.cluster.local")
    db_port_file=$(write_secret_file "${target_name}-port" 5432)
    "${oc_context[@]}" create secret generic "$target_name" -n "$target_namespace" \
        --from-file="${target_prefix}HOST=$db_host_file" \
        --from-file="${target_prefix}PORT=$db_port_file" \
        --from-file="${target_prefix}NAME=$db_name_file" \
        --from-file="${target_prefix}USER=$db_user_file" \
        --from-file="${target_prefix}PASSWORD=$db_password_file" \
        --dry-run=client -o yaml | "${oc_context[@]}" apply -f - >/dev/null
}

random_secret_if_missing() {
    local name="$1" namespace="$2" key="$3" value="$4" value_file
    value_file=$(write_secret_file "$name-$key" "$value")
    ensure_secret "$name" "$namespace" --from-file="$key=$value_file"
}

echo "==> Preparing database and storage credentials"
DB_PASSWORD="$(openssl rand -hex 16)"
DB_USER_FILE=$(write_secret_file postgresql-user memoryhub)
DB_PASSWORD_FILE=$(write_secret_file postgresql-password "$DB_PASSWORD")
DB_NAME_FILE=$(write_secret_file postgresql-name memoryhub)
ensure_secret memoryhub-pg-credentials memoryhub-db \
    --from-file="POSTGRES_USER=$DB_USER_FILE" \
    --from-file="POSTGRES_PASSWORD=$DB_PASSWORD_FILE" \
    --from-file="POSTGRES_DB=$DB_NAME_FILE"
MINIO_PASSWORD="$(openssl rand -hex 24)"
MINIO_USER_FILE=$(write_secret_file minio-user memoryhub)
MINIO_PASSWORD_FILE=$(write_secret_file minio-password "$MINIO_PASSWORD")
ensure_secret memoryhub-minio-credentials memoryhub-storage \
    --from-file="MINIO_ROOT_USER=$MINIO_USER_FILE" \
    --from-file="MINIO_ROOT_PASSWORD=$MINIO_PASSWORD_FILE"
unset DB_PASSWORD MINIO_PASSWORD

# Stage 2 starts the database, object store, and cache. App and model workloads
# remain off until migrations, credentials, and locally built images are ready.
cat > "$TEMP_DIR/infrastructure.yaml" <<'EOF'
postgresql:
  enabled: true
minio:
  enabled: true
valkey:
  enabled: true
mcp:
  enabled: false
auth:
  enabled: false
ui:
  enabled: false
models:
  enabled: false
maintenance:
  retention:
    enabled: false
  cleanup:
    enabled: false
EOF
helm_stage "$TEMP_DIR/infrastructure.yaml"

echo "==> Waiting for PostgreSQL"
"${oc_context[@]}" rollout status statefulset/memoryhub-pg -n memoryhub-db --timeout=5m
echo "==> Preparing local migration environment"
if [[ ! -x "$REPO_ROOT/.venv/bin/alembic" ]]; then
    python3 -m venv "$REPO_ROOT/.venv"
    "$REPO_ROOT/.venv/bin/pip" install --upgrade pip
    "$REPO_ROOT/.venv/bin/pip" install -e "$REPO_ROOT[dev]"
fi
if [[ ! -x "$REPO_ROOT/memoryhub-auth/.venv/bin/alembic" ]]; then
    make -C "$REPO_ROOT/memoryhub-auth" install
fi
echo "==> Running database migrations"
MEMORYHUB_CONTEXT="$CONTEXT" "$REPO_ROOT/scripts/run-migrations.sh" memoryhub-db memoryhub-pg-credentials
MEMORYHUB_CONTEXT="$CONTEXT" "$REPO_ROOT/scripts/run-auth-migrations.sh" memoryhub-db memoryhub-pg-credentials

echo "==> Preparing application credentials"
copy_secret memoryhub-pg-credentials memoryhub-db memoryhub-pg-credentials memoryhub-auth
remap_db_secret "$NAMESPACE" memoryhub-db-credentials MEMORYHUB_DB_
copy_secret memoryhub-minio-credentials memoryhub-storage memoryhub-minio-credentials "$NAMESPACE"

random_secret_if_missing auth-admin-key memoryhub-auth AUTH_ADMIN_KEY "$(openssl rand -hex 32)"
random_secret_if_missing auth-internal-service-key memoryhub-auth AUTH_INTERNAL_SERVICE_KEY "$(openssl rand -hex 32)"
copy_secret auth-internal-service-key memoryhub-auth auth-internal-service-key "$NAMESPACE"

if ! "${oc_context[@]}" get secret auth-rsa-keys -n memoryhub-auth >/dev/null 2>&1; then
    openssl genrsa -out "$TEMP_DIR/auth-private.pem" 2048 2>/dev/null
    openssl rsa -in "$TEMP_DIR/auth-private.pem" -pubout -out "$TEMP_DIR/auth-public.pem" 2>/dev/null
    "${oc_context[@]}" create secret generic auth-rsa-keys -n memoryhub-auth \
        --from-file=AUTH_RSA_PRIVATE_KEY_PEM="$TEMP_DIR/auth-private.pem" \
        --from-file=AUTH_RSA_PUBLIC_KEY_PEM="$TEMP_DIR/auth-public.pem" >/dev/null
fi

OAUTH_CLIENT_SECRET="$(openssl rand -base64 32 | tr -d '\n')"
random_secret_if_missing openshift-oauth-client-secret memoryhub-auth AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET "$OAUTH_CLIENT_SECRET"
OAUTH_CLIENT_SECRET="$(read_secret openshift-oauth-client-secret memoryhub-auth AUTH_OPENSHIFT_OAUTH_CLIENT_SECRET)"
OAUTH_CLIENT_SECRET_FILE=$(write_secret_file oauth-client-secret "$OAUTH_CLIENT_SECRET")
ADMIN_KEY="$(read_secret auth-admin-key memoryhub-auth AUTH_ADMIN_KEY)"
ADMIN_KEY_FILE=$(write_secret_file ui-admin-key "$ADMIN_KEY")
"${oc_context[@]}" create secret generic memoryhub-ui-admin-key -n memoryhub-ui \
    --from-file="MEMORYHUB_ADMIN_KEY=$ADMIN_KEY_FILE" --dry-run=client -o yaml | "${oc_context[@]}" apply -f - >/dev/null
unset ADMIN_KEY
remap_db_secret memoryhub-ui memoryhub-db-credentials MEMORYHUB_DB_
if ! "${oc_context[@]}" get secret memoryhub-ui-proxy -n memoryhub-ui >/dev/null 2>&1; then
    SESSION_SECRET_FILE=$(write_secret_file ui-session-secret "$(openssl rand -hex 32)")
    "${oc_context[@]}" create secret generic memoryhub-ui-proxy -n memoryhub-ui \
        --from-file="session-secret=$SESSION_SECRET_FILE" >/dev/null
fi

if ! "${oc_context[@]}" get configmap memoryhub-users -n "$NAMESPACE" >/dev/null 2>&1; then
    USERS_SOURCE="$REPO_ROOT/memory-hub-mcp/deploy/users-configmap.yaml"
    if [[ ! -f "$USERS_SOURCE" ]]; then
        USERS_SOURCE="$REPO_ROOT/memory-hub-mcp/deploy/users-configmap.example.yaml"
    fi
    python3 - "$USERS_SOURCE" "$TEMP_DIR/users-configmap.yaml" "$NAMESPACE" "${USER:-$(whoami)}" <<'PY'
import pathlib, re, secrets, sys

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
namespace = sys.argv[3]
user = sys.argv[4]
text = source.read_text()
text = text.replace("CURRENT_USER_DISPLAY", user.replace("-", " ").title())
text = text.replace("CURRENT_USER", user)
text = re.sub(
    r"REPLACE-ME-GENERATE-WITH-openssl-rand-hex-16",
    lambda _: "mh-dev-" + secrets.token_hex(8),
    text,
)
text = re.sub(r"(?m)^  namespace: .*?$", f"  namespace: {namespace}", text)
target.write_text(text)
PY
    "${oc_context[@]}" apply -f "$TEMP_DIR/users-configmap.yaml" >/dev/null
fi

echo "==> Seeding initial OAuth clients"
"${oc_context[@]}" get configmap memoryhub-users -n "$NAMESPACE" -o json \
    | python3 -c '
import json, pathlib, sys
cm=json.load(sys.stdin)
users=json.loads(cm["data"]["users.json"])["users"]
clients=[]
for user in users:
    scopes=["memory:read", "memory:write:user"]
    if "organizational" in user.get("scopes", []): scopes.append("memory:write:organizational")
    if "enterprise" in user.get("scopes", []): scopes.append("memory:write:enterprise")
    clients.append({
        "client_id": user["user_id"], "client_secret": user["api_key"],
        "client_name": user.get("name", user["user_id"]),
        "identity_type": user.get("identity_type", "user"),
        "tenant_id": user.get("tenant_id", "default"), "default_scopes": scopes,
    })
pathlib.Path(sys.argv[1]).write_text(json.dumps(clients, indent=2))
' "$TEMP_DIR/seed-clients.json"
MEMORYHUB_CONTEXT="$CONTEXT" MEMORYHUB_SEED_CLIENTS_FILE="$TEMP_DIR/seed-clients.json" \
    "$REPO_ROOT/scripts/run-seed-oauth-clients.sh" memoryhub-db

echo "==> Registering OpenShift OAuth client"
python3 - "$REPO_ROOT/memoryhub-auth/deploy/oauthclient.yaml" "$TEMP_DIR/oauthclient.yaml" "$OAUTH_CLIENT_SECRET_FILE" "https://${AUTH_HOST}/oauth/openshift/callback" <<'PY'
import pathlib, sys

source, target, secret_file, redirect = sys.argv[1:]
secret = pathlib.Path(secret_file).read_text()
text = pathlib.Path(source).read_text()
text = text.replace("secret: PLACEHOLDER-SEE-COMMENTS-ABOVE", "secret: " + secret)
text = text.replace("__REDIRECT_URI__", redirect)
pathlib.Path(target).write_text(text)
PY
"${oc_context[@]}" apply -f "$TEMP_DIR/oauthclient.yaml" >/dev/null
unset OAUTH_CLIENT_SECRET

if [[ "$PREBUILT_IMAGES" == true ]]; then
    echo "==> Using prebuilt MCP, auth, and UI images; skipping application image builds"
else
    echo "==> Building MCP, auth, and UI images"
    MEMORYHUB_CONTEXT="$CONTEXT" "$REPO_ROOT/scripts/build-full.sh"
fi

cat > "$TEMP_DIR/full-stack.yaml" <<'EOF'
postgresql:
  enabled: true
minio:
  enabled: true
valkey:
  enabled: true
mcp:
  enabled: true
auth:
  enabled: true
ui:
  enabled: true
models:
  enabled: true
maintenance:
  retention:
    enabled: true
  cleanup:
    enabled: false
EOF
helm_stage "$TEMP_DIR/full-stack.yaml"

echo "==> Deploying RHOAI dashboard tile (skipped if RHOAI is not installed)"
RHOAI_NS="redhat-ods-applications"
if "${oc_context[@]}" get namespace "$RHOAI_NS" >/dev/null 2>&1; then
    UI_CLUSTER_IP=$("${oc_context[@]}" get svc memoryhub-ui -n memoryhub-ui \
        -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
    if [[ -n "$UI_CLUSTER_IP" ]]; then
        "${oc_context[@]}" apply -f - >/dev/null <<PROXY_EOF
apiVersion: v1
kind: Service
metadata:
  name: memoryhub-ui
  namespace: ${RHOAI_NS}
spec:
  ports:
  - port: 8080
    protocol: TCP
    targetPort: 8080
---
apiVersion: v1
kind: Endpoints
metadata:
  name: memoryhub-ui
  namespace: ${RHOAI_NS}
subsets:
- addresses:
  - ip: ${UI_CLUSTER_IP}
  ports:
  - port: 8080
    protocol: TCP
PROXY_EOF
        if ! "${oc_context[@]}" get route memoryhub-ui -n "$RHOAI_NS" >/dev/null 2>&1; then
            "${oc_context[@]}" apply -f - >/dev/null <<ROUTE_EOF
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: memoryhub-ui
  namespace: ${RHOAI_NS}
spec:
  to:
    kind: Service
    name: memoryhub-ui
  port:
    targetPort: 8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
ROUTE_EOF
        fi
        if "${oc_context[@]}" get crd odhapplications.dashboard.opendatahub.io >/dev/null 2>&1; then
            "${oc_context[@]}" apply -f "$REPO_ROOT/memoryhub-ui/openshift/odh-application.yaml" >/dev/null
            echo "  RHOAI tile deployed (proxy ClusterIP: ${UI_CLUSTER_IP})"
        else
            echo "  OdhApplication CRD not found — proxy route synced, tile skipped"
        fi
    else
        echo "  WARNING: memoryhub-ui Service ClusterIP not yet available — skipping tile"
        echo "  Re-run: bash memoryhub-ui/deploy/deploy.sh"
    fi
else
    echo "  RHOAI not installed (${RHOAI_NS} namespace not found) — skipping tile"
fi

echo "==> Saving the generated first-user API key to local MemoryHub credentials"
"${oc_context[@]}" get configmap memoryhub-users -n "$NAMESPACE" -o json \
    | python3 -c 'import json,sys; print(json.loads(json.load(sys.stdin)["data"]["users.json"])["users"][0]["api_key"])' \
    > "$TEMP_DIR/first-user-key"
MCP_URL="https://${MCP_HOST}/mcp/"
"$REPO_ROOT/.venv/bin/python" - "$REPO_ROOT" "$CONTEXT" "$TEMP_DIR/first-user-key" "$MCP_URL" <<'PY'
import pathlib, sys

repo, context, key_path, url = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(repo) / "memoryhub-cli" / "src"))
from memoryhub_cli.config import migrate_flat_to_credentials, write_credentials_section

migrate_flat_to_credentials()
write_credentials_section(context, pathlib.Path(key_path).read_text().strip(), url)
PY

echo ""
echo "MemoryHub is installed by Helm."
echo "  UI:  https://${UI_HOST}"
echo "  MCP: ${MCP_URL}"
echo "  Credentials: ~/.config/memoryhub/credentials [${CONTEXT}]"
echo ""
