"""Tests for the graduate action in the memory tool.

Tests the graduate dispatcher, service integration, and error handling.
The graduate action converts experiential memories to knowledge memories.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.tools.memory import memory


class FakeMemoryNode:
    """Mock memory node for testing."""

    def __init__(
        self,
        id: uuid.UUID,
        content: str,
        scope: str = "user",
        scope_id: str | None = None,
        content_type: str = "experiential",
        weight: float = 0.5,
        metadata: dict | None = None,
        created_at=None,
    ):
        self.id = id
        self.content = content
        self.scope = scope
        self.scope_id = scope_id
        self.content_type = content_type
        self.weight = weight
        self.metadata = metadata or {}
        # Use a fake datetime if not provided
        from datetime import datetime, timezone
        self.created_at = created_at or datetime.now(timezone.utc)


# ── Required parameter validation ──────────────────────────────────────────

class TestGraduateParamValidation:
    """Test that required parameters are validated."""

    @pytest.mark.asyncio
    async def test_graduate_requires_memory_id(self):
        """graduate action requires memory_id."""
        with pytest.raises(ToolError, match="action='graduate' requires 'memory_id'"):
            await memory(action="graduate")

    @pytest.mark.asyncio
    async def test_graduate_rejects_empty_memory_id(self):
        """graduate action rejects empty string memory_id."""
        with pytest.raises(ToolError, match="action='graduate' requires 'memory_id'"):
            await memory(action="graduate", memory_id="   ")


# ── Basic dispatch routing ─────────────────────────────────────────────────

class TestGraduateDispatch:
    """Test that the graduate action dispatches correctly to the service layer."""

    @pytest.mark.asyncio
    async def test_graduate_via_memory_action(self):
        """Graduate an experiential memory to knowledge via memory() dispatcher."""
        source_id = uuid.uuid4()
        graduated_id = uuid.uuid4()

        # Create mock graduated memory
        graduated_memory = FakeMemoryNode(
            id=graduated_id,
            content="Testing patterns for MCP servers",
            scope="user",
            content_type="knowledge",
            weight=0.8,
            metadata={
                "graduated_from": {
                    "source_id": str(source_id),
                    "graduated_by": "test-user",
                    "reviewer_note": "Well-tested approach",
                },
            },
        )

        # Mock the service layer
        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        mock_embedding_service = AsyncMock()

        with (
            patch("src.core.authz.get_claims_from_context", return_value={
                "sub": "test-user",
                "tenant_id": "tenant-a",
            }),
            patch("src.core.authz.get_tenant_filter", return_value="tenant-a"),
            patch("src.tools._deps.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools._deps.get_embedding_service", return_value=mock_embedding_service),
            patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
            patch("memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock) as mock_graduate,
        ):
            mock_graduate.return_value = graduated_memory

            result = await memory(
                action="graduate",
                memory_id=str(source_id),
                options={"reviewer_note": "Well-tested approach"},
            )

            # Verify the service was called correctly
            mock_graduate.assert_called_once()
            call_kwargs = mock_graduate.call_args[1]
            assert call_kwargs["memory_id"] == source_id
            assert call_kwargs["session"] == mock_session
            assert call_kwargs["embedding_service"] == mock_embedding_service
            assert call_kwargs["tenant_id"] == "tenant-a"
            assert call_kwargs["graduated_by"] == "test-user"
            assert call_kwargs["reviewer_note"] == "Well-tested approach"
            assert call_kwargs["evidence"] is None
            assert call_kwargs["project_id"] is None

            # Verify the response structure
            assert "graduated_memory" in result
            assert "message" in result
            grad_mem = result["graduated_memory"]
            assert grad_mem["id"] == str(graduated_id)
            assert grad_mem["content"] == "Testing patterns for MCP servers"
            assert grad_mem["content_type"] == "knowledge"
            assert grad_mem["weight"] == 0.8
            assert "graduated_from" in grad_mem["metadata"]
            assert grad_mem["metadata"]["graduated_from"]["reviewer_note"] == "Well-tested approach"


    @pytest.mark.asyncio
    async def test_graduate_with_evidence(self):
        """Graduate with evidence option."""
        source_id = uuid.uuid4()
        graduated_id = uuid.uuid4()

        graduated_memory = FakeMemoryNode(
            id=graduated_id,
            content="FastAPI dependency injection pattern",
            scope="project",
            scope_id="mcp-server-template",
            content_type="knowledge",
            weight=0.9,
            metadata={
                "graduated_from": {
                    "source_id": str(source_id),
                    "graduated_by": "test-user",
                    "evidence": "Verified across 10+ projects",
                },
            },
        )

        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        mock_embedding_service = AsyncMock()

        with (
            patch("src.core.authz.get_claims_from_context", return_value={
                "sub": "test-user",
                "tenant_id": "tenant-a",
            }),
            patch("src.core.authz.get_tenant_filter", return_value="tenant-a"),
            patch("src.tools._deps.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools._deps.get_embedding_service", return_value=mock_embedding_service),
            patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
            patch("memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock) as mock_graduate,
        ):
            mock_graduate.return_value = graduated_memory

            result = await memory(
                action="graduate",
                memory_id=str(source_id),
                project_id="mcp-server-template",
                options={
                    "evidence": "Verified across 10+ projects",
                },
            )

            # Verify the service was called with evidence
            call_kwargs = mock_graduate.call_args[1]
            assert call_kwargs["evidence"] == "Verified across 10+ projects"
            assert call_kwargs["project_id"] == "mcp-server-template"
            assert call_kwargs["reviewer_note"] is None

            # Verify the response
            grad_mem = result["graduated_memory"]
            assert grad_mem["content_type"] == "knowledge"
            assert grad_mem["scope"] == "project"
            assert grad_mem["scope_id"] == "mcp-server-template"


    @pytest.mark.asyncio
    async def test_graduate_with_both_evidence_and_reviewer_note(self):
        """Graduate with both evidence and reviewer_note."""
        source_id = uuid.uuid4()
        graduated_id = uuid.uuid4()

        graduated_memory = FakeMemoryNode(
            id=graduated_id,
            content="Memory pattern",
            content_type="knowledge",
            metadata={
                "graduated_from": {
                    "source_id": str(source_id),
                    "graduated_by": "test-user",
                    "evidence": "Test evidence",
                    "reviewer_note": "Test note",
                },
            },
        )

        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        mock_embedding_service = AsyncMock()

        with (
            patch("src.core.authz.get_claims_from_context", return_value={
                "sub": "test-user",
                "tenant_id": "tenant-a",
            }),
            patch("src.core.authz.get_tenant_filter", return_value="tenant-a"),
            patch("src.tools._deps.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools._deps.get_embedding_service", return_value=mock_embedding_service),
            patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
            patch("memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock) as mock_graduate,
        ):
            mock_graduate.return_value = graduated_memory

            await memory(
                action="graduate",
                memory_id=str(source_id),
                options={
                    "evidence": "Test evidence",
                    "reviewer_note": "Test note",
                },
            )

            # Verify both were passed
            call_kwargs = mock_graduate.call_args[1]
            assert call_kwargs["evidence"] == "Test evidence"
            assert call_kwargs["reviewer_note"] == "Test note"


# ── Options forwarding ─────────────────────────────────────────────────────

class TestGraduateOptionsForwarding:
    """Test that only valid graduate options are forwarded."""

    @pytest.mark.asyncio
    async def test_graduate_forwards_only_valid_options(self):
        """Graduate should only forward evidence and reviewer_note options."""
        source_id = uuid.uuid4()
        graduated_id = uuid.uuid4()

        graduated_memory = FakeMemoryNode(
            id=graduated_id,
            content="Test",
            content_type="knowledge",
        )

        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        mock_embedding_service = AsyncMock()

        with (
            patch("src.core.authz.get_claims_from_context", return_value={
                "sub": "test-user",
                "tenant_id": "tenant-a",
            }),
            patch("src.core.authz.get_tenant_filter", return_value="tenant-a"),
            patch("src.tools._deps.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools._deps.get_embedding_service", return_value=mock_embedding_service),
            patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
            patch("memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock) as mock_graduate,
        ):
            mock_graduate.return_value = graduated_memory

            # Try passing invalid options that should be ignored
            await memory(
                action="graduate",
                memory_id=str(source_id),
                options={
                    "evidence": "Valid option",
                    "reviewer_note": "Also valid",
                    "invalid_option": "Should be ignored",
                    "weight": 0.9,  # Not a graduate option
                },
            )

            # Verify only valid options were used
            call_kwargs = mock_graduate.call_args[1]
            assert call_kwargs["evidence"] == "Valid option"
            assert call_kwargs["reviewer_note"] == "Also valid"
            # The service layer shouldn't receive invalid options
            assert "invalid_option" not in str(call_kwargs)
            assert "weight" not in str(call_kwargs)


# ── Error handling ─────────────────────────────────────────────────────────

class TestGraduateErrorHandling:
    """Test error handling from the service layer."""

    @pytest.mark.asyncio
    async def test_graduate_service_error_propagates(self):
        """Service layer errors should propagate to the caller."""
        source_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        mock_embedding_service = AsyncMock()

        with (
            patch("src.core.authz.get_claims_from_context", return_value={
                "sub": "test-user",
                "tenant_id": "tenant-a",
            }),
            patch("src.core.authz.get_tenant_filter", return_value="tenant-a"),
            patch("src.tools._deps.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools._deps.get_embedding_service", return_value=mock_embedding_service),
            patch("src.tools._deps.release_db_session", new_callable=AsyncMock),
            patch("memoryhub_core.services.graduation.graduate_memory", new_callable=AsyncMock) as mock_graduate,
        ):
            # Simulate service layer raising an error
            mock_graduate.side_effect = ValueError("Cannot graduate knowledge memory")

            with pytest.raises(ValueError, match="Cannot graduate knowledge memory"):
                await memory(
                    action="graduate",
                    memory_id=str(source_id),
                )
