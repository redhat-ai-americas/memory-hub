"""EvalHub adapter entrypoint for Kubernetes and local job execution."""

import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("memoryhub-evalhub")

SIDECAR_DRAIN_SECONDS = 5


def main() -> None:
    from evalhub.adapter.callbacks import DefaultCallbacks
    from evalhub.adapter import get_job_spec_path
    from memoryhub_evalhub.adapter import AMBAdapter

    spec_path = get_job_spec_path()
    logger.info("Loading job spec from %s", spec_path)

    adapter = AMBAdapter(job_spec_path=str(spec_path))
    job = adapter.job_spec

    callbacks = DefaultCallbacks.from_adapter(adapter)

    logger.info("Starting benchmark job %s (provider=%s, benchmark=%s)",
                job.id, job.provider_id, job.benchmark_id)

    results = adapter.run_benchmark_job(job, callbacks)

    manifest = getattr(adapter, "preflight_manifest", None)
    if manifest:
        import json
        from pathlib import Path

        manifest_path = Path("outputs") / "preflight-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        logger.info("Preflight manifest written to %s", manifest_path)

    # Save to MLflow before reporting so mlflow_run_id is included
    mlflow_run_id = callbacks.mlflow.save(results, job)
    if mlflow_run_id:
        results.mlflow_run_id = mlflow_run_id
        logger.info("MLflow run saved: %s", mlflow_run_id)

    callbacks.report_results(results)

    logger.info("Job complete: score=%.4f, examples=%d, duration=%.1fs",
                results.overall_score, results.num_examples_evaluated,
                results.duration_seconds)

    # Give the sidecar time to forward results to the EvalHub server
    # before the container exits and the pod is terminated.
    time.sleep(SIDECAR_DRAIN_SECONDS)


if __name__ == "__main__":
    main()
