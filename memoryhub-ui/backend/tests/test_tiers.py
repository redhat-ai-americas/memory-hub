"""#667: three tiers — user, admin (no user-scope content), super-user (incident grants)."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src import breakglass, routes
from src.access import ADMIN_SCOPES, Access
from src.config import get_settings
from src.ui_common import Viewer, real_viewer


def _viewer(role, username="kr"):
    return Viewer(username=username, name=username, email=None, source="account", role=role)


def _request(headers):
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_roles_from_openshift_groups(monkeypatch):
    monkeypatch.setenv("MEMORYHUB_UI_SUPERUSER_USERS", "sec-lead")
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert real_viewer(_request({"X-Forwarded-User": "ann"}), s).role == "user"
        admin = _request({"X-Forwarded-User": "bob", "X-Forwarded-Groups": "memoryhub-admins"})
        assert real_viewer(admin, s).role == "admin"
        su = _request({"X-Forwarded-User": "cy", "X-Forwarded-Groups": "memoryhub-superusers"})
        assert real_viewer(su, s).role == "superuser"
        assert real_viewer(_request({"X-Forwarded-User": "sec-lead"}), s).role == "superuser"
    finally:
        get_settings.cache_clear()


def test_superuser_is_an_admin():
    su = _viewer("superuser")
    assert su.is_admin and su.can_admin and su.redacts_content and su.is_superuser
    assert not _viewer("admin").is_superuser


def test_admin_reads_every_scope_but_user():
    acc = Access(viewer=_viewer("admin"), grants=None, open_scopes=ADMIN_SCOPES)
    assert acc.hidden_scopes == ("user",)
    item = {"id": "m1", "scope": "user", "owner_id": "ann", "content_preview": "Prefers Podman"}
    assert acc.redact(dict(item))["redacted"] is True
    project = {**item, "scope": "project"}
    assert acc.redact(dict(project))["content_preview"] == "Prefers Podman"


def test_admin_moderates_only_readable_scopes():
    acc = Access(viewer=_viewer("admin"), grants=None, open_scopes=ADMIN_SCOPES)
    acc.ensure_moderatable(SimpleNamespace(scope="enterprise"))
    with pytest.raises(HTTPException) as exc:
        acc.ensure_moderatable(SimpleNamespace(scope="user"))
    assert exc.value.status_code == 403 and "super-user" in exc.value.detail


def test_superuser_grant_opens_user_scope_and_records_reveals():
    grant = {"id": "g1", "incident_ref": "INC-42", "justification": "Classified spill in a user memory"}
    state = breakglass.start_request()
    su = _viewer("superuser")
    breakglass.bind_request(su, grant, "default")
    acc = Access(viewer=su, grants=None, open_scopes=("user", *ADMIN_SCOPES), break_glass=grant)
    out = acc.redact({"id": "m1", "scope": "user", "owner_id": "ann", "content_preview": "secret"})
    assert out["content_preview"] == "secret"
    acc.redact_tree(
        [
            {"id": "m2", "scope": "user", "owner_id": "bob", "content": "x"},
            {"id": "m3", "scope": "project", "content": "y"},
        ]
    )
    assert state["reveals"] == {"m1": "ann", "m2": "bob"}  # project content is not a privacy-invasive read
    acc.ensure_moderatable(SimpleNamespace(scope="user"))


def test_superuser_without_grant_is_an_admin():
    state = breakglass.start_request()
    acc = Access(viewer=_viewer("superuser"), grants=None, open_scopes=ADMIN_SCOPES)
    assert acc.redact({"id": "m1", "scope": "user", "content_preview": "secret"})["redacted"] is True
    assert state["reveals"] == {}


@pytest.mark.asyncio
async def test_only_superusers_start_grants():
    with pytest.raises(HTTPException) as exc:
        breakglass._superuser(_viewer("admin"))
    assert exc.value.status_code == 403
    breakglass._superuser(_viewer("superuser"))


@pytest.mark.parametrize(
    "ref,ok", [("INC-1234", True), ("SEC-7", True), ("1234", False), ("INC 12", False), ("x-1", False)]
)
def test_incident_reference_format(ref, ok):
    import re

    assert bool(re.fullmatch(breakglass.DEFAULT_PATTERN, ref)) is ok


@pytest.mark.asyncio
async def test_users_change_only_their_own_rules(monkeypatch):
    monkeypatch.setattr("src.routes.viewer_from_request", lambda request, settings: _viewer("user", "ar"))
    rule = SimpleNamespace(layer="organizational", owner_id=None)

    class _Db:
        async def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: rule)

    with pytest.raises(HTTPException) as exc:
        await routes._own_rule_guard(str(uuid.uuid4()), request=None, db=_Db(), settings=get_settings())
    assert exc.value.status_code == 403 and "Organizational rules" in exc.value.detail
    rule.layer, rule.owner_id = "user", "ar"
    await routes._own_rule_guard(str(uuid.uuid4()), request=None, db=_Db(), settings=get_settings())
