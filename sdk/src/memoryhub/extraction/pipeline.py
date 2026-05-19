"""Extraction pipeline orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from memoryhub.extraction.base import Extractor
from memoryhub.extraction.dedup import DedupFilter
from memoryhub.extraction.models import CandidateMemory, ExtractionResult, TraceEvent

if TYPE_CHECKING:
    from memoryhub.client import MemoryHubClient

logger = logging.getLogger(__name__)

# Callback for human review of candidates. Returns True to write, False to skip.
CandidateCallback = Callable[[CandidateMemory], Awaitable[bool]]


class ExtractionPipeline:
    """Orchestrate extraction, enrichment, dedup, and routing of trace events.

    The pipeline processes TraceEvent instances through a multi-stage flow:

    1. **Extract**: Run configured extractors to produce candidate memories
    2. **Enrich**: For extractors that support relationship enrichment, add
       relate_to links to candidates
    3. **Dedup**: Check candidates against existing memories to prevent duplicates
    4. **Route**: Write high-confidence candidates automatically, route
       uncertain ones to human review

    All exceptions are caught and logged; the pipeline never raises to the caller.
    """

    def __init__(
        self,
        client: MemoryHubClient,
        extractors: list[Extractor] | None = None,
        *,
        confidence_threshold: float = 0.7,
        dedup_threshold: float = 0.90,
        auto_write: bool = True,
        project_id: str | None = None,
        scope: str = "user",
        domains: list[str] | None = None,
    ):
        """Initialize the extraction pipeline.

        Args:
            client: Connected MemoryHub client for write/search operations.
            extractors: List of extractor instances. If None, pipeline runs
                with no extractors (useful for testing routing logic).
            confidence_threshold: Minimum candidate.confidence to auto-write.
                Default 0.7. Candidates below threshold go to review callback.
            dedup_threshold: Similarity threshold for DedupFilter. Default 0.90.
            auto_write: If True, write high-confidence candidates automatically.
                If False, all candidates route to review callback.
            project_id: Project identifier for memory writes and searches.
            scope: Default scope for memory writes (default "user").
            domains: Default domain tags for memory writes.
        """
        self._client = client
        self._extractors = extractors or []
        self._dedup = DedupFilter(threshold=dedup_threshold)
        self._callback: CandidateCallback | None = None
        self._confidence_threshold = confidence_threshold
        self._auto_write = auto_write
        self._project_id = project_id
        self._scope = scope
        self._domains = domains

    def on_candidate(self, callback: CandidateCallback) -> CandidateCallback:
        """Decorator to register a review callback.

        The callback receives candidates that don't meet the confidence
        threshold for auto-write. Return True to write the candidate,
        False to skip.

        Example::

            @pipeline.on_candidate
            async def review(candidate: CandidateMemory) -> bool:
                print(f"Review: {candidate.content}")
                return input("Write? (y/n): ").lower() == "y"
        """
        self._callback = callback
        return callback

    async def observe(self, event: TraceEvent) -> ExtractionResult:
        """Process a trace event through the full pipeline.

        Args:
            event: The trace event to process.

        Returns:
            ExtractionResult with candidates, written IDs, reviewed candidates,
            and filtered (duplicate) candidates.
        """
        result = ExtractionResult(event=event)

        # ── 1. Extract phase ────────────────────────────────────────
        candidates: list[CandidateMemory] = []
        enrichers: list[Extractor] = []

        for extractor in self._extractors:
            # Identify relationship enrichers for phase 2
            if extractor.__class__.__name__ == "RelationshipExtractor":
                enrichers.append(extractor)
                continue

            try:
                extracted = await extractor.extract(event)
                candidates.extend(extracted)
            except Exception as exc:
                logger.warning(
                    "Extractor %s raised during extract; continuing: %s",
                    extractor.name,
                    exc,
                    exc_info=True,
                )

        result.candidates = candidates

        # ── 2. Relationship enrichment ──────────────────────────────
        for candidate in candidates:
            for enricher in enrichers:
                try:
                    # RelationshipExtractor.enrich mutates candidate.relate_to
                    await enricher.enrich(candidate, self._client, self._project_id)  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.warning(
                        "Enricher %s raised during enrich; continuing: %s",
                        enricher.name,
                        exc,
                        exc_info=True,
                    )

        # ── 3. Dedup phase ──────────────────────────────────────────
        for candidate in candidates:
            try:
                await self._dedup.check(candidate, self._client, self._project_id)
            except Exception as exc:
                logger.warning(
                    "Dedup check failed for candidate from %s; continuing: %s",
                    candidate.extractor_name,
                    exc,
                    exc_info=True,
                )

            if candidate.is_duplicate:
                result.filtered.append(candidate)

        # ── 4. Routing phase ────────────────────────────────────────
        non_duplicates = [c for c in candidates if not c.is_duplicate]

        for candidate in non_duplicates:
            # Auto-write high-confidence candidates
            if candidate.confidence >= self._confidence_threshold and self._auto_write:
                memory_id = await self._write_candidate(candidate)
                if memory_id:
                    result.written.append(memory_id)
            # Route uncertain candidates to review callback
            elif self._callback is not None:
                try:
                    should_write = await self._callback(candidate)
                    if should_write:
                        memory_id = await self._write_candidate(candidate)
                        if memory_id:
                            result.written.append(memory_id)
                        else:
                            result.reviewed.append(candidate)
                    else:
                        result.reviewed.append(candidate)
                except Exception as exc:
                    logger.warning(
                        "Review callback raised for candidate from %s; skipping: %s",
                        candidate.extractor_name,
                        exc,
                        exc_info=True,
                    )
                    result.reviewed.append(candidate)
            # No callback registered and below threshold
            else:
                result.reviewed.append(candidate)

        return result

    async def _write_candidate(self, candidate: CandidateMemory) -> str | None:
        """Write a candidate memory and create relationships.

        Args:
            candidate: The candidate to write.

        Returns:
            The written memory ID on success, None on failure.
        """
        try:
            write_result = await self._client.write(
                content=candidate.content,
                scope=candidate.scope or self._scope,
                weight=candidate.weight,
                parent_id=candidate.parent_id,
                branch_type=candidate.branch_type,
                metadata=candidate.metadata,
                domains=candidate.domains or self._domains,
                project_id=self._project_id,
            )

            if write_result.memory is None:
                logger.info(
                    "Write gated for candidate from %s: %s",
                    candidate.extractor_name,
                    write_result.curation.reason or "no reason provided",
                )
                return None

            memory_id = write_result.memory.id

            # Create relationships if candidate specified relate_to
            for target_id in candidate.relate_to:
                try:
                    await self._client.create_relationship(
                        source_id=memory_id,
                        target_id=target_id,
                        relationship_type="related",
                        project_id=self._project_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to create relationship %s -> %s: %s",
                        memory_id,
                        target_id,
                        exc,
                    )

            return memory_id

        except Exception as exc:
            logger.error(
                "Failed to write candidate from %s: %s",
                candidate.extractor_name,
                exc,
                exc_info=True,
            )
            return None

    def flush(self) -> None:
        """Flush any pending writes.

        No-op in the current implementation — all operations are awaited
        synchronously within observe(). Placeholder for future batching.
        """
        pass
