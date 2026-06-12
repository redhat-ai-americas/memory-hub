"""Tests for conversation extraction pipeline service.

Uses mock AsyncSession to avoid SQLite ARRAY column compatibility issues.
Integration tests against PostgreSQL are in tests/integration/.
"""

import hashlib
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memoryhub_core.services.conversation_extraction import (
    _call_extraction_llm,
    _compute_windows,
    _extract_window,
    _format_messages,
    _load_prompt,
    _parse_json_best_effort,
    extract_from_thread,
)


# Mock helpers
def _mock_message(seq: int, role: str = "user", content: str = "test") -> MagicMock:
    """Create a mock that looks like a ConversationMessage ORM object."""
    msg = MagicMock()
    msg.sequence_number = seq
    msg.role = role
    msg.content = content
    return msg


def _mock_thread(
    thread_id=None,
    tenant_id="test-tenant",
    owner_id="test-owner",
    scope="user",
    extraction_cursor=0,
    retention_policy=None,
) -> MagicMock:
    """Create a mock that looks like a ConversationThread ORM object."""
    thread = MagicMock()
    thread.id = thread_id or uuid.uuid4()
    thread.tenant_id = tenant_id
    thread.owner_id = owner_id
    thread.scope = scope
    thread.scope_id = None
    thread.actor_id = None
    thread.extraction_cursor = extraction_cursor
    thread.retention_policy = retention_policy
    thread.deleted_at = None
    return thread


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


# Unit tests (no mocking needed)

class TestFormatMessages:
    def test_format_messages_produces_readable_transcript(self):
        messages = [
            _mock_message(seq=1, role="user", content="Hello"),
            _mock_message(seq=2, role="assistant", content="Hi there"),
            _mock_message(seq=3, role="user", content="How are you?"),
        ]
        result = _format_messages(messages)
        assert "[USER] (seq=1): Hello" in result
        assert "[ASSISTANT] (seq=2): Hi there" in result
        assert "[USER] (seq=3): How are you?" in result
        assert result.count("\n") == 2  # Three lines with 2 newlines

    def test_format_messages_handles_none_content(self):
        msg = _mock_message(seq=1, role="user", content=None)
        result = _format_messages([msg])
        assert "[USER] (seq=1): [content stored in S3]" in result


class TestParseJsonBestEffort:
    def test_parse_json_best_effort_valid_json(self):
        result = _parse_json_best_effort('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_best_effort_code_fence(self):
        result = _parse_json_best_effort('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_best_effort_code_fence_no_lang(self):
        result = _parse_json_best_effort('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_best_effort_invalid_json(self):
        result = _parse_json_best_effort("not json at all")
        assert result is None

    def test_parse_json_best_effort_empty_string(self):
        result = _parse_json_best_effort("")
        assert result is None


class TestComputeWindows:
    def test_compute_windows_per_turn_default(self):
        messages = [
            _mock_message(1, "user", "Hello"),
            _mock_message(2, "assistant", "Hi"),
            _mock_message(3, "user", "How are you?"),
            _mock_message(4, "assistant", "I'm good"),
        ]
        windows = _compute_windows(messages, mode="per_turn", window_size=4)

        assert len(windows) == 2
        assert len(windows[0]) == 2  # user + assistant
        assert len(windows[1]) == 2  # user + assistant

    def test_compute_windows_per_session_all_in_one(self):
        messages = [
            _mock_message(1, "user", "A"),
            _mock_message(2, "assistant", "B"),
            _mock_message(3, "user", "C"),
        ]
        windows = _compute_windows(messages, mode="per_session", window_size=4)

        assert len(windows) == 1
        assert len(windows[0]) == 3

    def test_compute_windows_per_message_one_each(self):
        messages = [
            _mock_message(1, "user", "A"),
            _mock_message(2, "assistant", "B"),
            _mock_message(3, "user", "C"),
        ]
        windows = _compute_windows(messages, mode="per_message", window_size=4)

        assert len(windows) == 3
        assert len(windows[0]) == 1
        assert len(windows[1]) == 1
        assert len(windows[2]) == 1

    def test_compute_windows_empty_list(self):
        windows = _compute_windows([], mode="per_turn", window_size=4)
        assert windows == []

    def test_compute_windows_respects_window_size_limit(self):
        # Create 6 user messages in a row (no assistant to trigger turn end)
        messages = [_mock_message(i, "user", f"msg{i}") for i in range(1, 7)]
        windows = _compute_windows(messages, mode="per_turn", window_size=4)

        # Should split at window_size=4 since there's no turn boundary
        assert len(windows) == 2
        assert len(windows[0]) == 4
        assert len(windows[1]) == 2


class TestLoadPrompt:
    def test_load_prompt_returns_system_prompt_and_hash(self):
        system_prompt, prompt_hash = _load_prompt()

        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0
        assert isinstance(prompt_hash, str)
        assert len(prompt_hash) == 64  # SHA-256 hex string

        # Verify the hash matches the prompt
        expected_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
        assert prompt_hash == expected_hash

    def test_load_prompt_caches_result(self):
        from memoryhub_core.services.conversation_extraction import _prompt_cache

        # Clear cache
        _prompt_cache.clear()

        # Load twice
        result1 = _load_prompt()
        result2 = _load_prompt()

        # Should return equal values (cached)
        assert result1 == result2
        # Verify cache was populated
        assert "default" in _prompt_cache


# Integration tests (with mocking)

class TestExtractWindow:
    @pytest.mark.asyncio
    async def test_extract_window_creates_memories(self):
        from memoryhub_core.models.conversation import ConversationExtraction

        session = _mock_session()
        thread = _mock_thread()
        messages = [_mock_message(1, "user", "Important fact")]

        mock_memory_node = MagicMock()
        mock_memory_node.id = uuid.uuid4()

        with patch("memoryhub_core.services.memory.create_memory") as mock_create:
            mock_create.return_value = (mock_memory_node, {"blocked": False})

            with patch("memoryhub_core.services.conversation_extraction._call_extraction_llm") as mock_llm:
                mock_llm.return_value = [
                    {"content": "User prefers concise answers", "weight": 0.8}
                ]

                mock_embedding = MagicMock()
                result = await _extract_window(
                    session,
                    thread=thread,
                    messages=messages,
                    model="test-model",
                    url="http://test",
                    client=MagicMock(),
                    embedding_service=mock_embedding,
                )

        # Verify create_memory was called with correct scope/owner/tenant
        assert mock_create.call_count == 1
        call_args = mock_create.call_args
        memory_data = call_args[0][0]
        assert memory_data.scope == thread.scope
        assert memory_data.owner_id == thread.owner_id
        assert call_args[1]["tenant_id"] == thread.tenant_id

        # Verify provenance record was created
        assert session.add.call_count == 1
        extraction_record = session.add.call_args[0][0]
        assert isinstance(extraction_record, ConversationExtraction)
        assert extraction_record.memory_node_id == mock_memory_node.id
        assert extraction_record.thread_id == thread.id
        assert extraction_record.source_messages == [1]
        assert extraction_record.extraction_model == "test-model"
        assert len(extraction_record.extraction_prompt_hash) == 64  # SHA-256

        # Verify result
        assert result == [mock_memory_node.id]
        assert session.commit.called

    @pytest.mark.asyncio
    async def test_extract_window_curation_blocks(self):
        session = _mock_session()
        thread = _mock_thread()
        messages = [_mock_message(1, "user", "spam")]

        with patch("memoryhub_core.services.memory.create_memory") as mock_create:
            # Curation blocks the memory
            mock_create.return_value = (None, {"blocked": True, "reason": "low quality"})

            with patch("memoryhub_core.services.conversation_extraction._call_extraction_llm") as mock_llm:
                mock_llm.return_value = [{"content": "spam content", "weight": 0.9}]

                mock_embedding = MagicMock()
                result = await _extract_window(
                    session,
                    thread=thread,
                    messages=messages,
                    model="test-model",
                    url="http://test",
                    client=MagicMock(),
                    embedding_service=mock_embedding,
                )

        # No provenance record should be created
        assert session.add.call_count == 0
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_window_filters_low_weight(self):
        session = _mock_session()
        thread = _mock_thread()
        messages = [_mock_message(1, "user", "test")]

        with patch("memoryhub_core.services.conversation_extraction._call_extraction_llm") as mock_llm:
            # LLM returns extraction with weight below 0.5 threshold
            mock_llm.return_value = [{"content": "irrelevant", "weight": 0.3}]

            mock_embedding = MagicMock()
            result = await _extract_window(
                session,
                thread=thread,
                messages=messages,
                model="test-model",
                url="http://test",
                client=MagicMock(),
                embedding_service=mock_embedding,
            )

        # Should skip the extraction
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_window_filters_empty_content(self):
        session = _mock_session()
        thread = _mock_thread()
        messages = [_mock_message(1, "user", "test")]

        with patch("memoryhub_core.services.conversation_extraction._call_extraction_llm") as mock_llm:
            # LLM returns extraction with empty content
            mock_llm.return_value = [{"content": "", "weight": 0.9}]

            mock_embedding = MagicMock()
            result = await _extract_window(
                session,
                thread=thread,
                messages=messages,
                model="test-model",
                url="http://test",
                client=MagicMock(),
                embedding_service=mock_embedding,
            )

        # Should skip the extraction
        assert result == []


class TestExtractFromThread:
    @pytest.mark.asyncio
    async def test_extract_from_thread_advances_cursor(self):
        session = _mock_session()
        thread_id = uuid.uuid4()
        thread = _mock_thread(thread_id=thread_id, extraction_cursor=0)

        # Mock thread query
        session.execute.return_value = _mock_execute_result(thread)

        # Mock messages query
        messages = [
            _mock_message(1, "user", "Hello"),
            _mock_message(2, "assistant", "Hi"),
        ]
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = messages
        session.execute.side_effect = [
            _mock_execute_result(thread),  # Thread query
            msg_result,  # Messages query
        ]

        with patch("memoryhub_core.services.conversation_extraction._extract_window") as mock_extract:
            mock_extract.return_value = [uuid.uuid4()]

            mock_embedding = MagicMock()
            result = await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                model_override="test-model",
                url_override="http://test",
            )

        # Cursor should advance to last message sequence
        assert thread.extraction_cursor == 2
        assert thread.last_extracted_at is not None
        assert isinstance(thread.last_extracted_at, datetime)
        assert result["extracted_count"] == 1
        assert result["cursor"] == 2

    @pytest.mark.asyncio
    async def test_extract_from_thread_no_messages(self):
        session = _mock_session()
        thread_id = uuid.uuid4()
        thread = _mock_thread(thread_id=thread_id, extraction_cursor=10)

        # Mock thread query
        session.execute.return_value = _mock_execute_result(thread)

        # Mock empty messages query
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = []
        session.execute.side_effect = [
            _mock_execute_result(thread),
            msg_result,
        ]

        mock_embedding = MagicMock()
        result = await extract_from_thread(
            session,
            thread_id=thread_id,
            tenant_id="test-tenant",
            owner_id="test-owner",
            embedding_service=mock_embedding,
            model_override="test-model",
            url_override="http://test",
        )

        assert result["extracted_count"] == 0
        assert result["cursor"] == 10
        assert result["failures"] == 0

    @pytest.mark.asyncio
    async def test_extract_from_thread_turn_range_override(self):
        session = _mock_session()
        thread_id = uuid.uuid4()
        thread = _mock_thread(thread_id=thread_id, extraction_cursor=0)

        # Mock thread query
        session.execute.return_value = _mock_execute_result(thread)

        # Mock messages query - should only get messages 3-6
        messages = [
            _mock_message(3, "user", "msg3"),
            _mock_message(4, "assistant", "msg4"),
            _mock_message(5, "user", "msg5"),
            _mock_message(6, "assistant", "msg6"),
        ]
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = messages
        session.execute.side_effect = [
            _mock_execute_result(thread),
            msg_result,
        ]

        with patch("memoryhub_core.services.conversation_extraction._extract_window") as mock_extract:
            mock_extract.return_value = [uuid.uuid4()]

            mock_embedding = MagicMock()
            result = await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                model_override="test-model",
                url_override="http://test",
                turn_range=(3, 6),
            )

        # With turn_range, cursor should NOT advance
        assert thread.extraction_cursor == 0
        assert result["extracted_count"] == 2  # 2 windows

    @pytest.mark.asyncio
    async def test_extract_from_thread_logs_failure_to_db(self):
        from memoryhub_core.models.conversation import ConversationExtractionFailure

        session = _mock_session()
        thread_id = uuid.uuid4()
        thread = _mock_thread(thread_id=thread_id)

        session.execute.return_value = _mock_execute_result(thread)

        messages = [_mock_message(1, "user", "test")]
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = messages
        session.execute.side_effect = [
            _mock_execute_result(thread),
            msg_result,
        ]

        with patch("memoryhub_core.services.conversation_extraction._extract_window") as mock_extract:
            mock_extract.side_effect = ValueError("LLM error")

            mock_embedding = MagicMock()
            result = await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                model_override="test-model",
                url_override="http://test",
            )

        # Should have logged failure
        assert result["failures"] == 1
        assert result["extracted_count"] == 0

        # Verify failure record was created
        failure_record = None
        for call in session.add.call_args_list:
            arg = call[0][0]
            if isinstance(arg, ConversationExtractionFailure):
                failure_record = arg
                break

        assert failure_record is not None
        assert failure_record.thread_id == thread_id
        assert failure_record.window_start == 1
        assert failure_record.window_end == 1
        assert "LLM error" in failure_record.last_error

    @pytest.mark.asyncio
    async def test_extract_from_thread_mode_from_retention_policy(self):
        session = _mock_session()
        thread_id = uuid.uuid4()
        thread = _mock_thread(
            thread_id=thread_id,
            retention_policy={"extraction_mode": "per_session"}
        )

        session.execute.return_value = _mock_execute_result(thread)

        messages = [
            _mock_message(1, "user", "A"),
            _mock_message(2, "assistant", "B"),
            _mock_message(3, "user", "C"),
        ]
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = messages
        session.execute.side_effect = [
            _mock_execute_result(thread),
            msg_result,
        ]

        with patch("memoryhub_core.services.conversation_extraction._extract_window") as mock_extract:
            mock_extract.return_value = [uuid.uuid4()]

            mock_embedding = MagicMock()
            await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                model_override="test-model",
                url_override="http://test",
            )

        # Should only call _extract_window once (per_session mode)
        assert mock_extract.call_count == 1
        # All messages in one window
        window_messages = mock_extract.call_args[1]["messages"]
        assert len(window_messages) == 3

    @pytest.mark.asyncio
    async def test_extract_from_thread_missing_config_raises(self):

        session = _mock_session()
        thread_id = uuid.uuid4()

        # Thread exists
        thread = _mock_thread(thread_id=thread_id)
        session.execute.return_value = _mock_execute_result(thread)

        mock_embedding = MagicMock()

        # Missing model and URL (empty strings from settings)
        with pytest.raises(ValueError, match="Extraction model and URL must be configured"):
            await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                # No overrides, settings will return empty strings
            )

    @pytest.mark.asyncio
    async def test_extract_from_thread_not_found_raises(self):
        from memoryhub_core.services.exceptions import ThreadNotFoundError

        session = _mock_session()
        thread_id = uuid.uuid4()

        # Thread not found
        session.execute.return_value = _mock_execute_result(None)

        mock_embedding = MagicMock()
        with pytest.raises(ThreadNotFoundError):
            await extract_from_thread(
                session,
                thread_id=thread_id,
                tenant_id="test-tenant",
                owner_id="test-owner",
                embedding_service=mock_embedding,
                model_override="test-model",
                url_override="http://test",
            )


class TestCallExtractionLLM:
    @pytest.mark.asyncio
    async def test_call_extraction_llm_retry_on_error(self):
        import httpx

        formatted = "[USER]: Hello"
        system_prompt = "You are a memory extractor"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"extractions": []}'}}]
        }

        call_count = [0]

        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise httpx.ConnectError("Connection error")
            return mock_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post_side_effect)

        with patch("asyncio.sleep"):
            result = await _call_extraction_llm(
                formatted,
                system_prompt,
                client=mock_client,
                model="test-model",
                url="http://test",
            )

        assert call_count[0] == 3
        assert result == []

    @pytest.mark.asyncio
    async def test_call_extraction_llm_logs_failure_after_max_retries(self):
        import httpx

        formatted = "[USER]: Hello"
        system_prompt = "You are a memory extractor"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection error"))

        with patch("asyncio.sleep"), pytest.raises(httpx.ConnectError):
            await _call_extraction_llm(
                formatted,
                system_prompt,
                client=mock_client,
                model="test-model",
                url="http://test",
            )

        # 4 attempts: 1 initial + 1 immediate retry + 2 backoff
        assert mock_client.post.call_count == 4

    @pytest.mark.asyncio
    async def test_call_extraction_llm_success(self):
        formatted = "[USER]: Remember that I like Python"
        system_prompt = "You are a memory extractor"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"extractions": [{"content": "User prefers Python", "weight": 0.9}]}'
                }
            }]
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await _call_extraction_llm(
            formatted,
            system_prompt,
            client=mock_client,
            model="test-model",
            url="http://test",
        )

        assert len(result) == 1
        assert result[0]["content"] == "User prefers Python"
        assert result[0]["weight"] == 0.9
