#!/usr/bin/env python3
"""Standalone runner for the two-vector retrieval benchmark.

Embeds the synthetic dataset, runs every (query, pipeline, condition,
weight) combination against the deployed embedding and reranker
services, prints a results table, and writes raw runs to
``benchmarks/two-vector-retrieval-<timestamp>.json``.

Usage::

    python scripts/bench-two-vector.py

Environment overrides::

    MEMORYHUB_EMBEDDING_URL  override the embedding endpoint
    MEMORYHUB_RERANKER_URL   override the reranker endpoint

The benchmark talks to live deployed services and takes a few minutes
to run. Results are committed to git so future sessions can reproduce
the comparison without re-running the network-bound sweep.
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

from tests.perf.two_vector_bench import (  # noqa: E402
    AggregatedRow,
    aggregate,
    run_full_benchmark,
)


def log(msg: str) -> None:
    print(msg, flush=True)


def format_table(rows: list[AggregatedRow], title: str) -> str:
    header = (
        f"{'pipeline':<10} {'condition':<20} {'weight':>7} "
        f"{'n':>4} {'recall@10':>10} {'prec@10':>10} {'mrr':>10}"
    )
    sep = "-" * len(header)
    lines = [title, sep, header, sep]
    for r in rows:
        weight_str = f"{r.weight:.2f}" if r.weight is not None else "  -  "
        lines.append(
            f"{r.pipeline:<10} {r.condition:<20} {weight_str:>7} "
            f"{r.n_queries:>4} {r.mean_recall_at_10:>10.4f} "
            f"{r.mean_precision_at_10:>10.4f} {r.mean_mrr:>10.4f}"
        )
    lines.append(sep)
    return "\n".join(lines)


def main() -> int:
    log("=" * 70)
    log("Two-Vector Retrieval Benchmark")
    log("=" * 70)

    dataset, runs, timings = run_full_benchmark(progress=log)

    log("")
    log("Aggregating results...")
    rows_all = aggregate(runs)
    rows_specific = aggregate(runs, level_filter="specific")
    rows_ambiguous = aggregate(runs, level_filter="ambiguous")
    rows_cross = aggregate(runs, level_filter="cross_topic")

    log("")
    log(format_table(rows_all, "ALL QUERIES (40)"))
    log("")
    log(format_table(rows_specific, "SPECIFIC QUERIES (16)"))
    log("")
    log(format_table(rows_ambiguous, "AMBIGUOUS QUERIES (16)"))
    log("")
    log(format_table(rows_cross, "CROSS-TOPIC QUERIES (8)"))

    # Persist raw + aggregated for git history.
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "benchmarks"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"two-vector-retrieval-{timestamp}.json"

    payload = {
        "timestamp_utc": timestamp,
        "n_memories": len(dataset.memories),
        "n_queries": len(dataset.queries),
        "timings_seconds": timings,
        "aggregated": {
            "all": [asdict(r) for r in rows_all],
            "specific": [asdict(r) for r in rows_specific],
            "ambiguous": [asdict(r) for r in rows_ambiguous],
            "cross_topic": [asdict(r) for r in rows_cross],
        },
        "runs": [asdict(r) for r in runs],
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    log("")
    log(f"Wrote raw + aggregated results to {out_path}")
    log(f"Total run time: {sum(timings.values()):.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
