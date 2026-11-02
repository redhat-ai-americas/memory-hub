"""Central project provisioning: writing to a project never creates or joins it."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.services.exceptions import (
    ProjectMembershipRequiredError,
    ProjectNotProvisionedError,
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
