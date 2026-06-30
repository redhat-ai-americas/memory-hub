"""Shared retrieval quality metrics for perf benchmarks.

Extracted from two_vector_bench.py so both the two-vector and
cross-encoder benchmarks use the same metric implementations.
"""

from __future__ import annotations

import math


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of relevant items recovered in the top-k.

    Note: with 50 relevant memories per topic and k=10, the maximum
    achievable Recall@10 is 10/50=0.2. Compare relative values across
    pipelines, not absolute.
    """
    if not relevant_ids:
        return 0.0
    top = retrieved_ids[:k]
    hit = sum(1 for mid in top if mid in relevant_ids)
    return hit / len(relevant_ids)


def precision_at_k(
    retrieved_ids: list[str], relevant_ids: set[str], k: int
) -> float:
    """Fraction of top-k items that are relevant."""
    top = retrieved_ids[:k]
    if not top:
        return 0.0
    hit = sum(1 for mid in top if mid in relevant_ids)
    return hit / len(top)


def mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """Mean reciprocal rank: 1 / position of first relevant result."""
    for rank, mid in enumerate(retrieved_ids, start=1):
        if mid in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalized discounted cumulative gain with binary relevance.

    DCG  = sum(rel_i / log2(i + 2)) for i in range(k)
    IDCG = sum(1 / log2(i + 2))     for i in range(min(k, |relevant|))
    NDCG = DCG / IDCG; returns 0.0 if IDCG is 0.
    """
    top = retrieved_ids[:k]
    dcg = 0.0
    for i, mid in enumerate(top):
        if mid in relevant_ids:
            dcg += 1.0 / math.log2(i + 2)

    n_ideal = min(k, len(relevant_ids))
    if n_ideal == 0:
        return 0.0
    idcg = sum(1.0 / math.log2(i + 2) for i in range(n_ideal))
    return dcg / idcg
