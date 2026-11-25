"""Entitlement checks at sign-in, refresh and agent token issuance (#744).

docs/auth/human-role-resolution.md: a person (or the owner of a personal
agent) who may no longer use MemoryHub gets no new tokens; OpenShift being
unreachable is never an answer.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import src.entitlements as entitlements
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.config import settings
from src.entitlements import EntitlementUnavailableError
from src.models import AgentOwnerBinding, AuthSession, RefreshToken
from src.tokens import create_refresh_token

from tests.conftest import TEST_CLIENT_SECRET
from tests.test_authorization_code import _ready_session
from tests.test_openshift_callback import _create_pending_session


@pytest.fixture
def rbac(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("sa-token")
    monkeypatch.setattr(settings, "entitlement_mode", "openshift-rbac")
    monkeypatch.setattr(settings, "entitlement_namespace", "memoryhub-ui")
    monkeypatch.setattr(settings, "k8s_token_path", str(token))
    monkeypatch.setattr(settings, "k8s_api_server", "https://api.test")


def _fake_api(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(entitlements, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return seen


# --- the checks themselves ---------------------------------------------------

@pytest.mark.asyncio
async def test_person_may_use_asks_with_their_own_token(rbac, monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer person-token"
        assert body["spec"]["resourceAttributes"] == {
            "namespace": "memoryhub-ui", "group": "memoryhub.io", "resource": "dashboard", "verb": "use"}
        return httpx.Response(201, json={"status": {"allowed": True}})

    _fake_api(monkeypatch, handler)
    assert await entitlements.person_may_use("person-token") is True


@pytest.mark.asyncio
async def test_subject_check_resolves_groups_including_b64_members(rbac, monkeypatch):
    def handler(request):
        assert request.headers["authorization"] == "Bearer sa-token"
        if request.url.path.endswith("/groups"):
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": "admins"}, "users": ["b64:a3ViZTphZG1pbg=="]},
                {"metadata": {"name": "corp"}, "users": ["alice", "kube:admin"]},
                {"metadata": {"name": "other"}, "users": ["bob"]},
            ]})
        spec = json.loads(request.content)["spec"]
        return httpx.Response(201, json={"status": {"allowed": "corp" in spec["groups"] and spec["user"] == "alice"}})

    seen = _fake_api(monkeypatch, handler)
    assert await entitlements.groups_of("kube:admin") == ["admins", "corp"]
    assert await entitlements.subject_may_use("alice") is True
    spec = json.loads(seen[-1].content)["spec"]
    assert spec["groups"] == ["corp", "system:authenticated", "system:authenticated:oauth"]
    assert await entitlements.subject_may_use("bob") is False
    assert await entitlements.subject_may_use("system:serviceaccount:x:y") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["network", 403, 500])
async def test_unreachable_or_refusing_api_is_never_an_answer(rbac, monkeypatch, failure):
    def handler(request):
        if failure == "network":
            raise httpx.ConnectError("down")
        return httpx.Response(failure, json={})

    _fake_api(monkeypatch, handler)
    with pytest.raises(EntitlementUnavailableError):
        await entitlements.person_may_use("t")
    with pytest.raises(EntitlementUnavailableError):
        await entitlements.subject_may_use("alice")


@pytest.mark.asyncio
async def test_missing_service_account_token_is_unavailable(rbac, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "k8s_token_path", str(tmp_path / "missing"))
    with pytest.raises(EntitlementUnavailableError):
        await entitlements.subject_may_use("alice")


# --- sign-in through the broker -----------------------------------------------

@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(settings, "openshift_oauth_token_url", "https://openshift.example.com/oauth/token")
    monkeypatch.setattr(settings, "openshift_oauth_authorize_url", "https://openshift.example.com/oauth/authorize")


async def _callback(client, db_engine, *, allowed):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    pending = _create_pending_session()
    async with factory() as sess:
        sess.add(pending)
        await sess.commit()
    check = AsyncMock(side_effect=allowed) if isinstance(allowed, Exception) else AsyncMock(return_value=allowed)
    with patch("src.routes.openshift_callback._exchange_openshift_code", new=AsyncMock(return_value="os-token")), \
         patch("src.routes.openshift_callback._resolve_openshift_user", new=AsyncMock(return_value="alice")), \
         patch("src.routes.openshift_callback.person_may_use", new=check), \
         patch("src.routes.openshift_callback._check_group_membership", new=AsyncMock()) as legacy:
        resp = await client.get(f"/oauth/openshift/callback?code=c&state={pending.session_id}",
                                follow_redirects=False)
    return resp, check, legacy


@pytest.mark.asyncio
async def test_callback_admits_entitled_person_with_their_token(rbac, broker, client, sample_client, db_engine):
    resp, check, legacy = await _callback(client, db_engine, allowed=True)
    assert resp.status_code == 302
    check.assert_awaited_once_with("os-token")
    legacy.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_refuses_person_without_binding(rbac, broker, client, sample_client, db_engine):
    resp, _, _ = await _callback(client, db_engine, allowed=False)
    assert resp.status_code == 403 and resp.json()["error"] == "access_denied"


@pytest.mark.asyncio
async def test_callback_fails_closed_when_openshift_cannot_be_asked(rbac, broker, client, sample_client, db_engine):
    resp, _, _ = await _callback(client, db_engine, allowed=EntitlementUnavailableError("down"))
    assert resp.status_code == 503 and resp.json()["error"] == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_callback_keeps_legacy_group_check_when_off(broker, client, sample_client, db_engine):
    resp, check, legacy = await _callback(client, db_engine, allowed=True)
    assert resp.status_code == 302
    check.assert_not_awaited()
    legacy.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, scoped", [("openshift-rbac", True), ("off", False)])
async def test_authorize_asks_openshift_for_narrow_scopes_only_with_rbac(
        monkeypatch, broker, client, sample_client, mode, scoped):
    monkeypatch.setattr(settings, "entitlement_mode", mode)
    resp = await client.get("/authorize", params={
        "response_type": "code", "client_id": "test-agent", "redirect_uri": "https://example.com/callback",
        "state": "s", "code_challenge": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert (query.get("scope") == ["user:info user:check-access"]) is scoped


# --- refresh and agent tokens ---------------------------------------------------

async def _store_refresh(db_engine, *, subject, origin, client_id="test-agent"):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    raw, digest = create_refresh_token()
    async with factory() as sess:
        sess.add(RefreshToken(id=digest[:32], token_hash=digest, client_id=client_id, subject=subject,
                              scopes=["memory:read:user"], tenant_id="test-tenant", origin=origin,
                              expires_at=datetime.now(UTC) + timedelta(hours=1)))
        await sess.commit()
    return raw


async def _refresh(client, raw):
    return await client.post("/token", data={"grant_type": "refresh_token", "client_id": "test-agent",
                                             "client_secret": TEST_CLIENT_SECRET, "refresh_token": raw})


async def _token_row(db_engine, raw):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        return (await sess.execute(select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))).scalar_one()


@pytest.mark.asyncio
async def test_refresh_after_revocation_is_refused_without_rotating(rbac, client, sample_client, db_engine):
    raw = await _store_refresh(db_engine, subject="alice", origin="broker")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=False)) as check:
        resp = await _refresh(client, raw)
    assert resp.status_code == 401 and resp.json()["error"] == "invalid_grant"
    check.assert_awaited_once_with("alice")
    assert (await _token_row(db_engine, raw)).revoked is False


@pytest.mark.asyncio
async def test_refresh_of_entitled_person_rotates_and_keeps_origin(rbac, client, sample_client, db_engine):
    raw = await _store_refresh(db_engine, subject="alice", origin="broker")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=True)):
        resp = await _refresh(client, raw)
    assert resp.status_code == 200
    assert (await _token_row(db_engine, resp.json()["refresh_token"])).origin == "broker"
    assert (await _token_row(db_engine, raw)).revoked is True


@pytest.mark.asyncio
async def test_refresh_fails_closed_when_openshift_cannot_be_asked(rbac, client, sample_client, db_engine):
    raw = await _store_refresh(db_engine, subject="alice", origin="broker")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(side_effect=EntitlementUnavailableError("x"))):
        resp = await _refresh(client, raw)
    assert resp.status_code == 503 and resp.json()["error"] == "temporarily_unavailable"
    assert (await _token_row(db_engine, raw)).revoked is False


@pytest.mark.asyncio
async def test_refresh_is_not_checked_when_entitlements_are_off(client, sample_client, db_engine):
    raw = await _store_refresh(db_engine, subject="alice", origin="broker")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=False)) as check:
        resp = await _refresh(client, raw)
    assert resp.status_code == 200
    check.assert_not_awaited()


async def _own(db_session, owner):
    db_session.add(AgentOwnerBinding(tenant_id="test-tenant", client_id="test-agent", owner=owner))
    await db_session.commit()


async def _client_credentials(client):
    return await client.post("/token", data={"grant_type": "client_credentials", "client_id": "test-agent",
                                             "client_secret": TEST_CLIENT_SECRET})


@pytest.mark.asyncio
async def test_personal_agent_gets_no_token_once_its_owner_lost_access(rbac, client, sample_client, db_session):
    await _own(db_session, "alice")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=False)) as check:
        resp = await _client_credentials(client)
    assert resp.status_code == 403 and resp.json()["error"] == "access_denied"
    check.assert_awaited_once_with("alice")


@pytest.mark.asyncio
async def test_personal_agent_refresh_is_refused_too(rbac, client, sample_client, db_session, db_engine):
    await _own(db_session, "alice")
    raw = await _store_refresh(db_engine, subject="test-agent", origin="client")
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=False)):
        resp = await _refresh(client, raw)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_service_agent_without_owner_is_not_checked(rbac, client, sample_client, db_engine):
    with patch("src.routes.token.subject_may_use", new=AsyncMock(return_value=False)) as check:
        resp = await _client_credentials(client)
    assert resp.status_code == 200
    check.assert_not_awaited()
    assert (await _token_row(db_engine, resp.json()["refresh_token"])).origin == "client"


@pytest.mark.asyncio
async def test_broker_sign_in_issues_person_refresh_tokens(client, sample_client, db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    auth_sess, raw_code, verifier = _ready_session()
    async with factory() as sess:
        sess.add(auth_sess)
        await sess.commit()
    resp = await client.post("/token", data={
        "grant_type": "authorization_code", "client_id": "test-agent", "client_secret": TEST_CLIENT_SECRET,
        "code": raw_code, "redirect_uri": "https://example.com/callback", "code_verifier": verifier})
    assert resp.status_code == 200
    assert (await _token_row(db_engine, resp.json()["refresh_token"])).origin == "broker"
    assert isinstance(auth_sess, AuthSession)
