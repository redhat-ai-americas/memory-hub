"""Tests for project-scope visibility bugfixes.

Covers three fixes from BUGFIX-project-scope-visibility.md:

1. Bug 1 — Stale session claims after auto-enrollment (write_memory.py):
   After ensure_project_membership() auto-enrolls a user, the in-memory
   session claims must be updated so subsequent list/search calls see
   the new project without re-registering.

2. Bug 2 — owner_id filter blocking cross-user project visibility:
   a) list_memory.py: passes owner_id=None for project-scoped queries
   b) memory.py _build_search_filters: skips owner_id filter when
      scope="project" and project_ids is set
"""

import datetime as _dt
import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.tools.auth as auth_mod
from memoryhub_core.models.schemas import (
    MemoryNodeRead,
    MemoryScope,
    StorageType,
)


def _fake_project_node(
    content: str,
    owner_id: str = "dr_bob",
    scope_id: str = "all_doctors",
    weight: float = 0.8,
):
    """Build a MemoryNodeRead with scope=project for test fixtures."""
    return MemoryNodeRead(
        id=_uuid.uuid4(),
        parent_id=None,
        content=content,
        stub=content[:80],
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=weight,
        scope=MemoryScope.PROJECT,
        branch_type=None,
        owner_id=owner_id,
        tenant_id="default",
        scope_id=scope_id,
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=_dt.datetime.now(_dt.UTC),
        updated_at=_dt.datetime.now(_dt.UTC),
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
    )


# ---------------------------------------------------------------------------
# Bug 1 — Session claims updated after auto-enrollment
# ---------------------------------------------------------------------------


class TestAutoEnrollmentClaimsUpdate:
    """write_memory must update in-memory session claims after auto-enrollment."""

    @pytest.mark.asyncio
    async def test_session_claims_updated_after_auto_enrollment(self):
        """After ensure_project_membership auto-enrolls, the session's
        project_memberships list must include the new project."""
        from src.tools.write_memory import write_memory

        fake_node = _fake_project_node("test memory", owner_id="wjackson")
        fake_curation = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }
        fake_claims = {
            "sub": "wjackson",
            "identity_type": "user",
            "tenant_id": "default",
            "scopes": [
                "memory:write:user",
                "memory:write:project",
                "memory:read:user",
                "memory:read:project",
            ],
            "project_memberships": [],
        }
        session_user = {
            "user_id": "wjackson",
            "scopes": ["user", "project"],
            "identity_type": "user",
            "project_memberships": [],
        }

        async def _fake_get_db_session():
            return (AsyncMock(), AsyncMock())

        auth_mod._current_session = session_user
        try:
            with (
                patch(
                    "src.tools.write_memory.get_claims_from_context",
                    return_value=fake_claims,
                ),
                patch(
                    "src.tools.write_memory.get_db_session",
                    side_effect=_fake_get_db_session,
                ),
                patch(
                    "src.tools.write_memory.release_db_session",
                    new_callable=AsyncMock,
                ),
                patch(
                    "src.tools.write_memory.get_embedding_service",
                    return_value=MagicMock(),
                ),
                patch(
                    "src.tools.write_memory.create_memory",
                    new_callable=AsyncMock,
                    return_value=(fake_node, fake_curation),
                ),
                patch(
                    "src.tools.write_memory.broadcast_after_write",
                    new_callable=AsyncMock,
                ),
                patch(
                    "src.tools.write_memory.ensure_project_membership",
                    new_callable=AsyncMock,
                    return_value=({"all_doctors"}, True),
                ),
                patch(
                    "src.tools.write_memory.PROJECT_ISOLATION_ENABLED",
                    True,
                ),
                patch(
                    "src.tools.write_memory.ROLE_ISOLATION_ENABLED",
                    False,
                ),
                patch(
                    "src.tools.write_memory.authorize_write",
                ),
                patch(
                    "src.tools.write_memory.resolve_tenant",
                    return_value="default",
                ),
            ):
                result = await write_memory(
                    content="test memory",
                    scope="project",
                    project_id="all_doctors",
                    content_type="experiential",
                )

            assert "all_doctors" in session_user["project_memberships"], (
                "Session project_memberships must include the auto-enrolled project. "
                f"Got: {session_user['project_memberships']}"
            )
        finally:
            auth_mod._current_session = None

    @pytest.mark.asyncio
    async def test_session_claims_unchanged_without_auto_enrollment(self):
        """When the user is already a member (was_auto_enrolled=False),
        session claims must not be modified."""
        from src.tools.write_memory import write_memory

        fake_node = _fake_project_node("test memory", owner_id="wjackson")
        fake_curation = {
            "blocked": False,
            "reason": None,
            "detail": None,
            "similar_count": 0,
            "nearest_id": None,
            "nearest_score": None,
            "flags": [],
        }
        fake_claims = {
            "sub": "wjackson",
            "identity_type": "user",
            "tenant_id": "default",
            "scopes": [
                "memory:write:user",
                "memory:write:project",
                "memory:read:user",
                "memory:read:project",
            ],
            "project_memberships": ["all_doctors"],
        }
        session_user = {
            "user_id": "wjackson",
            "scopes": ["user", "project"],
            "identity_type": "user",
            "project_memberships": ["all_doctors"],
        }

        async def _fake_get_db_session():
            return (AsyncMock(), AsyncMock())

        auth_mod._current_session = session_user
        try:
            with (
                patch(
                    "src.tools.write_memory.get_claims_from_context",
                    return_value=fake_claims,
                ),
                patch(
                    "src.tools.write_memory.get_db_session",
                    side_effect=_fake_get_db_session,
                ),
                patch(
                    "src.tools.write_memory.release_db_session",
                    new_callable=AsyncMock,
                ),
                patch(
                    "src.tools.write_memory.get_embedding_service",
                    return_value=MagicMock(),
                ),
                patch(
                    "src.tools.write_memory.create_memory",
                    new_callable=AsyncMock,
                    return_value=(fake_node, fake_curation),
                ),
                patch(
                    "src.tools.write_memory.broadcast_after_write",
                    new_callable=AsyncMock,
                ),
                patch(
                    "src.tools.write_memory.ensure_project_membership",
                    new_callable=AsyncMock,
                    return_value=({"all_doctors"}, False),
                ),
                patch(
                    "src.tools.write_memory.PROJECT_ISOLATION_ENABLED",
                    True,
                ),
                patch(
                    "src.tools.write_memory.ROLE_ISOLATION_ENABLED",
                    False,
                ),
                patch(
                    "src.tools.write_memory.authorize_write",
                ),
                patch(
                    "src.tools.write_memory.resolve_tenant",
                    return_value="default",
                ),
            ):
                result = await write_memory(
                    content="test memory",
                    scope="project",
                    project_id="all_doctors",
                    content_type="experiential",
                )

            assert session_user["project_memberships"] == ["all_doctors"], (
                "Session project_memberships should remain unchanged when not auto-enrolled"
            )
        finally:
            auth_mod._current_session = None


# ---------------------------------------------------------------------------
# Bug 2a — list_memory skips owner_id for project-scoped queries
# ---------------------------------------------------------------------------


class TestListProjectScopeOwnerBypass:
    """list_memory must pass owner_id=None for project-scoped queries."""

    @pytest.mark.asyncio
    async def test_list_project_scope_passes_null_owner_id(self):
        """When scope='project' and project_ids are resolved,
        list_memories must be called with owner_id=None."""
        from src.tools.list_memory import list_memory

        items = [
            _fake_project_node("dr_bob memory", owner_id="dr_bob"),
            _fake_project_node("dr_alice memory", owner_id="dr_alice"),
        ]
        fake_claims = {
            "sub": "dr_bob",
            "identity_type": "user",
            "tenant_id": "default",
            "scopes": [
                "memory:read:user",
                "memory:read:project",
            ],
            "project_memberships": ["all_doctors"],
        }

        async def _fake_get_db_session():
            return (AsyncMock(), AsyncMock())

        with (
            patch(
                "src.tools.list_memory.get_claims_from_context",
                return_value=fake_claims,
            ),
            patch(
                "src.tools.list_memory.get_db_session",
                side_effect=_fake_get_db_session,
            ),
            patch(
                "src.tools.list_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.list_memory.list_memories",
                new_callable=AsyncMock,
                return_value=(items, None),
            ) as mock_list,
            patch(
                "src.tools.list_memory.get_campaigns_for_project",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "src.tools.list_memory.build_authorized_scopes",
                return_value={"user", "project"},
            ),
            patch(
                "src.tools.list_memory.PROJECT_ISOLATION_ENABLED",
                True,
            ),
            patch(
                "src.tools.list_memory.ROLE_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.list_memory.resolve_tenant",
                return_value="default",
            ),
        ):
            result = await list_memory(scope="project", project_id="all_doctors")

        _, kwargs = mock_list.call_args
        assert kwargs.get("owner_id") is None, (
            f"list_memories must be called with owner_id=None for project scope, "
            f"got owner_id={kwargs.get('owner_id')!r}"
        )

    @pytest.mark.asyncio
    async def test_list_user_scope_passes_caller_owner_id(self):
        """When scope is not 'project', list_memories must be called
        with owner_id=claims['sub'] (the caller's user ID)."""
        from src.tools.list_memory import list_memory

        items = [_fake_project_node("user memory", owner_id="dr_bob")]
        fake_claims = {
            "sub": "dr_bob",
            "identity_type": "user",
            "tenant_id": "default",
            "scopes": [
                "memory:read:user",
            ],
            "project_memberships": [],
        }

        async def _fake_get_db_session():
            return (AsyncMock(), AsyncMock())

        with (
            patch(
                "src.tools.list_memory.get_claims_from_context",
                return_value=fake_claims,
            ),
            patch(
                "src.tools.list_memory.get_db_session",
                side_effect=_fake_get_db_session,
            ),
            patch(
                "src.tools.list_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.list_memory.list_memories",
                new_callable=AsyncMock,
                return_value=(items, None),
            ) as mock_list,
            patch(
                "src.tools.list_memory.build_authorized_scopes",
                return_value={"user"},
            ),
            patch(
                "src.tools.list_memory.ROLE_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.list_memory.PROJECT_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.list_memory.resolve_tenant",
                return_value="default",
            ),
        ):
            result = await list_memory(scope="user")

        _, kwargs = mock_list.call_args
        assert kwargs.get("owner_id") == "dr_bob", (
            f"list_memories must be called with owner_id='dr_bob' for user scope, "
            f"got owner_id={kwargs.get('owner_id')!r}"
        )


# ---------------------------------------------------------------------------
# Bug 2b — _build_search_filters skips owner_id for project scope
# ---------------------------------------------------------------------------


class TestSearchFiltersProjectOwnerBypass:
    """_build_search_filters must skip the owner_id filter when
    scope='project' and project_ids is set."""

    def test_project_scope_with_project_ids_skips_owner_filter(self):
        """When scope='project' and project_ids is provided,
        the owner_id filter must NOT be applied."""
        from memoryhub_core.models.memory import MemoryNode
        from memoryhub_core.services.memory import _build_search_filters

        filters = _build_search_filters(
            scope="project",
            owner_id="dr_bob",
            current_only=True,
            authorized_scopes=None,
            tenant_id="default",
            project_ids={"all_doctors"},
        )

        for f in filters:
            clause_str = str(f.compile(compile_kwargs={"literal_binds": True}))
            assert not (
                "owner_id" in clause_str
                and "dr_bob" in clause_str
                and "!=" not in clause_str
            ), (
                f"owner_id filter must be skipped for project scope with project_ids, "
                f"but found: {clause_str}"
            )

    def test_user_scope_applies_owner_filter(self):
        """When scope='user', the owner_id filter must be applied."""
        from memoryhub_core.services.memory import _build_search_filters

        filters = _build_search_filters(
            scope="user",
            owner_id="dr_bob",
            current_only=True,
            authorized_scopes=None,
            tenant_id="default",
        )

        has_owner_filter = False
        for f in filters:
            clause_str = str(f.compile(compile_kwargs={"literal_binds": True}))
            if "owner_id" in clause_str and "dr_bob" in clause_str:
                has_owner_filter = True
                break

        assert has_owner_filter, (
            "owner_id filter must be applied for user scope"
        )

    def test_project_scope_without_project_ids_applies_owner_filter(self):
        """When scope='project' but project_ids is None/empty,
        the owner_id filter must still be applied as a safety fallback."""
        from memoryhub_core.services.memory import _build_search_filters

        filters = _build_search_filters(
            scope="project",
            owner_id="dr_bob",
            current_only=True,
            authorized_scopes=None,
            tenant_id="default",
            project_ids=None,
        )

        has_owner_filter = False
        for f in filters:
            clause_str = str(f.compile(compile_kwargs={"literal_binds": True}))
            if "owner_id" in clause_str and "dr_bob" in clause_str:
                has_owner_filter = True
                break

        assert has_owner_filter, (
            "owner_id filter must be applied for project scope when project_ids is None"
        )
