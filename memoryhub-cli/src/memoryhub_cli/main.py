"""MemoryHub CLI — terminal interface for centralized agent memory."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer
from memoryhub import CONFIG_FILENAME, ConfigError, load_project_config
from rich.console import Console
from rich.table import Table

from memoryhub_cli.config import get_connection_params, save_config
from memoryhub_cli.project_config import (
    InitChoices,
    LoadingPattern,
    SessionShape,
    build_project_config,
    rewrite_rule_file,
    suggest_pattern,
    write_init_files,
)

app = typer.Typer(
    name="memoryhub",
    help="CLI client for MemoryHub — centralized, governed memory for AI agents.",
    no_args_is_help=True,
)
config_app = typer.Typer(
    name="config",
    help="Manage project-level MemoryHub configuration (.memoryhub.yaml).",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
console = Console()
err_console = Console(stderr=True)


def _get_client():
    """Create a MemoryHubClient from config/env."""
    from memoryhub import MemoryHubClient

    params = get_connection_params()
    missing = [k for k, v in params.items() if not v]
    if missing:
        err_console.print(
            f"[red]Missing configuration: {', '.join(missing)}[/red]\n"
            "Run [bold]memoryhub login[/bold] or set environment variables."
        )
        raise typer.Exit(1)

    return MemoryHubClient(
        url=params["url"],
        auth_url=params["auth_url"],
        client_id=params["client_id"],
        client_secret=params["client_secret"],
    )


def _get_project_id_default() -> str | None:
    """Try to load project_id from .memoryhub.yaml campaigns config.

    Returns the project directory name as the project identifier when
    campaigns are configured, or None when no config/campaigns exist.
    """
    try:
        config = load_project_config()  # auto-discovers .memoryhub.yaml
        if config.memory_loading.campaigns:
            return Path.cwd().name
    except Exception:
        pass
    return None


def _run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


@app.command()
def login(
    url: str = typer.Option(..., prompt="MemoryHub MCP URL", help="MCP server URL"),
    auth_url: str = typer.Option(..., prompt="Auth service URL", help="OAuth 2.1 auth URL"),
    client_id: str = typer.Option(..., prompt="Client ID", help="OAuth client ID"),
    client_secret: str = typer.Option(
        ..., prompt="Client secret", hide_input=True, help="OAuth client secret"
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
        console.print("[green]Connection verified.[/green]")
    except Exception as exc:
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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Search memories using semantic similarity."""
    client = _get_client()
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.search(
                query, scope=scope, max_results=max_results,
                project_id=_project_id, domains=domains or None,
            )

    result = _run(_do())

    if json_output:
        console.print_json(result.model_dump_json())
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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Read a memory by ID."""
    client = _get_client()
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.read(memory_id, project_id=_project_id)

    memory = _run(_do())

    if json_output:
        console.print_json(memory.model_dump_json())
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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Write a new memory.

    Content can be passed as an argument or piped via stdin.
    """
    if content is None:
        if sys.stdin.isatty():
            err_console.print("[red]Provide content as argument or pipe via stdin.[/red]")
            raise typer.Exit(1)
        content = sys.stdin.read().strip()

    if not content:
        err_console.print("[red]Content cannot be empty.[/red]")
        raise typer.Exit(1)

    client = _get_client()
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.write(
                content, scope=scope, weight=weight,
                parent_id=parent_id, branch_type=branch_type,
                project_id=_project_id, domains=domains or None,
            )

    result = _run(_do())

    if json_output:
        console.print_json(result.model_dump_json())
        return

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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Soft-delete a memory and its version chain."""
    if not force:
        confirm = typer.confirm(f"Delete memory {memory_id} and all versions?")
        if not confirm:
            raise typer.Abort()

    client = _get_client()
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.delete(memory_id, project_id=_project_id)

    result = _run(_do())

    if json_output:
        console.print_json(result.model_dump_json())
        return

    console.print(
        f"[green]Deleted:[/green] {result.total_deleted} nodes "
        f"({result.versions_deleted} versions, {result.branches_deleted} branches)"
    )


@app.command()
def history(
    memory_id: str = typer.Argument(..., help="Memory UUID"),
    max_versions: int = typer.Option(20, "--max", "-n", help="Maximum versions to show"),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID for campaign access",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show version history for a memory."""
    client = _get_client()
    _project_id = project_id or _get_project_id_default()

    async def _do():
        async with client:
            return await client.get_history(
                memory_id, max_versions=max_versions,
                project_id=_project_id,
            )

    result = _run(_do())

    if json_output:
        console.print_json(result.model_dump_json())
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
):
    """Walk through project setup and write `.memoryhub.yaml` + the
    generated `.claude/rules/memoryhub-loading.md` rule file."""
    project_dir = project_dir.resolve()
    console.print(f"[bold]Configuring MemoryHub for[/bold] {project_dir}\n")

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
    )
    config = build_project_config(choices)

    try:
        result = write_init_files(config, project_dir, overwrite=force)
    except FileExistsError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

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
):
    """Re-render `.claude/rules/memoryhub-loading.md` from `.memoryhub.yaml`.

    Use this after editing the YAML by hand to refresh the rule file
    without running the interactive prompt again.
    """
    project_dir = project_dir.resolve()
    yaml_path = project_dir / CONFIG_FILENAME
    if not yaml_path.is_file():
        err_console.print(
            f"[red]No {CONFIG_FILENAME} in {project_dir}.[/red]\n"
            "Run [bold]memoryhub config init[/bold] first."
        )
        raise typer.Exit(1)

    try:
        config = load_project_config(yaml_path)
    except ConfigError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    result = rewrite_rule_file(config, project_dir)
    console.print(f"[green]Regenerated {result.rule_path}[/green]")
    if result.legacy_backup is not None:
        console.print(
            f"[yellow]Backed up legacy rule to {result.legacy_backup}.[/yellow]"
        )


if __name__ == "__main__":
    app()
