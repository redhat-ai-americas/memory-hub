"""Cross-encoder reranker service interface and implementations.

Wraps the deployed cross-encoder reranker (granite-embedding-reranker-english-r2)
served via TEI (Text Embeddings Inference). Used by `search_memories`
as the rerank stage of two-vector retrieval (#58).

The reranker is optional: when no URL is configured (or the call
fails) `search_memories` falls back to a cosine-rank-only blend. The
fallback path produces correct results, just without the cross-encoder
lift on noisy queries. Empirical results in the two-vector benchmark
show the cross-encoder is roughly neutral on short topic-coherent
project memories but the architecture handles longer noisier inputs
correctly when they appear in production.

See `research/agent-memory-ergonomics/two-vector-retrieval.md`
for the benchmark that drove this design.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


# The deployed reranker reports max_client_batch_size=32 from /info.
# This is a hard server-side limit -- larger batches are rejected.
RERANK_API_BATCH = 32

# Rerank pool size: how many candidates from the recall pool to rerank.
# Can exceed RERANK_API_BATCH; batched_rerank chunks the pool into
# API-sized batches and merges by score.
RERANK_POOL_SIZE = int(os.environ.get("MEMORYHUB_RERANK_POOL_SIZE", "24"))


class RerankerService(ABC):
    """Interface for cross-encoder reranking.

    Implementations take a query and a list of candidate texts and
    return the candidate indices in cross-encoder rank order (best
    first). The service may return fewer indices than inputs if the
    backend filters internally; callers should handle that case.
    """

    @abstractmethod
    async def rerank(self, query: str, texts: list[str]) -> list[int]:
        """Return candidate indices in descending cross-encoder rank order.

        Args:
            query: The query string to score candidates against.
            texts: Candidate texts. Length must be <= RERANK_API_BATCH.

        Returns:
            A list of input indices sorted by descending relevance.
            Length matches the input length when the backend returns
            scores for every input.

        Raises:
            ValueError: If `texts` exceeds RERANK_API_BATCH.
            httpx.HTTPError: If the network call fails. Callers in
                `search_memories` catch this and degrade to the cosine
                fallback path; do not retry inside the implementation.
        """
        ...

    @abstractmethod
    async def rerank_with_scores(
        self, query: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        """Return (index, score) pairs in descending score order.

        Same contract as rerank() but preserves the cross-encoder scores
        for cross-batch merging in batched_rerank().
        """
        ...


class HttpRerankerService(RerankerService):
    """Reranker service that calls a TEI-compatible HTTP endpoint.

    Compatible with the deployed `ms-marco-MiniLM-L12-v2` model. Sends
    `POST /rerank {"query": str, "texts": [str, ...]}` and parses
    `[{"index": int, "score": float}, ...]` responses. The service
    returns results pre-sorted by descending score, so this client
    only needs to extract the indices in order.
    """

    def __init__(self, url: str | None = None) -> None:
        base = url or os.environ.get("MEMORYHUB_RERANKER_URL", "")
        # Normalize to the /rerank endpoint regardless of how the URL
        # is configured. Some deployments will set the bare base URL
        # (no path); others may already include /rerank.
        if base and not base.rstrip("/").endswith("/rerank"):
            base = base.rstrip("/") + "/rerank"
        self.url = base
        self._client = httpx.AsyncClient(timeout=30.0)

    async def rerank(self, query: str, texts: list[str]) -> list[int]:
        if not self.url:
            # Should never reach here -- callers check is_configured()
            # before calling. Defensive guard with a clear message.
            raise RuntimeError(
                "HttpRerankerService called without a configured URL; "
                "set MEMORYHUB_RERANKER_URL or pass url=... to construct."
            )
        if len(texts) > RERANK_API_BATCH:
            raise ValueError(
                f"rerank batch size {len(texts)} exceeds "
                f"RERANK_API_BATCH={RERANK_API_BATCH}; the deployed reranker "
                "rejects larger batches in a single call"
            )
        response = await self._client.post(
            self.url, json={"query": query, "texts": texts}
        )
        response.raise_for_status()
        data = response.json()
        # Service returns [{"index": int, "score": float}, ...] sorted
        # descending by score. Extract indices preserving that order.
        return [item["index"] for item in data]

    async def rerank_with_scores(
        self, query: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        if not self.url:
            raise RuntimeError(
                "HttpRerankerService called without a configured URL; "
                "set MEMORYHUB_RERANKER_URL or pass url=... to construct."
            )
        if len(texts) > RERANK_API_BATCH:
            raise ValueError(
                f"rerank batch size {len(texts)} exceeds "
                f"RERANK_API_BATCH={RERANK_API_BATCH}; the deployed reranker "
                "rejects larger batches in a single call"
            )
        response = await self._client.post(
            self.url, json={"query": query, "texts": texts}
        )
        response.raise_for_status()
        data = response.json()
        return [(item["index"], item["score"]) for item in data]

    @property
    def is_configured(self) -> bool:
        """True iff a reranker URL was provided.

        Used by `search_memories` to decide whether to attempt the
        cross-encoder rerank stage at all. The service still raises
        on call when not configured, but callers can avoid the round
        trip by checking this property first.
        """
        return bool(self.url)


class NoopRerankerService(RerankerService):
    """Reranker that returns inputs in their original order.

    Used in tests and for deployments that don't have a reranker
    available. The `is_configured` property is always False so
    `search_memories` will skip the rerank stage and fall through
    to the cosine fallback path -- exactly the same code path that
    runs when the HTTP reranker is unreachable.
    """

    async def rerank(self, query: str, texts: list[str]) -> list[int]:
        return list(range(len(texts)))

    async def rerank_with_scores(
        self, query: str, texts: list[str]
    ) -> list[tuple[int, float]]:
        return [(i, 1.0 - i * 0.01) for i in range(len(texts))]

    @property
    def is_configured(self) -> bool:
        return False


async def batched_rerank(
    reranker: RerankerService, query: str, texts: list[str]
) -> list[int]:
    """Rerank texts in batches of RERANK_API_BATCH, merge by score.

    When len(texts) <= RERANK_API_BATCH, makes a single call.
    Otherwise splits into chunks, reranks each, and merges by
    cross-encoder score to produce a global ranking.
    """
    if len(texts) <= RERANK_API_BATCH:
        return await reranker.rerank(query, texts)

    all_scored: list[tuple[int, float]] = []
    for chunk_start in range(0, len(texts), RERANK_API_BATCH):
        chunk_texts = texts[chunk_start : chunk_start + RERANK_API_BATCH]
        chunk_scores = await reranker.rerank_with_scores(query, chunk_texts)
        for local_idx, score in chunk_scores:
            all_scored.append((chunk_start + local_idx, score))

    all_scored.sort(key=lambda pair: pair[1], reverse=True)
    return [idx for idx, _ in all_scored]
