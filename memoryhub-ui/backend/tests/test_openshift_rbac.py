"""OpenShift RBAC role resolution against a fake Kubernetes API (#744).

Covers the negative paths from docs/auth/human-role-resolution.md:
revocation with an open session, forged or mismatched identity, API
outages (fail closed, no extension of expired decisions), and that the
person's token never reaches the logs.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.datastructures import Headers

import src.authorization as authorization
import src.identity as identity
from src.config import Settings, get_settings
from src.database import get_db
from src.identity import Authentication, OpenShiftRbac, VerifiedIdentity
from src.kube import KubeClient
from src.main import app

NS = "memoryhub-ui"


class FakeKube:
    """Users by token, grants by username and group, and an outage switch."""

    def __init__(self):
        self.users = {"tok-alice": ("alice", "uid-alice", ["corp-users"]),
                      "tok-bob": ("bob", "uid-bob", ["corp-admins"]),
                      "tok-carol": ("carol", "uid-carol", [])}
        self.grants = {"group:corp-users": {"use"}, "group:corp-admins": {"use", "admin"}}
        self.down = False
        self.status_override: int | None = None
        self.calls: list[str] = []
        self.sar_bodies: list[dict] = []

    def verbs(self, name: str, groups: list[str]) -> set[str]:
        verbs = set(self.grants.get(f"user:{name}", set()))
        for group in groups:
            verbs |= self.grants.get(f"group:{group}", set())
        return verbs

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.down:
            raise httpx.ConnectError("api down")
        if self.status_override:
            return httpx.Response(self.status_override, json={})
        token = request.headers["authorization"].removeprefix("Bearer ")
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/users/~"):
            if token not in self.users:
                return httpx.Response(401, json={})
            name, uid, _ = self.users[token]
            return httpx.Response(200, json={"metadata": {"name": name, "uid": uid}, "fullName": name.title()})
        if path.endswith("/selfsubjectaccessreviews"):
            if token not in self.users:
                return httpx.Response(401, json={})
            name, _, groups = self.users[token]
            verb = body["spec"]["resourceAttributes"]["verb"]
            assert body["spec"]["resourceAttributes"]["group"] == "memoryhub.io"
            assert body["spec"]["resourceAttributes"]["namespace"] == NS
            return httpx.Response(201, json={"status": {"allowed": verb in self.verbs(name, groups)}})
        if path.endswith("/tokenreviews"):
            assert token == "sa-token"
            reviewed = body["spec"]["token"]
            if reviewed not in self.users:
                return httpx.Response(201, json={"status": {"authenticated": False}})
            name, uid, groups = self.users[reviewed]
            return httpx.Response(201, json={"status": {"authenticated": True, "user": {
                "username": name, "uid": uid, "groups": groups + ["system:authenticated"]}}})
        if path.endswith("/subjectaccessreviews"):
            assert token == "sa-token"
            self.sar_bodies.append(body)
            spec = body["spec"]
            verb = spec["resourceAttributes"]["verb"]
            return httpx.Response(201, json={"status": {"allowed": verb in self.verbs(spec["user"], spec["groups"])}})
        return httpx.Response(404, json={})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def fake(tmp_path):
    kube = FakeKube()
    token_file = tmp_path / "token"
    token_file.write_text("sa-token")
    client = KubeClient("https://api.test", "", str(token_file), transport=httpx.MockTransport(kube.handler))
    return kube, client


def _settings(**overrides):
    values = {"ui_tenant_id": "tenant-a", "ui_role_source": "openshift-rbac", "ui_rbac_namespace": NS,
              "ui_identity_issuer": "openshift:test"}
    values.update(overrides)
    return Settings(**values)


def _request(user="alice", token="tok-alice", peer="127.0.0.1"):
    headers = []
    if user is not None:
        headers.append((b"x-forwarded-user", user.encode()))
    if token is not None:
        for value in token if isinstance(token, list) else [token]:
            headers.append((b"x-forwarded-access-token", value.encode()))
    request = MagicMock()
    request.client.host = peer
    request.headers = Headers(raw=headers)
    return request


async def _role(adapter, **kwargs):
    authn = await adapter.authenticate(_request(**kwargs))
    return authn, await adapter.resolve(authn)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["self", "delegated"])
async def test_admin_then_use_then_forbidden(fake, mode):
    kube, client = fake
    adapter = OpenShiftRbac(_settings(ui_rbac_check=mode), kube=client, clock=Clock())
    authn, role = await _role(adapter, user="bob", token="tok-bob")
    assert role == "admin"
    assert authn.identity == VerifiedIdentity("bob", "openshift:test", "uid-bob",
                                              "Bob" if mode == "self" else None)
    assert (await _role(adapter))[1] == "user"
    with pytest.raises(HTTPException) as denied:
        await _role(adapter, user="carol", token="tok-carol")
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_delegated_review_passes_groups_and_uid_but_never_token_scopes(fake):
    kube, client = fake
    adapter = OpenShiftRbac(_settings(ui_rbac_check="delegated"), kube=client, clock=Clock())
    await _role(adapter)
    spec = kube.sar_bodies[0]["spec"]
    assert spec["user"] == "alice" and spec["uid"] == "uid-alice"
    assert "corp-users" in spec["groups"] and "extra" not in spec


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs, status", [
    ({"token": None}, 401),
    ({"token": ["tok-alice", "tok-bob"]}, 401),
    ({"user": None}, 401),
    ({"user": "bob"}, 401),              # token belongs to alice
    ({"token": "tok-unknown"}, 401),
    ({"peer": "10.1.2.3"}, 401),         # not the loopback sidecar
])
@pytest.mark.parametrize("mode", ["self", "delegated"])
async def test_identity_must_be_proven_by_the_forwarded_token(fake, kwargs, status, mode):
    _, client = fake
    adapter = OpenShiftRbac(_settings(ui_rbac_check=mode), kube=client, clock=Clock())
    with pytest.raises(HTTPException) as refused:
        await _role(adapter, **kwargs)
    assert refused.value.status_code == status


@pytest.mark.asyncio
async def test_cached_decision_is_not_reused_for_a_different_proxy_user(fake):
    _, client = fake
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    await _role(adapter)
    with pytest.raises(HTTPException) as refused:
        await _role(adapter, user="bob", token="tok-alice")
    assert refused.value.status_code == 401


@pytest.mark.asyncio
async def test_decisions_are_cached_per_token(fake):
    kube, client = fake
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    await _role(adapter)
    first = len(kube.calls)
    authn, role = await _role(adapter)
    assert role == "user" and len(kube.calls) == first and not authn.fresh
    await _role(adapter, user="bob", token="tok-bob")
    assert len(kube.calls) > first


@pytest.mark.asyncio
async def test_revoked_binding_takes_effect_after_the_cache_ttl_with_the_session_open(fake):
    kube, client = fake
    clock = Clock()
    adapter = OpenShiftRbac(_settings(), kube=client, clock=clock)
    assert (await _role(adapter))[1] == "user"
    del kube.grants["group:corp-users"]
    clock.now += 29
    assert (await _role(adapter))[1] == "user"
    clock.now += 2
    with pytest.raises(HTTPException) as revoked:
        await _role(adapter)
    assert revoked.value.status_code == 403


@pytest.mark.asyncio
async def test_a_grant_after_a_denial_waits_only_for_the_short_deny_ttl(fake):
    kube, client = fake
    clock = Clock()
    adapter = OpenShiftRbac(_settings(), kube=client, clock=clock)
    with pytest.raises(HTTPException):
        await _role(adapter, user="carol", token="tok-carol")
    kube.grants["user:carol"] = {"use"}
    clock.now += 6
    assert (await _role(adapter, user="carol", token="tok-carol"))[1] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["self", "delegated"])
async def test_api_outage_fails_closed_and_never_extends_an_expired_allow(fake, mode):
    kube, client = fake
    clock = Clock()
    adapter = OpenShiftRbac(_settings(ui_rbac_check=mode), kube=client, clock=clock)
    assert (await _role(adapter))[1] == "user"
    kube.down = True
    assert (await _role(adapter))[1] == "user"   # still fresh
    clock.now += 31
    with pytest.raises(HTTPException) as outage:
        await _role(adapter)
    assert outage.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 500])
async def test_unexpected_api_answers_are_unavailable_not_denials(fake, status):
    kube, client = fake
    kube.status_override = status
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    with pytest.raises(HTTPException) as refused:
        await _role(adapter)
    assert refused.value.status_code == 503


@pytest.mark.asyncio
async def test_identity_without_uid_is_refused(fake):
    kube, client = fake
    kube.users["tok-alice"] = ("alice", "", ["corp-users"])
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    with pytest.raises(HTTPException) as refused:
        await _role(adapter)
    assert refused.value.status_code == 503


@pytest.mark.asyncio
async def test_cache_is_bounded(fake):
    _, client = fake
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    adapter.MAX_ENTRIES = 1
    await _role(adapter)
    await _role(adapter, user="bob", token="tok-bob")
    assert len(adapter._decisions) == 1


@pytest.mark.asyncio
async def test_resolve_without_credential_is_unauthenticated(fake):
    _, client = fake
    adapter = OpenShiftRbac(_settings(), kube=client, clock=Clock())
    with pytest.raises(HTTPException) as refused:
        await adapter.resolve(Authentication(VerifiedIdentity("alice", "x", "y")))
    assert refused.value.status_code == 401


def test_local_identity_mode_cannot_use_rbac():
    assert "OAuth proxy" in _settings(ui_auth_mode="local", ui_local_user="dev").identity_problem()
    assert _settings(ui_admin_users="", ui_allowed_users="").identity_problem() is None


def test_namespace_and_issuer_defaults(tmp_path):
    ns_file = tmp_path / "namespace"
    ns_file.write_text("team-a-ui\n")
    settings = Settings(kube_namespace_path=str(ns_file), kube_api_url="https://api.c1:6443/")
    assert settings.rbac_namespace() == "team-a-ui"
    assert settings.identity_issuer() == "openshift:https://api.c1:6443"
    assert Settings(kube_namespace_path=str(tmp_path / "missing")).rbac_namespace() == "memoryhub-ui"


# --- through the HTTP app ---------------------------------------------------

@pytest.fixture
def http_app(fake, monkeypatch):
    _, client = fake
    settings = _settings()
    adapter = OpenShiftRbac(settings, kube=client, clock=Clock())
    monkeypatch.setattr(identity, "rbac_adapter_for", lambda _settings: adapter)
    recorded = AsyncMock(side_effect=lambda db, tenant, ident, refresh: MagicMock(id=f"uid-of-{ident.username}"))
    monkeypatch.setattr(authorization, "profile_for", recorded)
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = lambda: db
    yield recorded
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_http_roles_profile_and_no_token_in_logs(http_app, caplog):
    caplog.set_level(logging.DEBUG)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        admin = await http.get("/api/me", headers={"x-forwarded-user": "bob", "x-forwarded-access-token": "tok-bob"})
        again = await http.get("/api/me", headers={"x-forwarded-user": "bob", "x-forwarded-access-token": "tok-bob"})
        user = await http.get("/api/me", headers={"x-forwarded-user": "alice",
                                                 "x-forwarded-access-token": "tok-alice"})
        denied = await http.get("/api/me", headers={"x-forwarded-user": "carol",
                                                   "x-forwarded-access-token": "tok-carol"})
        forged = await http.get("/api/me", headers={"x-forwarded-user": "bob",
                                                   "x-forwarded-access-token": "tok-alice", "x-role": "admin"})
    assert admin.status_code == 200 and admin.json()["role"] == "admin"
    assert admin.json()["user_id"] == "uid-of-bob"
    assert again.status_code == 200
    assert user.json()["role"] == "user"
    assert denied.status_code == 403
    assert forged.status_code == 401
    # The profile is refreshed on a fresh verification and only read otherwise; denials never reach it.
    calls = [(call.args[2].username, call.kwargs["refresh"]) for call in http_app.await_args_list]
    assert calls == [("bob", True), ("bob", False), ("alice", True)]
    assert all("tok-" not in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_http_direct_call_to_the_app_port_is_refused(http_app):
    async with AsyncClient(transport=ASGITransport(app=app, client=("203.0.113.9", 5000)),
                           base_url="http://test") as http:
        response = await http.get("/api/me", headers={"x-forwarded-user": "bob",
                                                     "x-forwarded-access-token": "tok-bob"})
    assert response.status_code == 401
