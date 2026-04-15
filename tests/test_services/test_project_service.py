"""Unit tests for the project service layer.

Tests auto-enrollment, invite-only rejection, concurrent enrollment
handling, and project listing.
"""

import uuid

import pytest

from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.services.exceptions import ProjectInviteOnlyError
from memoryhub_core.services.project import (
    ensure_project_membership,
    get_project,
    get_projects_for_user,
    list_projects_for_tenant,
)

_TENANT = "default"


@pytest.fixture
async def seed_project(async_session):
    """Create an open project with one member."""
    project = Project(name="alpha", created_by="admin", tenant_id=_TENANT)
    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id="alpha", user_id="alice", joined_by="admin",
    )
    async_session.add_all([project, membership])
    await async_session.commit()
    return project


@pytest.fixture
async def invite_only_project(async_session):
    """Create an invite-only project."""
    project = Project(
        name="secret", created_by="admin", tenant_id=_TENANT, invite_only=True,
    )
    async_session.add(project)
    await async_session.commit()
    return project


# -- get_project --


@pytest.mark.asyncio
async def test_get_project_found(async_session, seed_project):
    project = await get_project(async_session, "alpha")
    assert project is not None
    assert project.name == "alpha"
    assert project.invite_only is False


@pytest.mark.asyncio
async def test_get_project_not_found(async_session):
    project = await get_project(async_session, "nonexistent")
    assert project is None


# -- get_projects_for_user --


@pytest.mark.asyncio
async def test_get_projects_for_user_returns_set(async_session, seed_project):
    ids = await get_projects_for_user(async_session, "alice")
    assert ids == {"alpha"}


@pytest.mark.asyncio
async def test_get_projects_for_user_empty(async_session):
    ids = await get_projects_for_user(async_session, "nobody")
    assert ids == set()


# -- ensure_project_membership --


@pytest.mark.asyncio
async def test_ensure_existing_member_returns_false(async_session, seed_project):
    """Already a member — no enrollment, was_auto_enrolled=False."""
    project_ids, enrolled = await ensure_project_membership(
        async_session, "alpha", "alice", _TENANT,
    )
    assert "alpha" in project_ids
    assert enrolled is False


@pytest.mark.asyncio
async def test_ensure_auto_enrolls_in_open_project(async_session, seed_project):
    """Project exists and is open — auto-enroll a new user."""
    project_ids, enrolled = await ensure_project_membership(
        async_session, "alpha", "bob", _TENANT,
    )
    assert "alpha" in project_ids
    assert enrolled is True

    # Verify the membership was persisted.
    ids = await get_projects_for_user(async_session, "bob")
    assert "alpha" in ids


@pytest.mark.asyncio
async def test_ensure_creates_project_and_enrolls(async_session):
    """Project does not exist — create it and enroll the user."""
    project_ids, enrolled = await ensure_project_membership(
        async_session, "new-proj", "carol", _TENANT,
    )
    assert "new-proj" in project_ids
    assert enrolled is True

    # Verify project was created with correct defaults.
    project = await get_project(async_session, "new-proj")
    assert project is not None
    assert project.invite_only is False
    assert project.created_by == "carol"
    assert project.tenant_id == _TENANT


@pytest.mark.asyncio
async def test_ensure_rejects_invite_only_project(async_session, invite_only_project):
    """Invite-only project — raise ProjectInviteOnlyError."""
    with pytest.raises(ProjectInviteOnlyError) as exc_info:
        await ensure_project_membership(
            async_session, "secret", "dave", _TENANT,
        )
    assert exc_info.value.project_id == "secret"
    assert "invitation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_ensure_idempotent_double_call(async_session, seed_project):
    """Calling ensure twice for the same user/project is safe."""
    _, enrolled1 = await ensure_project_membership(
        async_session, "alpha", "eve", _TENANT,
    )
    assert enrolled1 is True

    _, enrolled2 = await ensure_project_membership(
        async_session, "alpha", "eve", _TENANT,
    )
    assert enrolled2 is False  # Already a member on second call.


@pytest.mark.asyncio
async def test_ensure_records_auto_enroll_joined_by(async_session, seed_project):
    """The joined_by field should be 'auto-enroll' for auto-enrolled members."""
    await ensure_project_membership(async_session, "alpha", "frank", _TENANT)

    from sqlalchemy import select
    stmt = (
        select(ProjectMembership)
        .where(ProjectMembership.project_id == "alpha")
        .where(ProjectMembership.user_id == "frank")
    )
    result = await async_session.execute(stmt)
    membership = result.scalar_one()
    assert membership.joined_by == "auto-enroll"


# -- list_projects_for_tenant --


@pytest.mark.asyncio
async def test_list_mine_returns_user_projects(async_session, seed_project):
    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="alice",
    )
    assert len(projects) == 1
    assert projects[0]["name"] == "alpha"
    assert projects[0]["is_member"] is True


@pytest.mark.asyncio
async def test_list_mine_empty_for_non_member(async_session, seed_project):
    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="nobody",
    )
    assert projects == []


@pytest.mark.asyncio
async def test_list_all_open_includes_open_projects(async_session, seed_project):
    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="nobody", include_all_open=True,
    )
    assert len(projects) == 1
    assert projects[0]["name"] == "alpha"
    assert projects[0]["is_member"] is False


@pytest.mark.asyncio
async def test_list_all_open_hides_invite_only_for_non_member(
    async_session, seed_project, invite_only_project,
):
    """Non-members should not see invite-only projects in 'all' mode."""
    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="nobody", include_all_open=True,
    )
    names = {p["name"] for p in projects}
    assert "alpha" in names
    assert "secret" not in names


@pytest.mark.asyncio
async def test_list_all_open_shows_invite_only_for_member(async_session, invite_only_project):
    """Members of invite-only projects should see them in 'all' mode."""
    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id="secret", user_id="insider", joined_by="admin",
    )
    async_session.add(membership)
    await async_session.commit()

    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="insider", include_all_open=True,
    )
    names = {p["name"] for p in projects}
    assert "secret" in names


@pytest.mark.asyncio
async def test_list_no_user_id_returns_empty(async_session, seed_project):
    projects = await list_projects_for_tenant(async_session, _TENANT)
    assert projects == []


@pytest.mark.asyncio
async def test_list_cross_tenant_excluded(async_session):
    """Projects in a different tenant should not appear."""
    project = Project(name="other-tenant-proj", created_by="admin", tenant_id="other")
    async_session.add(project)
    await async_session.commit()

    projects = await list_projects_for_tenant(
        async_session, _TENANT, user_id="alice", include_all_open=True,
    )
    names = {p["name"] for p in projects}
    assert "other-tenant-proj" not in names
