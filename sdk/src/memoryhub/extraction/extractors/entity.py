"""Entity extractor for identifying proper nouns and technical terms."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent, TraceEventType

if TYPE_CHECKING:
    pass

# Try to import spaCy if available
try:
    import spacy
    from spacy.language import Language

    _HAS_SPACY = True
except ImportError:
    _HAS_SPACY = False
    Language = None  # type: ignore


class EntityExtractor(Extractor):
    """Identifies turns containing entities worth tracking.

    Uses pattern matching for capitalized multi-word names and technology
    detection. If spaCy is available, also runs NER for PERSON, ORG, GPE labels.
    """

    # Common technology patterns
    _TECH_PATTERNS = re.compile(
        r"\b(?:PostgreSQL|MySQL|MongoDB|Redis|Kubernetes|OpenShift|Docker|"
        r"Podman|FastAPI|Django|Flask|React|Vue|Angular|TypeScript|JavaScript|"
        r"Python|Java|Rust|Go|AWS|Azure|GCP|MinIO|Valkey|FastMCP)\b",
        re.IGNORECASE,
    )

    # Capitalized multi-word names (e.g., "Memory Hub", "John Smith")
    _CAPITALIZED_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

    def __init__(
        self,
        *,
        min_entity_count: int = 1,
        spacy_model: str = "en_core_web_sm",
    ) -> None:
        self.min_entity_count = min_entity_count
        self.spacy_model = spacy_model
        self._nlp: Language | None = None

        if _HAS_SPACY:
            try:
                self._nlp = spacy.load(spacy_model)
            except OSError:
                # Model not installed, fall back to pattern matching only
                pass

    @property
    def name(self) -> str:
        return "entity"

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        # Only extract from message events
        if event.event_type not in (
            TraceEventType.USER_MESSAGE,
            TraceEventType.ASSISTANT_MESSAGE,
        ):
            return []

        entities: dict[str, str] = {}

        # Pattern-based extraction
        tech_matches = self._TECH_PATTERNS.findall(event.content)
        for match in tech_matches:
            entities[match] = "TECHNOLOGY"

        cap_matches = self._CAPITALIZED_PATTERN.findall(event.content)
        for match in cap_matches:
            entities[match] = "PROPER_NOUN"

        # spaCy-based extraction if available
        if self._nlp:
            doc = self._nlp(event.content)
            for ent in doc.ents:
                if ent.label_ in ("PERSON", "ORG", "GPE"):
                    entities[ent.text] = ent.label_

        if len(entities) < self.min_entity_count:
            return []

        # Determine confidence based on detection method
        confidence = 0.75 if self._nlp else 0.55

        # Build content string
        entity_list = ", ".join(f"{name} ({etype})" for name, etype in entities.items())
        content = f"Entities mentioned: {entity_list}"

        return [
            CandidateMemory(
                content=content,
                scope="user",
                weight=0.7,
                confidence=confidence,
                source_event=event,
                extractor_name=self.name,
                metadata={
                    "entities": [
                        {"name": name, "type": etype} for name, etype in entities.items()
                    ],
                    "detection_method": "spacy+pattern" if self._nlp else "pattern",
                },
            )
        ]
