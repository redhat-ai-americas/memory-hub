"""Named API keys and last-use timestamps (#721)."""
import os

import pytest

os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")
os.environ["AUTH_INTERNAL_SERVICE_KEY"] = "test-service-key"

ADMIN = {"X-Admin-Key": "test-admin-key"}
SERVICE = {"X-Service-Key": "test-service-key"}


@pytest.fixture
def _service_key(monkeypatch):
    monkeypatch.setenv("AUTH_INTERNAL_SERVICE_KEY", "test-service-key")
    monkeypatch.setenv("AUTH_ADMIN_KEY", "test-admin-key")


async def _new_client(client, owner="alice", client_id="alice-agent"):
    payload = {"client_id": client_id, "client_name": "Alice agent", "tenant_id": "t1",
               "default_scopes": ["memory:read"]}
    if owner:
        payload["owner"] = owner
    resp = await client.post("/admin/clients", headers=ADMIN, json=payload)
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_service_key")
class TestNamedKeys:
    async def test_create_list_use_and_revoke(self, client):
        await _new_client(client)
        created = await client.post("/admin/clients/alice-agent/keys", headers=ADMIN,
                                    params={"tenant_id": "t1", "owner": "alice"},
                                    json={"name": "laptop", "created_by": "alice"})
        assert created.status_code == 201
        body = created.json()
        assert body["api_key"].startswith("mh-key-") and body["key_prefix"] == body["api_key"][:11]
        assert body["last_used_at"] is None

        listed = (await client.get("/admin/clients/alice-agent/keys", headers=ADMIN,
                                   params={"owner": "alice"})).json()
        assert [k["name"] for k in listed] == ["laptop"] and "api_key" not in listed[0]

        ok = await client.post("/internal/validate-api-key", headers=SERVICE, json={"api_key": body["api_key"]})
        assert ok.status_code == 200 and ok.json()["user_id"] == "alice-agent"
        used = (await client.get("/admin/clients/alice-agent/keys", headers=ADMIN)).json()[0]
        assert used["last_used_at"] is not None
        agent = (await client.get("/admin/clients/alice-agent", headers=ADMIN)).json()
        assert agent["last_used_via"] == "api_key" and agent["last_used_at"] is not None

        revoked = await client.delete(f"/admin/clients/alice-agent/keys/{body['id']}", headers=ADMIN,
                                      params={"owner": "alice"})
        assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
        refused = await client.post("/internal/validate-api-key", headers=SERVICE, json={"api_key": body["api_key"]})
        assert refused.status_code == 401

    async def test_keys_follow_the_owner_binding(self, client):
        await _new_client(client)
        for method, path in (("get", "/admin/clients/alice-agent/keys"),
                             ("post", "/admin/clients/alice-agent/keys"),
                             ("delete", "/admin/clients/alice-agent/keys/00000000-0000-0000-0000-000000000000")):
            kwargs = {"json": {"name": "x"}} if method == "post" else {}
            resp = await getattr(client, method)(path, headers=ADMIN, params={"owner": "mallory"}, **kwargs)
            assert resp.status_code == 404

    async def test_inactive_client_gets_no_new_key_and_its_keys_stop_working(self, client):
        await _new_client(client)
        key = (await client.post("/admin/clients/alice-agent/keys", headers=ADMIN, json={"name": "ci"})).json()
        await client.patch("/admin/clients/alice-agent", headers=ADMIN, json={"active": False})
        assert (await client.post("/admin/clients/alice-agent/keys", headers=ADMIN,
                                  json={"name": "again"})).status_code == 409
        assert (await client.post("/internal/validate-api-key", headers=SERVICE,
                                  json={"api_key": key["api_key"]})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("_service_key")
class TestLastUsed:
    async def test_client_credentials_and_primary_key_record_use(self, client):
        created = await _new_client(client)
        assert created["last_used_at"] is None
        token = await client.post("/token", data={"grant_type": "client_credentials", "client_id": "alice-agent",
                                                  "client_secret": created["client_secret"]})
        assert token.status_code == 200
        after = (await client.get("/admin/clients/alice-agent", headers=ADMIN)).json()
        assert after["last_used_via"] == "client_credentials" and after["last_used_at"] is not None

        primary = await client.post("/internal/validate-api-key", headers=SERVICE, json={"api_key": created["api_key"]})
        assert primary.status_code == 200
        assert (await client.get("/admin/clients/alice-agent", headers=ADMIN)).json()["api_key_last_used_at"]

    async def test_failed_authentication_records_nothing(self, client):
        await _new_client(client)
        bad = await client.post("/token", data={"grant_type": "client_credentials", "client_id": "alice-agent",
                                                "client_secret": "wrong"})
        assert bad.status_code == 401
        assert (await client.get("/admin/clients/alice-agent", headers=ADMIN)).json()["last_used_at"] is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_service_key")
class TestVerifySecret:
    async def test_proves_the_secret_without_issuing_tokens(self, client):
        created = await _new_client(client, owner=None, client_id="loose-agent")
        good = await client.post("/admin/clients/loose-agent/verify-secret", headers=ADMIN, params={"tenant_id": "t1"},
                                 json={"client_secret": created["client_secret"]})
        assert good.json() == {"client_id": "loose-agent", "valid": True}
        bad = await client.post("/admin/clients/loose-agent/verify-secret", headers=ADMIN,
                                json={"client_secret": "nope"})
        assert bad.json()["valid"] is False
        other_tenant = await client.post("/admin/clients/loose-agent/verify-secret", headers=ADMIN,
                                         params={"tenant_id": "t2"}, json={"client_secret": created["client_secret"]})
        assert other_tenant.status_code == 404
        assert (await client.get("/admin/clients/loose-agent", headers=ADMIN)).json()["last_used_at"] is None
