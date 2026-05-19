"""Tests for extraction pipeline data models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memoryhub.extraction.models import (
    CandidateMemory,
    ExtractionResult,
    TraceEvent,
    TraceEventType,
)

# ── TraceEvent classmethod constructors ──────────────────────────────────────


def test_user_message_constructor():
    event = TraceEvent.user_message("I prefer FastAPI over Flask")
    assert event.event_type == TraceEventType.USER_MESSAGE
    assert event.content == "I prefer FastAPI over Flask"
    assert event.tool_name is None


def test_assistant_message_constructor():
    event = TraceEvent.assistant_message("Created the API endpoint")
    assert event.event_type == TraceEventType.ASSISTANT_MESSAGE
    assert event.content == "Created the API endpoint"
    assert event.tool_name is None


def test_reasoning_constructor():
    event = TraceEvent.reasoning("Considering whether to use Redis or Valkey")
    assert event.event_type == TraceEventType.REASONING
    assert event.content == "Considering whether to use Redis or Valkey"


def test_tool_call_constructor_default_content():
    event = TraceEvent.tool_call(name="read_file", args={"path": "/tmp/test.txt"})
    assert event.event_type == TraceEventType.TOOL_CALL
    assert event.content == "Tool call: read_file"
    assert event.tool_name == "read_file"
    assert event.tool_args == {"path": "/tmp/test.txt"}


def test_tool_call_constructor_custom_content():
    event = TraceEvent.tool_call(
        name="search_docs", args={"query": "FastAPI"}, content="Custom content"
    )
    assert event.content == "Custom content"
    assert event.tool_name == "search_docs"


def test_tool_call_with_result():
    event = TraceEvent.tool_call(
        name="execute_command", args={"cmd": "ls"}, result="file1.txt\nfile2.txt"
    )
    assert event.tool_result == "file1.txt\nfile2.txt"


# ── TraceEvent immutability ──────────────────────────────────────────────────


def test_trace_event_is_frozen():
    event = TraceEvent.user_message("test")
    with pytest.raises((AttributeError, Exception)):
        event.content = "modified"  # type: ignore[misc]


# ── TraceEvent metadata and timestamp ────────────────────────────────────────


def test_trace_event_metadata():
    event = TraceEvent.user_message("test", metadata={"key": "value"})
    assert event.metadata == {"key": "value"}


def test_trace_event_has_timestamp():
    event = TraceEvent.user_message("test")
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo == UTC


# ── CandidateMemory defaults ─────────────────────────────────────────────────


def test_candidate_memory_defaults():
    event = TraceEvent.user_message("test")
    candidate = CandidateMemory(
        content="Use Podman not Docker", source_event=event, extractor_name="test"
    )
    assert candidate.scope == "user"
    assert candidate.weight == 0.7
    assert candidate.confidence == 0.5
    assert candidate.relate_to == []
    assert candidate.is_duplicate is False
    assert candidate.duplicate_of is None


def test_candidate_memory_relate_to_default():
    event = TraceEvent.user_message("test")
    candidate = CandidateMemory(
        content="Test memory", source_event=event, extractor_name="test"
    )
    assert candidate.relate_to == []
    assert isinstance(candidate.relate_to, list)


def test_candidate_memory_custom_values():
    event = TraceEvent.user_message("test")
    candidate = CandidateMemory(
        content="Custom memory",
        source_event=event,
        extractor_name="custom",
        scope="project",
        weight=0.9,
        confidence=0.8,
        parent_id="mem-parent",
        branch_type="rationale",
        metadata={"key": "value"},
        domains=["architecture"],
        relate_to=["mem-001", "mem-002"],
    )
    assert candidate.scope == "project"
    assert candidate.weight == 0.9
    assert candidate.confidence == 0.8
    assert candidate.parent_id == "mem-parent"
    assert candidate.branch_type == "rationale"
    assert candidate.metadata == {"key": "value"}
    assert candidate.domains == ["architecture"]
    assert candidate.relate_to == ["mem-001", "mem-002"]


# ── ExtractionResult accumulation ────────────────────────────────────────────


def test_extraction_result_defaults():
    event = TraceEvent.user_message("test")
    result = ExtractionResult(event=event)
    assert result.candidates == []
    assert result.written == []
    assert result.reviewed == []
    assert result.filtered == []


def test_extraction_result_accumulation():
    event = TraceEvent.user_message("test")
    result = ExtractionResult(event=event)

    candidate1 = CandidateMemory(
        content="Memory 1", source_event=event, extractor_name="test"
    )
    candidate2 = CandidateMemory(
        content="Memory 2", source_event=event, extractor_name="test"
    )

    result.candidates.append(candidate1)
    result.candidates.append(candidate2)
    result.written.append("mem-001")
    result.reviewed.append(candidate2)

    assert len(result.candidates) == 2
    assert len(result.written) == 1
    assert len(result.reviewed) == 1
    assert result.written[0] == "mem-001"
    assert result.reviewed[0] == candidate2
