"""Tests for the admin_memory MCP tool (issue #45).

Tests action dispatch routing, parameter validation, and authorization
checks. Underlying service functions are patched to isolate the tool layer.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from src.tools.admin_memory import (
    _VALID_ACTIONS,
    _check_admin_scope,
    admin_memory,
)

# ── Authorization tests ──────────────────────────────────────────────────


class TestAdminScopeCheck:
    def test_check_admin_scope_passes(self):
        _check_admin_scope(["memory:admin", "memory:read"])

    def test_check_admin_scope_fails(self):
        with pytest.raises(ToolError, match="memory:admin"):
            _check_admin_scope(["memory:read", "memory:write"])

    def test_check_admin_scope_empty(self):
        with pytest.raises(ToolError, match="memory:admin"):
            _check_admin_scope([])


# ── Action validation ─────────────────────────────────────────────────────


class TestActionValidation:
    @pytest.mark.asyncio
    async def test_invalid_action_raises(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value={
                "sub": "admin-1",
                "tenant_id": "default",
                "scopes": ["memory:admin"],
            },
        ):
            with pytest.raises(ToolError, match="Invalid admin action"):
                await admin_memory(action="bogus")

    @pytest.mark.asyncio
    async def test_invalid_action_lists_valid(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value={
                "sub": "admin-1",
                "tenant_id": "default",
                "scopes": ["memory:admin"],
            },
        ):
            with pytest.raises(ToolError) as exc_info:
                await admin_memory(action="not_real")
            msg = str(exc_info.value)
            assert "search" in msg
            assert "quarantine" in msg

    def test_valid_actions_count(self):
        assert len(_VALID_ACTIONS) == 4


# ── Required parameter validation ────────────────────────────────────────


class TestRequiredParams:
    def _admin_claims(self, extra_scopes=None):
        scopes = ["memory:admin"]
        if extra_scopes:
            scopes.extend(extra_scopes)
        return {
            "sub": "admin-1",
            "tenant_id": "default",
            "scopes": scopes,
        }

    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'query'"):
                await admin_memory(action="search")

    @pytest.mark.asyncio
    async def test_quarantine_requires_memory_id(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'memory_id'"):
                await admin_memory(
                    action="quarantine",
                    options={"reason": "test"},
                )

    @pytest.mark.asyncio
    async def test_quarantine_requires_reason(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'reason'"):
                await admin_memory(
                    action="quarantine",
                    memory_id="abc-123",
                )

    @pytest.mark.asyncio
    async def test_restore_requires_memory_id(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'memory_id'"):
                await admin_memory(
                    action="restore",
                    options={"reason": "test"},
                )

    @pytest.mark.asyncio
    async def test_restore_requires_reason(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'reason'"):
                await admin_memory(
                    action="restore",
                    memory_id="abc-123",
                )

    @pytest.mark.asyncio
    async def test_hard_delete_requires_memory_id(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'memory_id'"):
                await admin_memory(
                    action="hard_delete",
                    options={"reason": "test"},
                )

    @pytest.mark.asyncio
    async def test_hard_delete_requires_reason(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value=self._admin_claims(),
        ):
            with pytest.raises(ToolError, match="requires 'reason'"):
                await admin_memory(
                    action="hard_delete",
                    memory_id="abc-123",
                )


# ── Scope enforcement ────────────────────────────────────────────────────


class TestScopeEnforcement:
    @pytest.mark.asyncio
    async def test_no_admin_scope_rejected(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value={
                "sub": "user-1",
                "tenant_id": "default",
                "scopes": ["memory:read", "memory:write"],
            },
        ):
            with pytest.raises(ToolError, match="memory:admin"):
                await admin_memory(action="search", query="test")

    @pytest.mark.asyncio
    async def test_cross_tenant_requires_extra_scope(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value={
                "sub": "admin-1",
                "tenant_id": "default",
                "scopes": ["memory:admin"],
            },
        ):
            with pytest.raises(ToolError, match="cross_tenant"):
                await admin_memory(
                    action="search",
                    query="test",
                    options={"cross_tenant": True},
                )

    @pytest.mark.asyncio
    async def test_sanitized_audit_requires_extra_scope(self):
        with patch(
            "src.core.authz.get_claims_from_context",
            return_value={
                "sub": "admin-1",
                "tenant_id": "default",
                "scopes": ["memory:admin"],
            },
        ):
            with pytest.raises(ToolError, match="sanitized_audit"):
                await admin_memory(
                    action="hard_delete",
                    memory_id="abc-123",
                    options={
                        "reason": "test",
                        "sanitized_audit": True,
                    },
                )


# ── Dispatch routing ─────────────────────────────────────────────────────


class TestDispatchRouting:
    @staticmethod
    def _session():
        session = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        session.execute = AsyncMock(return_value=result)
        return session

    def _admin_claims(self, extra_scopes=None):
        scopes = ["memory:admin"]
        if extra_scopes:
            scopes.extend(extra_scopes)
        return {
            "sub": "admin-1",
            "tenant_id": "default",
            "scopes": scopes,
        }

    @pytest.mark.asyncio
    async def test_search_dispatches_to_service(self):
        mock_search = AsyncMock(return_value=[{"id": "test"}])

        with (
            patch(
                "src.core.authz.get_claims_from_context",
                return_value=self._admin_claims(),
            ),
            patch(
                "memoryhub_core.services.admin.search_memory_admin",
                mock_search,
            ),
            patch(
                "src.tools._deps.get_db_session",
                new_callable=AsyncMock,
                return_value=(self._session(), "mock_gen"),
            ),
            patch(
                "src.tools._deps.get_embedding_service",
                return_value="mock_emb",
            ),
            patch(
                "src.tools._deps.release_db_session",
                new_callable=AsyncMock,
            ),
        ):
            result = await admin_memory(action="search", query="API key")

        assert result["total"] == 1
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs[1]["query"] == "API key"

    @pytest.mark.asyncio
    async def test_quarantine_dispatches_to_service(self):
        mock_quarantine = AsyncMock(return_value={
            "memory_id": "abc",
            "previous_status": "active",
            "new_status": "quarantined",
            "reason": "test",
            "incident_reference": None,
        })

        with (
            patch(
                "src.core.authz.get_claims_from_context",
                return_value=self._admin_claims(),
            ),
            patch(
                "memoryhub_core.services.admin.quarantine_memory",
                mock_quarantine,
            ),
            patch(
                "src.tools._deps.get_db_session",
                new_callable=AsyncMock,
                return_value=(self._session(), "mock_gen"),
            ),
            patch(
                "src.tools._deps.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.core.audit.record_event",
            ),
        ):
            result = await admin_memory(
                action="quarantine",
                memory_id="00000000-0000-0000-0000-000000000001",
                options={"reason": "Suspected PII"},
            )

        assert result["new_status"] == "quarantined"
        mock_quarantine.assert_called_once()
