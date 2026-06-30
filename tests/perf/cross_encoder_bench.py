"""Cross-encoder cost/benefit benchmark engine.

Measures the relevance lift (NDCG, MRR) and latency cost of cross-encoder
re-ranking at candidate set sizes of 10, 25, 50, and 100. For each query
in the synthetic dataset, the benchmark:

  1. Retrieves `candidate_size` memories by cosine similarity.
  2. Computes vector-only quality metrics on the top N_FINAL results.
  3. Re-ranks with the deployed cross-encoder, measures latency.
  4. Computes re-ranked quality metrics on the top N_FINAL results.
  5. Reports per-query deltas and an aggregate efficiency metric
     (NDCG-delta per millisecond of re-ranking latency).

Both ``tests/perf/test_cross_encoder.py`` and
``scripts/bench-cross-encoder.py`` consume this module.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from tests.perf.metrics import mrr, ndcg_at_k, precision_at_k, recall_at_k
from tests.perf.two_vector_bench import (
    Dataset,
    EmbeddingClient,
    Memory,
    Query,
    RerankerClient,
    cosine_topk,
    load_dataset,
    rerank_candidates,
)

# ── Constants ──────────────────────────────────────────────────────

CANDIDATE_SIZES = [10, 25, 50, 100]
N_FINAL = 10  # final result count for metrics


# ── Result data classes ────────────────────────────────────────────


@dataclass
class CandidateSizeResult:
    """One query evaluated at one candidate size."""

    query_id: str
    query_topic: str
    candidate_size: int
    # Vector-only metrics (top N_FINAL from cosine ranking)
    vector_recall: float
    vector_precision: float
    vector_mrr: float
    vector_ndcg: float
    # Reranked metrics (top N_FINAL after cross-encoder)
    reranked_recall: float
    reranked_precision: float
    reranked_mrr: float
    reranked_ndcg: float
    # Deltas (reranked - vector)
    recall_delta: float
    precision_delta: float
    mrr_delta: float
    ndcg_delta: float
    # Latency
    rerank_latency_ms: float


@dataclass
class AggregatedCandidateSize:
    """Mean metrics across all queries for one candidate size."""

    candidate_size: int
    n_queries: int
    mean_vector_ndcg: float
    mean_reranked_ndcg: float
    mean_ndcg_delta: float
    mean_vector_mrr: float
    mean_reranked_mrr: float
    mean_mrr_delta: float
    mean_rerank_latency_ms: float
    ndcg_delta_per_ms: float  # efficiency: mean_ndcg_delta / mean_rerank_latency_ms


# ── Core functions ─────────────────────────────────────────────────


def get_relevant_ids(query: Query, dataset: Dataset) -> set[str]:
    """Determine which memories are relevant to a query based on topic match."""
    return {m.id for m in dataset.memories if m.topic == query.topic}


def batched_rerank(
    query_text: str,
    candidates: list[Memory],
    reranker: RerankerClient,
) -> list[str]:
    """Rerank candidates in batches of MAX_BATCH, merge by score.

    When candidate_size exceeds the reranker's per-call limit (32), we
    split into chunks, rerank each independently, then merge all
    (index, score) pairs by descending score to produce a single
    global ranking.
    """
    max_batch = RerankerClient.MAX_BATCH
    if len(candidates) <= max_batch:
        return rerank_candidates(query_text, candidates, reranker)

    # Split into chunks and rerank each
    all_scored: list[tuple[str, float]] = []
    for start in range(0, len(candidates), max_batch):
        chunk = candidates[start : start + max_batch]
        resp = reranker.rerank(query_text, [m.content for m in chunk])
        for item in resp:
            mem_id = chunk[item["index"]].id
            all_scored.append((mem_id, item["score"]))

    # Sort by descending score across all chunks
    all_scored.sort(key=lambda pair: pair[1], reverse=True)
    return [mid for mid, _ in all_scored]


def evaluate_query_at_size(
    query: Query,
    dataset: Dataset,
    reranker: RerankerClient,
    candidate_size: int,
    relevant_ids: set[str],
) -> CandidateSizeResult:
    """Run one query at one candidate size, measure everything."""
    # 1. Cosine top-k to get the candidate pool
    candidates = cosine_topk(query.embedding, dataset.memories, candidate_size)

    # 2. Vector-only: take first N_FINAL from cosine ranking
    vector_ids = [m.id for m in candidates[:N_FINAL]]

    # 3. Compute vector-only metrics
    v_recall = recall_at_k(vector_ids, relevant_ids, N_FINAL)
    v_precision = precision_at_k(vector_ids, relevant_ids, N_FINAL)
    v_mrr = mrr(vector_ids, relevant_ids)
    v_ndcg = ndcg_at_k(vector_ids, relevant_ids, N_FINAL)

    # 4. Rerank candidates, timing the call
    t0 = time.perf_counter()
    reranked_ids = batched_rerank(query.text, candidates, reranker)
    rerank_ms = (time.perf_counter() - t0) * 1000.0

    # 5. Reranked: take first N_FINAL
    reranked_top = reranked_ids[:N_FINAL]

    # 6. Compute reranked metrics
    r_recall = recall_at_k(reranked_top, relevant_ids, N_FINAL)
    r_precision = precision_at_k(reranked_top, relevant_ids, N_FINAL)
    r_mrr = mrr(reranked_top, relevant_ids)
    r_ndcg = ndcg_at_k(reranked_top, relevant_ids, N_FINAL)

    return CandidateSizeResult(
        query_id=query.id,
        query_topic=query.topic,
        candidate_size=candidate_size,
        vector_recall=v_recall,
        vector_precision=v_precision,
        vector_mrr=v_mrr,
        vector_ndcg=v_ndcg,
        reranked_recall=r_recall,
        reranked_precision=r_precision,
        reranked_mrr=r_mrr,
        reranked_ndcg=r_ndcg,
        recall_delta=r_recall - v_recall,
        precision_delta=r_precision - v_precision,
        mrr_delta=r_mrr - v_mrr,
        ndcg_delta=r_ndcg - v_ndcg,
        rerank_latency_ms=rerank_ms,
    )


def aggregate_by_size(
    results: list[CandidateSizeResult],
) -> list[AggregatedCandidateSize]:
    """Group results by candidate_size and compute means."""
    groups: dict[int, list[CandidateSizeResult]] = {}
    for r in results:
        groups.setdefault(r.candidate_size, []).append(r)

    aggregated: list[AggregatedCandidateSize] = []
    for size in sorted(groups):
        group = groups[size]
        n = len(group)
        mean_v_ndcg = sum(r.vector_ndcg for r in group) / n
        mean_r_ndcg = sum(r.reranked_ndcg for r in group) / n
        mean_ndcg_d = sum(r.ndcg_delta for r in group) / n
        mean_v_mrr = sum(r.vector_mrr for r in group) / n
        mean_r_mrr = sum(r.reranked_mrr for r in group) / n
        mean_mrr_d = sum(r.mrr_delta for r in group) / n
        mean_lat = sum(r.rerank_latency_ms for r in group) / n
        efficiency = mean_ndcg_d / mean_lat if mean_lat > 0 else 0.0

        aggregated.append(
            AggregatedCandidateSize(
                candidate_size=size,
                n_queries=n,
                mean_vector_ndcg=mean_v_ndcg,
                mean_reranked_ndcg=mean_r_ndcg,
                mean_ndcg_delta=mean_ndcg_d,
                mean_vector_mrr=mean_v_mrr,
                mean_reranked_mrr=mean_r_mrr,
                mean_mrr_delta=mean_mrr_d,
                mean_rerank_latency_ms=mean_lat,
                ndcg_delta_per_ms=efficiency,
            )
        )

    return aggregated


def recommend_candidate_size(
    aggregated: list[AggregatedCandidateSize],
) -> dict:
    """Pick optimal candidate size by NDCG-delta-per-ms efficiency.

    Returns a dict with the recommended size, the reason, and the
    efficiency score.  When all deltas are non-positive (re-ranking
    hurts or is neutral), the recommendation is the smallest size
    with a note explaining why.
    """
    if not aggregated:
        return {
            "recommended_size": CANDIDATE_SIZES[0],
            "reason": "no data",
            "efficiency": 0.0,
        }

    # Filter to sizes where reranking actually helped
    positive = [a for a in aggregated if a.mean_ndcg_delta > 0]
    if not positive:
        smallest = min(aggregated, key=lambda a: a.candidate_size)
        return {
            "recommended_size": smallest.candidate_size,
            "reason": (
                "re-ranking did not improve NDCG at any candidate size; "
                "recommend smallest to minimize wasted latency"
            ),
            "efficiency": smallest.ndcg_delta_per_ms,
        }

    best = max(positive, key=lambda a: a.ndcg_delta_per_ms)
    return {
        "recommended_size": best.candidate_size,
        "reason": (
            f"best NDCG-delta-per-ms efficiency at candidate_size={best.candidate_size}: "
            f"+{best.mean_ndcg_delta:.4f} NDCG in {best.mean_rerank_latency_ms:.1f}ms"
        ),
        "efficiency": best.ndcg_delta_per_ms,
    }


# ── Top-level driver ───────────────────────────────────────────────


def run_cross_encoder_benchmark(
    progress: Callable[[str], None] | None = None,
) -> tuple[Dataset, list[CandidateSizeResult], dict]:
    """Full benchmark: load dataset, run all queries x all candidate sizes.

    Returns (dataset, all_results, timings).
    """
    log = progress or (lambda msg: None)
    timings: dict[str, float] = {}

    # 1. Load and embed dataset
    log("loading and embedding dataset")
    t0 = time.perf_counter()
    embedder = EmbeddingClient()
    try:
        dataset = load_dataset(embedder)
    finally:
        embedder.close()
    timings["embed_dataset_seconds"] = time.perf_counter() - t0
    log(
        f"  embedded {len(dataset.memories)} memories, "
        f"{len(dataset.queries)} queries "
        f"({timings['embed_dataset_seconds']:.1f}s)"
    )

    # 2. Run all queries x all candidate sizes
    log("running cross-encoder benchmark")
    t1 = time.perf_counter()
    all_results: list[CandidateSizeResult] = []
    reranker = RerankerClient()
    try:
        for idx, query in enumerate(dataset.queries, start=1):
            relevant = get_relevant_ids(query, dataset)
            for size in CANDIDATE_SIZES:
                log(
                    f"  query {idx}/{len(dataset.queries)} ({query.id}), "
                    f"candidates={size}"
                )
                result = evaluate_query_at_size(
                    query, dataset, reranker, size, relevant
                )
                all_results.append(result)
    finally:
        reranker.close()
    timings["benchmark_seconds"] = time.perf_counter() - t1
    log(
        f"  produced {len(all_results)} results "
        f"({timings['benchmark_seconds']:.1f}s)"
    )

    return dataset, all_results, timings
