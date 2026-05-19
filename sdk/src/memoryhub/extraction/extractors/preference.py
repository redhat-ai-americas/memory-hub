"""Preference extractor for detecting stated user preferences."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Awaitable, Callable

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent, TraceEventType

if TYPE_CHECKING:
    pass


class PreferenceExtractor(Extractor):
    """Detects stated preferences in user messages.

    Uses regex patterns for common preference signals. If an LLM is provided,
    uses it to classify ambiguous turns.
    """

    # Preference signal patterns
    _PATTERNS = [
        re.compile(r"\b(?:I|we)\s+prefer\s+([^,.\n]+?)(?:\s+over\s+([^,.\n]+))?", re.IGNORECASE),
        re.compile(r"\balways\s+use\s+([^,.\n]+)", re.IGNORECASE),
        re.compile(r"\bnever\s+use\s+([^,.\n]+)", re.IGNORECASE),
        re.compile(r"\bdon'?t\s+use\s+([^,.\n]+)", re.IGNORECASE),
        re.compile(r"\buse\s+([^,.\n]+?)\s+instead\s+of\s+([^,.\n]+)", re.IGNORECASE),
        re.compile(r"\bavoid\s+([^,.\n]+)", re.IGNORECASE),
    ]

    _LLM_PROMPT_TEMPLATE = """Extract preferences from the following text. Return JSON only.

Text: {text}

Return a JSON array of objects with fields:
- "subject": what the preference is about
- "polarity": "positive" (prefer/use) or "negative" (avoid/don't use)
- "alternative": optional, what is preferred over (if comparison)

Return empty array [] if no preferences found.
"""

    def __init__(
        self,
        *,
        llm: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.llm = llm

    @property
    def name(self) -> str:
        return "preference"

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        # Only extract from user messages
        if event.event_type != TraceEventType.USER_MESSAGE:
            return []

        candidates: list[CandidateMemory] = []

        # Pattern-based extraction
        pattern_matches = self._extract_patterns(event.content)
        if pattern_matches:
            for match in pattern_matches:
                candidates.append(
                    CandidateMemory(
                        content=match["content"],
                        scope="user",
                        weight=0.85,
                        confidence=0.7,
                        source_event=event,
                        extractor_name=self.name,
                        metadata={
                            "subject": match["subject"],
                            "polarity": match["polarity"],
                            "alternative": match.get("alternative"),
                            "detection_method": "pattern",
                        },
                    )
                )

        # LLM-based extraction for ambiguous cases
        if self.llm and not pattern_matches:
            llm_matches = await self._extract_llm(event.content)
            for match in llm_matches:
                candidates.append(
                    CandidateMemory(
                        content=match["content"],
                        scope="user",
                        weight=0.85,
                        confidence=0.85,
                        source_event=event,
                        extractor_name=self.name,
                        metadata={
                            "subject": match["subject"],
                            "polarity": match["polarity"],
                            "alternative": match.get("alternative"),
                            "detection_method": "llm",
                        },
                    )
                )

        return candidates

    def _extract_patterns(self, text: str) -> list[dict[str, str]]:
        """Extract preferences using regex patterns."""
        matches = []

        for pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                groups = match.groups()
                subject = groups[0].strip() if groups else ""
                alternative = groups[1].strip() if len(groups) > 1 and groups[1] else None

                # Determine polarity based on pattern
                if "never" in match.group(0).lower() or "don't" in match.group(0).lower() or "avoid" in match.group(0).lower():
                    polarity = "negative"
                    content = f"Avoid using {subject}"
                elif alternative:
                    polarity = "positive"
                    content = f"Prefer {subject} over {alternative}"
                else:
                    polarity = "positive"
                    content = f"Prefer {subject}"

                matches.append({
                    "subject": subject,
                    "polarity": polarity,
                    "alternative": alternative,
                    "content": content,
                })

        return matches

    async def _extract_llm(self, text: str) -> list[dict[str, str]]:
        """Extract preferences using LLM classification."""
        if not self.llm:
            return []

        prompt = self._LLM_PROMPT_TEMPLATE.format(text=text)
        try:
            response = await self.llm(prompt)
            # Try to parse JSON from response
            parsed = json.loads(response)
            if not isinstance(parsed, list):
                return []

            results = []
            for item in parsed:
                subject = item.get("subject", "")
                polarity = item.get("polarity", "positive")
                alternative = item.get("alternative")

                if alternative:
                    content = f"Prefer {subject} over {alternative}"
                elif polarity == "negative":
                    content = f"Avoid using {subject}"
                else:
                    content = f"Prefer {subject}"

                results.append({
                    "subject": subject,
                    "polarity": polarity,
                    "alternative": alternative,
                    "content": content,
                })

            return results
        except (json.JSONDecodeError, KeyError):
            return []
