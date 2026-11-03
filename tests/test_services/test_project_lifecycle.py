"""Project lifecycle (#671): archive, soft delete, policies, member roles."""

import uuid
from datetime import UTC, datetime

import pytest

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.services.exceptions import (
    InvalidProjectPolicyError,
    LastAdminError,
    ProjectAlreadyExistsError,
    ProjectArchivedError,
    ProjectNotProvisionedError,
    ProjectQuotaExceededError,
)
from memoryhub_core.services.project import (
    archive_project,
    create_project,
    delete_project,
    ensure_project_membership,
    get_project,
    get_projects_for_user,
    list_projects_for_tenant,
    lock_project,
    project_memory_count,
    project_write_policies,
    relevant_until_from_policies,
    unarchive_project,
    update_member_role,
    update_project,
    validate_policies,
)

T = "default"


@pytest.fixture
async def team(async_session):
    async_session.add(Project(name="team-x", created_by="ray", tenant_id=T))
    await async_session.flush()
    async_session.add_all(
        [
            ProjectMembership(id=uuid.uuid4(), project_id="team-x", user_id="carol", role="admin", joined_by="ray"),
            ProjectMembership(id=uuid.uuid4(), project_id="team-x", user_id="alice", role="member", joined_by="ray"),
        ]
    )
    await async_session.commit()


def _memory(content="decision", parent_id=None, scope_id="team-x"):
    now = datetime.now(UTC)
    mid = uuid.uuid4()
    return MemoryNode(
        id=mid, logical_id=mid, content=content, stub=content, scope="project", scope_id=scope_id,
        owner_id="team-x", tenant_id=T, status="active", weight=0.7, is_current=True, version=1,
        storage_type="inline", parent_id=parent_id, created_at=now, updated_at=now,
    )


# -- archive -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_project_refuses_writes_but_keeps_members(async_session, team):
    await archive_project(async_session, "team-x", by="carol")
    with pytest.raises(ProjectArchivedError, match="read-only"):
        await ensure_project_membership(async_session, "team-x", "alice", T, mode="central")
    assert "team-x" in await get_projects_for_user(async_session, "alice")  # still readable
    listed = await list_projects_for_tenant(async_session, T, user_id="alice")
    assert listed[0]["archived"] is True

    await unarchive_project(async_session, "team-x")
    ids, _ = await ensure_project_membership(async_session, "team-x", "alice", T, mode="central")
    assert "team-x" in ids


@pytest.mark.asyncio
async def test_archived_project_refuses_self_service_joins(async_session, team):
    await archive_project(async_session, "team-x", by="carol")
    with pytest.raises(ProjectArchivedError):
        await ensure_project_membership(async_session, "team-x", "newbie", T, mode="self_service")


# -- delete --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_soft_deletes_project_and_its_memories(async_session, team):
    root = _memory()
    async_session.add_all([root, _memory("other project", scope_id="elsewhere")])
    await async_session.flush()
    async_session.add(_memory("rationale", parent_id=root.id))
    await async_session.commit()
    assert await project_memory_count(async_session, "team-x", T) == 2

    result = await delete_project(async_session, "team-x", T, by="ray")
    assert result["memories_deleted"] == 2
    assert await project_memory_count(async_session, "team-x", T) == 0
    assert await project_memory_count(async_session, "elsewhere", T) == 1
    assert await get_project(async_session, "team-x") is None
    assert "team-x" not in await get_projects_for_user(async_session, "alice")
    assert await list_projects_for_tenant(async_session, T, user_id="alice") == []


@pytest.mark.asyncio
async def test_deleted_name_stays_reserved(async_session, team):
    await delete_project(async_session, "team-x", T, by="ray")
    with pytest.raises(ProjectAlreadyExistsError):
        await create_project(async_session, name="team-x", tenant_id=T, created_by="ray")
    with pytest.raises(ProjectNotProvisionedError):
        await ensure_project_membership(async_session, "team-x", "alice", T, mode="self_service")


# -- policies ------------------------------------------------------------------


def test_policy_validation():
    assert validate_policies({"ttl_days": 30, "max_memories": None, "default_weight": 1}) == {
        "ttl_days": 30,
        "default_weight": 1.0,
    }
    for bad in ({"ttl_days": 0}, {"ttl_days": 1.5}, {"max_memories": -1}, {"default_weight": 1.2}, {"color": "red"}):
        with pytest.raises(InvalidProjectPolicyError):
            validate_policies(bad)


@pytest.mark.asyncio
async def test_quota_counts_current_root_memories_only(async_session, team):
    await update_project(async_session, "team-x", policies={"max_memories": 2})
    root = _memory()
    async_session.add(root)
    await async_session.flush()
    async_session.add(_memory("branch", parent_id=root.id))
    await async_session.commit()
    await project_write_policies(async_session, "team-x", T)  # 1 root < 2

    async_session.add(_memory("second"))
    await async_session.commit()
    with pytest.raises(ProjectQuotaExceededError, match="limit of 2"):
        await project_write_policies(async_session, "team-x", T)
    # Branches and new versions are not new memories.
    await project_write_policies(async_session, "team-x", T, new_memory=False)


@pytest.mark.asyncio
async def test_policy_updates_merge_and_clear(async_session, team):
    await update_project(async_session, "team-x", policies={"ttl_days": 30, "default_weight": 0.5})
    project = await update_project(async_session, "team-x", policies={"ttl_days": None}, description="Team X")
    assert project.policies == {"default_weight": 0.5}
    assert project.description == "Team X"
    with pytest.raises(InvalidProjectPolicyError):
        await update_project(async_session, "team-x", policies={"ttl_days": 99999})


def test_ttl_becomes_relevant_until():
    now = datetime(2026, 11, 2, tzinfo=UTC)
    assert relevant_until_from_policies({"ttl_days": 10}, now) == datetime(2026, 11, 12, tzinfo=UTC)
    assert relevant_until_from_policies({}, now) is None


# -- roles ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_roles_keep_one_admin(async_session, team):
    assert await update_member_role(async_session, "team-x", "alice", "admin") is True
    assert await update_member_role(async_session, "team-x", "alice", "admin") is False
    assert await update_member_role(async_session, "team-x", "carol", "member") is True
    with pytest.raises(LastAdminError):
        await update_member_role(async_session, "team-x", "alice", "member")



def test_lock_project_is_select_for_update():
    """The guards lock the project row so concurrent requests take turns (#671)."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    stmt = select(Project).where(Project.name == "x").with_for_update()
    assert "FOR UPDATE" in str(stmt.compile(dialect=postgresql.dialect()))


async def test_lock_project_returns_the_row(async_session, team):
    assert (await lock_project(async_session, "team-x")).name == "team-x"
    assert await lock_project(async_session, "missing") is None
