"""EvalHub adapter entrypoint for Kubernetes and local job execution."""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("memoryhub-evalhub")


def main() -> None:
    from evalhub.adapter.callbacks import DefaultCallbacks
    from evalhub.adapter import get_job_spec_path
    from memoryhub_evalhub.adapter import AMBAdapter

    spec_path = get_job_spec_path()
    logger.info("Loading job spec from %s", spec_path)

    adapter = AMBAdapter(job_spec_path=str(spec_path))
    job = adapter.job_spec

    callbacks = DefaultCallbacks(
        job_id=job.id,
        benchmark_id=job.benchmark_id,
        provider_id=job.provider_id,
        benchmark_index=job.benchmark_index,
    )

    logger.info("Starting benchmark job %s (provider=%s, benchmark=%s)",
                job.id, job.provider_id, job.benchmark_id)

    results = adapter.run_benchmark_job(job, callbacks)
    callbacks.report_results(results)

    logger.info("Job complete: score=%.4f, examples=%d, duration=%.1fs",
                results.overall_score, results.num_examples_evaluated,
                results.duration_seconds)


if __name__ == "__main__":
    main()
