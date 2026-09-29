"""Deterministic threshold gates for the dreaming pipeline (#562).

Candidates must pass all configured thresholds before reaching the LLM
consolidation / routing phase. Candidates below threshold are deferred
(returned to the caller), not discarded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memoryhub.extraction.models import CandidateMemory

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateThresholds:
    """Configurable thresholds for dreaming gates.

    Set a threshold to 0 to effectively disable that gate.
    """

    min_recall_count: int = 0
    min_unique_queries: int = 0
    min_score: float = 0.0


@dataclass
class GateResult:
    """Outcome of running candidates through the dreaming gates."""

    passed: list[CandidateMemory] = field(default_factory=list)
    deferred: list[CandidateMemory] = field(default_factory=list)


class DreamingGate:
    """Deterministic quality gate for extraction candidates.

    Applies configurable threshold checks before the expensive LLM
    consolidation step. Candidates that fail any threshold are deferred
    to the next dreaming cycle, not discarded.

    Thresholds:
        min_recall_count: Minimum times the candidate was retrieved in
            search results before qualifying for promotion.
        min_unique_queries: Minimum distinct queries that surfaced the
            candidate.
        min_score: Minimum confidence score (maps to candidate.confidence).
    """

    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self._thresholds = thresholds or GateThresholds()

    @property
    def thresholds(self) -> GateThresholds:
        return self._thresholds

    def evaluate(self, candidates: list[CandidateMemory]) -> GateResult:
        """Run all candidates through the threshold gates.

        Returns a GateResult with passed and deferred lists.
        """
        result = GateResult()

        for candidate in candidates:
            reasons = self._check(candidate)
            if reasons:
                logger.debug(
                    "Candidate from %s deferred: %s",
                    candidate.extractor_name,
                    ", ".join(reasons),
                )
                result.deferred.append(candidate)
            else:
                result.passed.append(candidate)

        if result.deferred:
            logger.info(
                "Dreaming gates: %d passed, %d deferred",
                len(result.passed),
                len(result.deferred),
            )

        return result

    def _check(self, candidate: CandidateMemory) -> list[str]:
        """Check a single candidate against all thresholds.

        Returns a list of failure reasons (empty if all gates pass).
        """
        reasons: list[str] = []
        t = self._thresholds

        if t.min_recall_count > 0 and candidate.recall_count < t.min_recall_count:
            reasons.append(
                f"recall_count {candidate.recall_count} < {t.min_recall_count}"
            )

        if t.min_unique_queries > 0 and candidate.unique_query_count < t.min_unique_queries:
            reasons.append(
                f"unique_query_count {candidate.unique_query_count} < {t.min_unique_queries}"
            )

        if t.min_score > 0 and candidate.confidence < t.min_score:
            reasons.append(
                f"confidence {candidate.confidence:.2f} < {t.min_score:.2f}"
            )

        return reasons
