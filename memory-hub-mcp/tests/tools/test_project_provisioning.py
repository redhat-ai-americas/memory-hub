"""Central project provisioning: writing to a project never creates or joins it."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.services.exceptions import (
    ProjectArchivedError,
    ProjectMembershipRequiredError,
    ProjectNotProvisionedError,
    ProjectQuotaExceededError,
)

_CLAIMS = {
    "sub": "kate",
    "identity_type": "user",
    "tenant_id": "default",
    "scopes": ["memory:write:project", "memory:read:project"],
    "project_memberships": [],
}


async def _db():
    return (AsyncMock(), AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected",
    [
        (ProjectNotProvisionedError("my-app-2"), "does not exist"),
        (ProjectMembershipRequiredError("my-app"), "not a member"),
    ],
)
async def test_write_to_unprovisioned_project_explains_what_to_do(error, expected):
    from src.tools.write_memory import write_memory

    create = AsyncMock()
    with (
        patch("src.tools.write_memory.get_claims_from_context", return_value=_CLAIMS),
        patch("src.tools.write_memory.get_db_session", side_effect=_db),
        patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.write_memory.get_embedding_service", return_value=MagicMock(max_tokens=8192)),
        patch("src.tools.write_memory.create_memory", create),
        patch("src.tools.write_memory.ensure_project_membership", new_callable=AsyncMock, side_effect=error),
        patch("src.tools.write_memory.PROJECT_ISOLATION_ENABLED", True),
        patch("src.tools.write_memory.ROLE_ISOLATION_ENABLED", False),
        patch("src.tools.write_memory.authorize_write", return_value=True),
        patch("src.tools.write_memory.resolve_tenant", return_value="default"),
        pytest.raises(ToolError, match=expected),
    ):
        await write_memory(
            content="team decision", scope="project", project_id="my-app-2", content_type="experiential"
        )
    create.assert_not_called()


def _patches(create, policies=None, policy_error=None):
    return [
        patch("src.tools.write_memory.get_claims_from_context", return_value=_CLAIMS),
        patch("src.tools.write_memory.get_db_session", side_effect=_db),
        patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.write_memory.get_embedding_service", return_value=MagicMock(max_tokens=8192)),
        patch("src.tools.write_memory.create_memory", create),
        patch("src.tools.write_memory.broadcast_after_write", new_callable=AsyncMock),
        patch(
            "src.tools.write_memory.ensure_project_membership",
            new_callable=AsyncMock,
            return_value=({"team-x"}, False),
        ),
        patch(
            "src.tools.write_memory.project_write_policies",
            new_callable=AsyncMock,
            return_value=policies or {},
            side_effect=policy_error,
        ),
        patch("src.tools.write_memory.PROJECT_ISOLATION_ENABLED", True),
        patch("src.tools.write_memory.ROLE_ISOLATION_ENABLED", False),
        patch("src.tools.write_memory.authorize_write", return_value=True),
        patch("src.tools.write_memory.resolve_tenant", return_value="default"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected",
    [
        (ProjectArchivedError("team-x"), "archived and read-only"),
        (ProjectQuotaExceededError("team-x", 100), "limit of 100"),
    ],
)
async def test_archived_and_full_projects_refuse_writes(error, expected):
    from contextlib import ExitStack

    from src.tools.write_memory import write_memory

    create = AsyncMock()
    with ExitStack() as stack:
        for p in _patches(create, policy_error=error):
            stack.enter_context(p)
        with pytest.raises(ToolError, match=expected):
            await write_memory(content="x", scope="project", project_id="team-x", content_type="experiential")
    create.assert_not_called()


@pytest.mark.asyncio
async def test_project_policies_shape_the_write():
    from contextlib import ExitStack
    from datetime import UTC, datetime, timedelta

    from src.tools.write_memory import write_memory

    create = AsyncMock(side_effect=RuntimeError("stop after create"))
    with ExitStack() as stack:
        for p in _patches(create, policies={"ttl_days": 30, "default_weight": 0.4}):
            stack.enter_context(p)
        with pytest.raises(Exception):  # noqa: B017 - we only inspect what create_memory received
            await write_memory(content="x", scope="project", project_id="team-x", content_type="experiential")
    data = create.await_args.args[0]
    assert data.weight == 0.4
    assert abs((data.relevant_until - datetime.now(UTC)) - timedelta(days=30)) < timedelta(minutes=1)
