"""Deduplication filter for the extraction pipeline."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from memoryhub.extraction.models import CandidateMemory

if TYPE_CHECKING:
    from memoryhub.client import MemoryHubClient

logger = logging.getLogger(__name__)


class DedupFilter:
    """Check candidates against existing memories to prevent duplicates.

    Uses semantic search to detect near-duplicate content. If a candidate
    matches an existing memory above the similarity threshold, it is marked
    as a duplicate and filtered from the write path.
    """

    def __init__(self, threshold: float = 0.90):
        """Initialize the deduplication filter.

        Args:
            threshold: Minimum cosine similarity (0.0-1.0) to mark as duplicate.
                Default 0.90 catches near-exact matches while allowing minor
                rewording.
        """
        self._threshold = threshold

    async def check(
        self,
        candidate: CandidateMemory,
        client: MemoryHubClient,
        project_id: str | None = None,
    ) -> CandidateMemory:
        """Check if a candidate duplicates an existing memory.

        Calls client.search() to find similar memories. If any result has a
        relevance_score >= threshold, the candidate is marked as a duplicate
        with the highest-scoring match ID.

        Args:
            candidate: The candidate memory to check.
            client: Connected MemoryHub client for search.
            project_id: Optional project identifier for scoped search.

        Returns:
            The candidate, possibly mutated with is_duplicate=True and
            duplicate_of=<memory_id> if a match was found. On search
            failure, returns the candidate unchanged (fail-open).
        """
        try:
            results = await client.search(
                candidate.content,
                max_results=3,
                project_id=project_id,
            )
        except Exception as exc:
            logger.warning(
                "Dedup search failed for candidate from %s; allowing write: %s",
                candidate.extractor_name,
                exc,
            )
            return candidate

        # Find the highest-scoring result above threshold
        best_match = None
        best_score = 0.0

        for memory in results.results:
            if memory.relevance_score is not None and memory.relevance_score >= self._threshold:
                if memory.relevance_score > best_score:
                    best_match = memory.id
                    best_score = memory.relevance_score

        if best_match is not None:
            candidate.is_duplicate = True
            candidate.duplicate_of = best_match
            logger.debug(
                "Candidate from %s marked duplicate of %s (score=%.2f)",
                candidate.extractor_name,
                best_match,
                best_score,
            )

        return candidate
