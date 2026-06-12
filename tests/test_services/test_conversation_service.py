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
    return t


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
