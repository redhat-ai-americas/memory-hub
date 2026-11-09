"""Regression tests: tenant-bound admin keys (QA 2026-11-06 cross-tenant client creation)."""

import json
import os

os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")
os.environ["AUTH_TENANT_ADMIN_KEYS"] = json.dumps({"tenant-a": "key-tenant-a", "tenant-b": "key-tenant-b"})

import pytest  # noqa: E402

A = {"X-Admin-Key": "key-tenant-a"}
B = {"X-Admin-Key": "key-tenant-b"}
PLATFORM = {"X-Admin-Key": "test-admin-key"}


def _body(cid, tenant, scopes=None):
    return {
        "client_id": cid,
        "client_name": cid,
        "identity_type": "service",
        "tenant_id": tenant,
        "default_scopes": scopes or ["memory:read"],
    }


@pytest.mark.asyncio
class TestTenantBoundAdminKeys:
    async def test_tenant_key_creates_in_own_tenant(self, client):
        r = await client.post(
            "/admin/clients", json=_body("a-ok", "tenant-a", ["memory:read", "memory:admin"]), headers=A
        )
        assert r.status_code == 201, r.text
        assert r.json()["tenant_id"] == "tenant-a"

    async def test_tenant_key_cannot_create_in_foreign_tenant_body(self, client):
        r = await client.post(
            "/admin/clients", json=_body("a-into-b", "tenant-b", ["memory:read", "memory:admin"]), headers=A
        )
        assert r.status_code == 403, r.text
        listed = await client.get("/admin/clients", headers=PLATFORM)
        assert "a-into-b" not in [c["client_id"] for c in listed.json()]

    async def test_tenant_key_query_override_refused(self, client):
        r = await client.post("/admin/clients?tenant_id=tenant-b", json=_body("a-q", "tenant-a"), headers=A)
        assert r.status_code == 403, r.text
        r = await client.get("/admin/clients?tenant_id=tenant-b", headers=A)
        assert r.status_code == 403, r.text

    async def test_tenant_key_lists_only_own_tenant(self, client):
        await client.post("/admin/clients", json=_body("a-1", "tenant-a"), headers=A)
        await client.post("/admin/clients", json=_body("b-1", "tenant-b"), headers=B)
        ids = [c["client_id"] for c in (await client.get("/admin/clients", headers=A)).json()]
        assert "a-1" in ids and "b-1" not in ids

    async def test_tenant_key_cannot_touch_foreign_client(self, client):
        await client.post("/admin/clients", json=_body("b-2", "tenant-b"), headers=B)
        assert (await client.get("/admin/clients/b-2", headers=A)).status_code == 404
        assert (await client.patch("/admin/clients/b-2", json={"active": False}, headers=A)).status_code == 404
        assert (await client.post("/admin/clients/b-2/rotate-secret", headers=A)).status_code == 404
        assert (await client.post("/admin/clients/b-2/rotate-api-key", headers=A)).status_code == 404
        assert (
            await client.patch("/admin/clients/b-2?tenant_id=tenant-b", json={"active": False}, headers=A)
        ).status_code == 403
        still = (await client.get("/admin/clients/b-2", headers=PLATFORM)).json()
        assert still["active"] is True

    async def test_cross_tenant_scope_platform_only(self, client):
        r = await client.post(
            "/admin/clients", json=_body("a-xt", "tenant-a", ["memory:read", "memory:admin:cross_tenant"]), headers=A
        )
        assert r.status_code == 403, r.text
        await client.post("/admin/clients", json=_body("a-up", "tenant-a"), headers=A)
        r = await client.patch("/admin/clients/a-up", json={"default_scopes": ["memory:admin:cross_tenant"]}, headers=A)
        assert r.status_code == 403, r.text
        r = await client.post(
            "/admin/clients", json=_body("p-xt", "tenant-a", ["memory:admin:cross_tenant"]), headers=PLATFORM
        )
        assert r.status_code == 201, r.text

    async def test_unknown_scope_rejected(self, client):
        r = await client.post("/admin/clients", json=_body("a-bad", "tenant-a", ["memory:everything"]), headers=A)
        assert r.status_code == 422, r.text
        r = await client.post("/admin/clients", json=_body("p-bad", "tenant-a", ["root"]), headers=PLATFORM)
        assert r.status_code == 422, r.text

    async def test_platform_key_still_manages_any_tenant(self, client):
        r = await client.post("/admin/clients", json=_body("p-b", "tenant-b"), headers=PLATFORM)
        assert r.status_code == 201 and r.json()["tenant_id"] == "tenant-b"

    async def test_wrong_key_rejected(self, client):
        assert (await client.get("/admin/clients", headers={"X-Admin-Key": "key-tenant-c"})).status_code == 401
