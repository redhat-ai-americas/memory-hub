"""Lightweight eval runner for BaseAgent agents.

Loads eval cases from ``evals.yaml``, creates an agent instance, runs each
case through the agent's ``step()`` method, checks assertions against the
output, and prints a pass/fail report.

Usage::

    # Dry-run — list cases without executing
    python -m evals.run_evals --dry-run

    # Run all cases (mock LLM, default)
    python -m evals.run_evals

    # Run a single case
    python -m evals.run_evals --case basic_research_query

    # Run with a real LLM (requires configured endpoint)
    python -m evals.run_evals --real-llm

    # Filter by tag
    python -m evals.run_evals --tag smoke

The runner is intentionally minimal.  It handles the assertion types defined
in ``evals.yaml`` and is designed to be replaced or augmented by external
eval frameworks (Braintrust, Promptfoo, etc.) that consume the same YAML.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import yaml

from evals import _EVALS_DIR, _FIXTURES_DIR
from evals.assertions import Assertion, AssertionResult, check_assertion
from evals.mock_factory import _build_mock_responses, create_agent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class EvalCase:
    """One eval case loaded from evals.yaml."""

    name: str
    description: str
    input: str
    expected_behavior: str
    tags: list[str] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)


@dataclass
class CaseResult:
    """Outcome of running one eval case."""

    case: EvalCase
    passed: bool
    skipped: bool = False
    error: str | None = None
    assertion_results: list[AssertionResult] = field(default_factory=list)
    tool_calls_log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def load_eval_cases(path: Path | None = None) -> list[EvalCase]:
    """Load eval cases from a YAML file."""
    yaml_path = path or (_EVALS_DIR / "evals.yaml")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for entry in raw.get("cases", []):
        assertions = [
            Assertion(type=a.pop("type"), params=a)
            for a in (entry.get("assertions") or [])
        ]
        cases.append(
            EvalCase(
                name=entry["name"],
                description=entry.get("description", ""),
                input=entry["input"],
                expected_behavior=entry.get("expected_behavior", ""),
                tags=entry.get("tags", []),
                assertions=assertions,
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------


def load_fixture(name: str) -> Any:
    """Load a JSON fixture file from the fixtures/ directory."""
    path = _FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------


async def run_case(
    case: EvalCase,
    *,
    use_real_llm: bool = False,
) -> CaseResult:
    """Execute a single eval case and return its result."""
    tool_calls_log: list[str] = []

    try:
        agent = await create_agent(use_real_llm=use_real_llm)
        agent.add_message("user", case.input)

        if not use_real_llm:
            # Wire up mock responses.
            side_effects, report, validation_text = _build_mock_responses(
                case.input
            )
            agent.llm.call_model = AsyncMock(side_effect=side_effects)
            if report is not None:
                agent.llm.call_model_json = AsyncMock(return_value=report)
            agent.llm.call_model_validated = AsyncMock(
                return_value=validation_text
            )

        # Run one step.
        step_result = await agent.step()

        # Collect tool call information from mock interactions.
        if not use_real_llm and agent.llm.call_model.call_count > 0:
            # The first mock response contains a web_search tool call.
            # Record it so tool_called assertions work.
            for resp in side_effects:
                if resp.tool_calls:
                    for tc in resp.tool_calls:
                        tool_calls_log.append(tc.function.name)

        # Evaluate assertions.
        output = step_result.result if step_result else None
        assertion_results = [
            check_assertion(a, output, tool_calls_log)
            for a in case.assertions
        ]
        all_passed = all(ar.passed for ar in assertion_results)

        return CaseResult(
            case=case,
            passed=all_passed,
            assertion_results=assertion_results,
            tool_calls_log=tool_calls_log,
        )

    except Exception as exc:
        return CaseResult(
            case=case,
            passed=False,
            error=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def print_report(results: list[CaseResult]) -> None:
    """Print a human-readable eval report to stdout."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)

    print()
    print("=" * 60)
    print("  EVAL RESULTS")
    print("=" * 60)

    for r in results:
        if r.skipped:
            status = "SKIP"
        elif r.passed:
            status = "PASS"
        else:
            status = "FAIL"

        print(f"\n  [{status}] {r.case.name}")
        if r.case.tags:
            print(f"         tags: {', '.join(r.case.tags)}")

        if r.error:
            print(f"         error: {r.error}")

        for ar in r.assertion_results:
            mark = "ok" if ar.passed else "FAIL"
            print(f"         [{mark}] {ar.assertion.type}: {ar.detail}")

    print()
    print("-" * 60)
    print(f"  Total: {total}  Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
    print("-" * 60)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run eval cases for the agent.",
        prog="python -m evals.run_evals",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eval cases without executing them.",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Run only the named eval case.",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default=None,
        help="Run only cases matching this tag.",
    )
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Use a real LLM endpoint instead of mocks.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--evals-file",
        type=str,
        default=None,
        help="Path to evals YAML file (default: evals/evals.yaml).",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    """Run evals and return an exit code (0 = all passed)."""
    evals_path = Path(args.evals_file) if args.evals_file else None
    cases = load_eval_cases(evals_path)

    # Filter by --case.
    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            print(f"No eval case named '{args.case}' found.", file=sys.stderr)
            return 1

    # Filter by --tag.
    if args.tag:
        cases = [c for c in cases if args.tag in c.tags]
        if not cases:
            print(f"No eval cases with tag '{args.tag}' found.", file=sys.stderr)
            return 1

    # Dry run: just list.
    if args.dry_run:
        print(f"\n  {len(cases)} eval case(s):\n")
        for c in cases:
            tags = f"  [{', '.join(c.tags)}]" if c.tags else ""
            print(f"    - {c.name}{tags}")
            print(f"      {c.description.strip()[:80]}")
        print()
        return 0

    # Execute.
    results: list[CaseResult] = []
    for case in cases:
        result = await run_case(case, use_real_llm=args.real_llm)
        results.append(result)

    print_report(results)

    return 0 if all(r.passed for r in results) else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    exit_code = asyncio.run(async_main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
