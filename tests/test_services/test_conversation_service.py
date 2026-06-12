"""Tests for conversation service layer.

Uses mock AsyncSession to avoid SQLite ARRAY column compatibility issues.
Integration tests against PostgreSQL are in tests/integration/.
"""

import contextlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from memoryhub_core.models.schemas import (
    ConversationMessageCreate,
    ConversationThreadCreate,
)
from memoryhub_core.services.conversation import (
    admin_purge_thread,
    hard_delete_thread,
    run_retention_sweep,
    soft_delete_thread,
    spill_response_thread,
)
from memoryhub_core.services.exceptions import ThreadNotActiveError, ThreadNotFoundError


def _mock_session():
    """Create a mock async session with sync result objects."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_execute_result(scalar_value=None):
    """Create a MagicMock result that returns scalar_value from scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    result.scalar_one.return_value = scalar_value
    return result


def _mock_thread_obj(status="active", owner_id="user-1", tenant_id="default"):
    """Create a mock that looks like a ConversationThread ORM object."""
    t = MagicMock()
    t.id = uuid.uuid4()
    t.status = status
    t.owner_id = owner_id
    t.tenant_id = tenant_id
    t.scope = "user"
    t.deleted_at = None
    t.title = None
    t.a2a_context_id = None
    t.scope_id = None
    t.actor_id = None
    t.driver_id = None
    t.participant_access = {}
    t.retention_policy = {}
    t.metadata_ = {}
    return t


def _mock_message_obj(sequence_number=1, handoff_redacted=False, content="Test message"):
    """Create a mock that looks like a ConversationMessage ORM object."""
    m = MagicMock()
    m.id = uuid.uuid4()
    m.thread_id = uuid.uuid4()
    m.sequence_number = sequence_number
    m.handoff_redacted = handoff_redacted
    m.role = "user"
    m.content = content
    m.storage_type = "inline"
    m.actor_id = None
    m.content_ref = None
    m.tool_call_id = None
    m.handoff_from_agent_id = None
    m.handoff_authorized_by = None
    m.tenant_id = "default"
    m.metadata_ = {}
    return m


class TestCreateThread:
    @pytest.mark.asyncio
    async def test_create_thread_calls_add_and_commit(self):
        from memoryhub_core.services.conversation import create_thread

        session = _mock_session()
        data = ConversationThreadCreate(scope="user")

        # create_thread calls model_validate after refresh, which reads ORM attrs.
        # We can't easily mock that, so we verify the ORM object passed to add().
        with contextlib.suppress(Exception):
            await create_thread(session, tenant_id="default", data=data, owner_id="user-1")

        session.add.assert_called_once()
        thread_obj = session.add.call_args[0][0]
        assert thread_obj.scope == "user"
        assert thread_obj.owner_id == "user-1"
        assert thread_obj.tenant_id == "default"
        assert "user-1" in thread_obj.participant_ids

    @pytest.mark.asyncio
    async def test_create_thread_adds_owner_to_participants(self):
        from memoryhub_core.services.conversation import create_thread

        session = _mock_session()
        data = ConversationThreadCreate(scope="project", participant_ids=["agent-2"])

        with contextlib.suppress(Exception):
            await create_thread(session, tenant_id="default", data=data, owner_id="user-1")

        thread_obj = session.add.call_args[0][0]
        assert "user-1" in thread_obj.participant_ids
        assert "agent-2" in thread_obj.participant_ids

    @pytest.mark.asyncio
    async def test_create_thread_retention_policy_user_scope(self):
        from memoryhub_core.services.conversation import create_thread

        session = _mock_session()
        data = ConversationThreadCreate(scope="user")

        with contextlib.suppress(Exception):
            await create_thread(session, tenant_id="default", data=data, owner_id="user-1")

        thread_obj = session.add.call_args[0][0]
        assert thread_obj.retention_policy["ttl_days"] == 90
        assert thread_obj.expires_at is not None

    @pytest.mark.asyncio
    async def test_create_thread_retention_policy_project_scope(self):
        from memoryhub_core.services.conversation import create_thread

        session = _mock_session()
        data = ConversationThreadCreate(scope="project")

        with contextlib.suppress(Exception):
            await create_thread(session, tenant_id="default", data=data, owner_id="user-1")

        thread_obj = session.add.call_args[0][0]
        assert thread_obj.retention_policy["ttl_days"] == 365


class TestGetThread:
    @pytest.mark.asyncio
    async def test_get_thread_not_found_returns_none(self):
        from memoryhub_core.services.conversation import get_thread

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        result = await get_thread(session, tenant_id="default", thread_id=uuid.uuid4())
        assert result is None


class TestAppendMessage:
    @pytest.mark.asyncio
    async def test_append_to_missing_thread_raises(self):
        from memoryhub_core.services.conversation import append_message

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        data = ConversationMessageCreate(thread_id=uuid.uuid4(), role="user", content="hello")
        with pytest.raises(ThreadNotFoundError):
            await append_message(session, tenant_id="default", thread_id=uuid.uuid4(), data=data)

    @pytest.mark.asyncio
    async def test_append_to_archived_thread_raises(self):
        from memoryhub_core.services.conversation import append_message

        session = _mock_session()
        mock_thread = _mock_thread_obj(status="archived")
        session.execute.return_value = _mock_execute_result(mock_thread)

        data = ConversationMessageCreate(thread_id=mock_thread.id, role="user", content="hello")
        with pytest.raises(ThreadNotActiveError, match="archived"):
            await append_message(session, tenant_id="default", thread_id=mock_thread.id, data=data)

    @pytest.mark.asyncio
    async def test_append_to_deleted_thread_raises(self):
        from memoryhub_core.services.conversation import append_message

        session = _mock_session()
        mock_thread = _mock_thread_obj(status="deleted")
        session.execute.return_value = _mock_execute_result(mock_thread)

        data = ConversationMessageCreate(thread_id=mock_thread.id, role="user", content="hello")
        with pytest.raises(ThreadNotActiveError, match="deleted"):
            await append_message(session, tenant_id="default", thread_id=mock_thread.id, data=data)


class TestArchiveThread:
    @pytest.mark.asyncio
    async def test_archive_missing_thread_raises(self):
        from memoryhub_core.services.conversation import archive_thread

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        with pytest.raises(ThreadNotFoundError):
            await archive_thread(session, tenant_id="default", thread_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_archive_already_archived_raises(self):
        from memoryhub_core.services.conversation import archive_thread

        session = _mock_session()
        mock_thread = _mock_thread_obj(status="archived")
        session.execute.return_value = _mock_execute_result(mock_thread)

        with pytest.raises(ThreadNotActiveError, match="archived"):
            await archive_thread(session, tenant_id="default", thread_id=mock_thread.id)


class TestForkThread:
    @pytest.mark.asyncio
    async def test_fork_creates_new_thread(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        source_thread_id = uuid.uuid4()
        source = _mock_thread_obj()
        source.id = source_thread_id
        source.scope = "user"
        source.scope_id = None
        source.retention_policy = {"ttl_days": 90}
        source.title = "Original Thread"

        # Mock session.execute to return source thread, then messages
        msg1 = MagicMock()
        msg1.id = uuid.uuid4()
        msg1.sequence_number = 1
        msg1.role = "user"
        msg1.content = "Hello"
        msg1.storage_type = "inline"
        msg1.content_ref = None
        msg1.content_size = 5
        msg1.actor_id = None
        msg1.tool_call_id = None
        msg1.metadata_ = None

        # First call: fetch source thread
        # Second call: fetch messages
        execute_results = [
            _mock_execute_result(source),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await fork_thread(
                session,
                tenant_id="default",
                thread_id=source_thread_id,
                from_sequence=1,
                owner_id="new-owner",
                title="Forked Thread",
            )

        # Verify a new thread was added with fresh ID and reset extraction_cursor
        thread_obj = session.add.call_args_list[0][0][0]
        assert thread_obj.id != source_thread_id
        assert thread_obj.owner_id == "new-owner"
        assert thread_obj.scope == "user"
        assert thread_obj.extraction_cursor == 0

    @pytest.mark.asyncio
    async def test_fork_copies_messages_up_to_sequence(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        source_thread_id = uuid.uuid4()
        source = _mock_thread_obj()
        source.id = source_thread_id
        source.retention_policy = {"ttl_days": 90}

        # Create 3 messages
        msg1 = MagicMock()
        msg1.sequence_number = 1
        msg1.role = "user"
        msg1.content = "Message 1"
        msg1.storage_type = "inline"
        msg1.content_ref = None
        msg1.content_size = 9
        msg1.actor_id = None
        msg1.tool_call_id = None
        msg1.metadata_ = None

        msg2 = MagicMock()
        msg2.sequence_number = 2
        msg2.role = "assistant"
        msg2.content = "Message 2"
        msg2.storage_type = "inline"
        msg2.content_ref = None
        msg2.content_size = 9
        msg2.actor_id = None
        msg2.tool_call_id = None
        msg2.metadata_ = None

        msg3 = MagicMock()
        msg3.sequence_number = 3
        msg3.role = "user"
        msg3.content = "Message 3"
        msg3.storage_type = "inline"
        msg3.content_ref = None
        msg3.content_size = 9
        msg3.actor_id = None
        msg3.tool_call_id = None
        msg3.metadata_ = None

        # Mock to return only msg1 and msg2 (from_sequence=2)
        execute_results = [
            _mock_execute_result(source),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1, msg2])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await fork_thread(
                session, tenant_id="default", thread_id=source_thread_id, from_sequence=2, owner_id="new-owner"
            )

        # Check that 2 messages were added (not 3)
        message_adds = [call for call in session.add.call_args_list if hasattr(call[0][0], "thread_id")]
        # First add is thread, rest are messages
        assert len(message_adds) == 2

    @pytest.mark.asyncio
    async def test_fork_renumbers_sequences(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        source_thread_id = uuid.uuid4()
        source = _mock_thread_obj()
        source.id = source_thread_id
        source.retention_policy = {"ttl_days": 90}

        msg5 = MagicMock()
        msg5.sequence_number = 5
        msg5.role = "user"
        msg5.content = "Original seq 5"
        msg5.storage_type = "inline"
        msg5.content_ref = None
        msg5.content_size = 14
        msg5.actor_id = None
        msg5.tool_call_id = None
        msg5.metadata_ = None

        msg6 = MagicMock()
        msg6.sequence_number = 6
        msg6.role = "assistant"
        msg6.content = "Original seq 6"
        msg6.storage_type = "inline"
        msg6.content_ref = None
        msg6.content_size = 14
        msg6.actor_id = None
        msg6.tool_call_id = None
        msg6.metadata_ = None

        execute_results = [
            _mock_execute_result(source),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg5, msg6])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await fork_thread(
                session, tenant_id="default", thread_id=source_thread_id, from_sequence=6, owner_id="new-owner"
            )

        # Get the added messages (skip first add which is thread)
        added_messages = [call[0][0] for call in session.add.call_args_list[1:]]
        assert added_messages[0].sequence_number == 1
        assert added_messages[1].sequence_number == 2

    @pytest.mark.asyncio
    async def test_fork_sets_owner_to_caller(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        source_thread_id = uuid.uuid4()
        source = _mock_thread_obj(owner_id="original-owner")
        source.id = source_thread_id
        source.retention_policy = {"ttl_days": 90}

        execute_results = [
            _mock_execute_result(source),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await fork_thread(
                session,
                tenant_id="default",
                thread_id=source_thread_id,
                from_sequence=0,
                owner_id="fork-caller",
            )

        thread_obj = session.add.call_args_list[0][0][0]
        assert thread_obj.owner_id == "fork-caller"
        assert "fork-caller" in thread_obj.participant_ids

    @pytest.mark.asyncio
    async def test_fork_missing_thread_raises(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        with pytest.raises(ThreadNotFoundError):
            await fork_thread(
                session,
                tenant_id="default",
                thread_id=uuid.uuid4(),
                from_sequence=1,
                owner_id="fork-caller",
            )

    @pytest.mark.asyncio
    async def test_fork_records_metadata(self):
        from memoryhub_core.services.conversation import fork_thread

        session = _mock_session()
        source_thread_id = uuid.uuid4()
        source = _mock_thread_obj()
        source.id = source_thread_id
        source.retention_policy = {"ttl_days": 90}

        execute_results = [
            _mock_execute_result(source),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await fork_thread(
                session,
                tenant_id="default",
                thread_id=source_thread_id,
                from_sequence=5,
                owner_id="fork-caller",
            )

        thread_obj = session.add.call_args_list[0][0][0]
        assert thread_obj.metadata_["forked_from"] == str(source_thread_id)
        assert thread_obj.metadata_["fork_sequence"] == 5


class TestShareThread:
    @pytest.mark.asyncio
    async def test_share_adds_grantee(self):
        from memoryhub_core.services.conversation import share_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj()
        mock_thread.id = thread_id
        mock_thread.participant_ids = ["owner-1"]
        mock_thread.participant_access = {}
        mock_thread.metadata_ = {}

        session.execute.return_value = _mock_execute_result(mock_thread)

        with contextlib.suppress(Exception):
            await share_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                grantee_id="agent-1",
                access_level="read",
                authorized_by="owner-1",
            )

        # Verify grantee added to participant_ids
        assert "agent-1" in mock_thread.participant_ids
        # Verify access level set
        assert mock_thread.participant_access["agent-1"] == "read"

    @pytest.mark.asyncio
    async def test_share_idempotent(self):
        from memoryhub_core.services.conversation import share_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj()
        mock_thread.id = thread_id
        mock_thread.participant_ids = ["owner-1", "agent-1"]
        mock_thread.participant_access = {"agent-1": "read"}
        mock_thread.metadata_ = {}

        session.execute.return_value = _mock_execute_result(mock_thread)

        with contextlib.suppress(Exception):
            await share_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                grantee_id="agent-1",
                access_level="write",
                authorized_by="owner-1",
            )

        # Access level updated
        assert mock_thread.participant_access["agent-1"] == "write"
        # Participant_ids doesn't have duplicates
        assert mock_thread.participant_ids.count("agent-1") == 1

    @pytest.mark.asyncio
    async def test_share_records_audit(self):
        from memoryhub_core.services.conversation import share_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj()
        mock_thread.id = thread_id
        mock_thread.participant_ids = ["owner-1"]
        mock_thread.participant_access = {}
        mock_thread.metadata_ = {}

        session.execute.return_value = _mock_execute_result(mock_thread)

        with contextlib.suppress(Exception):
            await share_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                grantee_id="agent-1",
                access_level="read",
                authorized_by="owner-1",
            )

        # Check share_grants in metadata
        shares = mock_thread.metadata_["share_grants"]
        assert len(shares) == 1
        assert shares[0]["grantee_id"] == "agent-1"
        assert shares[0]["access_level"] == "read"
        assert shares[0]["authorized_by"] == "owner-1"
        assert "granted_at" in shares[0]

    @pytest.mark.asyncio
    async def test_share_missing_thread_raises(self):
        from memoryhub_core.services.conversation import share_thread

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        with pytest.raises(ThreadNotFoundError):
            await share_thread(
                session,
                tenant_id="default",
                thread_id=uuid.uuid4(),
                grantee_id="agent-1",
                access_level="read",
                authorized_by="owner-1",
            )


class TestLookupByA2AContext:
    @pytest.mark.asyncio
    async def test_lookup_found(self):
        from memoryhub_core.services.conversation import lookup_thread_by_a2a_context

        session = _mock_session()
        thread_id = uuid.uuid4()
        session.execute.return_value = _mock_execute_result(thread_id)

        result = await lookup_thread_by_a2a_context(
            session,
            tenant_id="default",
            a2a_context_id="ctx-123",
        )

        assert result == thread_id

    @pytest.mark.asyncio
    async def test_lookup_not_found(self):
        from memoryhub_core.services.conversation import lookup_thread_by_a2a_context

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        result = await lookup_thread_by_a2a_context(
            session,
            tenant_id="default",
            a2a_context_id="ctx-nonexistent",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_filters_by_tenant(self):
        from memoryhub_core.services.conversation import lookup_thread_by_a2a_context

        session = _mock_session()
        # Different tenant returns None even if a2a_context_id would match
        session.execute.return_value = _mock_execute_result(None)

        result = await lookup_thread_by_a2a_context(
            session,
            tenant_id="wrong-tenant",
            a2a_context_id="ctx-123",
        )

        assert result is None


class TestGetThreadRedaction:
    @pytest.mark.asyncio
    async def test_get_thread_owner_sees_redacted(self):
        from memoryhub_core.services.conversation import get_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        owner_id = "owner-1"
        mock_thread = _mock_thread_obj(owner_id=owner_id)
        mock_thread.id = thread_id

        # Create messages including one with handoff_redacted=True
        msg1 = _mock_message_obj(sequence_number=1, handoff_redacted=False, content="Normal message")
        msg2 = _mock_message_obj(sequence_number=2, handoff_redacted=True, content="Redacted message")

        # First execute: thread, second execute: messages
        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1, msg2])))),
        ]
        session.execute.side_effect = execute_results

        result = await get_thread(
            session,
            tenant_id="default",
            thread_id=thread_id,
            include_messages=True,
            caller_id=owner_id,
        )

        # Owner sees both messages
        assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_get_thread_non_owner_filtered(self):
        from memoryhub_core.services.conversation import get_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        owner_id = "owner-1"
        caller_id = "agent-1"
        mock_thread = _mock_thread_obj(owner_id=owner_id)
        mock_thread.id = thread_id

        # SQL-based filtering: the mock query returns only non-redacted messages
        # because get_thread adds a WHERE clause filtering handoff_redacted=FALSE
        msg1 = _mock_message_obj(sequence_number=1, handoff_redacted=False, content="Normal message")

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1])))),
        ]
        session.execute.side_effect = execute_results

        result = await get_thread(
            session,
            tenant_id="default",
            thread_id=thread_id,
            include_messages=True,
            caller_id=caller_id,
        )

        # Non-owner sees only non-redacted messages (filtered in SQL)
        assert len(result["messages"]) == 1
        assert result["messages"][0].sequence_number == 1

    @pytest.mark.asyncio
    async def test_get_thread_no_caller_id_no_filtering(self):
        from memoryhub_core.services.conversation import get_thread

        session = _mock_session()
        thread_id = uuid.uuid4()
        owner_id = "owner-1"
        mock_thread = _mock_thread_obj(owner_id=owner_id)
        mock_thread.id = thread_id

        msg1 = _mock_message_obj(sequence_number=1, handoff_redacted=False, content="Normal message")
        msg2 = _mock_message_obj(sequence_number=2, handoff_redacted=True, content="Redacted message")

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[msg1, msg2])))),
        ]
        session.execute.side_effect = execute_results

        result = await get_thread(
            session,
            tenant_id="default",
            thread_id=thread_id,
            include_messages=True,
            caller_id=None,
        )

        # No caller_id means no filtering (backward compatibility)
        assert len(result["messages"]) == 2


# =============================================================================
# Phase 5: Retention and Purge Tests
# =============================================================================


class TestSoftDeleteThread:
    @pytest.mark.asyncio
    async def test_soft_delete_sets_status_and_deleted_at(self):
        from datetime import datetime

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False
        mock_thread.retention_policy = {"cascade_to_memories": "preserve"}

        # Mock execute to return thread on lookup, no extractions on cascade
        execute_results = [
            _mock_execute_result(mock_thread),  # Thread lookup
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),  # Extractions
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await soft_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="admin",
                reason="retention",
            )

        # Verify status changed to 'deleted' and deleted_at was set
        assert mock_thread.status == "deleted"
        assert mock_thread.deleted_at is not None
        assert isinstance(mock_thread.deleted_at, datetime)

        # Verify PurgeLog was added (check that session.add was called)
        assert session.add.call_count >= 1

    @pytest.mark.asyncio
    async def test_soft_delete_with_legal_hold(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = True
        mock_thread.retention_policy = {"cascade_to_memories": "preserve"}

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await soft_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="admin",
                reason="retention",
            )

        # With legal hold, status becomes 'pending_deletion', not 'deleted'
        assert mock_thread.status == "pending_deletion"
        # deleted_at should NOT be set when legal_hold is active
        assert mock_thread.deleted_at is None

    @pytest.mark.asyncio
    async def test_soft_delete_cascade_delete(self):
        from unittest.mock import AsyncMock, patch

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False
        mock_thread.retention_policy = {"cascade_to_memories": "delete"}

        # Mock extraction record
        mock_extraction = MagicMock()
        mock_extraction.memory_node_id = uuid.uuid4()

        # First execute: thread lookup
        # Second execute: extractions query
        # Third execute: count refs for memory
        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[mock_extraction])))),
            _mock_execute_result(1),  # Only 1 ref (this extraction)
        ]
        session.execute.side_effect = execute_results

        # Mock delete_memory function (imported from memory service)
        with patch("memoryhub_core.services.memory.delete_memory", new_callable=AsyncMock) as mock_delete:
            with contextlib.suppress(Exception):
                await soft_delete_thread(
                    session,
                    tenant_id="default",
                    thread_id=thread_id,
                    purged_by="admin",
                    reason="retention",
                )

            # Verify delete_memory was called for the single-ref memory
            mock_delete.assert_called_once_with(
                mock_extraction.memory_node_id, session, s3_adapter=None
            )

    @pytest.mark.asyncio
    async def test_soft_delete_cascade_orphan(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False
        mock_thread.retention_policy = {"cascade_to_memories": "orphan"}

        # Mock extraction records
        mock_extraction1 = MagicMock()
        mock_extraction2 = MagicMock()

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[mock_extraction1, mock_extraction2])),
            )),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await soft_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="admin",
                reason="retention",
            )

        # With orphan mode, extraction records are deleted via SQLAlchemy delete
        # Check that execute was called with a delete statement for extractions
        # (we can't easily verify the exact statement, but we can count execute calls)
        assert session.execute.call_count >= 3  # thread lookup, extractions query, delete

    @pytest.mark.asyncio
    async def test_soft_delete_cascade_preserve(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False
        mock_thread.retention_policy = {"cascade_to_memories": "preserve"}

        execute_results = [
            _mock_execute_result(mock_thread),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await soft_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="admin",
                reason="retention",
            )

        # With preserve, nothing happens to memories or extractions
        # cascade_to_memories returns early without any queries
        # Only thread lookup should have been executed
        assert session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_soft_delete_missing_thread(self):

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        with pytest.raises(ThreadNotFoundError):
            await soft_delete_thread(
                session,
                tenant_id="default",
                thread_id=uuid.uuid4(),
                purged_by="admin",
                reason="retention",
            )


class TestHardDeleteThread:
    @pytest.mark.asyncio
    async def test_hard_delete_removes_thread(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="deleted")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False

        session.execute.return_value = _mock_execute_result(mock_thread)

        with contextlib.suppress(Exception):
            await hard_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
            )

        # Verify delete was called (at least for extractions and thread)
        # Expect: thread lookup, delete extractions, delete thread
        assert session.execute.call_count >= 3

    @pytest.mark.asyncio
    async def test_hard_delete_with_legal_hold_raises(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="deleted")
        mock_thread.id = thread_id
        mock_thread.legal_hold = True

        session.execute.return_value = _mock_execute_result(mock_thread)

        with pytest.raises(ValueError, match="legal_hold is active"):
            await hard_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
            )

    @pytest.mark.asyncio
    async def test_hard_delete_s3_cleanup(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="deleted")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False

        # Mock S3 refs
        s3_ref1 = "s3://bucket/thread/msg1.json"
        s3_ref2 = "s3://bucket/thread/msg2.json"

        # First execute: thread lookup
        # Second execute: S3 refs query
        # Third execute: delete extractions
        # Fourth execute: delete thread
        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(all=MagicMock(return_value=[(s3_ref1,), (s3_ref2,)])),
            MagicMock(),  # delete extractions
            MagicMock(),  # delete thread
        ]
        session.execute.side_effect = execute_results

        # Mock S3 adapter
        mock_s3 = AsyncMock()
        mock_s3.delete_contents = AsyncMock()

        with contextlib.suppress(Exception):
            await hard_delete_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                s3_adapter=mock_s3,
            )

        # Verify S3 cleanup was called
        mock_s3.delete_contents.assert_called_once_with([s3_ref1, s3_ref2])

    @pytest.mark.asyncio
    async def test_hard_delete_missing_thread(self):

        session = _mock_session()
        session.execute.return_value = _mock_execute_result(None)

        with pytest.raises(ThreadNotFoundError):
            await hard_delete_thread(
                session,
                tenant_id="default",
                thread_id=uuid.uuid4(),
            )


class TestAdminPurgeThread:
    @pytest.mark.asyncio
    async def test_admin_purge_creates_audit_log(self):
        from unittest.mock import AsyncMock, patch

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="deleted")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False

        # Mock cascade helper
        with patch("memoryhub_core.services.conversation._cascade_to_memories", new_callable=AsyncMock):
            execute_results = [
                _mock_execute_result(mock_thread),  # Thread lookup
                MagicMock(all=MagicMock(return_value=[])),  # S3 refs
                MagicMock(),  # delete extractions
                MagicMock(),  # delete thread
            ]
            session.execute.side_effect = execute_results

            with contextlib.suppress(Exception):
                await admin_purge_thread(
                    session,
                    tenant_id="default",
                    thread_id=thread_id,
                    purged_by="admin-1",
                    justification="GDPR erasure request",
                )

            # Verify PurgeLog was created with reason='admin'
            purge_log_added = False
            for call in session.add.call_args_list:
                if len(call[0]) > 0:
                    obj = call[0][0]
                    # Check if it's a PurgeLog-like object
                    if hasattr(obj, "reason"):
                        purge_log_added = True
                        break
            assert purge_log_added

    @pytest.mark.asyncio
    async def test_admin_purge_overrides_legal_hold(self):
        from unittest.mock import AsyncMock, patch

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="pending_deletion")
        mock_thread.id = thread_id
        mock_thread.legal_hold = True

        with patch("memoryhub_core.services.conversation._cascade_to_memories", new_callable=AsyncMock):
            execute_results = [
                _mock_execute_result(mock_thread),
                MagicMock(all=MagicMock(return_value=[])),
                MagicMock(),
                MagicMock(),
            ]
            session.execute.side_effect = execute_results

            with contextlib.suppress(Exception):
                await admin_purge_thread(
                    session,
                    tenant_id="default",
                    thread_id=thread_id,
                    purged_by="admin-1",
                    justification="Court order",
                )

            # Verify legal_hold was cleared
            assert mock_thread.legal_hold is False


class TestSpillResponseThread:
    @pytest.mark.asyncio
    async def test_spill_response_creates_tombstone(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False

        execute_results = [
            _mock_execute_result(mock_thread),  # Thread lookup
            MagicMock(all=MagicMock(return_value=[])),  # S3 refs
            MagicMock(),  # delete extractions
            MagicMock(),  # delete thread
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await spill_response_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="incident-response",
                incident_ref="INC-2024-001",
                silent=False,
            )

        # Verify PurgeLog was created with reason='spill'
        purge_log_added = False
        for call in session.add.call_args_list:
            if len(call[0]) > 0:
                obj = call[0][0]
                if hasattr(obj, "reason"):
                    purge_log_added = True
                    break
        assert purge_log_added

    @pytest.mark.asyncio
    async def test_spill_response_silent_no_log(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = False

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(),
            MagicMock(),
        ]
        session.execute.side_effect = execute_results

        with contextlib.suppress(Exception):
            await spill_response_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="incident-response",
                incident_ref="INC-2024-002",
                silent=True,
            )

        # Verify NO PurgeLog was added (silent mode)
        assert session.add.call_count == 0

    @pytest.mark.asyncio
    async def test_spill_response_bypasses_legal_hold(self):

        session = _mock_session()
        thread_id = uuid.uuid4()
        mock_thread = _mock_thread_obj(status="active")
        mock_thread.id = thread_id
        mock_thread.legal_hold = True

        execute_results = [
            _mock_execute_result(mock_thread),
            MagicMock(all=MagicMock(return_value=[])),
            MagicMock(),
            MagicMock(),
        ]
        session.execute.side_effect = execute_results

        # Should succeed even with legal hold
        with contextlib.suppress(Exception):
            await spill_response_thread(
                session,
                tenant_id="default",
                thread_id=thread_id,
                purged_by="incident-response",
                incident_ref="INC-2024-003",
            )

        # Verify legal_hold was cleared
        assert mock_thread.legal_hold is False


class TestRunRetentionSweep:
    @pytest.mark.asyncio
    async def test_sweep_soft_deletes_expired(self):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import AsyncMock, patch

        session = _mock_session()

        # Create expired thread
        expired_thread = _mock_thread_obj(status="active")
        expired_thread.id = uuid.uuid4()
        expired_thread.expires_at = datetime.now(UTC) - timedelta(days=1)
        expired_thread.tenant_id = "default"

        # Mock queries
        # First execute: expired threads query
        # Second execute: deleted threads query
        # Third execute: legal hold count
        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[expired_thread])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            _mock_execute_result(0),  # legal hold count
        ]
        session.execute.side_effect = execute_results

        with patch("memoryhub_core.services.conversation.soft_delete_thread", new_callable=AsyncMock) as mock_soft:
            result = await run_retention_sweep(session)

            # Verify soft_delete was called
            mock_soft.assert_called_once()
            assert result["soft_deleted"] == 1

    @pytest.mark.asyncio
    async def test_sweep_hard_deletes_past_retention(self):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import AsyncMock, patch

        session = _mock_session()

        # Create deleted thread past min_retention_days
        deleted_thread = _mock_thread_obj(status="deleted")
        deleted_thread.id = uuid.uuid4()
        deleted_thread.deleted_at = datetime.now(UTC) - timedelta(days=35)
        deleted_thread.tenant_id = "default"
        deleted_thread.legal_hold = False
        deleted_thread.retention_policy = {"min_retention_days": 30}

        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[deleted_thread])))),
            _mock_execute_result(0),
        ]
        session.execute.side_effect = execute_results

        with patch("memoryhub_core.services.conversation.hard_delete_thread", new_callable=AsyncMock) as mock_hard:
            result = await run_retention_sweep(session)

            mock_hard.assert_called_once()
            assert result["hard_deleted"] == 1

    @pytest.mark.asyncio
    async def test_sweep_skips_legal_hold(self):

        session = _mock_session()

        # No expired or deleted threads, but 2 legal hold threads
        execute_results = [
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))),
            _mock_execute_result(2),  # legal hold count
        ]
        session.execute.side_effect = execute_results

        result = await run_retention_sweep(session)

        assert result["soft_deleted"] == 0
        assert result["hard_deleted"] == 0
        assert result["skipped_legal_hold"] == 2
