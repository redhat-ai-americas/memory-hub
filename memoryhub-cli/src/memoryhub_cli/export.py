"""Export subcommand for memoryhub CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from memoryhub import MemoryHubClient, load_project_config
from memoryhub.exceptions import (
    AuthenticationError,
    ConflictError,
    ConnectionFailedError,
    CurationVetoError,
    MemoryHubError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from memoryhub.export import export_obsidian

from memoryhub_cli.config import get_connection_params
from memoryhub_cli.output import (
    EXIT_AUTH_ERROR,
    EXIT_CLIENT_ERROR,
    EXIT_SERVER_ERROR,
    OutputFormat,
    console,
    handle_error,
    json_success,
)

export_app = typer.Typer(name="export", help="Export memories to external formats")


def _get_client(output: OutputFormat = OutputFormat.table) -> MemoryHubClient:
    """Create a MemoryHubClient from config/env."""
    params = get_connection_params()
    missing = [k for k, v in params.items() if not v]
    if missing:
        handle_error(
            "missing_config",
            f"Missing configuration: {', '.join(missing)}. "
            "Run 'memoryhub login' or set environment variables.",
            output,
            EXIT_CLIENT_ERROR,
        )

    return MemoryHubClient(
        url=params["url"],
        auth_url=params["auth_url"],
        client_id=params["client_id"],
        client_secret=params["client_secret"],
    )


def _get_project_id_default() -> str | None:
    """Try to load project_id from .memoryhub.yaml."""
    try:
        config = load_project_config()
        if config.project_id:
            return config.project_id
        if config.memory_loading.campaigns:
            return Path.cwd().name
    except Exception:
        pass
    return None


def _run_command(coro, output: OutputFormat):
    """Run an async coroutine with structured error handling."""
    try:
        return asyncio.run(coro)
    except AuthenticationError as exc:
        handle_error("auth_failed", str(exc), output, EXIT_AUTH_ERROR)
    except (PermissionDeniedError, ValidationError, ConflictError, CurationVetoError) as exc:
        handle_error(type(exc).__name__.lower(), str(exc), output, EXIT_CLIENT_ERROR)
    except NotFoundError as exc:
        handle_error("not_found", str(exc), output, EXIT_CLIENT_ERROR)
    except (ConnectionFailedError, ToolError) as exc:
        handle_error("server_error", str(exc), output, EXIT_SERVER_ERROR)
    except MemoryHubError as exc:
        handle_error("error", str(exc), output, EXIT_SERVER_ERROR)


@export_app.command("obsidian")
def obsidian(
    output_dir: str = typer.Argument(..., help="Output directory path"),
    scope: str | None = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    include_branches: bool = typer.Option(
        False, "--include-branches", help="Include branch memories",
    ),
    weight_threshold: float = typer.Option(
        0.0, "--weight-threshold", "-w", help="Minimum weight to export",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Export memories to Obsidian-compatible markdown files.

    Creates a directory structure with markdown files organized by scope,
    complete with YAML frontmatter, wikilinks for relationships, and
    Obsidian graph configuration.
    """
    # Validate output directory doesn't exist or is empty
    output_path = Path(output_dir)
    if output_path.exists() and not output_path.is_dir():
        handle_error(
            "invalid_output",
            f"Output path exists but is not a directory: {output_dir}",
            output,
            EXIT_CLIENT_ERROR,
        )

    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await export_obsidian(
                client,
                output_dir,
                scope=scope,
                project_id=_project_id,
                include_branches=include_branches,
                weight_threshold=weight_threshold,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Export complete:[/green] {result['files_written']} files written")
    console.print(f"  Output: {result['output_dir']}")
    console.print(f"  Scopes: {', '.join(result['scopes']) if result['scopes'] else 'none'}")

    if result["errors"]:
        console.print(f"\n[yellow]Errors encountered:[/yellow] {len(result['errors'])}")
        for error in result["errors"][:5]:  # Show first 5 errors
            console.print(f"  - {error.get('type', 'unknown')}: {error.get('message', '')}")
        if len(result["errors"]) > 5:
            console.print(f"  ... and {len(result['errors']) - 5} more")
