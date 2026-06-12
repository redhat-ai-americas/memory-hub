"""Tests for conversation persistence Pydantic schemas."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from memoryhub_core.models.schemas import (
    AccessLevel,
    ConversationExtractionRead,
    ConversationMessageCreate,
    ConversationMessageRead,
    ConversationThreadCreate,
    ConversationThreadRead,
    MemoryScope,
    MessageRole,
    PurgeLogRead,
    PurgeReason,
    StorageType,
    ThreadStatus,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestThreadStatus:
    def test_valid_statuses(self):
        for value in ("active", "archived", "deleted"):
            assert ThreadStatus(value) == value

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="'completed' is not a valid ThreadStatus"):
            ThreadStatus("completed")


class TestMessageRole:
    def test_valid_roles(self):
        for value in ("user", "assistant", "tool_call", "tool_result", "system"):
            assert MessageRole(value) == value

    def test_invalid_role(self):
        with pytest.raises(ValueError, match="'narrator' is not a valid MessageRole"):
            MessageRole("narrator")

    def test_role_string_behavior(self):
        """StrEnum values work as plain strings."""
        assert MessageRole.USER == "user"
        assert f"role={MessageRole.ASSISTANT}" == "role=assistant"


class TestAccessLevel:
    def test_valid_levels(self):
        for value in ("read", "write", "admin"):
            assert AccessLevel(value) == value

    def test_invalid_level(self):
        with pytest.raises(ValueError, match="'superadmin' is not a valid AccessLevel"):
            AccessLevel("superadmin")


class TestPurgeReason:
    def test_valid_reasons(self):
        for value in ("retention", "admin", "gdpr", "spill"):
            assert PurgeReason(value) == value

    def test_invalid_reason(self):
        with pytest.raises(ValueError, match="'unknown' is not a valid PurgeReason"):
            PurgeReason("unknown")


# ---------------------------------------------------------------------------
# ConversationThreadCreate
# ---------------------------------------------------------------------------


class TestConversationThreadCreate:
    def test_minimal_create(self):
        thread = ConversationThreadCreate(scope="user")
        assert thread.scope == MemoryScope.USER
        assert thread.title is None
        assert thread.participant_ids == []
        assert thread.participant_access is None
        assert thread.metadata is None

    def test_full_create(self):
        thread = ConversationThreadCreate(
            scope="project",
            title="Design review",
            participant_ids=["agent-1", "user-2"],
            participant_access={"agent-1": "read", "user-2": "write"},
            metadata={"session_id": "abc123"},
        )
        assert thread.scope == MemoryScope.PROJECT
        assert thread.title == "Design review"
        assert thread.participant_ids == ["agent-1", "user-2"]
        assert thread.participant_access == {"agent-1": "read", "user-2": "write"}
        assert thread.metadata == {"session_id": "abc123"}

    def test_participant_access_valid(self):
        thread = ConversationThreadCreate(
            scope="user",
            participant_access={"agent-1": "read", "user-2": "write"},
        )
        assert thread.participant_access == {"agent-1": "read", "user-2": "write"}

    def test_participant_access_invalid_level(self):
        with pytest.raises(ValidationError, match="participant_access"):
            ConversationThreadCreate(
                scope="user",
                participant_access={"agent-1": "superadmin"},
            )

    def test_participant_access_empty_dict(self):
        thread = ConversationThreadCreate(scope="user", participant_access={})
        assert thread.participant_access == {}

    def test_participant_access_none(self):
        thread = ConversationThreadCreate(scope="user", participant_access=None)
        assert thread.participant_access is None

    def test_invalid_scope_rejected(self):
        with pytest.raises(ValidationError, match="scope"):
            ConversationThreadCreate(scope="galaxy")


# ---------------------------------------------------------------------------
# ConversationThreadRead
# ---------------------------------------------------------------------------


def _make_thread_read_data(**overrides) -> dict:
    """Build a complete ConversationThreadRead-compatible dict."""
    base = {
        "id": uuid.uuid4(),
        "scope": "user",
        "owner_id": "user-1",
        "tenant_id": "default",
        "status": "active",
        "legal_hold": False,
        "extraction_cursor": 0,
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return base


class TestConversationThreadRead:
    def test_round_trip(self):
        data = _make_thread_read_data()
        thread = ConversationThreadRead(**data)
        assert thread.id == data["id"]
        assert thread.scope == MemoryScope.USER
        assert thread.status == ThreadStatus.ACTIVE
        assert thread.legal_hold is False
        assert thread.extraction_cursor == 0

    def test_with_participants(self):
        data = _make_thread_read_data(
            participant_ids=["agent-1", "user-2"],
            participant_access={"agent-1": "read", "user-2": "write"},
        )
        thread = ConversationThreadRead(**data)
        assert thread.participant_ids == ["agent-1", "user-2"]
        assert thread.participant_access == {"agent-1": "read", "user-2": "write"}

    def test_json_round_trip(self):
        data = _make_thread_read_data()
        thread = ConversationThreadRead(**data)
        json_str = thread.model_dump_json()
        restored = ConversationThreadRead.model_validate_json(json_str)
        assert restored.id == thread.id
        assert restored.scope == thread.scope
        assert restored.status == thread.status

    def test_metadata_alias(self):
        data = _make_thread_read_data(metadata_={"session": "xyz"})
        thread = ConversationThreadRead(**data)
        assert thread.metadata == {"session": "xyz"}


# ---------------------------------------------------------------------------
# ConversationMessageCreate
# ---------------------------------------------------------------------------


class TestConversationMessageCreate:
    def test_valid_message(self):
        thread_id = uuid.uuid4()
        msg = ConversationMessageCreate(
            thread_id=thread_id,
            role="user",
            content="Hello, world!",
        )
        assert msg.thread_id == thread_id
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello, world!"
        assert msg.tool_call_id is None

    def test_nullable_content(self):
        msg = ConversationMessageCreate(
            thread_id=uuid.uuid4(),
            role="assistant",
            content=None,
        )
        assert msg.content is None

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError, match="role"):
            ConversationMessageCreate(
                thread_id=uuid.uuid4(),
                role="narrator",
                content="test",
            )

    def test_with_tool_call_id(self):
        msg = ConversationMessageCreate(
            thread_id=uuid.uuid4(),
            role="tool_result",
            content="result data",
            tool_call_id="call-123",
        )
        assert msg.tool_call_id == "call-123"


# ---------------------------------------------------------------------------
# ConversationMessageRead
# ---------------------------------------------------------------------------


def _make_message_read_data(**overrides) -> dict:
    """Build a complete ConversationMessageRead-compatible dict."""
    base = {
        "id": uuid.uuid4(),
        "thread_id": uuid.uuid4(),
        "sequence_number": 1,
        "role": "user",
        "storage_type": "inline",
        "content": "Hello",
        "handoff_redacted": False,
        "tenant_id": "default",
        "created_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return base


class TestConversationMessageRead:
    def test_round_trip(self):
        data = _make_message_read_data()
        msg = ConversationMessageRead(**data)
        assert msg.id == data["id"]
        assert msg.thread_id == data["thread_id"]
        assert msg.sequence_number == 1
        assert msg.role == MessageRole.USER
        assert msg.storage_type == StorageType.INLINE
        assert msg.content == "Hello"
        assert msg.handoff_redacted is False

    def test_s3_storage(self):
        data = _make_message_read_data(
            storage_type="s3",
            content=None,
            content_ref="threads/default/abc/1",
        )
        msg = ConversationMessageRead(**data)
        assert msg.storage_type == StorageType.S3
        assert msg.content is None
        assert msg.content_ref == "threads/default/abc/1"

    def test_json_round_trip(self):
        data = _make_message_read_data()
        msg = ConversationMessageRead(**data)
        json_str = msg.model_dump_json()
        restored = ConversationMessageRead.model_validate_json(json_str)
        assert restored.id == msg.id
        assert restored.thread_id == msg.thread_id
        assert restored.sequence_number == msg.sequence_number


# ---------------------------------------------------------------------------
# ConversationExtractionRead
# ---------------------------------------------------------------------------


class TestConversationExtractionRead:
    def test_round_trip(self):
        extraction = ConversationExtractionRead(
            id=uuid.uuid4(),
            memory_node_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            source_messages=[1, 2, 3],
            extracted_by="extraction-pipeline",
            extraction_model="claude-haiku-4-5",
            tenant_id="default",
            created_at=datetime.now(tz=UTC),
        )
        assert len(extraction.source_messages) == 3
        assert extraction.source_messages == [1, 2, 3]
        assert extraction.extracted_by == "extraction-pipeline"
        assert extraction.extraction_model == "claude-haiku-4-5"

    def test_empty_source_messages(self):
        extraction = ConversationExtractionRead(
            id=uuid.uuid4(),
            memory_node_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            extracted_by="pipeline",
            tenant_id="default",
            created_at=datetime.now(tz=UTC),
        )
        assert extraction.source_messages == []

    def test_json_round_trip(self):
        extraction = ConversationExtractionRead(
            id=uuid.uuid4(),
            memory_node_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            source_messages=[5, 6],
            extracted_by="pipeline",
            tenant_id="default",
            created_at=datetime.now(tz=UTC),
        )
        json_str = extraction.model_dump_json()
        restored = ConversationExtractionRead.model_validate_json(json_str)
        assert restored.id == extraction.id
        assert restored.source_messages == [5, 6]


# ---------------------------------------------------------------------------
# PurgeLogRead
# ---------------------------------------------------------------------------


class TestPurgeLogRead:
    def test_round_trip(self):
        log = PurgeLogRead(
            id=uuid.uuid4(),
            resource_type="thread",
            resource_id=uuid.uuid4(),
            purged_by="admin-user",
            reason="retention",
            incident_ref="INC-2026-123",
            purged_at=datetime.now(tz=UTC),
        )
        assert log.reason == PurgeReason.RETENTION
        assert log.incident_ref == "INC-2026-123"
        assert log.resource_type == "thread"
        assert log.purged_by == "admin-user"

    def test_without_incident_ref(self):
        log = PurgeLogRead(
            id=uuid.uuid4(),
            resource_type="memory",
            resource_id=uuid.uuid4(),
            purged_by="retention-sweep",
            reason="admin",
            purged_at=datetime.now(tz=UTC),
        )
        assert log.incident_ref is None

    def test_invalid_reason(self):
        with pytest.raises(ValidationError, match="reason"):
            PurgeLogRead(
                id=uuid.uuid4(),
                resource_type="thread",
                resource_id=uuid.uuid4(),
                purged_by="admin",
                reason="unknown",
                purged_at=datetime.now(tz=UTC),
            )


# ---------------------------------------------------------------------------
# Participant Access Validation
# ---------------------------------------------------------------------------


class TestParticipantAccessValidation:
    def test_valid_mixed_levels(self):
        thread = ConversationThreadCreate(
            scope="project",
            participant_access={
                "agent-1": "read",
                "agent-2": "write",
                "admin-1": "admin",
            },
        )
        assert thread.participant_access == {
            "agent-1": "read",
            "agent-2": "write",
            "admin-1": "admin",
        }

    def test_rejects_invalid_level(self):
        with pytest.raises(ValidationError, match="participant_access"):
            ConversationThreadCreate(
                scope="user",
                participant_access={"agent-1": "superuser"},
            )

    def test_empty_dict_valid(self):
        thread = ConversationThreadCreate(scope="user", participant_access={})
        assert thread.participant_access == {}

    def test_none_valid(self):
        thread = ConversationThreadCreate(scope="user", participant_access=None)
        assert thread.participant_access is None
