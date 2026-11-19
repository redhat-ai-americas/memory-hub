"""Public OAuth Route and internal technical Auth API stay separate."""

import os
from pathlib import Path

os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from src.main import public_app


@pytest.mark.asyncio
async def test_public_app_excludes_technical_routes_even_with_service_keys(client):
    public_paths = set(public_app.openapi()["paths"])
    assert {
        "/authorize", "/token", "/oauth/openshift/callback",
        "/.well-known/oauth-authorization-server", "/.well-known/jwks.json", "/healthz",
    } <= public_paths
    assert not any(path.startswith(("/admin", "/internal")) for path in public_paths)
    async with AsyncClient(
        transport=ASGITransport(app=public_app), base_url="https://test"
    ) as public:
        for method, path, body in (
            ("GET", "/admin/clients", None),
            ("POST", "/admin/clients", {"client_id": "forbidden"}),
            ("POST", "/internal/validate-api-key", {"api_key": "secret"}),
        ):
            response = await public.request(
                method, path, json=body,
                headers={"X-Admin-Key": "test-admin-key", "X-Service-Key": "test-service-key"},
            )
            assert response.status_code == 404

        for path in (
            "/healthz", "/.well-known/oauth-authorization-server",
            "/.well-known/jwks.json",
        ):
            assert (await public.get(path)).status_code == 200

    assert (await client.get("/admin/clients")).status_code == 401
    assert (await client.get("/admin/clients", headers={"X-Admin-Key": "wrong"})).status_code == 401
    assert (await client.get("/admin/clients", headers={"X-Admin-Key": "test-admin-key"})).status_code == 200
    assert (await client.post("/internal/validate-api-key", json={"api_key": "secret"})).status_code == 401


def test_route_targets_public_listener_and_private_service_remains_internal():
    manifest = Path(__file__).resolve().parents[1] / "openshift.yaml"
    resources = {
        (item["kind"], item["metadata"]["name"]): item
        for item in yaml.safe_load_all(manifest.read_text()) if item
    }
    route = resources[("Route", "auth-server")]
    public_service = resources[("Service", "auth-server-public")]
    internal_service = resources[("Service", "auth-server")]
    deployment = resources[("Deployment", "auth-server")]
    containers = {item["name"]: item for item in deployment["spec"]["template"]["spec"]["containers"]}

    assert route["spec"]["to"] == {"kind": "Service", "name": "auth-server-public"}
    assert route["spec"]["port"]["targetPort"] == 8082
    assert public_service["spec"]["ports"][0]["targetPort"] == 8082
    assert internal_service["spec"]["ports"][0]["targetPort"] == 8081
    assert "src.main:public_app" in containers["auth-public"]["args"]
    assert any(port["containerPort"] == 8082 for port in containers["auth-public"]["ports"])
    assert any(port["containerPort"] == 8081 for port in containers["auth-server"]["ports"])
    public_secrets = {
        source["secretRef"]["name"] for source in containers["auth-public"]["envFrom"]
    }
    private_secrets = {
        source["secretRef"]["name"] for source in containers["auth-server"]["envFrom"]
    }
    assert "auth-admin-key" not in public_secrets
    assert "auth-internal-service-key" not in public_secrets
    assert {"auth-admin-key", "auth-internal-service-key"} <= private_secrets
