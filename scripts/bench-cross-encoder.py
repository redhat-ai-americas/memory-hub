#!/usr/bin/env python3
"""Cross-encoder cost/benefit benchmark.

Measures re-ranking latency, relevance improvement (NDCG/MRR delta),
and resource consumption at candidate set sizes of 10, 25, 50, 100.

Prints an ASCII results table, emits a recommendation for the optimal
candidate size, and writes raw + aggregated results to
``benchmarks/cross-encoder-<timestamp>.json``.

Usage::

    python scripts/bench-cross-encoder.py

Environment overrides::

    MEMORYHUB_EMBEDDING_URL  override the embedding endpoint
    MEMORYHUB_RERANKER_URL   override the reranker endpoint
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Make the project root importable when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.perf.cross_encoder_bench import (  # noqa: E402
    CANDIDATE_SIZES,
    N_FINAL,
    AggregatedCandidateSize,
    aggregate_by_size,
    recommend_candidate_size,
    run_cross_encoder_benchmark,
)


def log(msg: str) -> None:
    print(msg, flush=True)  # noqa: T201


def format_table(rows: list[AggregatedCandidateSize]) -> str:
    header = (
        f"{'size':>6}  {'n':>4}  "
        f"{'NDCG(vec)':>10}  {'NDCG(rer)':>10}  {'delta':>8}  "
        f"{'MRR(vec)':>9}  {'MRR(rer)':>9}  {'delta':>8}  "
        f"{'lat(ms)':>8}  {'eff':>10}"
    )
    sep = "-" * len(header)
    lines = [sep, header, sep]
    for r in rows:
        lines.append(
            f"{r.candidate_size:>6}  {r.n_queries:>4}  "
            f"{r.mean_vector_ndcg:>10.4f}  {r.mean_reranked_ndcg:>10.4f}  "
            f"{r.mean_ndcg_delta:>+8.4f}  "
            f"{r.mean_vector_mrr:>9.4f}  {r.mean_reranked_mrr:>9.4f}  "
            f"{r.mean_mrr_delta:>+8.4f}  "
            f"{r.mean_rerank_latency_ms:>8.1f}  "
            f"{r.ndcg_delta_per_ms:>10.6f}"
        )
    lines.append(sep)
    return "\n".join(lines)


def main() -> int:
    log("=" * 70)
    log("Cross-Encoder Cost/Benefit Benchmark")
    log("=" * 70)

    dataset, results, timings = run_cross_encoder_benchmark(progress=log)
    aggregated = aggregate_by_size(results)
    recommendation = recommend_candidate_size(aggregated)

    log("")
    log(f"Results (N_FINAL={N_FINAL}):")
    log(format_table(aggregated))
    log("")
    log(
        f"Recommendation: candidate_size={recommendation['recommended_size']} "
        f"(efficiency={recommendation['efficiency']:.6f} NDCG-delta/ms)"
    )
    log(f"  {recommendation['reason']}")

    # Persist raw + aggregated for git history.
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"cross-encoder-{timestamp}.json"

    payload = {
        "benchmark": "cross-encoder-cost-benefit",
        "timestamp": timestamp,
        "config": {
            "candidate_sizes": CANDIDATE_SIZES,
            "n_final": N_FINAL,
            "n_queries": len(dataset.queries),
            "n_memories": len(dataset.memories),
        },
        "results": {
            "by_size": [asdict(r) for r in aggregated],
            "recommendation": recommendation,
        },
        "timing": timings,
        "runs": [asdict(r) for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    log("")
    log(f"Wrote results to {out_path}")
    log(f"Total run time: {sum(timings.values()):.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
