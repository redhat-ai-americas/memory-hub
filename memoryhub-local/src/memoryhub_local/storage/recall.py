"""RecallBackend protocol -- the abstraction boundary between services and storage.

Services use RecallBackend for the four query shapes that differ between
PostgreSQL (pgvector, tsvector, recursive CTEs) and SQLite (sqlite-vec,
FTS5, iterative CTEs). Everything else -- CRUD, version chains, branch
flags, filter construction -- uses portable SQLAlchemy ORM and does NOT
go through this protocol.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from memoryhub_local.models.memory import MemoryNode


@runtime_checkable
class RecallBackend(Protocol):
    """Storage-engine-specific recall operations.

    Implementations:
      - SQLiteBackend  (sqlite-vec + FTS5)
      - PostgresBackend (pgvector + tsvector)  [session 2]
    """

    async def vector_recall(
        self,
        query_embedding: list[float],
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """Return (node, distance) pairs sorted by ascending cosine distance."""
        ...

    async def keyword_recall(
        self,
        query_text: str,
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """Return (node, rank) pairs sorted by descending BM25/ts_rank score."""
        ...

    async def similarity_check(
        self,
        embedding: list[float],
        filters: list,
        max_distance: float,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[uuid.UUID, float]]:
        """Return (id, distance) pairs within max_distance.

        Used by the curation similarity gate. The similar-memory API
        (get_similar_memories) uses this for ranked IDs, then does a
        follow-up ORM query for full node stubs and pagination.
        """
        ...

    async def graph_neighbors(
        self,
        seed_ids: list[uuid.UUID],
        max_depth: int,
        max_neighbors: int,
        session: AsyncSession,
    ) -> list[uuid.UUID]:
        """Return neighbor IDs reachable within max_depth hops."""
        ...
