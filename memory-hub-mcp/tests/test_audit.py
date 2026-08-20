"""Tests for audit logging (#67).

Verifies that record_event emits structured JSON to the memoryhub.audit
logger with the expected fields.
"""

import json
import logging

from src.core.audit import record_event


def test_record_event_logs_json(caplog):
    """Basic audit event emits valid JSON with required fields."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.write",
            actor_id="user-1",
            driver_id="user-1",
            scope="user",
            owner_id="user-1",
            memory_id="abc-123",
            decision="allowed",
        )
    assert len(caplog.records) == 1
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "memory.write"
    assert event["actor_id"] == "user-1"
    assert event["driver_id"] == "user-1"
    assert event["scope"] == "user"
    assert event["owner_id"] == "user-1"
    assert event["memory_id"] == "abc-123"
    assert event["decision"] == "allowed"
    assert "timestamp" in event


def test_record_event_denied_decision(caplog):
    """Denied decisions are captured with correct actor/driver split."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.write",
            actor_id="user-1",
            driver_id="agent-x",
            scope="project",
            owner_id="proj-1",
            memory_id=None,
            decision="denied",
        )
    event = json.loads(caplog.records[0].message)
    assert event["decision"] == "denied"
    assert event["memory_id"] is None
    assert event["actor_id"] == "user-1"
    assert event["driver_id"] == "agent-x"


def test_record_event_with_metadata(caplog):
    """Optional metadata dict is included when provided."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.search",
            actor_id="user-1",
            driver_id="user-1",
            scope="user",
            owner_id="user-1",
            memory_id=None,
            decision="allowed",
            metadata={"query": "deployment tips", "max_results": 10},
        )
    event = json.loads(caplog.records[0].message)
    assert event["metadata"]["query"] == "deployment tips"
    assert event["metadata"]["max_results"] == 10


def test_record_event_without_metadata(caplog):
    """When metadata is None, the key is absent from the event."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.read",
            actor_id="bot-1",
            driver_id="human-alice",
            scope="user",
            owner_id="human-alice",
            memory_id="def-456",
            decision="allowed",
            metadata=None,
        )
    event = json.loads(caplog.records[0].message)
    assert "metadata" not in event


def test_record_event_session_registered(caplog):
    """Session registration events use scope='session'."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="session.registered",
            actor_id="user-1",
            driver_id="user-1",
            scope="session",
            owner_id="user-1",
            memory_id=None,
            decision="allowed",
            metadata={"auth_method": "api_key", "session_id": "sess-abc"},
        )
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "session.registered"
    assert event["scope"] == "session"
    assert event["metadata"]["auth_method"] == "api_key"


def test_record_event_session_denied(caplog):
    """Failed session registration emits a denied event."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="session.denied",
            actor_id="unknown",
            driver_id="unknown",
            scope="session",
            owner_id="unknown",
            memory_id=None,
            decision="denied",
            metadata={"auth_method": "api_key"},
        )
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "session.denied"
    assert event["decision"] == "denied"


# ==============================================================================
# Phase 0: Integration tests for denied operations
# ==============================================================================


class TestFireAndForget:
    """Verify audit failures never block tool operations (audit.py:8)."""

    def test_logger_exception_does_not_propagate(self):
        """Audit logging failures are swallowed (fire-and-forget)."""
        from unittest.mock import patch

        with patch("src.core.audit.logger.info") as mock_logger:
            mock_logger.side_effect = RuntimeError("Simulated logger failure")

            # Should not raise despite the logger failure
            record_event(
                event_type="memory.write",
                actor_id="user-alice",
                driver_id="user-alice",
                scope="user",
                owner_id="user-alice",
                memory_id=None,
                decision="allowed",
            )

            # The exception was raised inside record_event, proving it tried to log
            assert mock_logger.called


class TestDeniedOperationAudit:
    """Verify denied operations emit decision='denied' audit events.

    These tests use mocks to isolate the audit call sites without requiring
    a full database setup. They verify that authorization failures trigger
    audit events before raising ToolError.
    """

    def test_read_memory_denied(self, caplog):
        """read_memory records decision='denied' when authorize_read fails."""
        import pytest
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from src.tools.read_memory import read_memory

        # Mock the authorization and service layers
        mock_node = SimpleNamespace(
            id="550e8400-e29b-41d4-a716-446655440000",
            scope="user",
            owner_id="user-bob",
            tenant_id="default",
        )

        async def run_test():
            with patch("src.tools.read_memory.get_claims_from_context") as mock_claims, \
                 patch("src.tools.read_memory._read_memory") as mock_read, \
                 patch("src.tools.read_memory.authorize_read") as mock_authz, \
                 patch("src.tools.read_memory.get_db_session") as mock_db, \
                 caplog.at_level(logging.INFO, logger="memoryhub.audit"):

                mock_claims.return_value = {"sub": "user-alice", "scopes": ["memory:read"]}
                mock_read.return_value = mock_node
                mock_authz.return_value = False  # Authorization fails

                # Mock database session context manager
                mock_session = MagicMock()
                mock_gen = MagicMock()
                mock_db.return_value = (mock_session, mock_gen)

                from fastmcp.exceptions import ToolError
                with pytest.raises(ToolError, match="Not authorized"):
                    await read_memory(memory_id="550e8400-e29b-41d4-a716-446655440000")

                # Verify denied audit event was recorded
                assert len(caplog.records) == 1
                parsed = json.loads(caplog.records[0].message)
                assert parsed["event_type"] == "memory.read"
                assert parsed["actor_id"] == "user-alice"
                assert parsed["decision"] == "denied"
                assert parsed["scope"] == "user"
                assert parsed["owner_id"] == "user-bob"

        import asyncio
        asyncio.run(run_test())

    def test_write_memory_denied_project_scope(self, caplog):
        """write_memory records decision='denied' for non-member project write."""
        import pytest
        from unittest.mock import patch

        from src.tools.write_memory import write_memory

        async def run_test():
            with patch("src.tools.write_memory.get_claims_from_context") as mock_claims, \
                 patch("src.tools.write_memory.authorize_write") as mock_authz, \
                 patch("src.tools.write_memory.resolve_tenant") as mock_tenant, \
                 patch("src.tools.write_memory.PROJECT_ISOLATION_ENABLED", True), \
                 caplog.at_level(logging.INFO, logger="memoryhub.audit"):

                mock_claims.return_value = {
                    "sub": "user-alice",
                    "scopes": ["memory:write"],
                    "project_memberships": [],  # Not a member of any projects
                }
                mock_tenant.return_value = "default"
                mock_authz.return_value = False  # Not authorized for project-1

                from fastmcp.exceptions import ToolError
                with pytest.raises(ToolError, match="Not authorized"):
                    await write_memory(
                        content="Test memory",
                        scope="project",
                        owner_id="project-1",
                        project_id="project-1",
                    )

                # Verify denied audit event was recorded
                assert len(caplog.records) == 1
                parsed = json.loads(caplog.records[0].message)
                assert parsed["event_type"] == "memory.write"
                assert parsed["actor_id"] == "user-alice"
                assert parsed["decision"] == "denied"
                assert parsed["scope"] == "project"
                assert parsed["owner_id"] == "project-1"

        import asyncio
        asyncio.run(run_test())

    def test_manage_graph_create_relationship_denied_gap(self, caplog):
        """manage_graph create_relationship DOES NOT record denied (Gap #2).

        This test documents the gap identified in phase0-audit-inventory.md.
        When authorization fails for source or target node, no audit event
        is recorded before raising ToolError.
        """
        import pytest
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from src.tools.manage_graph import manage_graph

        mock_source = SimpleNamespace(
            id="550e8400-e29b-41d4-a716-446655440000",
            scope="user",
            owner_id="user-bob",
            tenant_id="default",
        )

        async def run_test():
            with patch("src.tools.manage_graph.get_claims_from_context") as mock_claims, \
                 patch("src.tools.manage_graph.read_memory_service") as mock_read, \
                 patch("src.tools.manage_graph.authorize_read") as mock_authz, \
                 patch("src.tools.manage_graph.get_db_session") as mock_db, \
                 caplog.at_level(logging.INFO, logger="memoryhub.audit"):

                mock_claims.return_value = {"sub": "user-alice", "scopes": ["memory:read"]}
                mock_read.return_value = mock_source
                mock_authz.return_value = False  # Can't read source node

                mock_session = MagicMock()
                mock_gen = MagicMock()
                mock_db.return_value = (mock_session, mock_gen)

                from fastmcp.exceptions import ToolError
                with pytest.raises(ToolError, match="Not authorized"):
                    await manage_graph(
                        action="create_relationship",
                        source_id="550e8400-e29b-41d4-a716-446655440000",
                        target_id="660e8400-e29b-41d4-a716-446655440000",
                        relationship_type="derived_from",
                    )

                # GAP: No audit event was recorded (this assertion documents the bug)
                assert len(caplog.records) == 0, \
                    "Gap #2: manage_graph does not record denied audit events"

        import asyncio
        asyncio.run(run_test())
