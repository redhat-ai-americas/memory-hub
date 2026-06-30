"""Tests for the cross-encoder cost/benefit benchmark engine.

Unit tests exercise the metrics and aggregation logic with synthetic
data and never touch the network. Live smoke tests (auto-marked ``perf``
by conftest.py) hit the deployed embedding and reranker services.

Run offline tests only::

    pytest tests/perf/test_cross_encoder.py -k "not single_query"

Run everything (requires cluster access)::

    pytest tests/perf/test_cross_encoder.py -v
"""

from __future__ import annotations

import math

from tests.perf.cross_encoder_bench import (
    CANDIDATE_SIZES,
    AggregatedCandidateSize,
    CandidateSizeResult,
    aggregate_by_size,
    recommend_candidate_size,
)
from tests.perf.metrics import ndcg_at_k


# ── NDCG unit tests ────────────────────────────────────────────────


def test_ndcg_perfect_ranking():
    """All relevant items ranked first -> NDCG = 1.0."""
    assert ndcg_at_k(["a", "b", "c", "x", "y"], {"a", "b", "c"}, k=5) == 1.0


def test_ndcg_inverse_ranking():
    """Relevant items at end -> NDCG < 1.0."""
    score = ndcg_at_k(["x", "y", "a", "b", "c"], {"a", "b", "c"}, k=5)
    assert 0 < score < 1.0


def test_ndcg_empty_relevant():
    """No relevant items -> NDCG = 0.0."""
    assert ndcg_at_k(["a", "b", "c"], set(), k=3) == 0.0


def test_ndcg_no_retrieved():
    """Empty retrieval -> NDCG = 0.0."""
    assert ndcg_at_k([], {"a"}, k=5) == 0.0


def test_ndcg_partial_overlap():
    """One relevant item at position 2 out of 3 relevant total."""
    score = ndcg_at_k(["x", "a", "y"], {"a", "b", "c"}, k=3)
    # DCG  = 0 + 1/log2(3) + 0 = 1/log2(3)
    # IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4)
    dcg = 1.0 / math.log2(3)
    idcg = 1.0 / math.log2(2) + 1.0 / math.log2(3) + 1.0 / math.log2(4)
    assert math.isclose(score, dcg / idcg, abs_tol=1e-9)


def test_ndcg_k_larger_than_retrieved():
    """k > len(retrieved) uses only available positions."""
    score = ndcg_at_k(["a", "b"], {"a", "b", "c"}, k=10)
    # Both retrieved items are relevant, but only 2 positions available
    dcg = 1.0 / math.log2(2) + 1.0 / math.log2(3)
    # IDCG uses min(k=10, |relevant|=3) = 3 ideal positions
    idcg = 1.0 / math.log2(2) + 1.0 / math.log2(3) + 1.0 / math.log2(4)
    assert math.isclose(score, dcg / idcg, abs_tol=1e-9)


# ── Aggregation unit tests ─────────────────────────────────────────


def _make_result(
    query_id: str,
    size: int,
    v_ndcg: float = 0.5,
    r_ndcg: float = 0.7,
    v_mrr: float = 0.4,
    r_mrr: float = 0.6,
    latency: float = 50.0,
) -> CandidateSizeResult:
    """Factory for synthetic CandidateSizeResult records."""
    return CandidateSizeResult(
        query_id=query_id,
        query_topic="deployment",
        candidate_size=size,
        vector_recall=0.1,
        vector_precision=0.5,
        vector_mrr=v_mrr,
        vector_ndcg=v_ndcg,
        reranked_recall=0.14,
        reranked_precision=0.6,
        reranked_mrr=r_mrr,
        reranked_ndcg=r_ndcg,
        recall_delta=0.04,
        precision_delta=0.1,
        mrr_delta=r_mrr - v_mrr,
        ndcg_delta=r_ndcg - v_ndcg,
        rerank_latency_ms=latency,
    )


def test_aggregate_groups_by_size():
    """Aggregation groups by candidate_size and averages metrics."""
    results = [
        _make_result("q1", 10, v_ndcg=0.4, r_ndcg=0.6, latency=30.0),
        _make_result("q2", 10, v_ndcg=0.5, r_ndcg=0.8, latency=40.0),
        _make_result("q1", 25, v_ndcg=0.3, r_ndcg=0.7, latency=60.0),
    ]
    agg = aggregate_by_size(results)
    assert len(agg) == 2  # sizes 10 and 25

    size_10 = next(a for a in agg if a.candidate_size == 10)
    assert size_10.n_queries == 2
    assert math.isclose(size_10.mean_vector_ndcg, 0.45, abs_tol=1e-9)
    assert math.isclose(size_10.mean_reranked_ndcg, 0.70, abs_tol=1e-9)
    assert math.isclose(size_10.mean_ndcg_delta, 0.25, abs_tol=1e-9)
    assert math.isclose(size_10.mean_rerank_latency_ms, 35.0, abs_tol=1e-9)
    # efficiency = 0.25 / 35.0
    assert math.isclose(size_10.ndcg_delta_per_ms, 0.25 / 35.0, abs_tol=1e-9)

    size_25 = next(a for a in agg if a.candidate_size == 25)
    assert size_25.n_queries == 1


def test_aggregate_sorted_by_size():
    """Aggregation returns results sorted by candidate_size ascending."""
    results = [
        _make_result("q1", 100),
        _make_result("q1", 10),
        _make_result("q1", 50),
    ]
    agg = aggregate_by_size(results)
    sizes = [a.candidate_size for a in agg]
    assert sizes == [10, 50, 100]


# ── Recommendation unit tests ──────────────────────────────────────


def test_recommend_picks_best_efficiency():
    """Recommendation picks the size with highest NDCG-delta-per-ms."""
    aggregated = [
        AggregatedCandidateSize(
            candidate_size=10, n_queries=40,
            mean_vector_ndcg=0.5, mean_reranked_ndcg=0.6,
            mean_ndcg_delta=0.10, mean_vector_mrr=0.4, mean_reranked_mrr=0.5,
            mean_mrr_delta=0.1, mean_rerank_latency_ms=30.0,
            ndcg_delta_per_ms=0.10 / 30.0,
        ),
        AggregatedCandidateSize(
            candidate_size=25, n_queries=40,
            mean_vector_ndcg=0.5, mean_reranked_ndcg=0.7,
            mean_ndcg_delta=0.20, mean_vector_mrr=0.4, mean_reranked_mrr=0.6,
            mean_mrr_delta=0.2, mean_rerank_latency_ms=50.0,
            ndcg_delta_per_ms=0.20 / 50.0,
        ),
        AggregatedCandidateSize(
            candidate_size=50, n_queries=40,
            mean_vector_ndcg=0.5, mean_reranked_ndcg=0.72,
            mean_ndcg_delta=0.22, mean_vector_mrr=0.4, mean_reranked_mrr=0.62,
            mean_mrr_delta=0.22, mean_rerank_latency_ms=120.0,
            ndcg_delta_per_ms=0.22 / 120.0,
        ),
    ]
    rec = recommend_candidate_size(aggregated)
    # Size 25 has best efficiency: 0.20/50 = 0.004 vs 0.10/30 = 0.0033
    assert rec["recommended_size"] == 25
    assert rec["efficiency"] > 0


def test_recommend_handles_no_improvement():
    """When reranking never helps, recommend smallest size."""
    aggregated = [
        AggregatedCandidateSize(
            candidate_size=10, n_queries=10,
            mean_vector_ndcg=0.5, mean_reranked_ndcg=0.49,
            mean_ndcg_delta=-0.01, mean_vector_mrr=0.4, mean_reranked_mrr=0.39,
            mean_mrr_delta=-0.01, mean_rerank_latency_ms=30.0,
            ndcg_delta_per_ms=-0.01 / 30.0,
        ),
        AggregatedCandidateSize(
            candidate_size=50, n_queries=10,
            mean_vector_ndcg=0.5, mean_reranked_ndcg=0.48,
            mean_ndcg_delta=-0.02, mean_vector_mrr=0.4, mean_reranked_mrr=0.38,
            mean_mrr_delta=-0.02, mean_rerank_latency_ms=100.0,
            ndcg_delta_per_ms=-0.02 / 100.0,
        ),
    ]
    rec = recommend_candidate_size(aggregated)
    assert rec["recommended_size"] == 10
    assert "did not improve" in rec["reason"]


def test_recommend_empty_input():
    """Empty aggregation falls back to first default candidate size."""
    rec = recommend_candidate_size([])
    assert rec["recommended_size"] == CANDIDATE_SIZES[0]
    assert rec["reason"] == "no data"


# ── Live smoke test ────────────────────────────────────────────────


def test_single_query_all_candidate_sizes():
    """Smoke test: one query through all 4 candidate sizes.

    Exercises the full pipeline end-to-end against deployed services.
    Runs one query to keep latency manageable while still validating
    that embedding, cosine retrieval, batched reranking, and metric
    computation all work together.
    """
    from tests.perf.cross_encoder_bench import evaluate_query_at_size, get_relevant_ids
    from tests.perf.two_vector_bench import EmbeddingClient, RerankerClient, load_dataset

    embedder = EmbeddingClient()
    try:
        dataset = load_dataset(embedder)
    finally:
        embedder.close()

    query = next(q for q in dataset.queries if q.id == "deployment-s1")
    relevant = get_relevant_ids(query, dataset)

    reranker = RerankerClient()
    try:
        for size in CANDIDATE_SIZES:
            result = evaluate_query_at_size(query, dataset, reranker, size, relevant)
            assert result.candidate_size == size
            assert result.rerank_latency_ms > 0
            assert 0 <= result.reranked_ndcg <= 1.0
            assert 0 <= result.vector_ndcg <= 1.0
            assert result.query_id == "deployment-s1"
    finally:
        reranker.close()
