"""Regression tests for issue #514's project-membership checks.

Verify that list_memory and search_memory enforce explicit-project membership
for user and service identities, regardless of project isolation. Also cover
the no-project fallback when claims omit project memberships.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from memoryhub_core.services.exceptions import MembershipNotFoundError


def _project_tool_claims(identity_type="user"):
    return {
        "sub": "dr_bob",
        "identity_type": identity_type,
        "tenant_id": "default",
        "scopes": ["memory:read:user", "memory:read:project"],
        # Explicit project_id must be validated by the helper, not this claim.
        "project_memberships": [],
    }

class TestListProjectMembershipValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "identity_type,isolation_enabled",
        [
            pytest.param("user", True, id="user-isolation-on"),
            pytest.param("user", False, id="user-isolation-off"),
            pytest.param("service", True, id="service-isolation-on"),
            pytest.param("service", False, id="service-isolation-off"),
        ],
    )
    async def test_list_project_non_member_is_rejected(
        self, identity_type, isolation_enabled
    ):
        from src.tools.list_memory import list_memory

        claims = _project_tool_claims(identity_type)
        project_session, project_gen = AsyncMock(), AsyncMock()

        with (
            patch("src.tools.list_memory.get_claims_from_context", return_value=claims),
            patch(
                "src.tools.list_memory.get_db_session",
                new_callable=AsyncMock,
                return_value=(project_session, project_gen),
            ),
            patch("src.tools.list_memory.release_db_session", new_callable=AsyncMock),
            patch(
                "src.tools.list_memory.assert_project_membership",
                new_callable=AsyncMock,
                side_effect=MembershipNotFoundError("all_doctors", "dr_bob"),
            ) as mock_membership,
            patch(
                "src.tools.list_memory.get_campaigns_for_project",
                new_callable=AsyncMock,
            ) as mock_campaigns,
            patch(
                "src.tools.list_memory.list_memories",
                new_callable=AsyncMock,
            ) as mock_list,
            patch(
                "src.tools.list_memory.PROJECT_ISOLATION_ENABLED",
                isolation_enabled,
            ),
            patch("src.tools.list_memory.ROLE_ISOLATION_ENABLED", False),
            patch("src.tools.list_memory.resolve_tenant", return_value="default"),
            pytest.raises(ToolError, match="Not authorized"),
        ):
            await list_memory(scope="project", project_id="all_doctors")

        mock_membership.assert_awaited_once_with(
            project_session, "dr_bob", "all_doctors", "default"
        )
        mock_campaigns.assert_not_awaited()
        mock_list.assert_not_awaited()


class TestSearchProjectMembershipValidation:
    """Explicit project searches require membership before data lookup."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "isolation_enabled, expected_project_ids",
        [
            pytest.param(True, {"all_doctors"}, id="isolation_enabled"),
            pytest.param(False, None, id="isolation_disabled")
        ],
    )
    async def test_member_explicit_project_passes_filters(
        self, isolation_enabled, expected_project_ids
    ):
        from src.tools.search_memory import search_memory

        claims = _project_tool_claims()
        project_session, search_session = AsyncMock(), AsyncMock()
        project_gen, search_gen = AsyncMock(), AsyncMock()

        with (
            patch(
                "src.tools.search_memory.get_claims_from_context",
                return_value=claims,
            ),
            patch(
                "src.tools.search_memory.get_db_session",
                new_callable=AsyncMock,
                side_effect=[
                    (project_session, project_gen),
                    (search_session, search_gen),
                ],
            ),
            patch(
                "src.tools.search_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.search_memory.assert_project_membership",
                new_callable=AsyncMock,
            ) as mock_membership,
            patch(
                "src.tools.search_memory.get_campaigns_for_project",
                new_callable=AsyncMock,
                return_value={"campaign-1"},
            ) as mock_campaigns,
            patch(
                "src.tools.search_memory.build_authorized_scopes",
                return_value={},
            ),
            patch(
                "src.tools.search_memory.PROJECT_ISOLATION_ENABLED",
                isolation_enabled,
            ),
            patch("src.tools.search_memory.ROLE_ISOLATION_ENABLED", False),
            patch("src.tools.search_memory.resolve_tenant", return_value="default"),
            patch(
                "src.tools.search_memory.get_embedding_service",
                return_value=AsyncMock(),
            ),
            patch(
                "src.tools.search_memory.get_reranker_service",
                return_value=MagicMock(),
            ),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_search,
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.tools.search_memory.detect_patterns",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.tools.search_memory.get_valkey_client", return_value=AsyncMock()),
            patch(
                "src.tools.search_memory.record_audit_event",
                new_callable=AsyncMock,
            ),
        ):
            await search_memory(
                query="example",
                scope="project",
                project_id="all_doctors",
            )

        mock_membership.assert_awaited_once_with(
            project_session, "dr_bob", "all_doctors", "default"
        )
        mock_campaigns.assert_awaited_once_with(
            project_session, "all_doctors", "default"
        )
        kwargs = mock_search.await_args.kwargs
        assert kwargs["project_ids"] == expected_project_ids
        assert kwargs["campaign_ids"] == {"campaign-1"}


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "identity_type,isolation_enabled",
        [
            pytest.param("user", True, id="user-isolation-on"),
            pytest.param("user", False, id="user-isolation-off"),
            pytest.param("service", True, id="service-isolation-on"),
            pytest.param("service", False, id="service-isolation-off"),
        ],
    )
    async def test_non_member_explicit_project_is_rejected(
        self, identity_type, isolation_enabled
    ):
        from src.tools.search_memory import search_memory

        claims = _project_tool_claims(identity_type)
        project_session, project_gen = AsyncMock(), AsyncMock()

        with (
            patch(
                "src.tools.search_memory.get_claims_from_context",
                return_value=claims,
            ),
            patch(
                "src.tools.search_memory.get_db_session",
                new_callable=AsyncMock,
                return_value=(project_session, project_gen),
            ),
            patch(
                "src.tools.search_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.search_memory.assert_project_membership",
                new_callable=AsyncMock,
                side_effect=MembershipNotFoundError("all_doctors", "dr_bob"),
            ) as mock_membership,
            patch(
                "src.tools.search_memory.get_campaigns_for_project",
                new_callable=AsyncMock,
            ) as mock_campaigns,
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
            ) as mock_search,
            patch(
                "src.tools.search_memory.PROJECT_ISOLATION_ENABLED",
                isolation_enabled,
            ),
            patch("src.tools.search_memory.resolve_tenant", return_value="default"),
            pytest.raises(ToolError, match="Not authorized"),
        ):
            await search_memory(
                query="example",
                scope="project",
                project_id="all_doctors",
            )

        mock_membership.assert_awaited_once_with(
            project_session, "dr_bob", "all_doctors", "default"
        )
        mock_campaigns.assert_not_awaited()
        mock_search.assert_not_awaited()

class TestListProjectMembershipFallback:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "isolation_enabled",
        [
            pytest.param(True, id="isolation-on"),
            pytest.param(False, id="isolation-off"),
        ],
    )
    async def test_list_without_project_id_respects_isolation(
        self, isolation_enabled
    ):
        from src.tools.list_memory import list_memory

        claims = _project_tool_claims()
        membership_session, list_session = AsyncMock(), AsyncMock()
        membership_gen, list_gen = AsyncMock(), AsyncMock()

        sessions = [(list_session, list_gen)]
        if isolation_enabled:
            sessions.insert(0, (membership_session, membership_gen))

        with (
            patch(
                "src.tools.list_memory.get_claims_from_context",
                return_value=claims,
            ),
            patch(
                "src.tools.list_memory.get_db_session",
                new_callable=AsyncMock,
                side_effect=sessions,
            ),
            patch(
                "src.tools.list_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.list_memory.get_projects_for_user_in_tenant",
                new_callable=AsyncMock,
                return_value={"alpha"},
            ) as mock_projects,
            patch(
                "src.tools.list_memory.build_authorized_scopes",
                return_value={},
            ) as mock_authorized,
            patch(
                "src.tools.list_memory.list_memories",
                new_callable=AsyncMock,
                return_value=([], None),
            ) as mock_list,
            patch(
                "src.tools.list_memory.PROJECT_ISOLATION_ENABLED",
                isolation_enabled,
            ),
            patch("src.tools.list_memory.ROLE_ISOLATION_ENABLED", False),
            patch(
                "src.tools.list_memory.resolve_tenant",
                return_value="default",
            ),
        ):
            await list_memory(scope="project")

        kwargs = mock_list.await_args.kwargs
        expected_owner_id = None if isolation_enabled else "dr_bob"
        assert kwargs["owner_id"] == expected_owner_id
        if isolation_enabled:
            mock_projects.assert_awaited_once_with(
                membership_session, "dr_bob", "default",
            )
            assert kwargs["project_ids"] == {"alpha"}
            effective_claims = mock_authorized.call_args.args[0]
            assert effective_claims["project_memberships"] == ["alpha"]
        else:
            mock_projects.assert_not_awaited()
            assert kwargs["project_ids"] is None

class TestSearchProjectMembershipFallback:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "isolation_enabled",
        [
            pytest.param(True, id="isolation-on"),
            pytest.param(False, id="isolation-off"),
        ],
    )
    async def test_search_without_project_id_respects_isolation(
        self, isolation_enabled
    ):
        from src.tools.search_memory import search_memory

        claims = _project_tool_claims()
        membership_session, search_session = AsyncMock(), AsyncMock()
        membership_gen, search_gen = AsyncMock(), AsyncMock()

        sessions = [(search_session, search_gen)]
        if isolation_enabled:
            sessions.insert(0, (membership_session, membership_gen))

        with (
            patch(
                "src.tools.search_memory.get_claims_from_context",
                return_value=claims,
            ),
            patch(
                "src.tools.search_memory.get_db_session",
                new_callable=AsyncMock,
                side_effect=sessions,
            ),
            patch(
                "src.tools.search_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.search_memory.get_projects_for_user_in_tenant",
                new_callable=AsyncMock,
                return_value={"alpha"},
            ) as mock_projects,
            patch(
                "src.tools.search_memory.build_authorized_scopes",
                return_value={},
            ) as mock_authorized,
            patch(
                "src.tools.search_memory.PROJECT_ISOLATION_ENABLED",
                isolation_enabled,
            ),
            patch("src.tools.search_memory.ROLE_ISOLATION_ENABLED", False),
            patch(
                "src.tools.search_memory.resolve_tenant",
                return_value="default",
            ),
            patch(
                "src.tools.search_memory.get_embedding_service",
                return_value=AsyncMock(),
            ),
            patch(
                "src.tools.search_memory.get_reranker_service",
                return_value=MagicMock(),
            ),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_search,
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.tools.search_memory.detect_patterns",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.tools.search_memory.get_valkey_client",
                return_value=AsyncMock(),
            ),
            patch(
                "src.tools.search_memory.record_audit_event",
                new_callable=AsyncMock,
            ),
        ):
            await search_memory(query="example", scope="project")

        kwargs = mock_search.await_args.kwargs
        assert kwargs["owner_id"] == "dr_bob"

        if isolation_enabled:
            mock_projects.assert_awaited_once_with(
                membership_session, "dr_bob", "default"
            )
            assert kwargs["project_ids"] == {"alpha"}
            effective_claims = mock_authorized.call_args.args[0]
            assert effective_claims["project_memberships"] == ["alpha"]
        else:
            mock_projects.assert_not_awaited()
            assert kwargs["project_ids"] is None
