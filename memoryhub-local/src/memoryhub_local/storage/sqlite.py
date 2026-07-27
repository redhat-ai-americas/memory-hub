"""SQLiteBackend -- RecallBackend implementation for SQLite.

Uses pure-Python cosine distance for vector operations (brute-force KNN)
and FTS5 for keyword search. At personal scale (<100K memories) the
brute-force approach is fast enough; sqlite-vec can be swapped in later
for hardware-accelerated distance when extension loading is available.
"""

from __future__ import annotations

import json
import math
import uuid

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.models.memory import MemoryNode


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance between two vectors: 1 - cosine_similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


FTS_TABLE_NAME = "memory_nodes_fts"

FTS_CREATE_SQL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE_NAME}
USING fts5(stub, content, content='memory_nodes', content_rowid='rowid')
"""

FTS_REBUILD_SQL = f"""
INSERT INTO {FTS_TABLE_NAME}({FTS_TABLE_NAME}) VALUES('rebuild')
"""


async def ensure_fts_table(session: AsyncSession) -> None:
    """Create the FTS5 virtual table if it doesn't exist and rebuild its index."""
    await session.execute(text(FTS_CREATE_SQL))
    await session.execute(text(FTS_REBUILD_SQL))


class SQLiteBackend:
    """RecallBackend implementation for SQLite.

    Satisfies the RecallBackend protocol with:
      - vector_recall: brute-force cosine distance in Python
      - keyword_recall: FTS5 MATCH with bm25() ranking
      - similarity_check: brute-force cosine distance with max_distance filter
      - graph_neighbors: deferred to session 2
    """

    async def vector_recall(
        self,
        query_embedding: list[float],
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """Brute-force KNN: load all matching nodes, compute distance in Python."""
        stmt = (
            select(MemoryNode)
            .where(and_(*filters))
            .where(MemoryNode.embedding.isnot(None))
        )
        result = await session.execute(stmt)
        nodes = result.scalars().all()

        scored: list[tuple[MemoryNode, float]] = []
        for node in nodes:
            emb = node.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            if emb:
                dist = _cosine_distance(query_embedding, emb)
                scored.append((node, dist))

        scored.sort(key=lambda x: x[1])
        return scored[:limit]

    async def keyword_recall(
        self,
        query_text: str,
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """FTS5 keyword search with bm25() ranking.

        Queries the FTS5 virtual table, then joins back to memory_nodes
        to apply ORM-level filters and return full MemoryNode objects.
        """
        fts_query = _sanitize_fts_query(query_text)
        if not fts_query:
            return []

        fts_sql = text(f"""
            SELECT rowid, bm25({FTS_TABLE_NAME}) AS rank
            FROM {FTS_TABLE_NAME}
            WHERE {FTS_TABLE_NAME} MATCH :query
            ORDER BY rank
            LIMIT :fts_limit
        """)

        fts_result = await session.execute(
            fts_sql, {"query": fts_query, "fts_limit": limit * 3}
        )
        fts_rows = fts_result.all()

        if not fts_rows:
            return []

        rowid_to_rank = {row.rowid: row.rank for row in fts_rows}
        rowids = list(rowid_to_rank.keys())

        in_clause = text(
            "memory_nodes.rowid IN ("
            + ",".join(str(r) for r in rowids)
            + ")"
        )
        node_stmt = (
            select(MemoryNode)
            .where(and_(*filters))
            .where(in_clause)
        )
        node_result = await session.execute(node_stmt)
        nodes = node_result.scalars().all()

        # Map nodes back to their FTS rank. Need to look up rowid for each
        # node -- but we don't have rowid on the ORM object. Re-query once
        # to get the mapping.
        if not nodes:
            return []

        # Build id->node map, then get rowids for those IDs
        id_to_node = {str(n.id): n for n in nodes}
        node_ids = list(id_to_node.keys())

        rowid_sql = text(
            "SELECT rowid, id FROM memory_nodes WHERE id IN ("
            + ",".join(f"'{nid}'" for nid in node_ids)
            + ")"
        )
        rowid_result = await session.execute(rowid_sql)
        rowid_map = {row.id: row.rowid for row in rowid_result.all()}

        scored: list[tuple[MemoryNode, float]] = []
        for node in nodes:
            nid = str(node.id)
            rowid = rowid_map.get(nid)
            if rowid is not None and rowid in rowid_to_rank:
                # bm25() returns negative scores; more negative = better match
                rank = abs(rowid_to_rank[rowid])
                scored.append((node, rank))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def similarity_check(
        self,
        embedding: list[float],
        filters: list,
        max_distance: float,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[uuid.UUID, float]]:
        """Brute-force similarity: load matching nodes, filter by distance."""
        stmt = (
            select(MemoryNode)
            .where(and_(*filters))
            .where(MemoryNode.embedding.isnot(None))
        )
        result = await session.execute(stmt)
        nodes = result.scalars().all()

        scored: list[tuple[uuid.UUID, float]] = []
        for node in nodes:
            emb = node.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            if emb:
                dist = _cosine_distance(embedding, emb)
                if dist <= max_distance:
                    scored.append((node.id, dist))

        scored.sort(key=lambda x: x[1])
        return scored[:limit]

    async def graph_neighbors(
        self,
        seed_ids: list[uuid.UUID],
        max_depth: int,
        max_neighbors: int,
        session: AsyncSession,
    ) -> list[uuid.UUID]:
        """Deferred to session 2 -- returns empty list."""
        return []


def _sanitize_fts_query(query: str) -> str:
    """Sanitize user input for FTS5 MATCH syntax.

    FTS5 special characters (*, ", ^, NEAR, OR, AND, NOT, etc.) can cause
    query parse errors. Wrap each token in double quotes to treat them as
    literal terms.
    """
    tokens = query.strip().split()
    if not tokens:
        return ""
    return " ".join(f'"{t}"' for t in tokens)
