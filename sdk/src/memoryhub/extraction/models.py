"""Data models for the extraction pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class TraceEventType(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REASONING = "reasoning"


class TraceEvent(BaseModel):
    """A single observation from an agent's conversation or execution."""

    model_config = ConfigDict(frozen=True)

    event_type: TraceEventType
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: Any = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def user_message(cls, content: str, **kwargs: Any) -> TraceEvent:
        return cls(event_type=TraceEventType.USER_MESSAGE, content=content, **kwargs)

    @classmethod
    def assistant_message(cls, content: str, **kwargs: Any) -> TraceEvent:
        return cls(event_type=TraceEventType.ASSISTANT_MESSAGE, content=content, **kwargs)

    @classmethod
    def tool_call(
        cls,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        result: Any = None,
        **kwargs: Any,
    ) -> TraceEvent:
        content = kwargs.pop("content", f"Tool call: {name}")
        return cls(
            event_type=TraceEventType.TOOL_CALL,
            content=content,
            tool_name=name,
            tool_args=args,
            tool_result=result,
            **kwargs,
        )

    @classmethod
    def reasoning(cls, content: str, **kwargs: Any) -> TraceEvent:
        return cls(event_type=TraceEventType.REASONING, content=content, **kwargs)


class CandidateMemory(BaseModel):
    """A proposed memory write from an extractor."""

    model_config = ConfigDict(extra="allow")

    content: str
    scope: str = "user"
    weight: float = 0.7
    confidence: float = 0.5
    source_event: TraceEvent
    extractor_name: str
    parent_id: str | None = None
    branch_type: str | None = None
    metadata: dict[str, Any] | None = None
    domains: list[str] | None = None
    relate_to: list[str] = Field(default_factory=list)
    is_duplicate: bool = False
    duplicate_of: str | None = None


class ExtractionResult(BaseModel):
    """Summary of processing a single trace event."""

    model_config = ConfigDict(extra="allow")

    event: TraceEvent
    candidates: list[CandidateMemory] = Field(default_factory=list)
    written: list[str] = Field(default_factory=list)
    reviewed: list[CandidateMemory] = Field(default_factory=list)
    filtered: list[CandidateMemory] = Field(default_factory=list)
