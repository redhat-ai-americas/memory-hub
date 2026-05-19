"""Abstract base class for extraction pipeline stages."""

from __future__ import annotations

from abc import ABC, abstractmethod

from memoryhub.extraction.models import CandidateMemory, TraceEvent


class Extractor(ABC):
    """Base class for extraction pipeline stages.

    Subclass and implement ``extract()`` to create a custom extractor.
    The pipeline calls ``extract()`` once per trace event; return an
    empty list when the event contains nothing relevant.
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def extract(self, event: TraceEvent) -> list[CandidateMemory]:
        ...
