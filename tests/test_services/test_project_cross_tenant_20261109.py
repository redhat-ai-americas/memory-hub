"""QA 2026-11-09 RT-XT-01/05: project membership and lookups are tenant-bound."""

import uuid

import pytest

from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.services.exceptions import ProjectNotFoundError, ProjectNotProvisionedError
from memoryhub_core.services.project import (
    add_project_member,
    ensure_project_membership,
    get_project,
)


@pytest.fixture
async def foreign_member(async_session):
    """Project of tenant-a that (wrongly) lists an identity of tenant-b as member."""
    async_session.add_all(
        [
            Project(name="a-proj", created_by="a-admin", tenant_id="tenant-a", invite_only=True),
            ProjectMembership(id=uuid.uuid4(), project_id="a-proj", user_id="b-agent", joined_by="a-admin"),
            ProjectMembership(id=uuid.uuid4(), project_id="a-proj", user_id="a-agent", joined_by="a-admin"),
        ]
    )
    await async_session.commit()


async def test_write_fast_path_ignores_membership_in_other_tenant(async_session, foreign_member):
    with pytest.raises(ProjectNotProvisionedError):
        await ensure_project_membership(async_session, "a-proj", "b-agent", "tenant-b")


async def test_write_fast_path_still_accepts_member_of_own_tenant(async_session, foreign_member):
    ids, enrolled = await ensure_project_membership(async_session, "a-proj", "a-agent", "tenant-a")
    assert "a-proj" in ids and enrolled is False


async def test_get_project_with_tenant_hides_foreign_project(async_session, foreign_member):
    assert await get_project(async_session, "a-proj", tenant_id="tenant-b") is None
    assert (await get_project(async_session, "a-proj", tenant_id="tenant-a")).name == "a-proj"


async def test_add_member_with_tenant_refuses_foreign_project(async_session, foreign_member):
    with pytest.raises(ProjectNotFoundError):
        await add_project_member(async_session, "a-proj", "intruder", added_by="b-admin", tenant_id="tenant-b")
