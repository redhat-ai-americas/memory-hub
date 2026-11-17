#!/usr/bin/env python3
"""Compare default Helm output with the repository's current Kustomize/YAML installs."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised by CI setup failure
    raise SystemExit("PyYAML is required: python3 -m pip install PyYAML") from exc


ROOT = Path(__file__).resolve().parents[1]
BASE_KUSTOMIZATIONS = (
    "deploy/postgresql",
    "deploy/minio",
    "deploy/valkey",
)
MODEL_KUSTOMIZATIONS = {
    "cpu": ("deploy/embedding", "deploy/reranker"),
    "gpu": ("deploy/embedding-gpu", "deploy/reranker-gpu"),
}
RAW_MANIFESTS = (
    ("memory-hub-mcp/deploy/openshift.yaml", "memory-hub-mcp"),
    ("memoryhub-auth/openshift.yaml", "memoryhub-auth"),
    ("memoryhub-ui/openshift.yaml", "memoryhub-ui"),
    ("memoryhub-ui/openshift/oauth-proxy-sa.yaml", "memoryhub-ui"),
    ("deploy/retention/cronjob.yaml", "memory-hub-mcp"),
)
CLUSTER_SCOPED = {"ClusterRole", "ClusterRoleBinding", "Namespace"}
EXPECTED_CHILD_NAMESPACES = {
    "memoryhub-db",
    "memoryhub-storage",
    "memoryhub-auth",
    "memoryhub-ui",
    "embedding-model",
    "reranker-model",
}
# Resources rendered by the chart but absent from Kustomize manifests.
# Update this set whenever a new chart-only resource is intentionally added
# (e.g. a new SCC RoleBinding). Missing entries cause alignment check failures.
EXPECTED_CHART_ONLY = {
    ("RoleBinding", "memoryhub-postgresql-anyuid", "memoryhub-db"),
    ("RoleBinding", "memoryhub-minio-anyuid", "memoryhub-storage"),
    ("RoleBinding", "memoryhub-valkey-anyuid", "memory-hub-mcp"),
}
DYNAMIC_ENV = {
    "AUTH_JWKS_URI",
    "AUTH_ISSUER",
    "AUTH_OPENSHIFT_OAUTH_AUTHORIZE_URL",
    "MEMORYHUB_DB_HOST",
}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "CronJob"}


def fail(message: str) -> None:
    raise SystemExit(f"Helm/Kustomize alignment check failed: {message}")


def load_yaml(text: str, origin: str) -> list[dict[str, Any]]:
    try:
        return [item for item in yaml.safe_load_all(text) if isinstance(item, dict)]
    except yaml.YAMLError as exc:
        fail(f"could not parse YAML from {origin}: {exc}")


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    try:
        return subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        fail(f"command failed ({' '.join(command)}): {exc.stderr.strip()}")


def resource_id(resource: dict[str, Any]) -> tuple[str, str, str]:
    metadata = resource.get("metadata", {})
    kind = resource.get("kind", "")
    namespace = "" if kind in CLUSTER_SCOPED else metadata.get("namespace", "")
    return kind, metadata.get("name", ""), namespace


def index_resources(resources: list[dict[str, Any]], label: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for resource in resources:
        key = resource_id(resource)
        if key in indexed:
            fail(f"duplicate {label} resource {key}")
        indexed[key] = resource
    return indexed


def source_resources(openshift: bool, model_variant: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    kubectl = shutil.which("kubectl")
    kustomize = shutil.which("kustomize")
    if not kubectl and not kustomize:
        fail("install kubectl (with kustomize support) or kustomize")

    if model_variant not in MODEL_KUSTOMIZATIONS:
        fail(f"unsupported source model variant: {model_variant}")

    for directory in BASE_KUSTOMIZATIONS + MODEL_KUSTOMIZATIONS[model_variant]:
        command = [kubectl, "kustomize", directory] if kubectl else [kustomize, "build", directory]
        resources.extend(load_yaml(run(command), directory))

    for relative_path, default_namespace in RAW_MANIFESTS:
        path = ROOT / relative_path
        for resource in load_yaml(path.read_text(), relative_path):
            kind = resource.get("kind")
            if kind == "Secret":
                continue
            if not openshift and kind == "Route":
                continue
            if not openshift and kind == "ConfigMap" and resource.get("metadata", {}).get("name") == "service-ca-bundle":
                continue
            if kind not in CLUSTER_SCOPED:
                resource.setdefault("metadata", {}).setdefault("namespace", default_namespace)
            if not openshift and relative_path == "memoryhub-auth/openshift.yaml" and kind == "Deployment":
                pod = resource.get("spec", {}).get("template", {}).get("spec", {})
                pod.pop("initContainers", None)
                pod["volumes"] = [
                    volume for volume in pod.get("volumes", [])
                    if volume.get("name") not in {"service-ca", "combined-ca"}
                ]
                for container in pod.get("containers", []):
                    container["volumeMounts"] = [
                        mount for mount in container.get("volumeMounts", [])
                        if mount.get("name") not in {"service-ca", "combined-ca"}
                    ]
                    container["env"] = [
                        item for item in container.get("env", [])
                        if item.get("name") != "AUTH_OPENSHIFT_CA_BUNDLE"
                    ]
            resources.append(resource)

    resources = [resource for resource in resources if resource.get("kind") != "Secret"]
    if not openshift:
        resources = [
            resource
            for resource in resources
            if resource.get("kind") != "Route"
            and resource_id(resource) != ("ClusterRoleBinding", "memoryhub-auth-delegator", "")
            and resource_id(resource) != ("ClusterRole", "memoryhub-auth-ns-reader", "")
            and resource_id(resource) != ("ClusterRoleBinding", "memoryhub-auth-ns-reader", "")
        ]

    # The current deployment creates these namespaces in deploy-full.sh even
    # where a component's Kustomize directory has no Namespace manifest.
    resources = [resource for resource in resources if resource.get("kind") != "Namespace"]
    for namespace in EXPECTED_CHILD_NAMESPACES:
        resources.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace}})
    return index_resources(resources, "source")


def chart_resources(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    return index_resources(load_yaml(path.read_text(), str(path)), "Helm")


def compare_inventory(source: dict, chart: dict, label: str) -> None:
    source_ids = set(source)
    chart_ids = set(chart)
    missing = source_ids - chart_ids
    extra = chart_ids - source_ids
    if "default Kubernetes" in label and ("ConfigMap", "service-ca-bundle", "memoryhub-auth") in missing:
        missing.remove(("ConfigMap", "service-ca-bundle", "memoryhub-auth"))
    if missing:
        fail(f"{label} chart is missing current resources: {sorted(missing)}")
    expected_extra = EXPECTED_CHART_ONLY if label.endswith("OpenShift") else set()
    if extra != expected_extra:
        fail(f"{label} chart-only resource set changed: {sorted(extra)}")


def pod_spec(resource: dict[str, Any]) -> dict[str, Any]:
    spec = resource.get("spec", {})
    if resource.get("kind") == "CronJob":
        return spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    return spec.get("template", {}).get("spec", {})


def all_containers(pod: dict[str, Any]) -> dict[str, dict[str, Any]]:
    containers = pod.get("initContainers", []) + pod.get("containers", [])
    return {container["name"]: container for container in containers}


def effective_pull_policy(container: dict[str, Any]) -> str:
    explicit = container.get("imagePullPolicy")
    if explicit:
        return explicit
    image = container.get("image", "")
    if "@sha256:" in image:
        return "IfNotPresent"
    final_part = image.rsplit("/", 1)[-1]
    tag = final_part.rsplit(":", 1)[-1] if ":" in final_part else "latest"
    return "Always" if tag == "latest" else "IfNotPresent"


def normalized_ports(container: dict[str, Any]) -> list[tuple[int, str]]:
    return sorted(
        (int(port["containerPort"]), port.get("protocol", "TCP"))
        for port in container.get("ports", [])
    )


def env_signature(entry: dict[str, Any]) -> Any:
    if "valueFrom" in entry:
        return entry["valueFrom"]
    value = str(entry.get("value", ""))
    return value.replace(".svc.cluster.local", ".svc")


def compare_env(source: dict[str, Any], chart: dict[str, Any], key: tuple) -> None:
    source_env = {item["name"]: item for item in source.get("env", [])}
    chart_env = {item["name"]: item for item in chart.get("env", [])}
    for name in sorted(source_env.keys() & chart_env.keys()):
        if name in DYNAMIC_ENV:
            continue
        if "__" in str(source_env[name].get("value", "")):
            continue
        if env_signature(source_env[name]) != env_signature(chart_env[name]):
            fail(f"{key} environment variable {name} differs from its source manifest")


def compare_workloads(source: dict, chart: dict) -> None:
    for key, source_resource in source.items():
        if key[0] not in WORKLOAD_KINDS:
            continue
        chart_resource = chart[key]
        source_spec = source_resource.get("spec", {})
        chart_spec = chart_resource.get("spec", {})
        if key[0] != "CronJob" and source_spec.get("replicas", 1) != chart_spec.get("replicas", 1):
            fail(f"{key} replica count differs")
        if key[0] in {"Deployment", "StatefulSet"}:
            for field in ("strategy", "serviceName"):
                if source_spec.get(field) != chart_spec.get(field):
                    fail(f"{key} spec.{field} differs")

        source_pod = pod_spec(source_resource)
        chart_pod = pod_spec(chart_resource)
        for field in ("serviceAccountName", "automountServiceAccountToken", "securityContext", "volumes"):
            source_value = source_pod.get(field, [] if field == "volumes" else None)
            chart_value = chart_pod.get(field, [] if field == "volumes" else None)
            if source_value != chart_value:
                fail(f"{key} pod {field} differs")

        source_containers = all_containers(source_pod)
        chart_containers = all_containers(chart_pod)
        if source_containers.keys() != chart_containers.keys():
            fail(f"{key} container names differ")
        for name in source_containers:
            left, right = source_containers[name], chart_containers[name]
            for field in (
                "image",
                "command",
                "args",
                "resources",
                "livenessProbe",
                "readinessProbe",
                "startupProbe",
                "volumeMounts",
                "securityContext",
            ):
                left_value = left.get(field, [] if field == "volumeMounts" else None)
                right_value = right.get(field, [] if field == "volumeMounts" else None)
                if left_value != right_value:
                    if field == "args" and name == "combine-ca":
                        left_command = " ".join(" ".join(left_value or []).replace("\\\n", " ").split())
                        right_command = " ".join(" ".join(right_value or []).replace("\\\n", " ").split())
                        if left_command == right_command:
                            continue
                    fail(f"{key} container {name} field {field} differs")
            if effective_pull_policy(left) != effective_pull_policy(right):
                fail(f"{key} container {name} image pull policy differs")
            if normalized_ports(left) != normalized_ports(right):
                fail(f"{key} container {name} ports differ")
            compare_env(left, right, key)


def workloads(resources: dict) -> list[tuple[tuple, dict[str, Any]]]:
    return [(key, item) for key, item in resources.items() if key[0] in {"Deployment", "StatefulSet"}]


def selected_workloads(service: dict, resources: dict) -> set[tuple]:
    selector = service.get("spec", {}).get("selector", {})
    selected = set()
    namespace = resource_id(service)[2]
    for key, workload in workloads(resources):
        if key[2] != namespace:
            continue
        labels = workload.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
        if all(labels.get(name) == value for name, value in selector.items()):
            selected.add(key)
    return selected


def resolved_target_port(port: dict[str, Any], targets: set[tuple], resources: dict) -> int:
    target = port.get("targetPort", port["port"])
    if isinstance(target, int):
        return target
    found = set()
    for key in targets:
        pod = pod_spec(resources[key])
        for container in pod.get("containers", []):
            for container_port in container.get("ports", []):
                if container_port.get("name") == target:
                    found.add(int(container_port["containerPort"]))
    if len(found) != 1:
        fail(f"service targetPort {target!r} does not resolve to exactly one container port")
    return found.pop()


def compare_services(source: dict, chart: dict) -> None:
    for key, left in source.items():
        if key[0] != "Service":
            continue
        right = chart[key]
        left_spec, right_spec = left.get("spec", {}), right.get("spec", {})
        if left_spec.get("type", "ClusterIP") != right_spec.get("type", "ClusterIP"):
            fail(f"{key} Service type differs")
        left_targets = selected_workloads(left, source)
        right_targets = selected_workloads(right, chart)
        if not left_targets or left_targets != right_targets:
            fail(f"{key} Service selects different workloads")
        left_ports = sorted(
            (int(port["port"]), port.get("protocol", "TCP"), resolved_target_port(port, left_targets, source))
            for port in left_spec.get("ports", [])
        )
        right_ports = sorted(
            (int(port["port"]), port.get("protocol", "TCP"), resolved_target_port(port, right_targets, chart))
            for port in right_spec.get("ports", [])
        )
        if left_ports != right_ports:
            fail(f"{key} Service ports differ: source={left_ports}, chart={right_ports}")


def compare_pvcs_and_configmaps(source: dict, chart: dict) -> None:
    for key, left in source.items():
        if key[0] == "PersistentVolumeClaim":
            right = chart[key]
            for field in ("accessModes", "resources", "storageClassName", "volumeMode"):
                if left.get("spec", {}).get(field) != right.get("spec", {}).get(field):
                    fail(f"{key} PVC spec.{field} differs")
        elif key[0] == "ConfigMap":
            right = chart[key]
            if left.get("data", {}) != right.get("data", {}):
                fail(f"{key} ConfigMap data differs")


def compare_routes(source: dict, chart: dict) -> None:
    def route_target_port(route: dict[str, Any], resources: dict) -> int:
        namespace = resource_id(route)[2]
        service_name = route.get("spec", {}).get("to", {}).get("name")
        service_key = ("Service", service_name, namespace)
        if service_key not in resources:
            fail(f"{resource_id(route)} route target Service is missing")

        target = route.get("spec", {}).get("port", {}).get("targetPort")
        if isinstance(target, int):
            return target

        service = resources[service_key]
        matching_ports = [
            port for port in service.get("spec", {}).get("ports", [])
            if port.get("name") == target
        ]
        if len(matching_ports) != 1:
            fail(f"{resource_id(route)} route target {target!r} does not resolve to one Service port")
        targets = selected_workloads(service, resources)
        if not targets:
            fail(f"{resource_id(route)} route target Service selects no workloads")
        return resolved_target_port(matching_ports[0], targets, resources)

    for key, left in source.items():
        if key[0] != "Route":
            continue
        right = chart[key]
        for field in ("to", "tls", "path"):
            if left.get("spec", {}).get(field) != right.get("spec", {}).get(field):
                fail(f"{key} Route spec.{field} differs")
        left_timeout = left.get("metadata", {}).get("annotations", {}).get("haproxy.router.openshift.io/timeout")
        right_timeout = right.get("metadata", {}).get("annotations", {}).get("haproxy.router.openshift.io/timeout")
        if left_timeout != right_timeout:
            fail(f"{key} Route timeout annotation differs")
        if route_target_port(left, source) != route_target_port(right, chart):
            fail(f"{key} Route targets a different backend port")


def compare_rbac_and_service_accounts(source: dict, chart: dict) -> None:
    for key, left in source.items():
        if key[0] in {"ClusterRole", "ClusterRoleBinding"}:
            right = chart[key]
            fields = ("rules",) if key[0] == "ClusterRole" else ("roleRef", "subjects")
            for field in fields:
                left_value = left.get(field, [])
                right_value = right.get(field, [])
                if field == "subjects":
                    left_value = sorted(left_value, key=lambda item: json.dumps(item, sort_keys=True))
                    right_value = sorted(right_value, key=lambda item: json.dumps(item, sort_keys=True))
                if left_value != right_value:
                    fail(f"{key} RBAC {field} differs")
        elif key[0] == "ServiceAccount":
            right = chart[key]
            for field in ("automountServiceAccountToken",):
                if left.get(field) != right.get(field):
                    fail(f"{key} ServiceAccount {field} differs")
            if left.get("metadata", {}).get("annotations", {}) != right.get("metadata", {}).get("annotations", {}):
                fail(f"{key} ServiceAccount annotations differ")

    for key in EXPECTED_CHART_ONLY:
        if key[0] != "RoleBinding":
            continue
        binding = chart[key]
        if binding.get("roleRef", {}).get("name") != "system:openshift:scc:anyuid":
            fail(f"{key} does not bind the anyuid SCC role")
        expected_sa = {
            "memoryhub-postgresql-anyuid": "memoryhub-postgresql",
            "memoryhub-minio-anyuid": "memoryhub-minio",
            "memoryhub-valkey-anyuid": "memoryhub-valkey",
        }[key[1]]
        subjects = binding.get("subjects", [])
        if len(subjects) != 1 or subjects[0].get("name") != expected_sa or subjects[0].get("namespace") != key[2]:
            fail(f"{key} SCC binding is not limited to its workload ServiceAccount")


def compare_namespace_contract(chart: dict) -> None:
    rendered = {key[1] for key in chart if key[0] == "Namespace"}
    if rendered != EXPECTED_CHILD_NAMESPACES:
        fail(f"chart-created namespaces changed: expected {sorted(EXPECTED_CHILD_NAMESPACES)}, got {sorted(rendered)}")


def compare_derived_connection_settings(chart: dict, model_variant: str) -> None:
    def env_for(key: tuple, container_name: str) -> dict[str, Any]:
        resource = chart[key]
        container = all_containers(pod_spec(resource))[container_name]
        return {item["name"]: item for item in container.get("env", [])}

    def literal(env: dict[str, Any], name: str, expected: str, key: tuple) -> None:
        if env.get(name, {}).get("value") != expected:
            fail(f"{key} {name} should be {expected!r}")

    def secret(env: dict[str, Any], name: str, secret_name: str, secret_key: str, key: tuple) -> None:
        actual = env.get(name, {}).get("valueFrom", {}).get("secretKeyRef", {})
        if actual != {"name": secret_name, "key": secret_key}:
            fail(f"{key} {name} must reference {secret_name}/{secret_key}")

    mcp_key = ("Deployment", "memory-hub-mcp", "memory-hub-mcp")
    mcp = env_for(mcp_key, "mcp-server")
    literal(mcp, "MEMORYHUB_DB_HOST", "memoryhub-pg.memoryhub-db.svc.cluster.local", mcp_key)
    for name, secret_key in (("MEMORYHUB_DB_PORT", "MEMORYHUB_DB_PORT"), ("MEMORYHUB_DB_NAME", "MEMORYHUB_DB_NAME"), ("MEMORYHUB_DB_USER", "MEMORYHUB_DB_USER"), ("MEMORYHUB_DB_PASSWORD", "MEMORYHUB_DB_PASSWORD")):
        secret(mcp, name, "memoryhub-db-credentials", secret_key, mcp_key)
    model_services = {
        "cpu": ("all-minilm-l6-v2", "ms-marco-minilm-l12-v2"),
        "gpu": ("granite-embedding", "granite-reranker"),
    }
    embedding_name, reranker_name = model_services[model_variant]
    literal(mcp, "MEMORYHUB_EMBEDDING_URL", f"http://{embedding_name}.embedding-model.svc.cluster.local:80/embed", mcp_key)
    literal(mcp, "MEMORYHUB_RERANKER_URL", f"http://{reranker_name}.reranker-model.svc.cluster.local:80", mcp_key)

    ui_key = ("Deployment", "memoryhub-ui", "memoryhub-ui")
    ui = env_for(ui_key, "memoryhub-ui")
    literal(ui, "MEMORYHUB_DB_HOST", "memoryhub-pg.memoryhub-db.svc.cluster.local", ui_key)
    for name, secret_key in (("MEMORYHUB_DB_PORT", "MEMORYHUB_DB_PORT"), ("MEMORYHUB_DB_NAME", "MEMORYHUB_DB_NAME"), ("MEMORYHUB_DB_USER", "MEMORYHUB_DB_USER"), ("MEMORYHUB_DB_PASSWORD", "MEMORYHUB_DB_PASSWORD")):
        secret(ui, name, "memoryhub-db-credentials", secret_key, ui_key)
    literal(ui, "MEMORYHUB_EMBEDDING_URL", f"http://{embedding_name}.embedding-model.svc.cluster.local:80", ui_key)


def main() -> None:
    if len(sys.argv) != 5:
        fail("usage: check_helm_chart_alignment.py DEFAULT_RENDER OPENSHIFT_RENDER GPU_RENDER OPENSHIFT_GPU_RENDER")

    renders = {
        ("cpu", False): chart_resources(Path(sys.argv[1])),
        ("cpu", True): chart_resources(Path(sys.argv[2])),
        ("gpu", False): chart_resources(Path(sys.argv[3])),
        ("gpu", True): chart_resources(Path(sys.argv[4])),
    }

    for (variant, is_openshift), chart in renders.items():
        source = source_resources(openshift=is_openshift, model_variant=variant)
        label = f"{variant} {'OpenShift' if is_openshift else 'default Kubernetes'}"
        compare_inventory(source, chart, label)
        if variant == "cpu" and not is_openshift:
            compare_namespace_contract(chart)
        compare_workloads(source, chart)
        compare_services(source, chart)
        compare_pvcs_and_configmaps(source, chart)
        compare_derived_connection_settings(chart, variant)
        if is_openshift:
            compare_routes(source, chart)
            compare_rbac_and_service_accounts(source, chart)

    print("CPU and GPU Helm resources and settings match the current Kubernetes and OpenShift deployment manifests.")
    print("Expected additions: Helm-managed component namespaces and scoped SCC RoleBindings.")


if __name__ == "__main__":
    main()
