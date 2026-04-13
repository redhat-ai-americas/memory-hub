"""End-to-end pgvector similarity search through the BFF (issue #39).

Verifies the full vertical slice:
    UI search → BFF → embedding service (all-MiniLM-L6-v2) → pgvector cosine → ranked results

Runs against the deployed OpenShift stack — exercises the real embedding
service, not MockEmbeddingService.  Port-forwards are managed by conftest.py.

Run::

    pytest memoryhub-ui/tests/integration/ -m deployed -v
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from .conftest import TENANT_ID, get_embedding

pytestmark = [pytest.mark.asyncio, pytest.mark.integration, pytest.mark.deployed]


# -- helpers -----------------------------------------------------------------

async def _seed_memory(
    db_session,
    embedding_url: str,
    content: str,
    *,
    scope: str = "user",
    owner_id: str = "e2e-test-user",
    weight: float = 0.7,
    tenant_id: str = TENANT_ID,
) -> str:
    """Insert a memory row with a real embedding vector into pgvector.

    Returns the memory ID (UUID as string).
    """
    memory_id = str(uuid.uuid4())
    vector = await get_embedding(content, embedding_url)

    await db_session.execute(
        text("""
            INSERT INTO memory_nodes
                (id, content, stub, scope, owner_id, weight, tenant_id,
                 is_current, version, embedding, storage_type)
            VALUES
                (:id, :content, :stub, :scope, :owner_id, :weight, :tenant_id,
                 true, 1, CAST(:embedding AS vector), 'inline')
        """),
        {
            "id": memory_id,
            "content": content,
            "stub": content[:120],
            "scope": scope,
            "owner_id": owner_id,
            "weight": weight,
            "tenant_id": tenant_id,
            "embedding": str(vector),
        },
    )
    await db_session.commit()
    return memory_id


# -- tests -------------------------------------------------------------------


class TestPgvectorSearchE2E:
    """Full vertical slice: BFF → real embedding service → pgvector cosine."""

    async def test_semantic_search_returns_ranked_results(
        self, db_session, embedding_url, bff_base_url, seed_cleanup,
    ):
        """Seed three memories of varying relevance, search for the most
        relevant, and verify results are ranked by cosine similarity with
        real float scores.
        """
        # Seed: one highly relevant, one moderately relevant, one unrelated.
        high_id = await _seed_memory(
            db_session, embedding_url,
            "Kubernetes pod scheduling uses node affinity and taints to place workloads",
        )
        seed_cleanup.add(high_id)

        mid_id = await _seed_memory(
            db_session, embedding_url,
            "Container orchestration platforms manage deployment and scaling of applications",
        )
        seed_cleanup.add(mid_id)

        low_id = await _seed_memory(
            db_session, embedding_url,
            "Chocolate cake recipe with vanilla frosting and sprinkles",
        )
        seed_cleanup.add(low_id)

        # Search via BFF — the BFF calls the cluster-internal embedding service
        # and runs pgvector cosine distance.
        async with httpx.AsyncClient(base_url=bff_base_url, timeout=10.0) as client:
            resp = await client.get(
                "/api/graph/search",
                params={"q": "Kubernetes pod scheduling and node affinity"},
            )

        assert resp.status_code == 200, f"BFF returned {resp.status_code}: {resp.text}"
        results = resp.json()

        assert isinstance(results, list), f"Expected list, got {type(results).__name__}"
        assert len(results) >= 3, (
            f"Expected at least 3 results (seeded 3 memories), got {len(results)}. "
            f"Results: {results}"
        )

        # Build a lookup of our seeded IDs → position in results.
        result_ids = [r["id"] for r in results]
        assert high_id in result_ids, f"High-relevance memory {high_id} missing from results"
        assert mid_id in result_ids, f"Mid-relevance memory {mid_id} missing from results"

        high_pos = result_ids.index(high_id)
        mid_pos = result_ids.index(mid_id)
        low_pos = result_ids.index(low_id) if low_id in result_ids else len(results)

        # Ranking: high > mid > low (lower index = higher rank).
        assert high_pos < mid_pos, (
            f"High-relevance memory should rank above mid-relevance: "
            f"high at {high_pos}, mid at {mid_pos}"
        )
        assert mid_pos < low_pos, (
            f"Mid-relevance memory should rank above low-relevance: "
            f"mid at {mid_pos}, low at {low_pos}"
        )

        # Scores are real floats from pgvector, not fallback 1.0 values.
        high_score = results[high_pos]["score"]
        mid_score = results[mid_pos]["score"]
        assert isinstance(high_score, float), f"Score should be float, got {type(high_score)}"
        assert isinstance(mid_score, float), f"Score should be float, got {type(mid_score)}"
        assert high_score > mid_score, (
            f"High-relevance score ({high_score:.4f}) should exceed "
            f"mid-relevance score ({mid_score:.4f})"
        )
        # Cosine similarity scores from pgvector are in (-1, 1]; real
        # embeddings should produce positive scores for related content.
        assert 0.0 < high_score <= 1.0, f"Score out of range: {high_score}"
        assert 0.0 < mid_score <= 1.0, f"Score out of range: {mid_score}"

    async def test_semantic_search_not_text_fallback(
        self, db_session, embedding_url, bff_base_url, seed_cleanup,
    ):
        """Verify the BFF uses the embedding path, not the text fallback.

        Seed a memory whose content does NOT contain the search query as a
        substring but IS semantically similar.  If the search returns it with
        a score < 1.0, the embedding path is active (text fallback would
        return score=1.0 and only match literal substrings).
        """
        mem_id = await _seed_memory(
            db_session, embedding_url,
            "PostgreSQL supports advanced indexing with GIN and GiST for full-text search",
        )
        seed_cleanup.add(mem_id)

        # Query is semantically related but shares no exact substring.
        async with httpx.AsyncClient(base_url=bff_base_url, timeout=10.0) as client:
            resp = await client.get(
                "/api/graph/search",
                params={"q": "database text indexing strategies"},
            )

        assert resp.status_code == 200
        results = resp.json()
        matched = [r for r in results if r["id"] == mem_id]
        assert matched, (
            f"Semantically similar memory {mem_id} not found in results — "
            f"embedding path may not be active. Got {len(results)} results."
        )
        score = matched[0]["score"]
        assert score < 1.0, (
            "Score is exactly 1.0, which indicates text fallback, not cosine similarity. "
            "Check that MEMORYHUB_EMBEDDING_URL is set on the BFF deployment."
        )
        assert score > 0.0, f"Score should be positive for related content: {score}"

    async def test_cross_tenant_isolation(
        self, db_session, embedding_url, bff_base_url, seed_cleanup,
    ):
        """Memories in a different tenant must not appear in search results."""
        other_tenant = f"other-tenant-{uuid.uuid4().hex[:8]}"
        mem_id = await _seed_memory(
            db_session, embedding_url,
            "Kubernetes cluster autoscaling with horizontal pod autoscaler",
            tenant_id=other_tenant,
        )
        seed_cleanup.add(mem_id)

        async with httpx.AsyncClient(base_url=bff_base_url, timeout=10.0) as client:
            resp = await client.get(
                "/api/graph/search",
                params={"q": "Kubernetes cluster autoscaling"},
            )

        assert resp.status_code == 200, f"BFF returned {resp.status_code}: {resp.text}"
        result_ids = [r["id"] for r in resp.json()]
        assert mem_id not in result_ids, (
            f"Memory {mem_id} from tenant '{other_tenant}' leaked into "
            f"default tenant search results"
        )

    async def test_empty_query_rejected(self, bff_base_url):
        """BFF should reject empty search queries with 422."""
        async with httpx.AsyncClient(base_url=bff_base_url, timeout=10.0) as client:
            resp = await client.get("/api/graph/search", params={"q": ""})

        assert resp.status_code == 422, f"Expected 422 for empty query, got {resp.status_code}"
