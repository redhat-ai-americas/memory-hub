"""Relationship enrichment extractor for candidate memories."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.models import CandidateMemory, TraceEvent

if TYPE_CHECKING:
    from memoryhub.client import MemoryHubClient

logger = logging.getLogger(__name__)


class RelationshipExtractor(Extractor):
    """Post-processes candidates by finding and attaching relationship suggestions.

    This extractor is special: it doesn't directly extract from trace events.
    Instead, the pipeline calls its `enrich()` method to search for related
    memories and attach relationship metadata to candidates from other extractors.
    """

    def __init__(
        self,
        relevance_threshold: float = 0.6,
        max_relations: int = 3,
    ):
        """Initialize the relationship enrichment extractor.

        Args:
            relevance_threshold: Minimum relevance score (0-1) to suggest a relation.
                Default 0.6.
            max_relations: Maximum number of relationships to suggest per candidate.
                Default 3.
        """
        self.relevance_threshold = relevance_threshold
        self.max_relations = max_relations

    @property
    def name(self) -> str:
        return "relationship"

    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        """Always returns empty list.

        The pipeline calls `enrich()` instead of `extract()` for this extractor.
        """
        return []

    async def enrich(
        self,
        candidate: CandidateMemory,
        client: MemoryHubClient,
        project_id: str | None = None,
    ) -> CandidateMemory:
        """Enrich a candidate memory with relationship suggestions.

        Searches for related memories and attaches their IDs to the candidate's
        `relate_to` field. If a very high relevance match (>0.85) is found and
        the candidate has no parent, sets that memory as the parent.

        Args:
            candidate: The candidate memory to enrich
            client: MemoryHub client for searching existing memories
            project_id: Optional project ID for scoped search

        Returns:
            The enriched candidate (mutated in place)
        """
        try:
            # Search for related memories
            search_results = await client.search(
                query=candidate.content,
                max_results=5,
                project_id=project_id,
            )

            related_ids = []
            very_high_match = None

            for result in search_results:
                # Skip if below relevance threshold
                if result.get("relevance_score", 0) < self.relevance_threshold:
                    continue

                memory_id = result.get("id")
                if not memory_id:
                    continue

                # Track very high relevance matches for parent assignment
                if result.get("relevance_score", 0) > 0.85:
                    if very_high_match is None:
                        very_high_match = memory_id

                # Add to relationships up to max_relations
                if len(related_ids) < self.max_relations:
                    related_ids.append(memory_id)

            # Update candidate with relationships
            candidate.relate_to.extend(related_ids)

            # If we found a very high match and candidate has no parent,
            # set it as the parent
            if very_high_match and not candidate.parent_id:
                candidate.parent_id = very_high_match

        except Exception as e:
            logger.warning(
                "Relationship enrichment failed for candidate from %s: %s",
                candidate.extractor_name,
                e,
            )

        return candidate
