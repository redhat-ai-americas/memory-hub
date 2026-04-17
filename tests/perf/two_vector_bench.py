"""Benchmark engine for two-vector retrieval.

Implements the four candidate pipelines (baseline, NEW-1 RRF blend,
NEW-2 focus-augmented query, NEW-3 cross-encoder only) and computes
recall/precision/MRR metrics over a synthetic dataset.

The engine takes pre-computed embeddings, so the network calls
(embedding service + reranker) happen exactly once per memory/query
regardless of how many pipelines or weight values get evaluated.

Both `tests/perf/test_two_vector_retrieval.py` and
`scripts/bench-two-vector.py` consume this module.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from tests.perf.fixtures.queries import QUERIES
from tests.perf.fixtures.topics import FOCUS_STRINGS, TOPICS, all_memories

# ── Endpoint configuration ───────────────────────────────────────────

DEFAULT_EMBEDDING_URL = (
    "https://all-minilm-l6-v2-embedding-model.apps.cluster-n7pd5."
    "n7pd5.sandbox5167.opentlc.com/embed"
)
DEFAULT_RERANKER_URL = (
    "https://ms-marco-minilm-l12-v2-reranker-model.apps.cluster-n7pd5."
    "n7pd5.sandbox5167.opentlc.com"
)


def embedding_url() -> str:
    return os.environ.get("MEMORYHUB_EMBEDDING_URL", DEFAULT_EMBEDDING_URL)


def reranker_url() -> str:
    return os.environ.get("MEMORYHUB_RERANKER_URL", DEFAULT_RERANKER_URL)


# ── Network helpers ─────────────────────────────────────────────────


class EmbeddingClient:
    """Thin sync wrapper around the deployed all-MiniLM-L6-v2 service.

    The deployed service accepts one input per call. This client batches
    sequentially and exposes a simple `embed_many` for fixture loading.
    """

    def __init__(self, url: str | None = None, timeout: float = 30.0) -> None:
        self._url = url or embedding_url()
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def embed(self, text: str) -> list[float]:
        resp = self._client.post(self._url, json={"inputs": text})
        resp.raise_for_status()
        data = resp.json()
        # Service returns [[float, ...]] or [float, ...]; normalize to flat.
        return data[0] if isinstance(data[0], list) else data

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class RerankerClient:
    """Thin sync wrapper around the deployed ms-marco-MiniLM-L12-v2 reranker.

    POST /rerank takes {query, texts} and returns a list of
    {index, score} dicts pre-sorted by descending score. We re-key by
    input index so callers can map back to memory IDs without juggling
    the sorted order themselves.
    """

    # Reranker /info reports max_client_batch_size=32. K=32 keeps every
    # rerank call single-batch and avoids the latency cliff at >32.
    MAX_BATCH = 32

    def __init__(self, url: str | None = None, timeout: float = 60.0) -> None:
        base = url or reranker_url()
        self._url = base.rstrip("/") + "/rerank"
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def rerank(self, query: str, texts: list[str]) -> list[dict]:
        """Return [{index, score}, ...] in the order returned by the service.

        The service is sorted by descending score. The caller can build
        rank_by_index from this list.
        """
        if len(texts) > self.MAX_BATCH:
            raise ValueError(
                f"reranker batch {len(texts)} exceeds MAX_BATCH={self.MAX_BATCH}; "
                "the benchmark expects K<=32"
            )
        resp = self._client.post(
            self._url, json={"query": query, "texts": texts}
        )
        resp.raise_for_status()
        return resp.json()


# ── Math helpers ────────────────────────────────────────────────────


def cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity for two equal-length float vectors.

    Assumes the vectors are already L2-normalized (the embedding service
    returns normalized vectors). Falls back to a full normalization if
    they aren't, so the function is correct even when callers feed it
    raw inputs.
    """
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def rank_dict(ordered_ids: list[str]) -> dict[str, int]:
    """Return {id: 1-based rank} for an ordered list."""
    return {mid: rank for rank, mid in enumerate(ordered_ids, start=1)}


def reciprocal_rank_fusion(
    rank_a: dict[str, int],
    rank_b: dict[str, int],
    weight_b: float,
    k: int = 60,
) -> list[str]:
    """Blend two rank dicts via weighted RRF.

    Standard RRF score is sum(1 / (k + rank)). The weight controls
    rank_b's contribution: weight_b=0.0 collapses to rank_a only,
    weight_b=1.0 collapses to rank_b only. Memories that appear in
    only one of the two rank dicts get a contribution from that dict
    only -- their absence from the other dict is treated as "rank
    infinity" (contributes 0 to the score).
    """
    weight_a = 1.0 - weight_b
    all_ids = set(rank_a) | set(rank_b)
    scored: list[tuple[str, float]] = []
    for mid in all_ids:
        score = 0.0
        if mid in rank_a:
            score += weight_a / (k + rank_a[mid])
        if mid in rank_b:
            score += weight_b / (k + rank_b[mid])
        scored.append((mid, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [mid for mid, _ in scored]


# ── Pipeline data and dataset cache ─────────────────────────────────


@dataclass
class Memory:
    id: str
    topic: str
    content: str
    weight: float
    embedding: list[float] = field(default_factory=list)


@dataclass
class Query:
    id: str
    topic: str
    level: str
    text: str
    embedding: list[float] = field(default_factory=list)


@dataclass
class Dataset:
    memories: list[Memory]
    queries: list[Query]
    focus_embeddings: dict[str, list[float]]  # topic -> embedding

    @property
    def memories_by_id(self) -> dict[str, Memory]:
        return {m.id: m for m in self.memories}


def load_dataset(embedder: EmbeddingClient) -> Dataset:
    """Materialize the synthetic dataset and embed everything once.

    The embedding pass dominates wall time -- ~244 calls (200 memories
    + 40 queries + 4 focus strings). With the deployed service responding
    in ~50ms each, total fixture warm-up is roughly 12 seconds.
    """
    memories = [
        Memory(
            id=row["id"],
            topic=row["topic"],
            content=row["content"],
            weight=row["weight"],
        )
        for row in all_memories()
    ]
    queries = [
        Query(
            id=q["id"],
            topic=q["topic"],
            level=q["level"],
            text=q["text"],
        )
        for q in QUERIES
    ]

    for mem in memories:
        mem.embedding = embedder.embed(mem.content)
    for q in queries:
        q.embedding = embedder.embed(q.text)
    focus_embeddings = {topic: embedder.embed(FOCUS_STRINGS[topic]) for topic in TOPICS}

    return Dataset(
        memories=memories,
        queries=queries,
        focus_embeddings=focus_embeddings,
    )


# ── Recall + ranking primitives ─────────────────────────────────────

K_RECALL = 32  # candidate pool size for cross-encoder rerank
N_FINAL = 10   # final result count for metrics


def cosine_topk(
    query_emb: list[float],
    memories: list[Memory],
    k: int,
) -> list[Memory]:
    """Top-k memories by cosine similarity to the query embedding."""
    scored = [(cosine_sim(query_emb, m.embedding), m) for m in memories]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _, m in scored[:k]]


def cosine_rank_for_focus(
    focus_emb: list[float],
    memories: list[Memory],
) -> dict[str, int]:
    """Rank-by-focus-cosine over a candidate set, 1-based."""
    scored = [(cosine_sim(focus_emb, m.embedding), m.id) for m in memories]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return {mid: rank for rank, (_, mid) in enumerate(scored, start=1)}


# ── Pipelines ───────────────────────────────────────────────────────


def pipeline_baseline(query: Query, dataset: Dataset) -> list[str]:
    """Pure pgvector cosine top-N. No rerank, no focus.

    Mirrors the current production behavior. Used as the floor for
    every other pipeline.
    """
    top = cosine_topk(query.embedding, dataset.memories, N_FINAL)
    return [m.id for m in top]


def rerank_candidates(
    query_text: str,
    candidates: list[Memory],
    reranker: RerankerClient,
) -> list[str]:
    """Rerank a candidate list with the cross-encoder.

    Returns the candidate IDs in cross-encoder rank order. Pulled out
    so callers (and the cached path in evaluate_query) can share one
    network call across multiple downstream blends.
    """
    rerank_resp = reranker.rerank(query_text, [m.content for m in candidates])
    return [candidates[item["index"]].id for item in rerank_resp]


def pipeline_new3_rerank_only(
    query: Query,
    dataset: Dataset,
    reranker: RerankerClient,
    *,
    precomputed_rerank: list[str] | None = None,
) -> list[str]:
    """Recall by query cosine, rerank by cross-encoder, no focus.

    Measures the lift from the cross-encoder alone, separately from
    any focus integration. NEW-3 in the design space. Pass
    `precomputed_rerank` to skip the network call when the same query
    has already been reranked by another pipeline (NEW-1 shares this
    rerank because its cross-encoder input is also `query.text`).
    """
    if precomputed_rerank is not None:
        return precomputed_rerank[:N_FINAL]
    candidates = cosine_topk(query.embedding, dataset.memories, K_RECALL)
    ordered_ids = rerank_candidates(query.text, candidates, reranker)
    return ordered_ids[:N_FINAL]


def pipeline_new1_rrf_blend(
    query: Query,
    dataset: Dataset,
    focus_emb: list[float] | None,
    weight: float,
    reranker: RerankerClient,
    *,
    precomputed_rerank: list[str] | None = None,
    precomputed_candidates: list[Memory] | None = None,
) -> list[str]:
    """Recall + cross-encoder rerank + RRF blend with focus cosine ranks.

    NEW-1 in the design space. weight=0.0 collapses to NEW-3 (rerank
    only). The cross-encoder call only depends on the query, so the
    caller can pass `precomputed_rerank` to amortize one network call
    across the entire weight sweep. `precomputed_candidates` lets the
    same caller skip the cosine_topk pass on each weight value.
    """
    candidates = (
        precomputed_candidates
        if precomputed_candidates is not None
        else cosine_topk(query.embedding, dataset.memories, K_RECALL)
    )

    if precomputed_rerank is not None:
        rerank_order = precomputed_rerank
    else:
        rerank_order = rerank_candidates(query.text, candidates, reranker)

    if focus_emb is None or weight <= 0.0:
        return rerank_order[:N_FINAL]

    rank_ce = rank_dict(rerank_order)
    rank_focus = cosine_rank_for_focus(focus_emb, candidates)
    blended = reciprocal_rank_fusion(rank_ce, rank_focus, weight_b=weight)
    return blended[:N_FINAL]


def pipeline_new2_augmented_query(
    query: Query,
    dataset: Dataset,
    focus_string: str | None,
    reranker: RerankerClient,
    *,
    precomputed_candidates: list[Memory] | None = None,
) -> list[str]:
    """Recall + cross-encoder rerank with focus prepended to query string.

    NEW-2 in the design space. The cross-encoder receives
    f"{focus_string}. {query.text}" instead of just query.text. When no
    focus is set, behaves exactly like NEW-3 but does NOT share that
    rerank because callers usually invoke NEW-2 only when focus is set.
    """
    candidates = (
        precomputed_candidates
        if precomputed_candidates is not None
        else cosine_topk(query.embedding, dataset.memories, K_RECALL)
    )
    rerank_text = (
        f"{focus_string}. {query.text}" if focus_string else query.text
    )
    ordered_ids = rerank_candidates(rerank_text, candidates, reranker)
    return ordered_ids[:N_FINAL]


# ── Metrics ─────────────────────────────────────────────────────────


def relevant_ids_for_query(query: Query, dataset: Dataset) -> set[str]:
    """Memories whose ground-truth topic matches the query's target topic."""
    return {m.id for m in dataset.memories if m.topic == query.topic}


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


# ── Sweep runner ────────────────────────────────────────────────────


@dataclass
class RunResult:
    """One pipeline run on one query under one session condition.

    `condition` is one of: 'baseline_no_focus', 'focus_match', 'focus_cross'.
    `weight` is only meaningful for NEW-1 (None for the others).
    `cross_focus_topic` records which topic the focus_cross run used,
    for averaging across the three other-topic foci.
    """

    pipeline: str
    query_id: str
    query_topic: str
    query_level: str
    condition: str
    weight: float | None
    cross_focus_topic: str | None
    retrieved_ids: list[str]
    recall_at_10: float
    precision_at_10: float
    mrr: float


PIPELINES_NO_FOCUS = ["baseline", "new3"]
PIPELINES_WITH_FOCUS = ["new1", "new2", "new3"]
NEW1_WEIGHT_SWEEP = [0.0, 0.2, 0.4, 0.6, 0.8]


def evaluate_query(
    query: Query,
    dataset: Dataset,
    reranker: RerankerClient,
    pipelines: list[str] | None = None,
) -> list[RunResult]:
    """Run every pipeline-condition combination for one query.

    Returns a flat list of RunResult records. The cross-encoder rerank
    by `query.text` is computed exactly once and shared by NEW-3 and
    every weight value of NEW-1 (their cross-encoder input is identical
    -- only the post-rerank blend changes). NEW-2 makes a separate
    rerank call per focus condition because its rerank input depends
    on the focus string.

    Per query, this issues:
        cosine_topk:  1 (in-process)
        rerank calls: 1 (NEW-3 / NEW-1, shared) + 1 (NEW-2 focus_match)
                      + (#other_topics) (NEW-2 focus_cross)
                    = 5 reranker calls per query for the full design space.
    """
    pipelines = pipelines or ["baseline", "new1", "new2", "new3"]
    relevant = relevant_ids_for_query(query, dataset)
    results: list[RunResult] = []

    def make_record(
        pipeline: str,
        condition: str,
        weight: float | None,
        cross_focus_topic: str | None,
        retrieved: list[str],
    ) -> RunResult:
        return RunResult(
            pipeline=pipeline,
            query_id=query.id,
            query_topic=query.topic,
            query_level=query.level,
            condition=condition,
            weight=weight,
            cross_focus_topic=cross_focus_topic,
            retrieved_ids=retrieved,
            recall_at_10=recall_at_k(retrieved, relevant, N_FINAL),
            precision_at_10=precision_at_k(retrieved, relevant, N_FINAL),
            mrr=mrr(retrieved, relevant),
        )

    # Pre-compute the candidate set + the shared cross-encoder rerank
    # once per query so the weight sweeps and rerank-sharing pipelines
    # only pay one network call.
    candidates = cosine_topk(query.embedding, dataset.memories, K_RECALL)
    needs_query_rerank = "new3" in pipelines or "new1" in pipelines
    cached_query_rerank: list[str] | None = None
    if needs_query_rerank:
        cached_query_rerank = rerank_candidates(query.text, candidates, reranker)

    # ── Condition: baseline_no_focus ────────────────────────────────
    if "baseline" in pipelines:
        retrieved = pipeline_baseline(query, dataset)
        results.append(
            make_record("baseline", "baseline_no_focus", None, None, retrieved)
        )

    if "new3" in pipelines:
        retrieved = pipeline_new3_rerank_only(
            query, dataset, reranker, precomputed_rerank=cached_query_rerank
        )
        results.append(
            make_record("new3", "baseline_no_focus", None, None, retrieved)
        )

    # ── Condition: focus_match ──────────────────────────────────────
    match_focus_emb = dataset.focus_embeddings[query.topic]
    match_focus_string = FOCUS_STRINGS[query.topic]

    if "new1" in pipelines:
        for w in NEW1_WEIGHT_SWEEP:
            retrieved = pipeline_new1_rrf_blend(
                query,
                dataset,
                match_focus_emb,
                w,
                reranker,
                precomputed_rerank=cached_query_rerank,
                precomputed_candidates=candidates,
            )
            results.append(
                make_record("new1", "focus_match", w, query.topic, retrieved)
            )

    if "new2" in pipelines:
        retrieved = pipeline_new2_augmented_query(
            query,
            dataset,
            match_focus_string,
            reranker,
            precomputed_candidates=candidates,
        )
        results.append(
            make_record("new2", "focus_match", None, query.topic, retrieved)
        )

    # ── Condition: focus_cross ──────────────────────────────────────
    other_topics = [t for t in TOPICS if t != query.topic]
    for cross_topic in other_topics:
        cross_focus_emb = dataset.focus_embeddings[cross_topic]
        cross_focus_string = FOCUS_STRINGS[cross_topic]

        if "new1" in pipelines:
            for w in NEW1_WEIGHT_SWEEP:
                retrieved = pipeline_new1_rrf_blend(
                    query,
                    dataset,
                    cross_focus_emb,
                    w,
                    reranker,
                    precomputed_rerank=cached_query_rerank,
                    precomputed_candidates=candidates,
                )
                results.append(
                    make_record("new1", "focus_cross", w, cross_topic, retrieved)
                )

        if "new2" in pipelines:
            retrieved = pipeline_new2_augmented_query(
                query,
                dataset,
                cross_focus_string,
                reranker,
                precomputed_candidates=candidates,
            )
            results.append(
                make_record("new2", "focus_cross", None, cross_topic, retrieved)
            )

    return results


# ── Aggregation ─────────────────────────────────────────────────────


@dataclass
class AggregatedRow:
    pipeline: str
    condition: str
    weight: float | None
    n_queries: int
    mean_recall_at_10: float
    mean_precision_at_10: float
    mean_mrr: float


def aggregate(
    runs: list[RunResult],
    level_filter: str | None = None,
) -> list[AggregatedRow]:
    """Group RunResults by (pipeline, condition, weight) and average metrics.

    `level_filter` lets the caller restrict to one query level
    (specific/ambiguous/cross_topic) without re-running the benchmark.
    """
    filtered = (
        [r for r in runs if r.query_level == level_filter]
        if level_filter
        else runs
    )

    groups: dict[tuple[str, str, float | None], list[RunResult]] = {}
    for r in filtered:
        key = (r.pipeline, r.condition, r.weight)
        groups.setdefault(key, []).append(r)

    rows: list[AggregatedRow] = []
    for (pipeline, condition, weight), group in groups.items():
        n = len(group)
        rows.append(
            AggregatedRow(
                pipeline=pipeline,
                condition=condition,
                weight=weight,
                n_queries=n,
                mean_recall_at_10=sum(r.recall_at_10 for r in group) / n,
                mean_precision_at_10=sum(r.precision_at_10 for r in group) / n,
                mean_mrr=sum(r.mrr for r in group) / n,
            )
        )

    rows.sort(
        key=lambda row: (
            row.pipeline,
            row.condition,
            row.weight if row.weight is not None else -1.0,
        )
    )
    return rows


# ── Top-level driver ────────────────────────────────────────────────


def run_full_benchmark(
    progress: Callable[[str], None] | None = None,
) -> tuple[Dataset, list[RunResult], dict]:
    """Embed the dataset, run every (query, pipeline, condition) combination.

    Returns (dataset, runs, timing_info). Caller decides what to do
    with the raw runs -- aggregate them, write to JSON, print a table.
    """
    log = progress or (lambda msg: None)
    timings: dict[str, float] = {}

    log("loading and embedding dataset")
    t0 = time.perf_counter()
    embedder = EmbeddingClient()
    try:
        dataset = load_dataset(embedder)
    finally:
        embedder.close()
    timings["embed_dataset_seconds"] = time.perf_counter() - t0
    log(
        f"  embedded {len(dataset.memories)} memories, {len(dataset.queries)} "
        f"queries, {len(dataset.focus_embeddings)} focus strings "
        f"({timings['embed_dataset_seconds']:.1f}s)"
    )

    log("running pipelines")
    t1 = time.perf_counter()
    reranker = RerankerClient()
    runs: list[RunResult] = []
    try:
        for idx, q in enumerate(dataset.queries, start=1):
            log(f"  query {idx}/{len(dataset.queries)}: {q.id}")
            runs.extend(evaluate_query(q, dataset, reranker))
    finally:
        reranker.close()
    timings["run_pipelines_seconds"] = time.perf_counter() - t1
    log(
        f"  produced {len(runs)} run records "
        f"({timings['run_pipelines_seconds']:.1f}s)"
    )

    return dataset, runs, timings
