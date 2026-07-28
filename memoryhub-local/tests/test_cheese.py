"""Cheese test: end-to-end validation of the SQLite backend.

Exercises the full lifecycle -- write, update, version chain, vector search,
keyword search, and similarity check -- proving the portable models and
SQLiteBackend work correctly on SQLite.

Named after Wes's favorite cheese (parmesan), because why not.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.models.memory import MemoryNode, MemoryRelationship
from memoryhub_local.models.utils import generate_stub
from memoryhub_local.storage.sqlite import SQLiteBackend, ensure_fts_table

# Deterministic embeddings for testing
EMB_CHEESE = [1.0, 0.0, 0.0] + [0.0] * 381  # 384-dim, points along axis 0
EMB_WINE = [0.0, 1.0, 0.0] + [0.0] * 381    # orthogonal to cheese
EMB_PARM = [0.9, 0.1, 0.0] + [0.0] * 381    # close to cheese


@pytest.fixture
def owner_id():
    return "test-user"


@pytest.fixture
def tenant_id():
    return "default"


async def _create_memory(
    session: AsyncSession,
    content: str,
    embedding: list[float],
    *,
    owner_id: str = "test-user",
    tenant_id: str = "default",
    scope: str = "user",
    weight: float = 0.8,
    version: int = 1,
    is_current: bool = True,
    previous_version_id: uuid.UUID | None = None,
) -> MemoryNode:
    """Helper to create a MemoryNode with sensible defaults."""
    node = MemoryNode(
        id=uuid.uuid4(),
        content=content,
        stub=generate_stub(content, scope, weight, 0, False),
        embedding=embedding,
        owner_id=owner_id,
        tenant_id=tenant_id,
        scope=scope,
        weight=weight,
        version=version,
        is_current=is_current,
        previous_version_id=previous_version_id,
    )
    session.add(node)
    await session.flush()
    return node


class TestWriteAndRead:
    """Basic CRUD: write a memory, read it back."""

    async def test_write_memory(self, async_session: AsyncSession):
        node = await _create_memory(
            async_session, "Parmesan is the best cheese", EMB_CHEESE,
        )
        assert node.id is not None
        assert node.content == "Parmesan is the best cheese"
        assert node.version == 1
        assert node.is_current is True

    async def test_read_memory_by_id(self, async_session: AsyncSession):
        node = await _create_memory(
            async_session, "Gouda is great too", EMB_CHEESE,
        )
        result = await async_session.execute(
            select(MemoryNode).where(MemoryNode.id == node.id)
        )
        loaded = result.scalar_one()
        assert loaded.content == "Gouda is great too"
        assert loaded.embedding is not None


class TestVersionChain:
    """Update a memory and verify version chain."""

    async def test_update_creates_new_version(self, async_session: AsyncSession):
        v1 = await _create_memory(
            async_session, "Cheddar is okay", EMB_CHEESE,
        )
        original_id = v1.id

        # Mark v1 as no longer current
        v1.is_current = False
        await async_session.flush()

        # Create v2
        v2 = await _create_memory(
            async_session, "Cheddar is actually great",
            EMB_CHEESE,
            version=2,
            is_current=True,
            previous_version_id=original_id,
        )
        await async_session.flush()

        assert v2.previous_version_id == original_id
        assert v2.version == 2
        assert v2.is_current is True

        # v1 should no longer be current
        result = await async_session.execute(
            select(MemoryNode).where(MemoryNode.id == original_id)
        )
        v1_reloaded = result.scalar_one()
        assert v1_reloaded.is_current is False

    async def test_version_chain_walkback(self, async_session: AsyncSession):
        """Walk the version chain from current back to v1."""
        v1 = await _create_memory(
            async_session, "Version 1", EMB_CHEESE, is_current=False,
        )
        v2 = await _create_memory(
            async_session, "Version 2", EMB_CHEESE,
            version=2, is_current=False, previous_version_id=v1.id,
        )
        v3 = await _create_memory(
            async_session, "Version 3", EMB_CHEESE,
            version=3, is_current=True, previous_version_id=v2.id,
        )
        await async_session.flush()

        # Walk chain: v3 -> v2 -> v1
        chain = [v3.content]
        current = v3
        while current.previous_version_id:
            result = await async_session.execute(
                select(MemoryNode).where(MemoryNode.id == current.previous_version_id)
            )
            current = result.scalar_one()
            chain.append(current.content)

        assert chain == ["Version 3", "Version 2", "Version 1"]


class TestVectorSearch:
    """vector_recall: find memories by embedding similarity."""

    async def test_finds_similar_embeddings(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(async_session, "Parmesan is delicious", EMB_CHEESE)
        await _create_memory(async_session, "A nice Barolo pairs well", EMB_WINE)
        await _create_memory(async_session, "Parmigiano Reggiano DOP", EMB_PARM)
        await async_session.flush()

        results = await backend.vector_recall(
            query_embedding=EMB_CHEESE,
            filters=[
                MemoryNode.owner_id == "test-user",
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
            ],
            limit=10,
            session=async_session,
        )

        assert len(results) == 3
        # First result should be the exact match (distance ~0)
        assert results[0][0].content == "Parmesan is delicious"
        assert results[0][1] < 0.01
        # Second should be parmesan-adjacent (distance ~0.1)
        assert results[1][0].content == "Parmigiano Reggiano DOP"
        assert results[1][1] < 0.2
        # Third should be the orthogonal wine vector (distance ~1.0)
        assert results[2][0].content == "A nice Barolo pairs well"
        assert results[2][1] > 0.9

    async def test_respects_limit(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        for i in range(5):
            emb = [0.0] * 384
            emb[i] = 1.0
            await _create_memory(async_session, f"Memory {i}", emb)
        await async_session.flush()

        results = await backend.vector_recall(
            query_embedding=EMB_CHEESE,
            filters=[MemoryNode.owner_id == "test-user"],
            limit=2,
            session=async_session,
        )
        assert len(results) == 2

    async def test_filters_applied(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(
            async_session, "My cheese", EMB_CHEESE, owner_id="alice",
        )
        await _create_memory(
            async_session, "Your cheese", EMB_CHEESE, owner_id="bob",
        )
        await async_session.flush()

        results = await backend.vector_recall(
            query_embedding=EMB_CHEESE,
            filters=[MemoryNode.owner_id == "alice"],
            limit=10,
            session=async_session,
        )
        assert len(results) == 1
        assert results[0][0].owner_id == "alice"


class TestKeywordSearch:
    """keyword_recall: FTS5 full-text search."""

    async def test_finds_by_keyword(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(async_session, "Parmesan is the king of cheeses", EMB_CHEESE)
        await _create_memory(async_session, "Red wine pairs with steak", EMB_WINE)
        await _create_memory(async_session, "Aged parmigiano has a nutty flavor", EMB_PARM)
        await async_session.commit()

        await ensure_fts_table(async_session)
        await async_session.commit()

        results = await backend.keyword_recall(
            query_text="parmesan",
            filters=[
                MemoryNode.owner_id == "test-user",
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
            ],
            limit=10,
            session=async_session,
        )

        assert len(results) >= 1
        contents = [r[0].content for r in results]
        assert "Parmesan is the king of cheeses" in contents

    async def test_no_results_for_unrelated_query(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(async_session, "Parmesan is delicious", EMB_CHEESE)
        await async_session.commit()

        await ensure_fts_table(async_session)
        await async_session.commit()

        results = await backend.keyword_recall(
            query_text="python programming",
            filters=[MemoryNode.owner_id == "test-user"],
            limit=10,
            session=async_session,
        )
        assert len(results) == 0


class TestSimilarityCheck:
    """similarity_check: curation gate for near-duplicates."""

    async def test_finds_similar_within_threshold(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(async_session, "Parmesan is great", EMB_CHEESE)
        await _create_memory(async_session, "Wine is great", EMB_WINE)
        await async_session.flush()

        # Should find the cheese memory (distance ~0) but not wine (distance ~1.0)
        results = await backend.similarity_check(
            embedding=EMB_PARM,  # close to cheese
            filters=[
                MemoryNode.owner_id == "test-user",
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
                MemoryNode.status == "active",
            ],
            max_distance=0.2,  # similarity >= 0.8
            limit=50,
            session=async_session,
        )

        assert len(results) == 1
        returned_id, distance = results[0]
        assert distance < 0.2

    async def test_empty_when_nothing_similar(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        await _create_memory(async_session, "Wine facts", EMB_WINE)
        await async_session.flush()

        results = await backend.similarity_check(
            embedding=EMB_CHEESE,
            filters=[MemoryNode.owner_id == "test-user"],
            max_distance=0.2,
            limit=50,
            session=async_session,
        )
        assert len(results) == 0

    async def test_respects_limit(
        self, async_session: AsyncSession, backend: SQLiteBackend,
    ):
        # Create multiple similar memories
        for i in range(5):
            emb = list(EMB_CHEESE)
            emb[1] = 0.01 * i  # slightly different
            await _create_memory(async_session, f"Cheese variant {i}", emb)
        await async_session.flush()

        results = await backend.similarity_check(
            embedding=EMB_CHEESE,
            filters=[MemoryNode.owner_id == "test-user"],
            max_distance=0.5,
            limit=2,
            session=async_session,
        )
        assert len(results) == 2


class TestGraphRelationships:
    """Verify graph edges can be created and queried via ORM."""

    async def test_create_relationship(self, async_session: AsyncSession):
        node_a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        node_b = await _create_memory(async_session, "Node B", EMB_WINE)
        await async_session.flush()

        rel = MemoryRelationship(
            id=uuid.uuid4(),
            source_id=node_a.id,
            target_id=node_b.id,
            relationship_type="derived_from",
            created_by="test-user",
            tenant_id="default",
        )
        async_session.add(rel)
        await async_session.flush()

        result = await async_session.execute(
            select(MemoryRelationship).where(
                MemoryRelationship.source_id == node_a.id
            )
        )
        loaded = result.scalar_one()
        assert loaded.target_id == node_b.id
        assert loaded.relationship_type == "derived_from"


async def _link(session, source, target, rel_type="related_to"):
    """Helper to create a relationship edge."""
    rel = MemoryRelationship(
        id=uuid.uuid4(),
        source_id=source.id,
        target_id=target.id,
        relationship_type=rel_type,
        created_by="test-user",
        tenant_id="default",
    )
    session.add(rel)
    await session.flush()
    return rel


class TestGraphNeighbors:
    """graph_neighbors: recursive CTE traversal on both backends."""

    async def test_direct_neighbors(
        self, async_session: AsyncSession, backend,
    ):
        a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        b = await _create_memory(async_session, "Node B", EMB_WINE)
        c = await _create_memory(async_session, "Node C", EMB_PARM)
        await _link(async_session, a, b)
        await _link(async_session, a, c)
        await async_session.commit()

        neighbors = await backend.graph_neighbors(
            seed_ids=[a.id], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        neighbor_ids = set(neighbors)
        assert b.id in neighbor_ids
        assert c.id in neighbor_ids
        assert a.id not in neighbor_ids

    async def test_bidirectional_traversal(
        self, async_session: AsyncSession, backend,
    ):
        a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        b = await _create_memory(async_session, "Node B", EMB_WINE)
        await _link(async_session, a, b)
        await async_session.commit()

        # Traverse from B should find A (reverse direction)
        neighbors = await backend.graph_neighbors(
            seed_ids=[b.id], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        assert a.id in neighbors

    async def test_multi_hop(
        self, async_session: AsyncSession, backend,
    ):
        a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        b = await _create_memory(async_session, "Node B", EMB_WINE)
        c = await _create_memory(async_session, "Node C", EMB_PARM)
        await _link(async_session, a, b)
        await _link(async_session, b, c)
        await async_session.commit()

        # depth=1: only b
        depth1 = await backend.graph_neighbors(
            seed_ids=[a.id], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        assert b.id in depth1
        assert c.id not in depth1

        # depth=2: b and c
        depth2 = await backend.graph_neighbors(
            seed_ids=[a.id], max_depth=2, max_neighbors=10,
            session=async_session,
        )
        assert b.id in depth2
        assert c.id in depth2

    async def test_excludes_deleted_nodes(
        self, async_session: AsyncSession, backend,
    ):
        from datetime import UTC, datetime

        a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        b = await _create_memory(async_session, "Node B", EMB_WINE)
        await _link(async_session, a, b)
        b.deleted_at = datetime.now(UTC)
        await async_session.commit()

        neighbors = await backend.graph_neighbors(
            seed_ids=[a.id], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        assert b.id not in neighbors

    async def test_excludes_expired_edges(
        self, async_session: AsyncSession, backend,
    ):
        from datetime import UTC, datetime

        a = await _create_memory(async_session, "Node A", EMB_CHEESE)
        b = await _create_memory(async_session, "Node B", EMB_WINE)
        rel = await _link(async_session, a, b)
        rel.valid_until = datetime.now(UTC)
        await async_session.commit()

        neighbors = await backend.graph_neighbors(
            seed_ids=[a.id], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        assert b.id not in neighbors

    async def test_empty_seeds_returns_empty(
        self, async_session: AsyncSession, backend,
    ):
        neighbors = await backend.graph_neighbors(
            seed_ids=[], max_depth=1, max_neighbors=10,
            session=async_session,
        )
        assert neighbors == []

    async def test_respects_max_neighbors(
        self, async_session: AsyncSession, backend,
    ):
        hub = await _create_memory(async_session, "Hub", EMB_CHEESE)
        spokes = []
        for i in range(5):
            emb = [0.0] * 384
            emb[i] = 1.0
            spoke = await _create_memory(async_session, f"Spoke {i}", emb)
            await _link(async_session, hub, spoke)
            spokes.append(spoke)
        await async_session.commit()

        neighbors = await backend.graph_neighbors(
            seed_ids=[hub.id], max_depth=1, max_neighbors=2,
            session=async_session,
        )
        assert len(neighbors) == 2
