"""EvalHub BYOF adapter wrapping the AMB harness EvalRunner."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from pathlib import Path

from evalhub.adapter.models.adapter import FrameworkAdapter
from evalhub.adapter.models.job import (
    EnvironmentCardMetadata,
    JobCallbacks,
    JobResults,
    JobSpec,
    JobStatusUpdate,
)
from evalhub.models.api import EvaluationResult, JobPhase, JobStatus

logger = logging.getLogger(__name__)


class AMBAdapter(FrameworkAdapter):
    """Wraps the Open Memory Benchmark harness as an EvalHub FrameworkAdapter.

    JobSpec contract:
      - model.url:  answer LLM endpoint (or provider name like "gemini")
      - model.name: answer model name (e.g. "gemini-2.5-flash-lite-preview-06-17")
      - parameters: {
            mode:            "library" | "dreaming"  (harness ingestion mode)
            answer_model:    model name override (optional, defaults to model.name)
            k:               top-k for retrieval (optional)
            dataset:         dataset name (default "personamem")
            dataset_variant: split name (default "32k")
            pipeline_sha:    git SHA of the MemoryHub pipeline code
            memory_provider: memory provider name (default "memoryhub")
            memoryhub_url:   MemoryHub server URL (optional)
            memoryhub_api_key: MemoryHub API key (optional)
            disabled_signals: comma-separated signal names to disable (optional)
            query_limit:     max queries (optional, None = all)
            category:        category filter (optional)
            output_dir:      output directory (optional)
        }
    """

    def run_benchmark_job(
        self, config: JobSpec, callbacks: JobCallbacks
    ) -> JobResults:
        # Import harness components (they live in the amb-harness package)
        from dotenv import load_dotenv
        load_dotenv(override=True)

        from memory_bench.dataset import get_dataset
        from memory_bench.llm import get_llm, get_answer_llm
        from memory_bench.memory import get_memory_provider
        from memory_bench.modes import get_mode
        from memory_bench.runner import EvalRunner

        params = config.parameters
        t_start = time.monotonic()

        callbacks.report_status(
            JobStatusUpdate(
                status=JobStatus.RUNNING,
                phase=JobPhase.INITIALIZING,
                progress=0.0,
            )
        )

        # Wire answer LLM from JobSpec.model
        answer_provider = _detect_llm_provider(config.model.url, config.model.name)
        answer_model = params.get("answer_model") or config.model.name
        os.environ["OMB_ANSWER_LLM"] = answer_provider
        os.environ["OMB_ANSWER_MODEL"] = answer_model

        # Resolve model credentials from mounted secret
        from evalhub.adapter import resolve_model_credentials
        creds = resolve_model_credentials()
        if creds.api_key:
            env_key = {
                "anthropic": "ANTHROPIC_API_KEY",
                "gemini": "GOOGLE_API_KEY",
            }.get(answer_provider, "OPENAI_API_KEY")
            os.environ[env_key] = creds.api_key

        # Wire MemoryHub connection if provided
        if params.get("memoryhub_url"):
            os.environ["MEMORYHUB_URL"] = params["memoryhub_url"]
        if params.get("memoryhub_api_key"):
            os.environ["MEMORYHUB_API_KEY"] = params["memoryhub_api_key"]

        # Wire disabled signals for ablation testing
        if params.get("disabled_signals"):
            os.environ["MEMORYHUB_DISABLED_SIGNALS"] = params["disabled_signals"]
        elif "MEMORYHUB_DISABLED_SIGNALS" in os.environ:
            del os.environ["MEMORYHUB_DISABLED_SIGNALS"]

        dataset_name = params.get("dataset", "personamem")
        split = params.get("dataset_variant", "32k")
        mode_name = params.get("mode", "library")
        memory_name = params.get("memory_provider", "memoryhub")
        query_limit = params.get("query_limit")
        category = params.get("category")
        output_dir = Path(params.get("output_dir", "outputs"))

        ds = get_dataset(dataset_name)
        memory = get_memory_provider(memory_name)
        answer_llm = get_answer_llm()
        mode = get_mode("rag", llm=answer_llm)

        run_name = f"evalhub-{config.id}"

        callbacks.report_status(
            JobStatusUpdate(
                status=JobStatus.RUNNING,
                phase=JobPhase.RUNNING_EVALUATION,
                progress=0.1,
            )
        )

        runner = EvalRunner(output_dir=output_dir)
        summary = runner.run(
            dataset=ds,
            split=split,
            memory=memory,
            mode=mode,
            category=category,
            query_limit=query_limit,
            run_name=run_name,
            description=f"EvalHub job {config.id}",
        )

        duration = time.monotonic() - t_start

        # Build EvaluationResult entries
        results: list[EvaluationResult] = [
            EvaluationResult(
                metric_name="mcq_accuracy",
                metric_value=summary.accuracy,
                metric_type="accuracy",
                num_samples=summary.total_queries,
                metadata={
                    "correct": summary.correct,
                    "total": summary.total_queries,
                },
            ),
        ]

        # Per-question-type slices from category_axes
        type_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "total": 0}
        )
        for r in summary.results:
            for axis, values in r.category_axes.items():
                for val in values:
                    key = f"{axis}:{val}"
                    type_counts[key]["total"] += 1
                    if r.correct:
                        type_counts[key]["correct"] += 1

        for key, counts in sorted(type_counts.items()):
            acc = counts["correct"] / counts["total"] if counts["total"] else 0.0
            results.append(
                EvaluationResult(
                    metric_name=f"accuracy/{key}",
                    metric_value=acc,
                    metric_type="accuracy",
                    num_samples=counts["total"],
                    metadata=counts,
                )
            )

        # Echo parameters into evaluation_metadata for comparability pinning
        eval_metadata = {
            "mode": mode_name,
            "answer_model": answer_model,
            "k": params.get("k"),
            "dataset_variant": split,
            "pipeline_sha": params.get("pipeline_sha"),
            "disabled_signals": params.get("disabled_signals"),
            "memory_provider": memory_name,
            "ingestion_time_ms": summary.ingestion_time_ms,
            "ingested_docs": summary.ingested_docs,
            "answer_llm": summary.answer_llm,
            "judge_llm": summary.judge_llm,
        }

        env_card = EnvironmentCardMetadata(
            framework_name="memoryhub-amb",
            framework_version=params.get("pipeline_sha", "unknown"),
            model_id=answer_model,
            model_provider=answer_provider,
            generated_by="memoryhub-evalhub-adapter",
            custom={
                "memoryhub_server_version": params.get("server_version", "unknown"),
                "pipeline_sha": params.get("pipeline_sha", "unknown"),
                "retrieval_config": {
                    "mode": mode_name,
                    "k": params.get("k"),
                    "memory_provider": memory_name,
                    "disabled_signals": params.get("disabled_signals"),
                },
                "harness_commit": params.get("pipeline_sha", "unknown"),
            },
        )

        callbacks.report_status(
            JobStatusUpdate(
                status=JobStatus.COMPLETED,
                phase=JobPhase.COMPLETED,
                progress=1.0,
            )
        )

        return JobResults(
            id=config.id,
            benchmark_id=config.benchmark_id,
            benchmark_index=config.benchmark_index,
            model_name=config.model.name,
            results=results,
            overall_score=summary.accuracy,
            num_examples_evaluated=summary.total_queries,
            duration_seconds=duration,
            evaluation_metadata=eval_metadata,
            env_card=env_card,
        )


def _detect_llm_provider(url: str, name: str) -> str:
    """Infer LLM provider from endpoint URL or model name."""
    url_lower = url.lower()
    name_lower = name.lower()
    if "gemini" in name_lower or "generativelanguage.googleapis" in url_lower:
        return "gemini"
    if "anthropic" in url_lower or "claude" in name_lower:
        return "anthropic"
    return "vllm"
