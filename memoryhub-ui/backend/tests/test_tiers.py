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
    monkeypatch.setenv("MEMORYHUB_UI_TRUST_PROXY_HEADERS", "true")
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


# --- #671 / #676: central project provisioning in the dashboard ------------


def test_central_provisioning_is_the_default():
    from src.config import Settings
    from src.routes_admin import _can_create_projects, _central

    central = Settings()
    assert _central(central)
    assert _can_create_projects(_viewer("admin"), central)
    assert _can_create_projects(_viewer("superuser"), central)
    assert not _can_create_projects(_viewer("user"), central)
    open_mode = Settings(project_provisioning="self_service")
    assert not _central(open_mode)
    assert _can_create_projects(_viewer("user"), open_mode)
    anon = Viewer(username="dashboard", name="d", email=None, source="anonymous", role="user")
    assert not _can_create_projects(anon, open_mode)


@pytest.mark.asyncio
async def test_project_admin_rights(monkeypatch):
    from src import routes_admin

    project = SimpleNamespace(name="team-x", invite_only=False)
    roles = {"carol": "admin", "alice": "member"}

    async def fake_role(db, name, user):
        return roles.get(user)

    monkeypatch.setattr(routes_admin, "_project_role", fake_role)
    await routes_admin._require_project_admin(None, _viewer("user", "carol"), project)
    await routes_admin._require_project_admin(None, _viewer("admin", "ray"), project)
    with pytest.raises(HTTPException) as exc:
        await routes_admin._require_project_admin(None, _viewer("user", "alice"), project)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_leads_cannot_hand_out_project_access(monkeypatch):
    """Adding someone to a linked team grants its projects: needs a project admin (#676)."""
    from src import teams
    from src.config import Settings

    class _Db:
        async def execute(self, *a, **k):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["team-z"]))

    granted = []

    async def fake_grant(db, viewer, tenant_id, project):
        granted.append(project)
        raise HTTPException(status_code=403, detail=f"Only an admin of {project} can give a team access to it")

    monkeypatch.setattr(teams, "_can_grant_project", fake_grant)
    with pytest.raises(HTTPException):
        await teams._can_grant_linked_projects(_Db(), _viewer("user", "lead"), Settings(), uuid.uuid4())
    assert granted == ["team-z"]
    # Platform admins and self-service deployments are not limited.
    await teams._can_grant_linked_projects(_Db(), _viewer("admin"), Settings(), uuid.uuid4())
    await teams._can_grant_linked_projects(
        _Db(), _viewer("user"), Settings(project_provisioning="self_service"), uuid.uuid4()
    )


# --- #671: project lifecycle and who deletes memories ------------------------


def _node(**kw):
    base = dict(scope="project", scope_id="team-x", owner_id="team-x", actor_id="bob-agent", driver_id="bob")
    base.update(kw)
    return SimpleNamespace(**base)


def test_authors_and_project_admins_delete_memories():
    me = {"alice", "alice-agent"}
    # Written by alice's agent into the shared project: hers to delete.
    assert routes.may_forget(me, set(), _node(actor_id="alice-agent", driver_id=None))
    # Written by bob: alice may read it, not delete it for the whole team...
    assert not routes.may_forget(me, set(), _node())
    # ...unless she administers the project.
    assert routes.may_forget(me, {"team-x"}, _node())
    assert not routes.may_forget(me, {"other"}, _node())
    # The author of the first version counts, not whoever edited last.
    assert routes.may_forget(me, set(), _node(), author=_node(actor_id="alice", driver_id="alice"))
    assert not routes.may_forget(me, set(), _node(actor_id="alice"), author=_node())
    # Own user-scope memories, whoever wrote them on her behalf.
    assert routes.may_forget(me, set(), _node(scope="user", scope_id=None, owner_id="alice", actor_id="svc"))
    # A project memory owned by the project name is not "owned" by a member called like it.
    assert not routes.may_forget({"team-x"}, set(), _node(actor_id="x", driver_id=None))


@pytest.mark.asyncio
async def test_forgetting_someone_elses_memory_is_refused(monkeypatch):
    async def first(db, tenant_id, node):
        return node

    async def admin_of(db, identities):
        return set()

    monkeypatch.setattr(routes, "first_version", first)
    monkeypatch.setattr(routes, "admin_projects", admin_of)
    grants = SimpleNamespace(identities={"alice"})
    with pytest.raises(HTTPException) as exc:
        await routes.ensure_forgettable(None, "default", grants, _node())
    assert exc.value.status_code == 403
    assert "admin of team-x" in exc.value.detail
    with pytest.raises(HTTPException):
        await routes.ensure_forgettable(None, "default", grants, _node(scope="organizational", scope_id=None))
    await routes.ensure_forgettable(None, "default", grants, _node(actor_id="alice"))


def test_archived_projects_are_read_only():
    from datetime import UTC, datetime

    from src.routes_admin import _lifecycle, _require_writable

    live = SimpleNamespace(name="a", archived_at=None, archived_by=None, policies=None)
    _require_writable(live)
    assert _lifecycle(live) == {"archived": False, "archived_at": None, "archived_by": None, "policies": {}}
    archived = SimpleNamespace(name="a", archived_at=datetime.now(UTC), archived_by="carol", policies={"ttl_days": 30})
    with pytest.raises(HTTPException) as exc:
        _require_writable(archived)
    assert exc.value.status_code == 409
    assert _lifecycle(archived)["archived"] is True


@pytest.mark.asyncio
async def test_only_platform_admins_delete_projects(monkeypatch):
    from src import routes_admin
    from src.config import Settings

    project = SimpleNamespace(name="team-x", tenant_id="default", archived_at=None)

    async def load(db, settings, name):
        return project

    monkeypatch.setattr(routes_admin, "_load_project", load)
    monkeypatch.setattr(routes_admin, "viewer_from_request", lambda request, settings: _viewer("user", "carol"))
    body = routes_admin.ProjectDeleteRequest(confirm="team-x")
    with pytest.raises(HTTPException) as exc:
        await routes_admin.delete_project("team-x", body, None, None, Settings())
    assert exc.value.status_code == 403
    assert "Archive it" in exc.value.detail
    monkeypatch.setattr(routes_admin, "viewer_from_request", lambda request, settings: _viewer("admin", "ray"))
    with pytest.raises(HTTPException) as exc:
        wrong = routes_admin.ProjectDeleteRequest(confirm="team")
        await routes_admin.delete_project("team-x", wrong, None, None, Settings())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_project_write_refusals_say_why(monkeypatch):
    """No project vs not a member: different errors, each with the next step (#676)."""
    from src import authz, routes_dashboard
    from src.config import Settings

    async def acc(db, settings, viewer):
        return SimpleNamespace(grants=SimpleNamespace(identities={"alice"}, projects=set()))

    monkeypatch.setattr(routes_dashboard, "access_for", acc)
    monkeypatch.setattr(authz, "person_can_write", lambda *a, **k: False)

    class _Db:
        def __init__(self, found):
            self.found = found

        async def execute(self, *a, **k):
            return SimpleNamespace(scalar_one_or_none=lambda: self.found)

    alice = _viewer("user", "alice")
    with pytest.raises(HTTPException) as exc:
        await routes_dashboard._writable_scope(_Db(None), Settings(), alice, "project", "ghost")
    assert exc.value.status_code == 404 and "does not exist" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await routes_dashboard._writable_scope(_Db("team-x"), Settings(), alice, "project", "team-x")
    assert exc.value.status_code == 403 and "not a member of team-x" in exc.value.detail
