"""Decision and rationale extractor for agent traces."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent, TraceEventType

logger = logging.getLogger(__name__)


class DecisionTraceExtractor(Extractor):
    """Identifies decisions and their rationale in agent traces.

    Uses pattern matching as a fallback and optionally an LLM for higher-quality
    extraction. When an LLM is available, it extracts structured decision data
    including summary, rationale, and alternatives. Pattern-only mode provides
    lower confidence but no external dependencies.
    """

    # Patterns for decision signals
    DECISION_PATTERNS = [
        r"(?:I|we)\s+(?:decided|chose|picked|selected)\s+([^.!?\n]+?)(?:\s+(?:because|since)\s+([^.!?\n]+))?",
        r"(?:the|our)\s+(?:approach|plan|strategy)\s+is\s+([^.!?\n]+)",
        r"(?:going|opted)\s+(?:with|for)\s+([^.!?\n]+?)(?:\s+(?:because|since)\s+([^.!?\n]+))?",
    ]

    def __init__(self, llm: Callable[[str], Awaitable[str]] | None = None):
        """Initialize the decision extractor.

        Args:
            llm: Optional async callable that takes a prompt string and returns
                a string response. When provided, used for structured decision
                extraction.
        """
        self.llm = llm

    @property
    def name(self) -> str:
        return "decision_trace"

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        """Extract decision-related memories from a trace event.

        Args:
            event: The trace event to analyze

        Returns:
            List of candidate memories (may be empty)
        """
        if event.event_type not in {
            TraceEventType.USER_MESSAGE,
            TraceEventType.ASSISTANT_MESSAGE,
        }:
            return []

        if self.llm:
            return await self._extract_with_llm(event)
        return await self._extract_with_patterns(event)

    async def _extract_with_llm(self, event: TraceEvent) -> list[CandidateMemory]:
        """Use LLM to extract structured decision data."""
        prompt = f"""Analyze the following message for decision-making content.
Extract any decisions, rationale, and alternatives considered.

Message: {event.content}

Respond with JSON in this format:
{{
  "has_decision": true/false,
  "decision_summary": "brief summary",
  "rationale": "why this was chosen",
  "alternatives": "alternatives considered (if any)"
}}

If no decision is present, return {{"has_decision": false}}."""

        try:
            response = await self.llm(prompt)
            data = json.loads(response)

            if not data.get("has_decision"):
                return []

            decision_summary = data.get("decision_summary", "")
            rationale = data.get("rationale", "")
            alternatives = data.get("alternatives", "")

            content_parts = [f"Decision: {decision_summary}"]
            if rationale:
                content_parts.append(f"Rationale: {rationale}")
            if alternatives:
                content_parts.append(f"Alternatives considered: {alternatives}")

            content = "\n".join(content_parts)

            metadata = {
                "decision_summary": decision_summary,
                "rationale": rationale,
            }
            if alternatives:
                metadata["alternatives"] = alternatives

            return [
                CandidateMemory(
                    content=content,
                    scope="user",
                    weight=0.8,
                    confidence=0.75,
                    source_event=event,
                    extractor_name=self.name,
                    branch_type="rationale",
                    metadata=metadata,
                )
            ]

        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.warning("LLM extraction failed, falling back to patterns: %s", e)
            return await self._extract_with_patterns(event)

    async def _extract_with_patterns(self, event: TraceEvent) -> list[CandidateMemory]:
        """Use regex patterns to identify decision signals."""
        candidates = []

        for pattern_str in self.DECISION_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            for match in pattern.finditer(event.content):
                decision = match.group(1).strip()
                rationale = match.group(2).strip() if match.lastindex >= 2 else None

                content_parts = [f"Decision: {decision}"]
                if rationale:
                    content_parts.append(f"Rationale: {rationale}")

                content = "\n".join(content_parts)

                metadata: dict[str, str] = {"decision_summary": decision}
                if rationale:
                    metadata["rationale"] = rationale

                candidates.append(
                    CandidateMemory(
                        content=content,
                        scope="user",
                        weight=0.8,
                        confidence=0.45,
                        source_event=event,
                        extractor_name=self.name,
                        branch_type="rationale",
                        metadata=metadata,
                    )
                )

        return candidates
