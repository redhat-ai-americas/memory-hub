"""Tests for batched_rerank cross-encoder merging logic."""

import pytest

from memoryhub_core.services.rerank import (
    RerankerService,
    batched_rerank,
    RERANK_API_BATCH,
)


class MockReranker(RerankerService):
    """Tracks calls and returns deterministic scores."""

    def __init__(self):
        self.rerank_calls = []
        self.rerank_with_scores_calls = []

    async def rerank(self, query: str, texts: list[str]) -> list[int]:
        self.rerank_calls.append((query, len(texts)))
        return list(range(len(texts)))

    async def rerank_with_scores(
        self, query: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        self.rerank_with_scores_calls.append((query, len(texts)))
        # Descending scores: first item gets highest score
        return [(i, 1.0 - i * 0.01) for i in range(len(texts))]


@pytest.mark.asyncio
async def test_single_batch():
    """With texts <= 32, calls rerank() directly."""
    reranker = MockReranker()
    texts = [f"text {i}" for i in range(20)]
    result = await batched_rerank(reranker, "query", texts)

    assert len(reranker.rerank_calls) == 1
    assert len(reranker.rerank_with_scores_calls) == 0
    assert result == list(range(20))


@pytest.mark.asyncio
async def test_multi_batch():
    """With texts > 32, chunks and merges by score."""
    reranker = MockReranker()
    texts = [f"text {i}" for i in range(50)]
    result = await batched_rerank(reranker, "query", texts)

    # Should have made 2 calls: 32 + 18
    assert len(reranker.rerank_with_scores_calls) == 2
    assert reranker.rerank_with_scores_calls[0][1] == RERANK_API_BATCH
    assert reranker.rerank_with_scores_calls[1][1] == 18
    assert len(result) == 50


@pytest.mark.asyncio
async def test_score_based_ordering():
    """Items from later batches with higher scores rank above earlier."""

    class ScoredReranker(RerankerService):
        async def rerank(self, query: str, texts: list[str]) -> list[int]:
            return list(range(len(texts)))

        async def rerank_with_scores(
            self, query: str, texts: list[str]
        ) -> list[tuple[int, float]]:
            # Second batch items get higher scores
            base_score = 2.0 if "batch2" in texts[0] else 1.0
            return [(i, base_score - i * 0.01) for i in range(len(texts))]

    texts = [f"batch1_{i}" for i in range(32)] + [
        f"batch2_{i}" for i in range(18)
    ]
    result = await batched_rerank(ScoredReranker(), "query", texts)

    # All batch2 items (indices 32-49) should rank before batch1 items
    batch2_positions = [result.index(i) for i in range(32, 50)]
    assert max(batch2_positions) < min([result.index(i) for i in range(32)])
