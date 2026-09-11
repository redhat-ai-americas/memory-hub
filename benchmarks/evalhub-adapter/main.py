"""EvalHub adapter entrypoint for Kubernetes and local job execution."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("memoryhub-evalhub")


def main() -> None:
    from evalhub.adapter.callbacks import DefaultCallbacks
    from evalhub.adapter import get_job_spec_path
    from memoryhub_evalhub.adapter import AMBAdapter
    from memoryhub_evalhub.sidecar_drain import report_results_and_drain

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

    # DefaultCallbacks.report_results() swallows sidecar HTTP errors, then the
    # process would exit and Kubernetes would SIGTERM the sidecar mid-forward
    # (#364/#426). Retry until the sidecar ACKs, then drain before exit.
    reported = report_results_and_drain(callbacks, results)
    if not reported:
        logger.error(
            "Results were not acknowledged by the sidecar; "
            "EvalHub may show score=N/A for job %s",
            job.id,
        )

    logger.info("Job complete: score=%.4f, examples=%d, duration=%.1fs",
                results.overall_score, results.num_examples_evaluated,
                results.duration_seconds)


if __name__ == "__main__":
    main()
