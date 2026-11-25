"""Who may get MemoryHub tokens, and when sessions end (#744).

docs/auth/human-role-resolution.md. Covers, against a fake OpenShift API:
sign-in, refresh after revocation / restoration / account recreation,
personal and service agents, refresh-token reuse and maximum session age,
and the explicit end-of-sessions and block endpoints.
"""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
import pytest_asyncio
import src.entitlements as entitlements
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.config import settings
from src.models import AgentOwnerBinding, AuthSession, HumanIdentity, OAuthClient, RefreshToken
from src.tokens import create_refresh_token

from tests.conftest import TEST_CLIENT_SECRET, TEST_CLIENT_SECRET_HASH
from tests.test_authorization_code import _ready_session
from tests.test_openshift_callback import _create_pending_session

os.environ.setdefault("AUTH_ADMIN_KEY", "test-admin-key")
ADMIN = {"X-Admin-Key": "test-admin-key"}
ISSUER = "openshift:https://api.test"
TENANT = "test-tenant"


class FakeOpenShift:
    """Users (name -> uid), Groups, RoleBindings for 'use', and an outage switch."""

    def __init__(self):
        self.users = {"alice": "uid-alice", "bob": "uid-bob"}
        self.groups = {"corp": ["alice"], "other": ["bob"]}
        self.allowed_groups = {"corp"}
        self.allowed_users: set[str] = set()
        self.down = False

    def grant(self, user):
        self.allowed_users.add(user)

    def revoke_all(self):
        self.allowed_groups.clear()
        self.allowed_users.clear()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("api down")
        path = request.url.path
        if path.startswith("/apis/user.openshift.io/v1/users/"):
            name = unquote(path.rsplit("/", 1)[1])
            if name not in self.users:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"metadata": {"name": name, "uid": self.users[name]}})
        if path.endswith("/groups"):
            return httpx.Response(200, json={"items": [
                {"metadata": {"name": g}, "users": members} for g, members in self.groups.items()]})
        if path.endswith("/subjectaccessreviews"):
            spec = json.loads(request.content)["spec"]
            ok = spec["user"] in self.allowed_users or bool(set(spec["groups"]) & self.allowed_groups)
            return httpx.Response(201, json={"status": {"allowed": ok}})
        if path.endswith("/selfsubjectaccessreviews"):
            return httpx.Response(201, json={"status": {"allowed": True}})
        return httpx.Response(404, json={})


@pytest.fixture
def openshift(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("sa-token")
    monkeypatch.setattr(settings, "entitlement_mode", "openshift-rbac")
    monkeypatch.setattr(settings, "entitlement_namespace", "memoryhub-ui")
    monkeypatch.setattr(settings, "entitlement_denial", "refuse")
    monkeypatch.setattr(settings, "k8s_token_path", str(token))
    monkeypatch.setattr(settings, "k8s_api_server", "https://api.test")
    monkeypatch.setattr(settings, "identity_issuer", "")
    monkeypatch.setattr(settings, "default_tenant_id", TENANT)
    monkeypatch.setattr(settings, "openshift_oauth_token_url", "https://openshift.example.com/oauth/token")
    monkeypatch.setattr(settings, "openshift_oauth_authorize_url", "https://openshift.example.com/oauth/authorize")
    fake = FakeOpenShift()
    monkeypatch.setattr(entitlements, "_http",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return fake


@pytest_asyncio.fixture
async def db(db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def add_profile(db, username, uid, *, disabled=False):
    db.add(HumanIdentity(id=str(uuid.uuid4()), tenant_id=TENANT, issuer=ISSUER, subject=uid, username=username,
                         disabled_at=datetime.now(UTC) if disabled else None))
    await db.commit()


async def store_session(db, *, subject="alice", uid="uid-alice", origin="broker", client_id="test-agent",
                        family=None, started=None):
    raw, digest = create_refresh_token()
    now = datetime.now(UTC)
    db.add(RefreshToken(id=str(uuid.uuid4()), token_hash=digest, client_id=client_id, subject=subject,
                        scopes=["memory:read:user"], tenant_id=TENANT, origin=origin, subject_uid=uid,
                        family_id=family or str(uuid.uuid4()), family_started_at=started or now,
                        expires_at=now + timedelta(hours=1)))
    await db.commit()
    return raw


async def row(db_engine, raw):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        return (await sess.execute(select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))).scalar_one()


async def live_tokens(db_engine, **filters):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        query = select(RefreshToken).where(RefreshToken.revoked == False)  # noqa: E712
        for key, value in filters.items():
            query = query.where(getattr(RefreshToken, key) == value)
        return (await sess.execute(query)).scalars().all()


async def refresh(client, raw, client_id="test-agent"):
    return await client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id,
                                             "client_secret": TEST_CLIENT_SECRET, "refresh_token": raw})


# --- the RBAC checks themselves -----------------------------------------------

@pytest.mark.asyncio
async def test_subject_check_uses_current_groups_not_remembered_ones(openshift):
    assert await entitlements.subject_may_use("alice") is True
    openshift.groups["corp"] = []                       # removed from the group in OpenShift
    assert await entitlements.subject_may_use("alice") is False


@pytest.mark.asyncio
async def test_b64_group_members_are_decoded(openshift):
    openshift.groups = {"admins": ["b64:a3ViZTphZG1pbg=="]}
    assert await entitlements.groups_of("kube:admin") == ["admins"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["network", 403, 500])
async def test_unreachable_or_refusing_api_is_never_an_answer(openshift, monkeypatch, failure):
    def handler(request):
        if failure == "network":
            raise httpx.ConnectError("down")
        return httpx.Response(failure, json={})

    monkeypatch.setattr(entitlements, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(entitlements.EntitlementUnavailableError):
        await entitlements.person_may_use("t")
    with pytest.raises(entitlements.EntitlementUnavailableError):
        await entitlements.subject_may_use("alice")
    with pytest.raises(entitlements.EntitlementUnavailableError):
        await entitlements.openshift_user("alice")


# --- sign-in through the broker ---------------------------------------------------

async def sign_in(client, db_engine, username="alice", allowed=True):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    pending = _create_pending_session()
    async with factory() as sess:
        sess.add(pending)
        await sess.commit()
    with patch("src.routes.openshift_callback._exchange_openshift_code", new=AsyncMock(return_value="os-token")), \
         patch("src.routes.openshift_callback._resolve_openshift_user", new=AsyncMock(return_value=username)), \
         patch("src.routes.openshift_callback.person_may_use", new=AsyncMock(return_value=allowed)), \
         patch("src.routes.openshift_callback._check_group_membership", new=AsyncMock()) as legacy:
        resp = await client.get(f"/oauth/openshift/callback?code=c&state={pending.session_id}",
                                follow_redirects=False)
    async with factory() as sess:
        stored = (await sess.execute(select(AuthSession).where(
            AuthSession.session_id == pending.session_id))).scalar_one()
    return resp, stored, legacy


@pytest.mark.asyncio
async def test_sign_in_binds_the_session_to_the_account_and_records_a_profile(openshift, client, sample_client,
                                                                             db_engine, db):
    resp, stored, legacy = await sign_in(client, db_engine)
    assert resp.status_code == 302
    assert stored.subject_uid == "uid-alice"
    legacy.assert_not_awaited()
    profile = (await db.execute(select(HumanIdentity))).scalar_one()
    assert (profile.username, profile.subject, profile.issuer) == ("alice", "uid-alice", ISSUER)


@pytest.mark.asyncio
async def test_sign_in_refused_without_role(openshift, client, sample_client, db_engine):
    resp, _, _ = await sign_in(client, db_engine, allowed=False)
    assert resp.status_code == 403 and resp.json()["error"] == "access_denied"


@pytest.mark.asyncio
async def test_sign_in_fails_closed_when_openshift_is_down(openshift, client, sample_client, db_engine):
    openshift.down = True
    resp, _, _ = await sign_in(client, db_engine)
    assert resp.status_code == 503 and resp.json()["error"] == "temporarily_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_uid, disabled", [("uid-old-alice", False), ("uid-alice", True)])
async def test_sign_in_refused_for_reused_name_or_disabled_profile(openshift, client, sample_client, db_engine,
                                                                  db, profile_uid, disabled):
    await add_profile(db, "alice", profile_uid, disabled=disabled)
    resp, _, _ = await sign_in(client, db_engine)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_legacy_group_check_when_entitlements_are_off(monkeypatch, client, sample_client, db_engine):
    monkeypatch.setattr(settings, "openshift_oauth_token_url", "https://openshift.example.com/oauth/token")
    resp, stored, legacy = await sign_in(client, db_engine)
    assert resp.status_code == 302 and stored.subject_uid is None
    legacy.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, scoped", [("openshift-rbac", True), ("off", False)])
async def test_authorize_asks_openshift_for_narrow_scopes_only_with_rbac(openshift, monkeypatch, client,
                                                                        sample_client, mode, scoped):
    monkeypatch.setattr(settings, "entitlement_mode", mode)
    resp = await client.get("/authorize", params={
        "response_type": "code", "client_id": "test-agent", "redirect_uri": "https://example.com/callback",
        "state": "s", "code_challenge": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "code_challenge_method": "S256",
    }, follow_redirects=False)
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert (query.get("scope") == ["user:info user:check-access"]) is scoped


@pytest.mark.asyncio
async def test_code_exchange_starts_a_family_bound_to_the_account(client, sample_client, db_engine):
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    auth_sess, raw_code, verifier = _ready_session(subject_uid="uid-alice")
    async with factory() as sess:
        sess.add(auth_sess)
        await sess.commit()
    resp = await client.post("/token", data={
        "grant_type": "authorization_code", "client_id": "test-agent", "client_secret": TEST_CLIENT_SECRET,
        "code": raw_code, "redirect_uri": "https://example.com/callback", "code_verifier": verifier})
    token = await row(db_engine, resp.json()["refresh_token"])
    assert (token.origin, token.subject_uid) == ("broker", "uid-alice") and token.family_id


# --- refresh of a person's session ------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_rotates_within_the_family(openshift, client, sample_client, db_engine, db):
    await add_profile(db, "alice", "uid-alice")
    raw = await store_session(db, family="fam-1")
    resp = await refresh(client, raw)
    assert resp.status_code == 200
    new = await row(db_engine, resp.json()["refresh_token"])
    assert (new.family_id, new.subject_uid, new.origin) == ("fam-1", "uid-alice", "broker")


@pytest.mark.asyncio
async def test_missing_role_refuses_and_restoring_it_restores_the_session(openshift, client, sample_client,
                                                                         db_engine, db):
    await add_profile(db, "alice", "uid-alice")
    raw = await store_session(db)
    openshift.revoke_all()
    refused = await refresh(client, raw)
    assert refused.status_code == 401 and refused.json()["error"] == "invalid_grant"
    assert (await row(db_engine, raw)).revoked is False
    openshift.allowed_groups.add("corp")
    assert (await refresh(client, raw)).status_code == 200


@pytest.mark.asyncio
async def test_missing_role_with_revoke_policy_ends_the_sessions_for_good(openshift, monkeypatch, client,
                                                                         sample_client, db_engine, db):
    monkeypatch.setattr(settings, "entitlement_denial", "revoke")
    await add_profile(db, "alice", "uid-alice")
    raw = await store_session(db)
    other = await store_session(db)
    openshift.revoke_all()
    assert (await refresh(client, raw)).status_code == 401
    assert not await live_tokens(db_engine, subject="alice")
    openshift.allowed_groups.add("corp")
    assert (await refresh(client, other)).status_code == 401


@pytest.mark.asyncio
async def test_recreated_account_with_the_same_name_cannot_use_the_old_session(openshift, client, sample_client,
                                                                              db_engine, db):
    """Old refresh token -> OpenShift User deleted -> new User, same name -> refresh."""
    await add_profile(db, "alice", "uid-alice")
    raw = await store_session(db)
    second = await store_session(db)
    openshift.users["alice"] = "uid-alice-2"
    resp = await refresh(client, raw)
    assert resp.status_code == 401 and resp.json()["error"] == "invalid_grant"
    assert not await live_tokens(db_engine, subject="alice")
    assert (await refresh(client, second)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "disabled", "legacy", "no-profile", "renamed-profile"])
async def test_identity_changes_end_every_session_of_the_name(openshift, client, sample_client, db_engine, db,
                                                             change):
    if change == "disabled":
        await add_profile(db, "alice", "uid-alice", disabled=True)
    elif change == "renamed-profile":
        await add_profile(db, "alice.old", "uid-alice")
    elif change != "no-profile":
        await add_profile(db, "alice", "uid-alice")
    if change == "deleted":
        del openshift.users["alice"]
    raw = await store_session(db, uid=None if change == "legacy" else "uid-alice")
    assert (await refresh(client, raw)).status_code == 401
    assert not await live_tokens(db_engine, subject="alice")


@pytest.mark.asyncio
async def test_api_outage_is_temporary_and_revokes_nothing(openshift, client, sample_client, db_engine, db):
    await add_profile(db, "alice", "uid-alice")
    raw = await store_session(db)
    openshift.down = True
    resp = await refresh(client, raw)
    assert resp.status_code == 503 and resp.json()["error"] == "temporarily_unavailable"
    assert (await row(db_engine, raw)).revoked is False


@pytest.mark.asyncio
async def test_reuse_of_a_rotated_token_revokes_the_family(client, sample_client, db_engine, db):
    raw = await store_session(db, family="fam-x", origin="client", subject="test-agent", uid=None)
    first = await refresh(client, raw)
    assert first.status_code == 200
    replayed = await refresh(client, raw)               # the stolen copy, or the old one
    assert replayed.status_code == 401
    assert not await live_tokens(db_engine, family_id="fam-x")
    assert (await refresh(client, first.json()["refresh_token"])).status_code == 401


@pytest.mark.asyncio
async def test_session_has_an_absolute_maximum_age(monkeypatch, client, sample_client, db_engine, db):
    monkeypatch.setattr(settings, "session_max_age", 3600)
    old = await store_session(db, origin="client", subject="test-agent", uid=None,
                              started=datetime.now(UTC) - timedelta(hours=2))
    assert (await refresh(client, old)).status_code == 401
    young = await store_session(db, origin="client", subject="test-agent", uid=None,
                                started=datetime.now(UTC) - timedelta(minutes=50))
    resp = await refresh(client, young)
    assert resp.status_code == 200
    new = await row(db_engine, resp.json()["refresh_token"])
    assert new.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC) + timedelta(minutes=11)


# --- agents ---------------------------------------------------------------------------

async def own(db, owner="alice"):
    db.add(AgentOwnerBinding(tenant_id=TENANT, client_id="test-agent", owner=owner))
    await db.commit()


async def client_credentials(client, client_id="test-agent"):
    return await client.post("/token", data={"grant_type": "client_credentials", "client_id": client_id,
                                             "client_secret": TEST_CLIENT_SECRET})


@pytest.mark.asyncio
async def test_personal_agent_without_owner_is_refused(openshift, client, sample_client):
    resp = await client_credentials(client)
    assert resp.status_code == 403 and "no verified owner" in resp.json()["error_description"]


@pytest.mark.asyncio
async def test_personal_agent_of_a_verified_entitled_owner_works(openshift, client, sample_client, db):
    await add_profile(db, "alice", "uid-alice")
    await own(db)
    assert (await client_credentials(client)).status_code == 200


@pytest.mark.asyncio
async def test_personal_agent_stops_when_owner_loses_role_and_resumes_when_restored(openshift, client,
                                                                                   sample_client, db):
    await add_profile(db, "alice", "uid-alice")
    await own(db)
    openshift.revoke_all()
    assert (await client_credentials(client)).status_code == 403
    openshift.grant("alice")
    assert (await client_credentials(client)).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "recreated", "disabled", "no-profile"])
async def test_personal_agent_tokens_end_when_the_owner_identity_changes(openshift, client, sample_client,
                                                                         db_engine, db, change):
    if change != "no-profile":
        await add_profile(db, "alice", "uid-alice", disabled=change == "disabled")
    await own(db)
    raw = await store_session(db, origin="client", subject="test-agent", uid=None)
    if change == "deleted":
        del openshift.users["alice"]
    if change == "recreated":
        openshift.users["alice"] = "uid-alice-2"
    assert (await refresh(client, raw)).status_code == 403
    assert not await live_tokens(db_engine, client_id="test-agent")


@pytest.mark.asyncio
async def test_service_agent_is_team_owned_and_not_tied_to_a_person(openshift, client, db):
    db.add(OAuthClient(id=str(uuid.uuid4()), client_id="team-svc", client_secret_hash=TEST_CLIENT_SECRET_HASH,
                       client_name="Team", identity_type="service", tenant_id=TENANT,
                       default_scopes=["memory:read"], active=True, public=False,
                       created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
    await db.commit()
    openshift.revoke_all()
    assert (await client_credentials(client, "team-svc")).status_code == 200


@pytest.mark.asyncio
async def test_without_entitlements_nothing_changes_for_unowned_clients(client, sample_client):
    assert (await client_credentials(client)).status_code == 200


# --- explicit end of sessions and blocking ---------------------------------------

@pytest.mark.asyncio
async def test_end_sessions_revokes_person_and_agents_and_blocks(openshift, client, sample_client, db_engine, db):
    await add_profile(db, "alice", "uid-alice")
    await own(db)
    person = await store_session(db)
    agent = await store_session(db, origin="client", subject="test-agent", uid=None)
    resp = await client.post("/admin/people/alice/end-sessions", headers=ADMIN, json={
        "tenant_id": TENANT, "include_agents": True, "disable": True, "reason": "laptop stolen"})
    assert resp.status_code == 200
    assert resp.json() == {"username": "alice", "sessions_revoked": 1, "agent_tokens_revoked": 1,
                           "disabled": True, "profile_found": True}
    assert (await refresh(client, person)).status_code == 401
    assert (await refresh(client, agent)).status_code == 401
    assert (await client_credentials(client)).status_code == 403      # blocked owner
    assert (await sign_in(client, db_engine))[0].status_code == 403

    enabled = await client.post("/admin/people/alice/enable", headers=ADMIN, params={"tenant_id": TENANT})
    assert enabled.status_code == 200
    assert (await refresh(client, person)).status_code == 401          # revoked stays revoked
    assert (await client_credentials(client)).status_code == 200


@pytest.mark.asyncio
async def test_blocking_someone_who_never_signed_in_still_blocks_them(openshift, client, sample_client, db_engine):
    resp = await client.post("/admin/people/bob/end-sessions", headers=ADMIN, json={
        "tenant_id": TENANT, "disable": True, "reason": "offboarding"})
    assert resp.json()["disabled"] is True
    openshift.grant("bob")
    assert (await sign_in(client, db_engine, username="bob"))[0].status_code == 403


@pytest.mark.asyncio
async def test_people_endpoints_need_the_admin_key(client):
    resp = await client.post("/admin/people/alice/end-sessions", json={"tenant_id": TENANT, "reason": "xyz"})
    assert resp.status_code == 401
