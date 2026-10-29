"""Roles, sessions, sign-up policy and admin redaction."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.access import Access, Grants, readable_python
from src.accounts import hash_password, password_problems, validate_access_settings, verify_password
from src.config import Settings
from src.main import app
from src.ui_common import DEFAULT_TENANT_SETTINGS, SESSION_COOKIE, Viewer, _merge, make_session_cookie, read_session


def _request(cookie: str | None = None, headers: dict | None = None):
    req = MagicMock()
    req.cookies = {SESSION_COOKIE: cookie} if cookie else {}
    req.headers = headers or {}
    return req


def test_password_hash_roundtrip_and_policy():
    stored = hash_password("correct horse 9")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse 9", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage")
    assert password_problems("short", 12)
    assert password_problems("onlyletterslong", 12)
    assert not password_problems("letters-and-1-digit", 12)


def test_session_cookie_carries_role_and_rejects_tampering():
    settings = Settings(ui_local_accounts=True, ui_session_secret="s3cret")
    cookie = make_session_cookie("alice", settings, role="user", source="account", name="Alice")
    session = read_session(_request(cookie), settings)
    assert session and session.username == "alice" and session.role == "user"
    forged = cookie.replace("|user|", "|admin|")
    assert read_session(_request(forged), settings) is None
    # Account sessions stop working when local accounts are switched off.
    assert read_session(_request(cookie), Settings(ui_session_secret="s3cret")) is None


def test_oauth_proxy_admin_group():
    from src.ui_common import viewer_from_request

    settings = Settings(ui_admin_group="memoryhub-admins")
    admin = viewer_from_request(
        _request(headers={"x-forwarded-user": "dk", "x-forwarded-groups": "dev,memoryhub-admins"}), settings
    )
    user = viewer_from_request(_request(headers={"x-forwarded-user": "ar", "x-forwarded-groups": "dev"}), settings)
    assert admin.is_admin and admin.redacts_content and not admin.restricted
    assert user.role == "user" and user.restricted and not user.can_admin
    listed = viewer_from_request(_request(headers={"x-forwarded-user": "ops"}), Settings(ui_admin_users="ops, dk"))
    assert listed.is_admin


def test_user_read_predicate():
    visible = readable_python(Grants(identity="ar", projects={"ui"}, roles={"sre"}, campaigns=set()))
    node = lambda **k: SimpleNamespace(**{"scope_id": None, "owner_id": "x", **k})  # noqa: E731
    assert visible(node(scope="user", owner_id="ar"))
    assert not visible(node(scope="user", owner_id="someone"))
    assert visible(node(scope="project", scope_id="ui"))
    assert not visible(node(scope="project", scope_id="other"))
    assert visible(node(scope="role", scope_id="sre"))
    assert not visible(node(scope="campaign", scope_id="c1"))
    assert visible(node(scope="enterprise"))


def test_admin_redaction_hides_content_but_keeps_metadata():
    admin = Viewer(username="dk", name="dk", email=None, source="account", role="admin")
    acc = Access(viewer=admin, grants=None, open_scopes=("organizational", "enterprise"))
    item = {
        "id": "7f3a0000-0000-0000-0000-000000000c21",
        "stub": "Prefers Podman",
        "content_preview": "Prefers Podman over Docker",
        "scope": "user",
        "owner_id": "ar",
        "weight": 0.9,
        "domains": ["containers"],
        "entities": [{"id": "e1", "name": "Podman", "type": "object"}],
    }
    out = acc.redact(item)
    assert out["redacted"] is True
    assert out["content_preview"] == "Content hidden" and "Podman" not in out["stub"]
    assert out["domains"] == [] and out["entities"] == [] and out["entity_count"] == 1
    assert out["owner_id"] == "ar" and out["weight"] == 0.9
    policy = {**item, "scope": "enterprise"}
    assert acc.redact(policy)["content_preview"] == "Prefers Podman over Docker"
    nested = acc.redact_tree({"memory": item, "versions": [{"id": "v", "content": "old text"}]}, "user")
    assert nested["memory"]["content_preview"] == "Content hidden"
    assert nested["versions"][0]["content"] == "Content hidden"


def test_access_settings_validation():
    values = _merge(DEFAULT_TENANT_SETTINGS, {})
    assert validate_access_settings(values) == []
    values["privacy"]["admin_readable_scopes"] = ["user"]
    values["signup"]["mode"] = "domain"
    errors = validate_access_settings(values)
    assert any("never read user memories" in e for e in errors)
    assert any("allowed domain" in e for e in errors)


def test_ensure_readable_raises_404():
    user = Viewer(username="ar", name="ar", email=None, source="account", role="user")
    acc = Access(viewer=user, grants=Grants(identity="ar"), open_scopes=())
    with pytest.raises(HTTPException) as exc:
        acc.ensure_readable(SimpleNamespace(scope="user", scope_id=None, owner_id="someone"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_reports_operator_role_in_open_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/api/auth/status")).json()
    assert body["mode"] == "open" and body["role"] == "operator" and body["local_accounts"] is False


@pytest.mark.asyncio
async def test_signed_in_user_is_forbidden_from_admin_endpoints(monkeypatch):
    from src import ui_common

    user = Viewer(username="ar", name="ar", email=None, source="account", role="user")
    monkeypatch.setattr("src.access.viewer_from_request", lambda request, settings: user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/audit")
    assert resp.status_code == 403
    assert ui_common.SESSION_COOKIE


def test_user_sees_memories_owned_by_their_agents():
    grants = Grants(identity="kromashk", agents={"claude-code-kr"})
    visible = readable_python(grants)
    node = lambda **k: SimpleNamespace(**{"scope_id": None, **k})  # noqa: E731
    assert visible(node(scope="user", owner_id="claude-code-kr"))
    assert visible(node(scope="user", owner_id="kromashk"))
    assert not visible(node(scope="user", owner_id="someone-elses-agent"))


def test_openshift_logout_url_is_derived_from_route_host():
    from src.routes_admin import _openshift_logout_url

    req = MagicMock()
    req.headers = {"host": "memoryhub-ui-memoryhub-ui.apps.cluster-kdtc8.dyn.example.io"}
    assert _openshift_logout_url(req, Settings()) == "https://oauth-openshift.apps.cluster-kdtc8.dyn.example.io/logout"
    assert _openshift_logout_url(req, Settings(ui_oauth_logout_url="https://idp/logout")) == "https://idp/logout"
    req.headers = {"host": "localhost:5173"}
    assert _openshift_logout_url(req, Settings()) is None


@pytest.mark.asyncio
async def test_logout_clears_cookies_and_returns_login_page():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["redirect"] == "/#/login?signed_out=1"
    cookies = resp.headers.get_list("set-cookie")
    assert any(c.startswith("_oauth_proxy=") for c in cookies)
    assert any(c.startswith(f"{SESSION_COOKIE}=") for c in cookies)


@pytest.mark.asyncio
async def test_oauth_proxy_logout_is_a_post_form():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (
            await client.post("/api/auth/logout", headers={"x-forwarded-user": "kr", "host": "ui.apps.c.example.io"})
        ).json()
    assert body["method"] == "POST"
    assert body["redirect"] == "https://oauth-openshift.apps.c.example.io/logout"
    assert body["fields"] == {"then": "https://ui.apps.c.example.io/"}


def test_test_mode_switcher_overrides_viewer_only_in_test_mode():
    from src.ui_common import VIEW_AS_COOKIE, make_view_as_cookie, viewer_from_request

    on = Settings(ui_test_mode=True, ui_session_secret="k")
    cookie = make_view_as_cookie("alice", "admin", on)
    req = _request(headers={"x-forwarded-user": "kr"})
    req.cookies = {VIEW_AS_COOKIE: cookie}
    v = viewer_from_request(req, on)
    assert v.username == "alice" and v.role == "admin" and v.real_username == "kr"
    off = Settings(ui_test_mode=False, ui_session_secret="k")
    assert viewer_from_request(req, off).username == "kr"
    req.cookies = {VIEW_AS_COOKIE: cookie.replace("|admin|", "|user|")}
    assert viewer_from_request(req, on).username == "kr"


@pytest.mark.asyncio
async def test_switch_endpoint_is_hidden_outside_test_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/auth/switch")).json() == {"enabled": False, "targets": []}
        assert (await client.post("/api/auth/switch", json={"username": "a", "role": "user"})).status_code == 404


@pytest.mark.asyncio
async def test_admins_cannot_dream_over_content(monkeypatch, labs_on):
    admin = Viewer(username="dk", name="dk", email=None, source="account", role="admin")
    monkeypatch.setattr("src.access.viewer_from_request", lambda request, settings: admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/dreams/run")).status_code == 403
        assert (await client.get("/api/dreams")).status_code == 403
