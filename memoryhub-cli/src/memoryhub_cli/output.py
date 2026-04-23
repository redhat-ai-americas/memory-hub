"""Structured output helpers for the memoryhub CLI.

Implements the output contract from issue #200:
  - OutputFormat enum: table, json, quiet
  - JSON success envelope:  {"status": "ok", "data": {...}}
  - JSON error envelope on stderr: {"status": "error", "error": {"code": ..., "message": ...}}
  - Exit codes: 0=success, 1=client error, 2=server error, 3=auth error
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

import typer
from rich.console import Console

# ── Shared console instances (single source of truth) ─────────────────────────

console = Console()
err_console = Console(stderr=True)


# ── Output format enum ────────────────────────────────────────────────────────


class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    quiet = "quiet"


# ── Exit codes ────────────────────────────────────────────────────────────────

EXIT_SUCCESS = 0
EXIT_CLIENT_ERROR = 1
EXIT_SERVER_ERROR = 2
EXIT_AUTH_ERROR = 3


# ── Success output ────────────────────────────────────────────────────────────


def json_success(data: Any) -> None:
    """Print a JSON success envelope to stdout."""
    payload = {"status": "ok", "data": data}
    console.print_json(json.dumps(payload, default=str))


# ── Error output ──────────────────────────────────────────────────────────────


def handle_error(
    code: str,
    message: str,
    output: OutputFormat,
    exit_code: int = EXIT_CLIENT_ERROR,
) -> None:
    """Emit a structured error and exit.

    In JSON mode, writes a JSON error envelope to stderr.
    In table/quiet mode, prints a Rich-formatted message to stderr.
    Always raises typer.Exit with the given exit_code.
    """
    if output == OutputFormat.json:
        payload = {
            "status": "error",
            "error": {"code": code, "message": message},
        }
        # Use plain print to avoid Rich markup interpretation on JSON
        err_console.print(json.dumps(payload), highlight=False)
    else:
        err_console.print(f"[red]Error ({code}):[/red] {message}")
    raise typer.Exit(exit_code)
