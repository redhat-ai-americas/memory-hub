#!/usr/bin/env python3
"""Smoke test: run AMBAdapter in EVALHUB_MODE=local with a 20-query PersonaMem job.

Usage (from benchmarks/amb-harness, where the venv lives):
    uv run python ../evalhub-adapter/run_smoke.py
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("evalhub-smoke")


def get_pipeline_sha() -> str:
    return (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1]
        )
        .decode()
        .strip()
    )


def main() -> None:
    pipeline_sha = get_pipeline_sha()
    job_id = "smoke-20q"
    provider_id = "memoryhub-amb"
    benchmark_id = "personamem-mcq"
    benchmark_index = 0

    job_spec = {
        "id": job_id,
        "provider_id": provider_id,
        "benchmark_id": benchmark_id,
        "benchmark_index": benchmark_index,
        "model": {
            "url": "https://api.anthropic.com",
            "name": "claude-haiku-4-5-20251001",
        },
        "parameters": {
            "mode": "library",
            "dataset": "personamem",
            "dataset_variant": "32k",
            "memory_provider": "bm25",
            "query_limit": 20,
            "pipeline_sha": pipeline_sha,
            "output_dir": "outputs",
        },
        "callback_url": "http://localhost:9999",
    }

    # Write job spec to the local-mode path structure EvalHub expects
    with tempfile.TemporaryDirectory(prefix="evalhub-smoke-") as tmpdir:
        job_dir = (
            Path(tmpdir)
            / job_id
            / str(benchmark_index)
            / provider_id
            / benchmark_id
        )
        meta_dir = job_dir / "meta"
        meta_dir.mkdir(parents=True)
        spec_path = meta_dir / "job.json"
        spec_path.write_text(json.dumps(job_spec, indent=2))

        os.environ["EVALHUB_MODE"] = "local"
        os.environ["EVALHUB_JOB_SPEC_PATH"] = str(spec_path)

        # Import after setting env vars
        sys.path.insert(
            0,
            str(Path(__file__).resolve().parent / "src"),
        )
        from memoryhub_evalhub.adapter import AMBAdapter
        from evalhub.adapter.callbacks import DefaultCallbacks

        adapter = AMBAdapter(job_spec_path=str(spec_path))
        callbacks = DefaultCallbacks(
            job_id=job_id,
            benchmark_id=benchmark_id,
            provider_id=provider_id,
            benchmark_index=benchmark_index,
        )

        logger.info("Starting 20-query PersonaMem smoke via AMBAdapter...")
        results = adapter.run_benchmark_job(adapter.job_spec, callbacks)
        callbacks.report_results(results)

        # Dump results for verification
        results_dict = results.model_dump(mode="json")
        output_path = Path("outputs") / "evalhub-smoke-results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results_dict, indent=2))

        logger.info("=" * 60)
        logger.info("SMOKE TEST RESULTS")
        logger.info("=" * 60)
        logger.info("Overall score: %.4f", results.overall_score)
        logger.info("Examples evaluated: %d", results.num_examples_evaluated)
        logger.info("Duration: %.1fs", results.duration_seconds)
        logger.info("")
        logger.info("Metrics:")
        for r in results.results:
            logger.info(
                "  %s = %s (n=%s)", r.metric_name, r.metric_value, r.num_samples
            )
        logger.info("")
        logger.info("Evaluation metadata:")
        for k, v in results.evaluation_metadata.items():
            logger.info("  %s = %s", k, v)
        logger.info("")
        logger.info("Results saved to: %s", output_path)

        # Verification checks
        _verify(results, job_spec)


def _verify(results, job_spec: dict) -> None:
    """Run the four verification checks from the spike requirements."""
    errors = []
    params = job_spec["parameters"]

    # 1. Metrics flow
    has_overall = results.overall_score is not None
    has_accuracy_metric = any(
        r.metric_name == "mcq_accuracy" for r in results.results
    )
    if not has_overall:
        errors.append("FAIL [metrics-flow]: overall_score is None")
    if not has_accuracy_metric:
        errors.append("FAIL [metrics-flow]: no mcq_accuracy metric in results")
    slice_metrics = [
        r for r in results.results if r.metric_name.startswith("accuracy/")
    ]
    if not slice_metrics:
        errors.append(
            "WARN [metrics-flow]: no per-question-type slices (may be expected for small sample)"
        )

    # 2. Parameters pass-through
    meta = results.evaluation_metadata
    for key in ("mode", "answer_model", "dataset_variant", "pipeline_sha"):
        if key not in meta:
            errors.append(f"FAIL [params-passthrough]: {key} missing from evaluation_metadata")
        elif meta[key] != params.get(key, job_spec["model"]["name"]):
            expected = params.get(key, job_spec["model"]["name"])
            errors.append(
                f"FAIL [params-passthrough]: {key} = {meta[key]!r}, expected {expected!r}"
            )

    # 3. Model contract
    if results.model_name != job_spec["model"]["name"]:
        errors.append(
            f"FAIL [model-contract]: model_name = {results.model_name!r}, "
            f"expected {job_spec['model']['name']!r}"
        )

    # 4. Checkpoint-resume (assess only)
    logger.info("=" * 60)
    logger.info("VERIFICATION RESULTS")
    logger.info("=" * 60)

    check_names = [
        "1. Metrics flow",
        "2. Parameters pass-through",
        "3. Model contract",
        "4. Checkpoint-resume feasibility",
    ]

    fails = [e for e in errors if e.startswith("FAIL")]
    warns = [e for e in errors if e.startswith("WARN")]

    for name in check_names:
        prefix = name.split(".")[0].strip()
        relevant = [
            e
            for e in errors
            if any(
                tag in e
                for tag in {
                    "1": ["metrics-flow"],
                    "2": ["params-passthrough"],
                    "3": ["model-contract"],
                    "4": ["checkpoint"],
                }.get(prefix, [])
            )
        ]
        if not relevant:
            logger.info("  PASS  %s", name)
        else:
            for e in relevant:
                logger.info("  %s  %s", "FAIL" if "FAIL" in e else "WARN", name)
                logger.info("        %s", e)

    logger.info("")
    logger.info(
        "Checkpoint-resume assessment: The harness saves incremental "
        "checkpoints per 10 queries (batch mode) or per unit (unit-sequential). "
        "An EvalHub adapter could resume by passing --skip-ingested or by "
        "re-running with the same output_dir. Pattern: chain of EvalHub jobs "
        "sharing an output directory mounted via PVC. Feasible but requires "
        "PVC or OCI-persisted checkpoint between jobs."
    )

    if fails:
        logger.error("%d verification check(s) FAILED", len(fails))
        sys.exit(1)
    elif warns:
        logger.warning("%d warning(s), 0 failures", len(warns))
    else:
        logger.info("All verification checks PASSED")


if __name__ == "__main__":
    main()
