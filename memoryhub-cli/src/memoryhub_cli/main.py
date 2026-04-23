"""MemoryHub CLI — terminal interface for centralized agent memory."""

from __future__ import annotations

import asyncio
import json
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

import typer
from memoryhub import CONFIG_FILENAME, ConfigError, load_project_config
from memoryhub.exceptions import (
    AuthenticationError,
    ConnectionFailedError,
    ConflictError,
    CurationVetoError,
    MemoryHubError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
from rich.table import Table

from memoryhub_cli.admin import admin_app
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
from memoryhub_cli.config import get_connection_params, save_config
from memoryhub_cli.project_config import (
    FocusSource,
    InitChoices,
    LoadingPattern,
    SessionShape,
    build_project_config,
    rewrite_rule_file,
    suggest_pattern,
    write_init_files,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"memoryhub {pkg_version('memoryhub-cli')}")
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


config_app = typer.Typer(
    name="config",
    help="Manage project-level MemoryHub configuration (.memoryhub.yaml).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(admin_app, name="admin", help="Manage agents and OAuth clients")

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


def _get_client(output: OutputFormat = OutputFormat.table):
    """Create a MemoryHubClient from config/env."""
    from memoryhub import MemoryHubClient

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
        console.print("[green]Configuration saved.[/green]")

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
            console.print("[green]Connection verified.[/green]")
    except Exception as exc:
        if output == OutputFormat.json:
            json_success({"saved": True, "connection": "failed", "warning": str(exc)})
        elif output == OutputFormat.table:
            err_console.print(f"[yellow]Warning: connection test failed: {exc}[/yellow]")
            err_console.print("Credentials saved anyway. Check URL and credentials.")


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
    output: OutputFormat = typer.Option(
        OutputFormat.table, "--output", "-o", help="Output format: table, json, quiet",
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
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if not result.results:
        console.print("[dim]No results found.[/dim]")
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

    console.print(table)
    more = " (more available)" if result.has_more else ""
    console.print(
        f"[dim]{len(result.results)} of {result.total_matching} matching{more}[/dim]"
    )


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

    console.print(f"[bold]{memory.scope}[/bold] | v{memory.version} | weight {memory.weight:.2f}")
    console.print(f"[dim]ID: {memory.id}[/dim]")
    console.print(f"[dim]Owner: {memory.owner_id}[/dim]")
    console.print()
    console.print(memory.content)

    if memory.branch_count:
        console.print(
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
            )

    result = _run_command(_do(), output)

    if output == OutputFormat.json:
        json_success(result.model_dump())
        return
    if output == OutputFormat.quiet:
        return

    if result.curation.gated:
        err_console.print("[yellow]Write gated by curation.[/yellow]")
        err_console.print(f"  Reason: {result.curation.reason}")
        if result.curation.existing_memory_id:
            err_console.print(f"  Existing: {result.curation.existing_memory_id}")
        if result.curation.recommendation:
            err_console.print(f"  Recommendation: {result.curation.recommendation}")
        raise typer.Exit(EXIT_CLIENT_ERROR)

    mem = result.memory
    console.print(f"[green]Memory created:[/green] {mem.id}")
    console.print(f"  Scope: {mem.scope} | Weight: {mem.weight:.2f} | Version: {mem.version}")
    if result.curation.blocked:
        console.print("[yellow]Note: curation pipeline blocked this write.[/yellow]")
    elif result.curation.similar_count > 0:
        console.print(
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

    console.print(
        f"[green]Deleted:[/green] {result.total_deleted} nodes "
        f"({result.versions_deleted} versions, {result.branches_deleted} branches)"
    )


@app.command()
def update(
    memory_id: str = typer.Argument(..., help="Memory UUID to update"),
    content: str | None = typer.Argument(None, help="New content (reads from stdin if omitted and stdin is not a tty)"),
    weight: float | None = typer.Option(None, "--weight", "-w", help="New priority weight 0.0-1.0"),
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

    console.print(f"[green]Memory updated:[/green] {memory.id}")
    console.print(f"  Scope: {memory.scope} | Weight: {memory.weight:.2f} | Version: {memory.version}")


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
        console.print("[dim]No version history found.[/dim]")
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

    console.print(table)
    if result.has_more:
        console.print(
            f"[dim]Showing {len(result.versions)} of {result.total_versions} versions[/dim]"
        )


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
        console.print(prompt_text)
        raw = typer.prompt(f"Choice [{default}]", default=str(default), show_default=False)
        try:
            value = int(raw)
        except ValueError:
            err_console.print(f"[red]Not a number: {raw}[/red]")
            continue
        if value in choices:
            return value
        err_console.print(
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
):
    """Walk through project setup and write `.memoryhub.yaml` + the
    generated `.claude/rules/memoryhub-loading.md` rule file."""
    project_dir = project_dir.resolve()
    console.print(f"[bold]Configuring MemoryHub for[/bold] {project_dir}\n")

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
            console.print(f"\n{blurb}\n")
            keep_contradictions = typer.confirm(
                "Enable cross-domain contradiction detection?",
                default=False,
            )

        # ── Campaign enrollment ──
        console.print(
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

    try:
        result = write_init_files(config, project_dir, overwrite=force)
    except FileExistsError as exc:
        handle_error("file_exists", str(exc), output, EXIT_CLIENT_ERROR)

    if output == OutputFormat.json:
        json_success({
            "yaml_path": str(result.yaml_path),
            "rule_path": str(result.rule_path),
            "legacy_backup": str(result.legacy_backup) if result.legacy_backup else None,
        })
        return
    if output == OutputFormat.quiet:
        return

    console.print(f"\n[green]Wrote {result.yaml_path}[/green]")
    console.print(f"[green]Wrote {result.rule_path}[/green]")
    if result.legacy_backup is not None:
        console.print(
            f"[yellow]Backed up legacy rule to {result.legacy_backup}.[/yellow]\n"
            f"Review and delete the .bak when you're satisfied with the new rule."
        )

    # ── Summary ──
    mode_label = {"focused": "focused", "broad": "broad", "adaptive": "focused"}[shape]
    if shape == "adaptive":
        mode_explanation = f"mode={mode_label} + {pattern}"
    else:
        mode_explanation = f"mode={mode_label}"
    console.print("\n[bold]Summary[/bold]")
    console.print(f"  Session shape: {shape} ({mode_explanation})")
    console.print(f"  Loading: {pattern}")
    console.print(f"  Focus source: {focus_source}")
    cross = "on" if keep_contradictions else "off"
    console.print(f"  Cross-domain contradictions: {cross}")
    if campaigns:
        console.print(f"  Campaigns: {', '.join(campaigns)}")
    if project:
        console.print(f"  Project: {project}")

    # ── #153: API key check ──
    api_key_path = Path.home() / ".config" / "memoryhub" / "api-key"
    if api_key_path.exists():
        console.print(f"\n[green]API key found at {api_key_path}[/green]")
    else:
        console.print(
            f"\n[yellow]Warning:[/yellow] No API key at {api_key_path}\n"
            "  Create this file with your MemoryHub API key before using\n"
            "  the agent. Ask your administrator for a key."
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
    console.print(f"[green]Regenerated {result.rule_path}[/green]")
    if result.legacy_backup is not None:
        console.print(
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

    console.print(
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
        console.print("[dim]No relationships found.[/dim]")
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

    console.print(table)


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
        console.print("[dim]No similar memories found.[/dim]")
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

    console.print(table)


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
    console.print(f"[green]Contradiction reported for[/green] {memory_id[:12]}")
    console.print(f"  Count: {result.contradiction_count} / {result.threshold} threshold")
    console.print(f"  Revision triggered: {triggered}")


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

    console.print(f"[green]Contradiction {contradiction_id[:12]} resolved:[/green] {action}")


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
    console.print(f"[green]Rule {verb}:[/green] {name}")
    console.print(f"  Tier: {rule.tier} | Action: {rule.action} | Priority: {rule.priority} | {enabled_label}")


# ── memoryhub project ─────────────────────────────────────────────────────────


@project_app.command("list")
def project_list(
    filter: str = typer.Option("mine", "--filter", "-f", help='"mine" (default) or "all"'),
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
        console.print("[dim]No projects found.[/dim]")
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

    console.print(table)


@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: str | None = typer.Option(None, "--description", help="Optional description"),
    invite_only: bool = typer.Option(False, "--invite-only", help="Restrict membership to invites"),
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

    console.print(f"[green]Project created:[/green] {name}")
    if description:
        console.print(f"  Description: {description}")
    policy = "invite-only" if invite_only else "open"
    console.print(f"  Policy: {policy}")


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

    console.print(f"[green]Added[/green] {user_id} to {project_name} as {role}")


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

    console.print(f"[green]Removed[/green] {user_id} from {project_name}")


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
    projects = [p.get("project_id", p) if isinstance(p, dict) else p for p in result.get("projects", [])]

    console.print(f"Session: {user_id} ({name})")
    console.print(f"  Scopes: {', '.join(scopes) if scopes else '-'}")
    console.print(f"  Expires: {expires_at}")
    console.print(f"  Projects: {', '.join(projects) if projects else '-'}")


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

    console.print(f"Focus set: {focus_text} (project: {project})")


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
        console.print("[dim]No focus history found.[/dim]")
    else:
        table = Table(title=f"Focus History: {project}")
        table.add_column("Focus", style="cyan")
        table.add_column("Count", justify="right")

        for entry in histogram:
            table.add_row(entry.get("focus", "-"), str(entry.get("count", 0)))

        console.print(table)

    console.print(f"[dim]Total sessions: {total}[/dim]")


if __name__ == "__main__":
    app()
