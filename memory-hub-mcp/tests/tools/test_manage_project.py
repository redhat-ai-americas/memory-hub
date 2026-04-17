"""Tests for manage_project tool (#166).

Exercises the consolidated project management tool: list, create, describe,
add_member, remove_member actions. Uses monkeypatching to avoid DB access.
"""

from __future__ import annotations

import inspect

import pytest
from fastmcp.exceptions import ToolError

from src.core.authz import AuthenticationError
from src.tools.manage_project import manage_project

_CLAIMS = {"sub": "wjackson", "tenant_id": "default", "scopes": []}


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    """Provide a default authenticated session."""
    monkeypatch.setattr(
        "src.tools.manage_project.get_claims_from_context",
        lambda: _CLAIMS,
    )


# ---------------------------------------------------------------------------
# Structural / decoration tests
# ---------------------------------------------------------------------------


def test_is_decorated():
    assert hasattr(manage_project, "__fastmcp__")


def test_is_async():
    assert inspect.iscoroutinefunction(manage_project)


def test_has_action_parameter():
    sig = inspect.signature(manage_project)
    assert "action" in sig.parameters


# ---------------------------------------------------------------------------
# Validation tests (no DB needed)
# ---------------------------------------------------------------------------


class TestValidation:
    async def test_rejects_unauthenticated(self, monkeypatch):
        def raise_auth():
            raise AuthenticationError("no session")

        monkeypatch.setattr(
            "src.tools.manage_project.get_claims_from_context", raise_auth,
        )
        with pytest.raises(ToolError, match="No authenticated session"):
            await manage_project(action="list")

    async def test_rejects_invalid_action(self):
        with pytest.raises(ToolError, match="Invalid action"):
            await manage_project(action="nope")

    async def test_create_requires_project_name(self):
        with pytest.raises(ToolError, match="requires a project_name"):
            await manage_project(action="create")

    async def test_describe_requires_project_name(self):
        with pytest.raises(ToolError, match="requires a project_name"):
            await manage_project(action="describe")

    async def test_add_member_requires_project_name(self):
        with pytest.raises(ToolError, match="requires a project_name"):
            await manage_project(action="add_member", user_id="someone")

    async def test_add_member_requires_user_id(self):
        with pytest.raises(ToolError, match="requires a user_id"):
            await manage_project(action="add_member", project_name="proj")

    async def test_remove_member_requires_user_id(self):
        with pytest.raises(ToolError, match="requires a user_id"):
            await manage_project(action="remove_member", project_name="proj")

    async def test_list_rejects_invalid_filter(self):
        with pytest.raises(ToolError, match="Invalid filter value"):
            await manage_project(action="list", filter="bogus")

    async def test_add_member_rejects_invalid_role(self):
        with pytest.raises(ToolError, match="Invalid role"):
            await manage_project(
                action="add_member", project_name="p", user_id="u", role="boss",
            )


# ---------------------------------------------------------------------------
# Action handler tests (mock the DB layer)
# ---------------------------------------------------------------------------


class TestListAction:
    async def test_list_mine(self, monkeypatch):
        async def fake_list(session, tenant_id, user_id, include_all_open):
            assert not include_all_open
            return [{"name": "proj-a", "description": None, "memory_count": 5}]

        monkeypatch.setattr(
            "src.tools.manage_project.list_projects_for_tenant", fake_list,
        )
        monkeypatch.setattr(
            "src.tools.manage_project.get_db_session",
            _fake_db_session,
        )
        monkeypatch.setattr(
            "src.tools.manage_project.release_db_session",
            _fake_release,
        )

        result = await manage_project(action="list")
        assert result["total"] == 1
        assert result["projects"][0]["name"] == "proj-a"

    async def test_list_all(self, monkeypatch):
        async def fake_list(session, tenant_id, user_id, include_all_open):
            assert include_all_open
            return []

        monkeypatch.setattr(
            "src.tools.manage_project.list_projects_for_tenant", fake_list,
        )
        monkeypatch.setattr(
            "src.tools.manage_project.get_db_session", _fake_db_session,
        )
        monkeypatch.setattr(
            "src.tools.manage_project.release_db_session", _fake_release,
        )

        result = await manage_project(action="list", filter="all")
        assert result["total"] == 0


class TestCreateAction:
    async def test_create_success(self, monkeypatch):
        class FakeProject:
            name = "new-proj"
            description = "A new project"
            invite_only = False
            created_by = "wjackson"

        async def fake_create(session, name, tenant_id, created_by, description, invite_only):
            return FakeProject()

        monkeypatch.setattr("src.tools.manage_project.create_project", fake_create)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(
            action="create", project_name="new-proj", description="A new project",
        )
        assert result["project"]["name"] == "new-proj"
        assert "created" in result["message"].lower() or "Created" in result["message"]

    async def test_create_duplicate(self, monkeypatch):
        from memoryhub_core.services.exceptions import ProjectAlreadyExistsError

        async def fake_create(session, name, tenant_id, created_by, description, invite_only):
            raise ProjectAlreadyExistsError("existing")

        monkeypatch.setattr("src.tools.manage_project.create_project", fake_create)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="already exists"):
            await manage_project(action="create", project_name="existing")


class TestDescribeAction:
    async def test_describe_success(self, monkeypatch):
        from datetime import UTC, datetime

        class FakeProject:
            name = "my-proj"
            description = "Test project"
            invite_only = False
            created_at = datetime(2026, 4, 1, tzinfo=UTC)
            created_by = "admin"

        async def fake_members(session, project_name):
            return [{"user_id": "wjackson", "role": "admin", "joined_at": "2026-04-01T00:00:00+00:00"}]

        async def fake_get_project(session, name):
            return FakeProject()

        async def fake_counts(session, tenant_id, names):
            return {"my-proj": 42}

        monkeypatch.setattr("src.tools.manage_project.get_project_members", fake_members)
        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get_project)
        monkeypatch.setattr("src.tools.manage_project.memory_counts", fake_counts)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(action="describe", project_name="my-proj")
        assert result["project"]["name"] == "my-proj"
        assert result["project"]["memory_count"] == 42
        assert result["total_members"] == 1
        assert result["members"][0]["user_id"] == "wjackson"

    async def test_describe_not_found(self, monkeypatch):
        from memoryhub_core.services.exceptions import ProjectNotFoundError

        async def fake_members(session, project_name):
            raise ProjectNotFoundError(project_name)

        monkeypatch.setattr("src.tools.manage_project.get_project_members", fake_members)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="not found"):
            await manage_project(action="describe", project_name="ghost")


class TestAddMemberAction:
    async def test_add_member_open_project(self, monkeypatch):
        class FakeProject:
            invite_only = False

        class FakeMembership:
            role = "member"

        async def fake_get(session, name):
            return FakeProject()

        async def fake_add(session, name, user_id, added_by, role):
            return True

        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get)
        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.add_project_member", fake_add)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(
            action="add_member", project_name="proj", user_id="newguy",
        )
        assert "newguy" in result["message"]

    async def test_add_member_requires_caller_membership(self, monkeypatch):
        """Non-members cannot add users even to open projects."""
        class FakeProject:
            invite_only = False

        async def fake_get(session, name):
            return FakeProject()

        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get)
        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(None))
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="not a member"):
            await manage_project(
                action="add_member", project_name="proj", user_id="newguy",
            )

    async def test_add_member_invite_only_by_non_admin(self, monkeypatch):
        class FakeProject:
            invite_only = True

        class FakeMembership:
            role = "member"

        async def fake_get(session, name):
            return FakeProject()

        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get)
        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="Only project admins"):
            await manage_project(
                action="add_member", project_name="proj", user_id="newguy",
            )

    async def test_add_member_invite_only_by_admin(self, monkeypatch):
        """Admins can add members to invite-only projects."""
        class FakeProject:
            invite_only = True

        class FakeMembership:
            role = "admin"

        async def fake_get(session, name):
            return FakeProject()

        async def fake_add(session, name, user_id, added_by, role):
            return True

        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get)
        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.add_project_member", fake_add)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(
            action="add_member", project_name="proj", user_id="newguy",
        )
        assert "newguy" in result["message"]

    async def test_add_member_already_member(self, monkeypatch):
        """Adding an existing member returns an informative message."""
        class FakeProject:
            invite_only = False

        class FakeMembership:
            role = "member"

        async def fake_get(session, name):
            return FakeProject()

        async def fake_add(session, name, user_id, added_by, role):
            return False  # already a member

        monkeypatch.setattr("src.tools.manage_project.get_project", fake_get)
        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.add_project_member", fake_add)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(
            action="add_member", project_name="proj", user_id="existing",
        )
        assert "already a member" in result["message"]


class TestRemoveMemberAction:
    async def test_remove_member_success(self, monkeypatch):
        """Admin can remove another member."""
        class FakeMembership:
            role = "admin"

        async def fake_remove(session, name, user_id):
            pass

        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.remove_project_member", fake_remove)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        result = await manage_project(
            action="remove_member", project_name="proj", user_id="leaver",
        )
        assert "leaver" in result["message"]

    async def test_remove_member_requires_admin_for_others(self, monkeypatch):
        """Non-admins cannot remove other users."""
        class FakeMembership:
            role = "member"

        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="Only project admins"):
            await manage_project(
                action="remove_member", project_name="proj", user_id="other",
            )

    async def test_remove_self_allowed_for_non_admin(self, monkeypatch):
        """Users can remove themselves from a project."""
        async def fake_remove(session, name, user_id):
            pass

        monkeypatch.setattr("src.tools.manage_project.remove_project_member", fake_remove)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        # Caller is "wjackson" (from _CLAIMS), removing self
        result = await manage_project(
            action="remove_member", project_name="proj", user_id="wjackson",
        )
        assert "wjackson" in result["message"]

    async def test_remove_member_not_found(self, monkeypatch):
        """Removing a non-member raises ToolError."""
        from memoryhub_core.services.exceptions import MembershipNotFoundError

        class FakeMembership:
            role = "admin"

        async def fake_remove(session, name, user_id):
            raise MembershipNotFoundError(name, user_id)

        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.remove_project_member", fake_remove)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="not a member"):
            await manage_project(
                action="remove_member", project_name="proj", user_id="ghost",
            )

    async def test_remove_last_admin(self, monkeypatch):
        from memoryhub_core.services.exceptions import LastAdminError

        class FakeMembership:
            role = "admin"

        async def fake_remove(session, name, user_id):
            raise LastAdminError(name)

        monkeypatch.setattr("src.tools.manage_project._get_membership", _fake_return(FakeMembership()))
        monkeypatch.setattr("src.tools.manage_project.remove_project_member", fake_remove)
        monkeypatch.setattr("src.tools.manage_project.get_db_session", _fake_db_session)
        monkeypatch.setattr("src.tools.manage_project.release_db_session", _fake_release)

        with pytest.raises(ToolError, match="Cannot remove the last admin"):
            await manage_project(
                action="remove_member", project_name="proj", user_id="lastadmin",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal session stand-in that supports commit()."""
    async def commit(self):
        pass

    async def execute(self, stmt):
        return _FakeResult()


class _FakeResult:
    def scalar_one_or_none(self):
        return None


async def _fake_db_session():
    return _FakeSession(), "gen"


async def _fake_release(gen):
    pass


def _fake_return(value):
    """Return an async function that returns the given value."""
    async def _inner(*args, **kwargs):
        return value
    return _inner
