"""Preflight smoke checks for benchmark runs.

Runs 3 deterministic queries through the real search pipeline before
the main loop starts. Catches data-level problems (wrong tenant,
missing source, empty results) that would otherwise waste hundreds
of API calls producing invalid results.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .models import Query

logger = logging.getLogger(__name__)

SMOKE_QUERY_COUNT = 3


@dataclass
class SmokeResult:
    query_id: str
    query_preview: str
    memories_returned: int
    context_chars: int
    source_counts: dict[str, int]


@dataclass
class PreflightResult:
    passed: bool
    aborted: bool
    abort_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    smoke_results: list[SmokeResult] = field(default_factory=list)


async def run_preflight(
    memory,
    queries: list[Query],
    expect_sources: list[str] | None,
    answer_llm_label: str = "",
    console: Console | None = None,
) -> PreflightResult:
    """Run preflight checks and print results.

    Args:
        memory: A MemoryHubProvider instance (must have preflight_search).
        queries: The full query set (3 will be selected deterministically).
        expect_sources: Source values that must appear in smoke results.
        answer_llm_label: Display label for the answer LLM.
        console: Rich console for output. Uses stderr default if None.
    """
    if console is None:
        console = Console(stderr=True)

    smoke_queries = sorted(queries, key=lambda q: q.id)[:SMOKE_QUERY_COUNT]
    if not smoke_queries:
        return PreflightResult(passed=False, aborted=True, abort_reason="No queries loaded.")

    lines = Text()
    lines.append("Config:\n", style="bold")
    lines.append(f"  project:        {memory._project_id}\n")
    lines.append(f"  tenant:         {memory._tenant_id or '(default)'}\n")
    lines.append(f"  source filter:  {memory._source_filter or '(none)'}\n")
    lines.append(f"  exclude_source: {memory._exclude_source or '(none)'}\n")
    if answer_llm_label:
        lines.append(f"  answer LLM:     {answer_llm_label}\n")
    lines.append("\n")

    smoke_results: list[SmokeResult] = []
    all_source_counts: Counter[str] = Counter()
    total_memories = 0

    for i, q in enumerate(smoke_queries, 1):
        memories = await memory.preflight_search(
            query=q.query, user_id=q.user_id,
        )
        source_counts: dict[str, int] = {}
        context_chars = 0
        for m in memories:
            src = getattr(m, "source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
            context_chars += len(m.content or "")

        all_source_counts.update(source_counts)
        total_memories += len(memories)

        sr = SmokeResult(
            query_id=q.id,
            query_preview=q.query[:60].replace("\n", " "),
            memories_returned=len(memories),
            context_chars=context_chars,
            source_counts=source_counts,
        )
        smoke_results.append(sr)

        src_label = ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items()))
        lines.append(f"  #{i} ")
        lines.append(f"[{q.id[:8]}] ", style="dim")
        lines.append(f"{len(memories)} memories, {context_chars:,} chars")
        if src_label:
            lines.append(f"  [{src_label}]")
        lines.append("\n")

    # --- Abort / warn logic ---
    result = PreflightResult(passed=True, aborted=False, smoke_results=smoke_results)

    if total_memories == 0:
        result.passed = False
        result.aborted = True
        result.abort_reason = (
            f"All {SMOKE_QUERY_COUNT} smoke queries returned 0 memories.\n"
            f"    project: {memory._project_id}  tenant: {memory._tenant_id or '(default)'}\n"
            f"    source filter: {memory._source_filter or '(none)'}  "
            f"exclude_source: {memory._exclude_source or '(none)'}\n"
            f"    Check that memories exist under this tenant+project with the expected source."
        )

    elif memory._source_filter and memory._source_filter not in all_source_counts:
        result.passed = False
        result.aborted = True
        found = ", ".join(sorted(all_source_counts)) or "(none)"
        result.abort_reason = (
            f"Source filter '{memory._source_filter}' matched 0 memories "
            f"across {SMOKE_QUERY_COUNT} smoke queries.\n"
            f"    Sources found: {found}\n"
            f"    tenant: {memory._tenant_id or '(default)'}  project: {memory._project_id}"
        )

    if expect_sources and not result.aborted:
        missing = [s for s in expect_sources if s not in all_source_counts]
        if missing:
            result.passed = False
            result.aborted = True
            found = ", ".join(sorted(all_source_counts)) or "(none)"
            result.abort_reason = (
                f"Expected source(s) not found in smoke results: {', '.join(missing)}\n"
                f"    Sources found: {found}\n"
                f"    Use --expect-sources to list only the sources you expect."
            )

    # Warn about single-source results when the operator hasn't declared expectations
    if (
        not result.aborted
        and not memory._source_filter
        and not memory._exclude_source
        and not expect_sources
        and len(all_source_counts) == 1
        and total_memories > 0
    ):
        only_source = next(iter(all_source_counts))
        result.warnings.append(
            f"All {total_memories} returned memories are source={only_source}. "
            f"If this run expects multiple sources, investigate or use --expect-sources."
        )

    # --- Print panel ---
    if result.aborted:
        lines.append("\n  ", style="")
        lines.append("ABORT", style="bold red")
        lines.append(f"  {result.abort_reason.split(chr(10))[0]}\n")
        console.print(Panel(lines, title="Preflight Check", border_style="red"))
    elif result.warnings:
        lines.append("\n  ", style="")
        lines.append("WARN", style="bold yellow")
        lines.append(f"  {result.warnings[0]}\n")
        console.print(Panel(lines, title="Preflight Check", border_style="yellow"))
    else:
        lines.append("\n  ", style="")
        lines.append("PASS", style="bold green")
        lines.append(f"  {total_memories} memories across {SMOKE_QUERY_COUNT} queries\n")
        console.print(Panel(lines, title="Preflight Check", border_style="green"))

    return result
