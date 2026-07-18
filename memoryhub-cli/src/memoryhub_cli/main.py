"""MemoryHub CLI — terminal interface for centralized agent memory."""

from __future__ import annotations

import asyncio
import sys
import warnings
from importlib.metadata import version as pkg_version
from pathlib import Path

_MAX_TESTED_PYTHON = (3, 13)

import typer
from memoryhub import CONFIG_FILENAME, ConfigError, load_project_config
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
from rich.table import Table

from memoryhub_cli.admin import admin_app
from memoryhub_cli.config import (
    get_api_key,
    get_connection_params,
    get_server_url,
    load_config,
    save_config,
)
from memoryhub_cli.export import export_app
from memoryhub_cli.output import (
    EXIT_AUTH_ERROR,
    EXIT_CLIENT_ERROR,
    EXIT_SERVER_ERROR,
    OutputFormat,
    console,
    err_console,
    handle_error,
    json_success,
)
from memoryhub_cli.project_config import (
    FocusSource,
    InitChoices,
    InstructionFormat,
    LoadingPattern,
    SessionShape,
    build_project_config,
    render_instructions,
    rewrite_rule_file,
    suggest_pattern,
    write_init_files,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"memoryhub {pkg_version('memoryhub-cli')}")  # noqa: T201
        raise typer.Exit()


app = typer.Typer(
    name="memoryhub",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """CLI client for MemoryHub — centralized, governed memory for AI agents."""
    if sys.version_info[:2] > _MAX_TESTED_PYTHON:
        warnings.warn(
            f"memoryhub-cli is tested on Python 3.10-{_MAX_TESTED_PYTHON[1]}. "
            f"You are running {sys.version_info[0]}.{sys.version_info[1]}, "
            f"which may cause import errors (e.g., fastmcp namespace packages). "
            f"Consider using Python {_MAX_TESTED_PYTHON[1]} or earlier.",
            stacklevel=2,
        )


config_app = typer.Typer(
    name="config",
    help="Manage project-level MemoryHub configuration (.memoryhub.yaml).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(admin_app, name="admin", help="Manage agents and OAuth clients")
app.add_typer(export_app, name="export", help="Export memories to external formats")

graph_app = typer.Typer(
    name="graph",
    help="Manage memory relationships and similarity.",
    no_args_is_help=True,
)
app.add_typer(graph_app, name="graph")

curation_app = typer.Typer(
    name="curation",
    help="Report contradictions, resolve them, and manage curation rules.",
    no_args_is_help=True,
)
app.add_typer(curation_app, name="curation")

project_app = typer.Typer(
    name="project",
    help="Manage projects and membership.",
    no_args_is_help=True,
)
app.add_typer(project_app, name="project")

session_app = typer.Typer(
    name="session",
    help="Check session status and manage focus topics.",
    no_args_is_help=True,
)
app.add_typer(session_app, name="session")

entity_app = typer.Typer(
    name="entity",
    help="List, merge, and rename extracted entities.",
    no_args_is_help=True,
)
app.add_typer(entity_app, name="entity")

thread_app = typer.Typer(
    name="thread",
    help="Conversation thread operations.",
    no_args_is_help=True,
)
app.add_typer(thread_app, name="thread")


def _get_client(output: OutputFormat = OutputFormat.table):
    """Create a MemoryHubClient from config/env.

    Tries API key auth first (env var, key file, or config). Falls back to
    OAuth if no API key is available.
    """
    from memoryhub import MemoryHubClient

    api_key = get_api_key()
    if api_key:
        url = get_server_url()
        if not url:
            handle_error(
                "missing_config",
                "API key found but no server URL. "
                "Set MEMORYHUB_URL or run 'memoryhub login'.",
                output,
                EXIT_CLIENT_ERROR,
            )
        return MemoryHubClient(url=url, api_key=api_key)

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
    """Try to load project_id from .memoryhub.yaml.

    Returns, in priority order:
    1. An explicit ``project_id`` field from the config.
    2. The project directory name when campaigns are configured.
    3. None when no config exists or neither field is set.
    """
    try:
        config = load_project_config()  # auto-discovers .memoryhub.yaml
        if config.project_id:
            return config.project_id
        if config.memory_loading.campaigns:
            return Path.cwd().name
    except Exception:
        pass
    return None


def _print_compact(memories, project_id: str | None = None) -> None:
    """Print memories as content-only text for LLM context injection."""
    attr = f' project="{project_id}"' if project_id else ""
    print(f"<memoryhub-context{attr}>")  # noqa: T201
    for mem in memories:
        content = mem.content or mem.stub or ""
        for line in content.splitlines():
            print(f"- {line}")  # noqa: T201
    print("</memoryhub-context>")  # noqa: T201


def _run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


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


@app.command()
def login(
    url: str = typer.Option(..., prompt="MemoryHub MCP URL", help="MCP server URL"),
    auth_url: str = typer.Option(..., prompt="Auth service URL", help="OAuth 2.1 auth URL"),
    client_id: str = typer.Option(..., prompt="Client ID", help="OAuth client ID"),
    client_secret: str = typer.Option(
        ..., prompt="Client secret", hide_input=True, help="OAuth client secret"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Configure connection to a MemoryHub instance.

    Credentials are stored in ~/.config/memoryhub/config.json (mode 600).
    Environment variables (MEMORYHUB_URL, etc.) take precedence over stored config.
    """
    save_config({
        "url": url,
        "auth_url": auth_url,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    if output == OutputFormat.table:
        console.print("[green]Configuration saved.[/green]")  # noqa: T201

    # Test connectivity
    async def _test():
        from memoryhub import MemoryHubClient

        client = MemoryHubClient(
            url=url, auth_url=auth_url,
            client_id=client_id, client_secret=client_secret,
        )
        async with client:
            result = await client.search("test", max_results=1)
            return result

    try:
        _run(_test())
        if output == OutputFormat.json:
            json_success({"saved": True, "connection": "verified"})
        elif output == OutputFormat.table:
            console.print("[green]Connection verified.[/green]")  # noqa: T201
    except Exception as exc:
        if output == OutputFormat.json:
            json_success({"saved": True, "connection": "failed", "warning": str(exc)})
        elif output == OutputFormat.table:
            err_console.print(f"[yellow]Warning: connection test failed: {exc}[/yellow]")  # noqa: T201
            err_console.print("Credentials saved anyway. Check URL and credentials.")  # noqa: T201


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    scope: str | None = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    max_results: int = typer.Option(10, "--max", "-n", help="Maximum results"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    domains: list[str] | None = typer.Option(
        None, "--domain", help="Domain tags to boost",
    ),
    content_type: str | None = typer.Option(
        None, "--content-type", help="Filter by content type: declarative or behavioral",
    ),
    source: str | None = typer.Option(
        None, "--source", help="Filter by source: agent, dreaming, import",
    ),
    exclude_source: str | None = typer.Option(
        None, "--exclude-source", help="Exclude memories from a source (e.g. dreaming)",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o",
        help="Output format: table, json, quiet, compact",
    ),
):
    """Search memories using semantic similarity."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.search(
                query, scope=scope, max_results=max_results,
                project_id=_project_id, domains=domains or None,
                content_type=content_type,
                source=source, exclude_source=exclude_source,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return
    if output == OutputFormat.compact:
        _print_compact(result.results, _project_id)
        return

    if not result.results:
        console.print("[dim]No results found.[/dim]")  # noqa: T201
        return

    table = Table(title=f"Search: {query}")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Scope", style="cyan")
    table.add_column("Weight", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Stub", max_width=60)

    for mem in result.results:
        score = f"{mem.relevance_score:.3f}" if mem.relevance_score else "-"
        table.add_row(
            str(mem.id)[:12],
            mem.scope,
            f"{mem.weight:.2f}",
            score,
            (mem.stub or mem.content)[:60],
        )

    console.print(table)  # noqa: T201
    more = " (more available)" if result.has_more else ""
    console.print(  # noqa: T201
        f"[dim]{len(result.results)} of {result.total_matching} matching{more}[/dim]"
    )


@app.command("list")
def list_memories(
    scope: str | None = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    max_results: int = typer.Option(20, "--max", "-n", help="Maximum results"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID",
    ),
    content_type: str | None = typer.Option(
        None, "--content-type", help="Filter by content type: declarative or behavioral",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet, compact",
    ),
):
    """List memories ordered by creation time (no semantic search)."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.list(
                scope=scope, max_results=max_results,
                project_id=_project_id, content_type=content_type,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    memories = result.get("results", [])
    if output == OutputFormat.compact:
        # Build lightweight objects with .content/.stub for _print_compact
        from types import SimpleNamespace
        mems = [SimpleNamespace(**m) for m in memories]
        _print_compact(mems, _project_id)
        return

    if not memories:
        console.print("[dim]No memories found.[/dim]")  # noqa: T201
        return

    table = Table(title="Memories")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Scope", style="cyan")
    table.add_column("Weight", justify="right")
    table.add_column("Stub", max_width=60)

    for mem in memories:
        table.add_row(
            str(mem.get("id", ""))[:12],
            mem.get("scope", ""),
            f"{mem.get('weight', 0):.2f}",
            (mem.get("stub") or mem.get("content", ""))[:60],
        )

    console.print(table)  # noqa: T201
    cursor = result.get("cursor")
    if cursor:
        console.print("[dim]More available. Use --cursor to paginate.[/dim]")  # noqa: T201


@app.command()
def reconstruct(
    scope: str | None = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    owner_id: str | None = typer.Option(
        None, "--owner-id", help="Override owner filter",
    ),
    max_results: int = typer.Option(20, "--max", "-n", help="Maximum results"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o",
        help="Output format: table, json, quiet, compact",
    ),
):
    """Retrieve behavioral memories (demonstrated patterns and approaches)."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.reconstruct(
                scope=scope, project_id=_project_id, owner_id=owner_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return
    if output == OutputFormat.compact:
        _print_compact(result.results, _project_id)
        return

    if not result.results:
        console.print("[dim]No behavioral memories found.[/dim]")  # noqa: T201
        return

    table = Table(title="Behavioral Memories")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Scope", style="cyan")
    table.add_column("Weight", justify="right")
    table.add_column("Stub", max_width=60)

    for mem in result.results[:max_results]:
        table.add_row(
            str(mem.id)[:12],
            mem.scope,
            f"{mem.weight:.2f}",
            (mem.stub or mem.content)[:60],
        )

    console.print(table)  # noqa: T201


@app.command()
def read(
    memory_id: str = typer.Argument(..., help="Memory UUID"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Read a memory by ID."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.read(memory_id, project_id=_project_id)

    memory = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(memory.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[bold]{memory.scope}[/bold] | v{memory.version} | weight {memory.weight:.2f}")  # noqa: T201
    console.print(f"[dim]ID: {memory.id}[/dim]")  # noqa: T201
    console.print(f"[dim]Owner: {memory.owner_id}[/dim]")  # noqa: T201
    console.print()  # noqa: T201
    console.print(memory.content)  # noqa: T201

    if memory.branch_count:
        console.print(  # noqa: T201
            f"\n[dim]{memory.branch_count} branch(es). "
            f"Search or read by ID to inspect them.[/dim]"
        )


@app.command()
def write(
    content: str = typer.Argument(None, help="Memory content (reads from stdin if omitted)"),
    scope: str = typer.Option("user", "--scope", "-s", help="Memory scope"),
    weight: float = typer.Option(0.7, "--weight", "-w", help="Priority weight 0.0-1.0"),
    parent_id: str | None = typer.Option(None, "--parent", help="Parent memory ID"),
    branch_type: str | None = typer.Option(None, "--branch-type", help="Branch type"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    domains: list[str] | None = typer.Option(
        None, "--domain", help="Domain tags",
    ),
    content_type: str | None = typer.Option(
        None, "--content-type", help="Content type: declarative (default) or behavioral",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Write a new memory.

    Content can be passed as an argument or piped via stdin.
    """
    if content is None:
        if sys.stdin.isatty():
            handle_error(
                "missing_content",
                "Provide content as argument or pipe via stdin.",
                output, EXIT_CLIENT_ERROR,
            )
        content = sys.stdin.read().strip()

    if not content:
        handle_error("empty_content", "Content cannot be empty.", output, EXIT_CLIENT_ERROR)

    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.write(
                content, scope=scope, weight=weight,
                parent_id=parent_id, branch_type=branch_type,
                project_id=_project_id, domains=domains or None,
                content_type=content_type,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if result.curation.gated:
        err_console.print("[yellow]Write gated by curation.[/yellow]")  # noqa: T201
        err_console.print(f"  Reason: {result.curation.reason}")  # noqa: T201
        if result.curation.existing_memory_id:
            err_console.print(f"  Existing: {result.curation.existing_memory_id}")  # noqa: T201
        if result.curation.recommendation:
            err_console.print(f"  Recommendation: {result.curation.recommendation}")  # noqa: T201
        raise typer.Exit(EXIT_CLIENT_ERROR)

    mem = result.memory
    console.print(f"[green]Memory created:[/green] {mem.id}")  # noqa: T201
    console.print(f"  Scope: {mem.scope} | Weight: {mem.weight:.2f} | Version: {mem.version}")  # noqa: T201
    if result.curation.blocked:
        console.print("[yellow]Note: curation pipeline blocked this write.[/yellow]")  # noqa: T201
    elif result.curation.similar_count > 0:
        console.print(  # noqa: T201
            f"[dim]Curation: {result.curation.similar_count} similar memories found"
            f" (nearest score: {result.curation.nearest_score:.3f})[/dim]"
        )


@app.command()
def delete(
    memory_id: str = typer.Argument(..., help="Memory UUID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Soft-delete a memory and its version chain."""
    if not force and output == OutputFormat.table:
        confirm = typer.confirm(f"Delete memory {memory_id} and all versions?")
        if not confirm:
            raise typer.Abort()
    elif not force:
        handle_error(
            "confirmation_required",
            "Delete requires --force in non-interactive mode.",
            output,
            EXIT_CLIENT_ERROR,
        )

    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.delete(memory_id, project_id=_project_id)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(  # noqa: T201
        f"[green]Deleted:[/green] {result.total_deleted} nodes "
        f"({result.versions_deleted} versions, {result.branches_deleted} branches)"
    )


@app.command()
def update(
    memory_id: str = typer.Argument(..., help="Memory UUID to update"),
    content: str | None = typer.Argument(
        None,
        help="New content (reads from stdin if omitted and stdin is not a tty)",
    ),
    weight: float | None = typer.Option(
        None, "--weight", "-w", help="New priority weight 0.0-1.0",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    domains: list[str] | None = typer.Option(
        None, "--domain", help="Domain tags",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Update an existing memory's content, weight, or domains.

    Content can be passed as an argument or piped via stdin.
    At least one of content or --weight must be provided.
    """
    # Resolve content from stdin if not provided as an argument
    if content is None and not sys.stdin.isatty():
        content = sys.stdin.read().strip() or None

    if content is None and weight is None and not domains:
        handle_error(
            "missing_input",
            "Provide at least one of: content, --weight, or --domain.",
            output, EXIT_CLIENT_ERROR,
        )

    if content is not None and not content:
        handle_error("empty_content", "Content cannot be empty.", output, EXIT_CLIENT_ERROR)

    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.update(
                memory_id,
                content=content,
                weight=weight,
                project_id=_project_id,
                domains=domains or None,
            )

    memory = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(memory.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Memory updated:[/green] {memory.id}")  # noqa: T201
    console.print(  # noqa: T201
        f"  Scope: {memory.scope} | Weight: {memory.weight:.2f} | "
        f"Version: {memory.version}"
    )


@app.command()
def history(
    memory_id: str = typer.Argument(..., help="Memory UUID"),
    max_versions: int = typer.Option(20, "--max", "-n", help="Maximum versions to show"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Show version history for a memory."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.get_history(
                memory_id, max_versions=max_versions,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if not result.versions:
        console.print("[dim]No version history found.[/dim]")  # noqa: T201
        return

    table = Table(title=f"History: {memory_id[:12]}...")
    table.add_column("Version", justify="right")
    table.add_column("Current", justify="center")
    table.add_column("Created", style="dim")
    table.add_column("Stub", max_width=60)

    for v in result.versions:
        current = "[green]Yes[/green]" if v.is_current else ""
        created = str(v.created_at)[:19] if v.created_at else "-"
        table.add_row(
            f"v{v.version}",
            current,
            created,
            (v.stub or v.content)[:60],
        )

    console.print(table)  # noqa: T201
    if result.has_more:
        console.print(  # noqa: T201
            f"[dim]Showing {len(result.versions)} of {result.total_versions} versions[/dim]"
        )


# ── promote / graduate / checkpoint ───────────────────────────────────────────


@app.command()
def promote(
    memory_id: str = typer.Argument(..., help="Memory UUID to promote"),
    target_scope: str = typer.Argument(
        ..., help="Target scope: project, organizational, or enterprise",
    ),
    target_scope_id: str | None = typer.Option(
        None, "--target-scope-id", help="Scope ID (e.g., project ID for project scope)",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Promote a memory to a broader scope."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.promote(
                memory_id, target_scope,
                target_scope_id=target_scope_id,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Promoted:[/green] {result.id}")  # noqa: T201
    console.print(f"  Scope: {result.scope} | Content type: {result.content_type}")  # noqa: T201
    console.print(f"  Source: {memory_id[:12]}...")  # noqa: T201


@app.command()
def graduate(
    memory_id: str = typer.Argument(..., help="Memory UUID to graduate"),
    evidence: str | None = typer.Option(
        None, "--evidence", "-e", help="Evidence text to attach",
    ),
    reviewer_note: str | None = typer.Option(
        None, "--reviewer-note", help="Note explaining the graduation",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Graduate an experiential memory to knowledge status."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.graduate(
                memory_id,
                evidence=evidence,
                reviewer_note=reviewer_note,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Graduated:[/green] {result.id}")  # noqa: T201
    console.print(f"  Content type: {result.content_type} | Scope: {result.scope}")  # noqa: T201
    console.print(f"  Source: {memory_id[:12]}...")  # noqa: T201
    if evidence:
        console.print("  Evidence branch attached.")  # noqa: T201


@app.command()
def checkpoint(
    workflow_name: str = typer.Argument(..., help="Workflow identifier"),
    state: str | None = typer.Option(
        None, "--state", help="JSON state to persist (omit to read current state)",
    ),
    scope: str = typer.Option("user", "--scope", "-s", help="Scope: user (default) or project"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID (required for project scope)",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Read or write durable checkpoint state for a workflow."""
    import json as json_mod

    state_dict = None
    if state is not None:
        try:
            state_dict = json_mod.loads(state)
        except json_mod.JSONDecodeError as exc:
            handle_error(
                "invalid_json",
                f"--state must be valid JSON: {exc}",
                output, EXIT_CLIENT_ERROR,
            )

    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.checkpoint(
                workflow_name,
                state=state_dict,
                scope=scope,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    wf = result.get("workflow_name", workflow_name)
    current_state = result.get("state")
    if state_dict is not None:
        verb = "Created" if result.get("created") else "Updated"
        console.print(f"[green]{verb} checkpoint:[/green] {wf}")  # noqa: T201
    else:
        if current_state is None:
            console.print(f"[dim]No checkpoint found for workflow '{wf}'.[/dim]")  # noqa: T201
            return
        console.print(f"[bold]Checkpoint:[/bold] {wf}")  # noqa: T201

    console.print(f"  State: {json_mod.dumps(current_state, indent=2)}")  # noqa: T201


# ── memoryhub config init / regenerate ───────────────────────────────────────


_SHAPE_PROMPT = """\
What's this project's typical session shape?
  1) One topic per session, narrow scope (focused)
  2) Multiple topics per session, broad context needed (broad)
  3) Sessions evolve — start narrow, may pivot (adaptive)\
"""

_PATTERN_PROMPT = """\
How should memories load?
  1) Eager — load at session start (best for broad)
  2) Lazy — load after first user turn (best for focused)
  3) Lazy + rebias on pivot (best for adaptive)
  4) Just-in-time — never preload, search on demand\
"""

_FOCUS_PROMPT = """\
How should session focus be inferred?
  1) Declared — agent will ask
  2) Inferred from working directory
  3) Inferred from first user turn
  4) Auto (try inference, fall back to ask)\
"""

_CONTRADICTION_BLURBS: dict[str, str] = {
    "focused": """\
Cross-domain contradiction detection:
  Focused sessions load only memories matching the session topic. If you
  make a decision that contradicts a memory from a different topic, the
  agent won't catch it. Enable this to load all domains (more tokens,
  broader coverage).""",
    "adaptive": """\
Cross-domain contradiction detection:
  Adaptive sessions load memories for the current topic and add more on
  pivot, but memories from unvisited topics aren't checked. Enable this
  to also load all domains at session start (more tokens, broader
  coverage).""",
}


_SHAPE_BY_INDEX: dict[int, SessionShape] = {1: "focused", 2: "broad", 3: "adaptive"}
_PATTERN_BY_INDEX: dict[int, LoadingPattern] = {
    1: "eager",
    2: "lazy",
    3: "lazy_with_rebias",
    4: "jit",
}
_FOCUS_BY_INDEX = {1: "declared", 2: "directory", 3: "first_turn", 4: "auto"}


def _prompt_choice(prompt_text: str, choices: dict, default: int) -> int:
    """Prompt for an integer in `choices`, defaulting to `default`."""
    while True:
        console.print(prompt_text)  # noqa: T201
        raw = typer.prompt(f"Choice [{default}]", default=str(default), show_default=False)
        try:
            value = int(raw)
        except ValueError:
            err_console.print(f"[red]Not a number: {raw}[/red]")  # noqa: T201
            continue
        if value in choices:
            return value
        err_console.print(  # noqa: T201
            f"[red]Pick one of: {', '.join(str(k) for k in choices)}[/red]"
        )


@config_app.command("init")
def config_init(
    project_dir: Path = typer.Option(
        Path("."),
        "--dir",
        "-d",
        help="Project directory (defaults to cwd).",
        file_okay=False,
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing .memoryhub.yaml or generated rule file.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        "-p",
        help="Project identifier for project-scoped memories.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Use defaults for all prompts, skip interactive setup.",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
    instruction_format: str = typer.Option(
        "claude-code",
        "--format",
        help="Instruction format: claude-code, system-prompt, agents-md, ogx, raw",
    ),
):
    """Walk through project setup and write `.memoryhub.yaml` + the
    generated `.claude/rules/memoryhub-loading.md` rule file."""
    project_dir = project_dir.resolve()
    console.print(f"[bold]Configuring MemoryHub for[/bold] {project_dir}\n")  # noqa: T201

    if non_interactive:
        shape: SessionShape = "focused"
        pattern: LoadingPattern = "lazy"
        focus_source: FocusSource = "auto"
        keep_contradictions = False
        campaigns: list[str] = []
    else:
        shape_idx = _prompt_choice(_SHAPE_PROMPT, _SHAPE_BY_INDEX, default=1)
        shape = _SHAPE_BY_INDEX[shape_idx]

        suggested_pattern = suggest_pattern(shape)
        pattern_default = next(
            i for i, p in _PATTERN_BY_INDEX.items() if p == suggested_pattern
        )
        pattern_idx = _prompt_choice(_PATTERN_PROMPT, _PATTERN_BY_INDEX, default=pattern_default)
        pattern = _PATTERN_BY_INDEX[pattern_idx]

        focus_idx = _prompt_choice(_FOCUS_PROMPT, _FOCUS_BY_INDEX, default=4)
        focus_source = _FOCUS_BY_INDEX[focus_idx]

        if shape == "broad":
            # Broad mode already loads everything — contradiction detection
            # is comprehensive by default.
            keep_contradictions = True
        else:
            blurb = _CONTRADICTION_BLURBS.get(shape, _CONTRADICTION_BLURBS["focused"])
            console.print(f"\n{blurb}\n")  # noqa: T201
            keep_contradictions = typer.confirm(
                "Enable cross-domain contradiction detection?",
                default=False,
            )

        # ── Campaign enrollment ──
        console.print(  # noqa: T201
            "\n[bold]Campaign enrollment[/bold]\n"
            "  Campaigns enable cross-project knowledge sharing. If this\n"
            "  project is part of a coordinated effort (e.g., a modernization\n"
            "  initiative), enter the campaign names. Skip if none."
        )
        campaigns_raw = typer.prompt(
            "Campaigns (comma-separated, or Enter to skip)",
            default="",
            show_default=False,
        )
        campaigns = (
            [c.strip() for c in campaigns_raw.split(",") if c.strip()]
            if campaigns_raw
            else []
        )

    choices = InitChoices(
        session_shape=shape,
        pattern=pattern,
        focus_source=focus_source,
        cross_domain_contradiction_detection=keep_contradictions,
        campaigns=campaigns,
        project_id=project,
    )
    config = build_project_config(choices)

    # Validate instruction_format early.
    valid_formats = ("claude-code", "system-prompt", "agents-md", "ogx", "raw")
    if instruction_format not in valid_formats:
        handle_error(
            "invalid_format",
            f"Unknown format {instruction_format!r}. Choose from: {', '.join(valid_formats)}",
            output,
            EXIT_CLIENT_ERROR,
        )

    try:
        result = write_init_files(
            config,
            project_dir,
            overwrite=force,
            instruction_format=instruction_format,  # type: ignore[arg-type]
        )
    except FileExistsError as exc:
        handle_error("file_exists", str(exc), output, EXIT_CLIENT_ERROR)

    if output == OutputFormat.json:
        json_success({
            "yaml_path": str(result.yaml_path),
            "rule_path": str(result.rule_path) if result.rule_path else None,
            "hook_path": str(result.hook_path) if result.hook_path else None,
            "settings_path": str(result.settings_path) if result.settings_path else None,
            "legacy_backup": str(result.legacy_backup) if result.legacy_backup else None,
            "instruction_format": instruction_format,
        })
        return
    if output == OutputFormat.quiet:
        return

    # For non-claude-code formats, print instructions to stdout.
    if instruction_format != "claude-code":
        console.print(f"\n[green]Wrote {result.yaml_path}[/green]")  # noqa: T201
        console.print(  # noqa: T201
            f"\n[bold]Instructions ({instruction_format}):[/bold]\n"
        )
        print(render_instructions(config, instruction_format))  # noqa: T201
    else:
        console.print(f"\n[green]Wrote {result.yaml_path}[/green]")  # noqa: T201
        console.print(f"[green]Wrote {result.rule_path}[/green]")  # noqa: T201
        if result.hook_path:
            console.print(f"[green]Wrote {result.hook_path}[/green]")  # noqa: T201
        if result.settings_path:
            console.print(f"[green]Updated {result.settings_path}[/green]")  # noqa: T201
        if result.legacy_backup is not None:
            console.print(  # noqa: T201
                f"[yellow]Backed up legacy rule to {result.legacy_backup}.[/yellow]\n"
                f"Review and delete the .bak when you're satisfied with the new rule."
            )

    # ── Summary ──
    mode_label = {"focused": "focused", "broad": "broad", "adaptive": "focused"}[shape]
    if shape == "adaptive":
        mode_explanation = f"mode={mode_label} + {pattern}"
    else:
        mode_explanation = f"mode={mode_label}"
    console.print("\n[bold]Summary[/bold]")  # noqa: T201
    console.print(f"  Session shape: {shape} ({mode_explanation})")  # noqa: T201
    console.print(f"  Loading: {pattern}")  # noqa: T201
    console.print(f"  Focus source: {focus_source}")  # noqa: T201
    cross = "on" if keep_contradictions else "off"
    console.print(f"  Cross-domain contradictions: {cross}")  # noqa: T201
    if campaigns:
        console.print(f"  Campaigns: {', '.join(campaigns)}")  # noqa: T201
    if project:
        console.print(f"  Project: {project}")  # noqa: T201

    # ── #153: API key check ──
    api_key_path = Path.home() / ".config" / "memoryhub" / "api-key"
    if api_key_path.exists():
        console.print(f"\n[green]API key found at {api_key_path}[/green]")  # noqa: T201
    else:
        console.print(  # noqa: T201
            f"\n[yellow]Warning:[/yellow] No API key at {api_key_path}\n"
            "  Create this file with your MemoryHub API key before using\n"
            "  the agent. Ask your administrator for a key."
        )

    # ── Server URL check ──
    existing_config = load_config()
    existing_url = existing_config.get("url", "")
    if existing_url:
        console.print(f"[green]Server URL configured:[/green] {existing_url}")  # noqa: T201
    elif non_interactive:
        env_url = get_server_url()
        if env_url:
            console.print(f"[green]Server URL (from env):[/green] {env_url}")  # noqa: T201
        else:
            console.print(  # noqa: T201
                "[yellow]Warning:[/yellow] No server URL configured.\n"
                "  Set MEMORYHUB_URL or add \"url\" to"
                " ~/.config/memoryhub/config.json."
            )
    else:
        console.print(  # noqa: T201
            "\n[yellow]Warning:[/yellow] No server URL configured.\n"
            "  The SessionStart hook and CLI commands need the MemoryHub\n"
            "  server URL. Set MEMORYHUB_URL env var or enter it now."
        )
        url_input = typer.prompt(
            "MemoryHub server URL (Enter to skip)",
            default="",
            show_default=False,
        )
        if url_input.strip():
            existing_config["url"] = url_input.strip()
            save_config(existing_config)
            console.print(  # noqa: T201
                "[green]URL saved to ~/.config/memoryhub/config.json[/green]"
            )


@config_app.command("regenerate")
def config_regenerate(
    project_dir: Path = typer.Option(
        Path("."),
        "--dir",
        "-d",
        help="Project directory (defaults to cwd).",
        file_okay=False,
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Re-render `.claude/rules/memoryhub-loading.md` from `.memoryhub.yaml`.

    Use this after editing the YAML by hand to refresh the rule file
    without running the interactive prompt again.
    """
    project_dir = project_dir.resolve()
    yaml_path = project_dir / CONFIG_FILENAME
    if not yaml_path.is_file():
        handle_error(
            "missing_config",
            f"No {CONFIG_FILENAME} in {project_dir}. "
            "Run 'memoryhub config init' first.",
            output,
            EXIT_CLIENT_ERROR,
        )

    try:
        config = load_project_config(yaml_path)
    except ConfigError as exc:
        handle_error("invalid_config", str(exc), output, EXIT_CLIENT_ERROR)

    result = rewrite_rule_file(config, project_dir)
    console.print(f"[green]Regenerated {result.rule_path}[/green]")  # noqa: T201
    if result.legacy_backup is not None:
        console.print(  # noqa: T201
            f"[yellow]Backed up legacy rule to {result.legacy_backup}.[/yellow]"
        )


# ── memoryhub graph ───────────────────────────────────────────────────────────


@graph_app.command("relate")
def graph_relate(
    source_id: str = typer.Argument(..., help="Source memory UUID"),
    target_id: str = typer.Argument(..., help="Target memory UUID"),
    relationship_type: str = typer.Argument(..., help="Relationship type label"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Create a directed relationship between two memories."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.create_relationship(
                source_id, target_id, relationship_type,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(  # noqa: T201
        f"[green]Relationship created:[/green] "
        f"{source_id[:12]} --[{relationship_type}]--> {target_id[:12]}"
    )


@graph_app.command("list")
def graph_list(
    node_id: str = typer.Argument(..., help="Memory UUID to query relationships for"),
    rel_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by relationship type",
    ),
    direction: str = typer.Option(
        "both", "--direction", "-d",
        help="Relationship direction: both (default), outgoing, incoming",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """List relationships for a memory node."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.get_relationships(
                node_id,
                relationship_type=rel_type,
                direction=direction,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if not result.relationships:
        console.print("[dim]No relationships found.[/dim]")  # noqa: T201
        return

    table = Table(title=f"Relationships: {node_id[:12]}...")
    table.add_column("Direction", justify="center")
    table.add_column("Related ID", style="dim", max_width=12)
    table.add_column("Type", style="cyan")
    table.add_column("Created", style="dim")

    for rel in result.relationships:
        if str(rel.source_id) == node_id:
            dir_arrow = "→"
            related = str(rel.target_id)[:12]
        else:
            dir_arrow = "←"
            related = str(rel.source_id)[:12]
        created = str(rel.created_at)[:19] if getattr(rel, "created_at", None) else "-"
        table.add_row(dir_arrow, related, rel.relationship_type, created)

    console.print(table)  # noqa: T201


@graph_app.command("similar")
def graph_similar(
    memory_id: str = typer.Argument(..., help="Memory UUID to find similar memories for"),
    threshold: float = typer.Option(
        0.80, "--threshold", help="Minimum cosine similarity score",
    ),
    max_results: int = typer.Option(10, "--max", "-n", help="Maximum results"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Find memories semantically similar to a given memory."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.get_similar(
                memory_id,
                threshold=threshold,
                max_results=max_results,
                project_id=_project_id,
            )

    results = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success([m.model_dump() for m in results])
        return
    if output == OutputFormat.quiet:
        return

    if not results:
        console.print("[dim]No similar memories found.[/dim]")  # noqa: T201
        return

    table = Table(title=f"Similar to: {memory_id[:12]}...")
    table.add_column("ID", style="dim", max_width=12)
    table.add_column("Score", justify="right")
    table.add_column("Scope", style="cyan")
    table.add_column("Stub", max_width=60)

    for mem in results:
        score = f"{mem.relevance_score:.3f}" if getattr(mem, "relevance_score", None) else "-"
        table.add_row(
            str(mem.id)[:12],
            score,
            mem.scope,
            (mem.stub or mem.content)[:60],
        )

    console.print(table)  # noqa: T201


# ── memoryhub curation ────────────────────────────────────────────────────────


@curation_app.command("report")
def curation_report(
    memory_id: str = typer.Argument(..., help="Memory UUID with contradicting behavior"),
    observed_behavior: str = typer.Argument(..., help="Description of the observed behavior"),
    confidence: float = typer.Option(
        0.7, "--confidence", "-c", help="Confidence in the contradiction report (0.0-1.0)",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Report a contradiction between a stored memory and observed behavior."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.report_contradiction(
                memory_id, observed_behavior,
                confidence=confidence,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    triggered = "Yes" if result.revision_triggered else "No"
    console.print(f"[green]Contradiction reported for[/green] {memory_id[:12]}")  # noqa: T201
    console.print(f"  Count: {result.contradiction_count} / {result.threshold} threshold")  # noqa: T201
    console.print(f"  Revision triggered: {triggered}")  # noqa: T201


@curation_app.command("resolve")
def curation_resolve(
    contradiction_id: str = typer.Argument(..., help="Contradiction UUID to resolve"),
    action: str = typer.Option(
        ..., "--action", "-a",
        help="Resolution action: accept_new, keep_old, mark_both_invalid, manual_merge",
    ),
    note: str | None = typer.Option(None, "--note", help="Optional resolution note"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Resolve a reported contradiction."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.resolve_contradiction(
                contradiction_id, action,
                resolution_note=note,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Contradiction {contradiction_id[:12]} resolved:[/green] {action}")  # noqa: T201


@curation_app.command("rule")
def curation_rule(
    name: str = typer.Argument(..., help="Rule name"),
    tier: str = typer.Option(
        "embedding", "--tier", help="Rule tier: embedding or regex",
    ),
    action: str = typer.Option(
        "flag", "--action", "-a",
        help="Action: flag, block, quarantine, etc.",
    ),
    threshold: float | None = typer.Option(
        None, "--threshold", help="Similarity threshold (for embedding tier)",
    ),
    scope_filter: str | None = typer.Option(
        None, "--scope-filter", help="Scope filter",
    ),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Enable or disable the rule"),
    priority: int = typer.Option(10, "--priority", help="Rule priority"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Create or update a curation rule."""
    client = _get_client(output)

    config: dict | None = {"threshold": threshold} if threshold is not None else None

    async def _do():
        async with client:
            return await client.set_curation_rule(
                name,
                tier=tier,
                action=action,
                config=config,
                scope_filter=scope_filter,
                enabled=enabled,
                priority=priority,
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    verb = "updated" if result.updated else "created"
    rule = result.rule
    enabled_label = "enabled" if rule.enabled else "disabled"
    console.print(f"[green]Rule {verb}:[/green] {name}")  # noqa: T201
    console.print(  # noqa: T201
        f"  Tier: {rule.tier} | Action: {rule.action} | "
        f"Priority: {rule.priority} | {enabled_label}"
    )


# ── memoryhub project ─────────────────────────────────────────────────────────


@project_app.command("list")
def project_list(
    filter: str = typer.Option("mine", "--filter", "-f", help='"mine" (default) or "all"'),  # noqa: A002
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """List projects you belong to (or all projects with --filter all)."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.list_projects(filter=filter)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    projects = result.get("projects", [])
    if not projects:
        console.print("[dim]No projects found.[/dim]")  # noqa: T201
        return

    table = Table(title="Projects")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Members", justify="right")
    table.add_column("Policy", style="cyan")

    for proj in projects:
        name = proj.get("name", "")
        description = proj.get("description") or ""
        if len(description) > 40:
            description = description[:37] + "..."
        members = proj.get("members", [])
        member_count = proj.get("member_count", len(members) if isinstance(members, list) else 0)
        invite_only = proj.get("invite_only", False)
        policy = "invite-only" if invite_only else "open"
        table.add_row(name, description, str(member_count), policy)

    console.print(table)  # noqa: T201


@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: str | None = typer.Option(None, "--description", help="Optional description"),
    invite_only: bool = typer.Option(
        False, "--invite-only", help="Restrict membership to invites",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Create a new project."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.create_project(
                name, description=description, invite_only=invite_only
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Project created:[/green] {name}")  # noqa: T201
    if description:
        console.print(f"  Description: {description}")  # noqa: T201
    policy = "invite-only" if invite_only else "open"
    console.print(f"  Policy: {policy}")  # noqa: T201


@project_app.command("add-member")
def project_add_member(
    project_name: str = typer.Argument(..., help="Project name"),
    user_id: str = typer.Argument(..., help="User ID to add"),
    role: str = typer.Option("member", "--role", "-r", help='"member" (default) or "admin"'),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Add a member to a project."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.add_project_member(project_name, user_id, role=role)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Added[/green] {user_id} to {project_name} as {role}")  # noqa: T201


@project_app.command("remove-member")
def project_remove_member(
    project_name: str = typer.Argument(..., help="Project name"),
    user_id: str = typer.Argument(..., help="User ID to remove"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Remove a member from a project."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.remove_project_member(project_name, user_id)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Removed[/green] {user_id} from {project_name}")  # noqa: T201


@project_app.command("describe")
def project_describe(
    project_name: str = typer.Argument(..., help="Project name"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Show project details, members, and memory count."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.describe_project(project_name)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    proj = result.get("project", {})
    console.print(f"[bold]{proj.get('name', project_name)}[/bold]")  # noqa: T201
    if proj.get("description"):
        console.print(f"  {proj['description']}")  # noqa: T201
    policy = "invite-only" if proj.get("invite_only") else "open"
    console.print(f"  Policy: {policy} | Memories: {proj.get('memory_count', 0)}")  # noqa: T201
    if proj.get("created_by"):
        created = str(proj.get("created_at", ""))[:19]
        console.print(f"  Created by {proj['created_by']} on {created}")  # noqa: T201

    members = result.get("members", [])
    if members:
        console.print()  # noqa: T201
        table = Table(title="Members")
        table.add_column("User", style="bold")
        table.add_column("Role", style="cyan")
        table.add_column("Joined", style="dim")
        for m in members:
            joined = str(m.get("joined_at", ""))[:19] if m.get("joined_at") else "-"
            table.add_row(m.get("user_id", ""), m.get("role", ""), joined)
        console.print(table)  # noqa: T201
    else:
        console.print("\n[dim]No members.[/dim]")  # noqa: T201


# ── memoryhub session ─────────────────────────────────────────────────────────


@session_app.command("status")
def session_status(
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Show current session info: user, scopes, expiry, and project memberships."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.get_session()

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    user_id = result.get("user_id", "-")
    name = result.get("name", "")
    scopes = result.get("scopes", [])
    expires_at = result.get("expires_at", "-")
    projects = [
        p.get("project_id", p) if isinstance(p, dict) else p
        for p in result.get("projects", [])
    ]

    console.print(f"Session: {user_id} ({name})")  # noqa: T201
    console.print(f"  Scopes: {', '.join(scopes) if scopes else '-'}")  # noqa: T201
    console.print(f"  Expires: {expires_at}")  # noqa: T201
    console.print(f"  Projects: {', '.join(projects) if projects else '-'}")  # noqa: T201


@session_app.command("focus")
def session_focus(
    focus_text: str = typer.Argument(..., help="Short topic description for this session"),
    project: str = typer.Option(..., "--project", "-p", help="Project identifier"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Set the focus topic for the current session."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.set_session_focus(focus_text, project)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"Focus set: {focus_text} (project: {project})")  # noqa: T201


@session_app.command("focus-history")
def session_focus_history(
    project: str = typer.Argument(..., help="Project identifier"),
    start: str | None = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Show focus topic history for a project."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.get_focus_history(project, start_date=start, end_date=end)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result)
        return
    if output == OutputFormat.quiet:
        return

    histogram = result.get("histogram", [])
    total = result.get("total_sessions", 0)

    if not histogram:
        console.print("[dim]No focus history found.[/dim]")  # noqa: T201
    else:
        table = Table(title=f"Focus History: {project}")
        table.add_column("Focus", style="cyan")
        table.add_column("Count", justify="right")

        for entry in histogram:
            table.add_row(entry.get("focus", "-"), str(entry.get("count", 0)))

        console.print(table)  # noqa: T201

    console.print(f"[dim]Total sessions: {total}[/dim]")  # noqa: T201


# ── Entity management commands ─────────────────────────────────────────────────


@entity_app.command("list")
def entity_list(
    entity_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by entity type (person, object, location, event, organization)",
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum entities to return"),
    offset: int = typer.Option(0, "--offset", help="Pagination offset"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """List extracted entities ordered by mention count."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.list_entities(
                entity_type=entity_type,
                limit=limit,
                offset=offset,
                project_id=_project_id,
            )

    result = _run_command(_do(), output)
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if not result.entities:
        console.print("[dim]No entities found.[/dim]")  # noqa: T201
        return

    table = Table(title=f"Entities ({result.total} total)")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    table.add_column("Mentions", justify="right")
    table.add_column("Aliases", style="dim")
    table.add_column("ID", style="dim")

    for ent in result.entities:
        aliases = ", ".join(ent.aliases) if ent.aliases else "-"
        table.add_row(
            ent.content,
            ent.entity_type or "-",
            str(ent.mentions_count),
            aliases,
            ent.id,
        )

    console.print(table)  # noqa: T201
    if result.has_more:
        shown_range = f"{result.offset + 1}-{result.offset + len(result.entities)}"
        console.print(  # noqa: T201
            f"[dim]Showing {shown_range} of {result.total}. Use --offset to paginate.[/dim]"
        )


@entity_app.command("merge")
def entity_merge(
    source_id: str = typer.Argument(..., help="ID of the entity to merge away (will be deleted)"),
    target_id: str = typer.Argument(..., help="ID of the surviving entity"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Merge one entity into another, reassigning all mention relationships."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.merge_entities(
                source_id, target_id, project_id=_project_id,
            )

    result = _run_command(_do(), output)
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Merged:[/green] {result.message}")  # noqa: T201
    surviving = result.surviving_entity
    ent_content = surviving.get("content", "?")
    ent_id = surviving.get("id", "?")
    console.print(f"  Surviving entity: {ent_content} ({ent_id})")  # noqa: T201
    console.print(f"  Reassigned mentions: {result.reassigned_mentions}")  # noqa: T201
    if result.skipped_duplicates > 0:
        console.print(f"  Skipped duplicates: {result.skipped_duplicates}")  # noqa: T201
    aliases = surviving.get("aliases", [])
    if aliases:
        console.print(f"  Aliases: {', '.join(aliases)}")  # noqa: T201


@entity_app.command("rename")
def entity_rename(
    entity_id: str = typer.Argument(..., help="ID of the entity to rename"),
    new_name: str = typer.Argument(..., help="New canonical name for the entity"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Rename an entity's canonical name (old name preserved as alias)."""
    client = _get_client(output)
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.rename_entity(
                entity_id, new_name, project_id=_project_id,
            )

    result = _run_command(_do(), output)
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    entity = result.entity
    new_content = entity.get("content", new_name)
    console.print(f"[green]Renamed:[/green] '{result.old_name}' -> '{new_content}'")  # noqa: T201
    console.print(f"  Entity ID: {entity.get('id', entity_id)}")  # noqa: T201
    console.print(f"  Type: {entity.get('entity_type', '?')}")  # noqa: T201
    aliases = entity.get("aliases", [])
    if aliases:
        console.print(f"  Aliases: {', '.join(aliases)}")  # noqa: T201


# ── memoryhub thread ──────────────────────────────────────────────────────────


@thread_app.command("create")
def thread_create(
    scope: str = typer.Argument(..., help="Thread scope: user, project, etc."),
    title: str | None = typer.Option(None, "--title", "-t", help="Thread title"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Create a new conversation thread."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.create_thread(scope, title=title)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Thread created:[/green] {result.id}")  # noqa: T201
    console.print(f"  Scope: {result.scope}")  # noqa: T201
    if result.title:
        console.print(f"  Title: {result.title}")  # noqa: T201
    console.print(f"  Status: {result.status}")  # noqa: T201


@thread_app.command("append")
def thread_append(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    role: str = typer.Option(..., "--role", "-r", help="Message role: user, assistant, system"),
    content: str = typer.Option(..., "--content", "-c", help="Message content"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Append a message to a conversation thread."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.append_message(thread_id, role, content)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Message appended:[/green] {result.id}")  # noqa: T201
    console.print(f"  Thread: {result.thread_id}")  # noqa: T201
    console.print(f"  Role: {result.role}")  # noqa: T201
    console.print(f"  Sequence: {result.sequence_number}")  # noqa: T201


@thread_app.command("get")
def thread_get(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max messages"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Retrieve a thread with its messages."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.get_thread(thread_id, limit=limit)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[bold]Thread:[/bold] {result.thread.id}")  # noqa: T201
    console.print(f"  Scope: {result.thread.scope} | Status: {result.thread.status}")  # noqa: T201
    if result.thread.title:
        console.print(f"  Title: {result.thread.title}")  # noqa: T201
    console.print(f"  Messages: {result.total_messages}")  # noqa: T201

    if not result.messages:
        console.print("\n[dim]No messages.[/dim]")  # noqa: T201
        return

    console.print()  # noqa: T201
    table = Table(title="Messages")
    table.add_column("Seq", justify="right")
    table.add_column("Role", style="cyan")
    table.add_column("Content", max_width=80)
    table.add_column("Created", style="dim")

    for msg in result.messages:
        content = (msg.content or msg.summary or "")[:80]
        created = str(msg.created_at)[:19] if msg.created_at else "-"
        table.add_row(
            str(msg.sequence_number),
            msg.role,
            content,
            created,
        )

    console.print(table)  # noqa: T201


@thread_app.command("list")
def thread_list(
    scope: str | None = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    status: str = typer.Option("active", "--status", help="Filter by status"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max threads"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """List conversation threads."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.list_threads(scope=scope, status=status, limit=limit)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if not result.threads:
        console.print("[dim]No threads found.[/dim]")  # noqa: T201
        return

    table = Table(title="Threads")
    table.add_column("ID", style="cyan", max_width=36)
    table.add_column("Title")
    table.add_column("Scope")
    table.add_column("Status")
    table.add_column("Created")

    for thread in result.threads:
        title = thread.title or ""
        created = str(thread.created_at)[:19] if thread.created_at else "-"
        table.add_row(
            thread.id,
            title,
            thread.scope,
            thread.status,
            created,
        )

    console.print(table)  # noqa: T201
    if result.total > len(result.threads):
        console.print(f"[dim]Showing {len(result.threads)} of {result.total}[/dim]")  # noqa: T201


@thread_app.command("archive")
def thread_archive(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Archive a conversation thread."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.archive_thread(thread_id)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Thread archived:[/green] {result.id}")  # noqa: T201
    console.print(f"  Status: {result.status}")  # noqa: T201


@thread_app.command("extract")
def thread_extract(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    model: str | None = typer.Option(None, "--model", help="Override extraction model"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Extract memories from a conversation thread."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.extract_thread(thread_id, model=model)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Extraction complete:[/green] {result.thread_id}")  # noqa: T201
    console.print(f"  Memories created: {result.memories_created}")  # noqa: T201
    if result.memories:
        console.print("\n[bold]Extracted memories:[/bold]")  # noqa: T201
        for mem in result.memories:
            console.print(f"  - {mem.id[:12]}... | {(mem.stub or mem.content)[:60]}")  # noqa: T201


@thread_app.command("fork")
def thread_fork(
    thread_id: str = typer.Argument(..., help="Source thread UUID"),
    from_sequence: int = typer.Option(
        ..., "--from-sequence", "-f", help="Fork point sequence number"
    ),
    title: str | None = typer.Option(None, "--title", "-t", help="New thread title"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Fork a thread from a specific message."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.fork_thread(thread_id, from_sequence, title=title)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Thread forked:[/green] {result.id}")  # noqa: T201
    console.print(f"  Parent: {result.parent_thread_id}")  # noqa: T201
    console.print(f"  Fork point: sequence {result.fork_point_sequence}")  # noqa: T201
    if result.title:
        console.print(f"  Title: {result.title}")  # noqa: T201


@thread_app.command("share")
def thread_share(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    grantee: str = typer.Option(..., "--grantee", "-g", help="Agent/user to share with"),
    access: str = typer.Option(..., "--access", "-a", help="Access level: read, write, admin"),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Share a thread with another agent or user."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.share_thread(thread_id, grantee, access)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Thread shared:[/green] {result.thread_id}")  # noqa: T201
    console.print(f"  Grantee: {result.grantee_id}")  # noqa: T201
    console.print(f"  Access: {result.access_level}")  # noqa: T201


@thread_app.command("delete")
def thread_delete(
    thread_id: str = typer.Argument(..., help="Thread UUID"),
    cascade: str | None = typer.Option(
        None, "--cascade", help="Cascade mode: delete, orphan, preserve"
    ),
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
    ),
):
    """Delete a conversation thread."""
    client = _get_client(output)

    async def _do():
        async with client:
            return await client.delete_thread(thread_id, cascade=cascade)

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"[green]Thread deleted:[/green] {result.id}")  # noqa: T201
    if result.messages_deleted:
        console.print(f"  Messages deleted: {result.messages_deleted}")  # noqa: T201
    if result.cascade_mode:
        console.print(f"  Cascade mode: {result.cascade_mode}")  # noqa: T201


if __name__ == "__main__":
    app()
