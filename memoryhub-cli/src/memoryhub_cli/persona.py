"""Persona subcommands — WRIG-1483.

Standing profile management for MemoryHub users.

Commands:
  memoryhub persona compile  --user <id>            Compile/refresh the profile
  memoryhub persona show     --user <id>            Display the current profile
  memoryhub persona status   --user <id>            Staleness, fact count, version
  memoryhub persona edit     --user <id>            Add a user-declared pinned fact
"""

from __future__ import annotations

import asyncio

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from memoryhub_cli.config import get_api_key, get_server_url
from memoryhub_cli.output import (
    EXIT_CLIENT_ERROR,
    EXIT_SERVER_ERROR,
    OutputFormat,
    console,
    handle_error,
    json_success,
)

persona_app = typer.Typer(
    name="persona",
    help="Standing profile compilation and management.",
    no_args_is_help=True,
)


def _run(coro):
    return asyncio.run(coro)


def _get_client(output: OutputFormat):
    from memoryhub import MemoryHubClient

    api_key = get_api_key()
    url = get_server_url()
    if not api_key or not url:
        handle_error(
            "missing_config",
            "API key and server URL are required. Run 'memoryhub login' or set "
            "MEMORYHUB_API_KEY and MEMORYHUB_URL.",
            output,
            EXIT_CLIENT_ERROR,
        )
    return MemoryHubClient(url=url, api_key=api_key)


def _stale_badge(is_stale: bool) -> str:
    return "[yellow bold][STALE][/yellow bold]" if is_stale else "[green]✓ current[/green]"


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


@persona_app.command("compile")
def compile_cmd(
    user_id: str = typer.Option(..., "--user", "-u", help="User ID to compile persona for."),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Scope to a project."),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o"),
) -> None:
    """Compile a standing persona profile from behavioral dreaming facts.

    Reads all current scope=user, source=dreaming, content_type=behavioral nodes,
    calls the LLM to synthesize a ≤400-token profile, stores it as a versioned
    synopsis node (weight=1.0). User-declared pins are preserved across recompiles.

    Requires MEMORYHUB_CONV_EXTRACTION_MODEL and MEMORYHUB_CONV_EXTRACTION_MODEL_URL.
    """
    async def _do():
        client = _get_client(output)
        async with client:
            try:
                return await client._call(
                    "compile_persona",
                    {"user_id": user_id, "project_id": project_id},
                )
            except Exception as exc:
                handle_error("compile_failed", str(exc), output, EXIT_SERVER_ERROR)

    result = _run(_do())
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result)
        return

    console.print(
        Panel(
            Markdown(result.get("content", "(no content)")),
            title=(
                f"[bold green]Persona Synopsis v{result.get('version', '?')}[/bold green]"
                f" — {user_id}"
            ),
            subtitle=(
                f"node={result.get('synopsis_id', '?')[:8]}… · "
                f"{result.get('source_fact_count', 0)} facts · "
                f"{result.get('pin_count', 0)} pins"
            ),
            border_style="green",
        )
    )
    if result.get("previous_synopsis_id"):
        console.print(
            f"[dim]Previous synopsis v{result.get('version', 1) - 1} retired: "
            f"{result['previous_synopsis_id'][:8]}…[/dim]"
        )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@persona_app.command("show")
def show_cmd(
    user_id: str = typer.Option(..., "--user", "-u", help="User ID to show persona for."),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Scope to a project."),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o"),
) -> None:
    """Show the current compiled persona synopsis.

    Profiles always load first at session start, before search results.
    When the profile is stale (new dreaming facts since last compile),
    a warning is shown. Use 'persona compile' to refresh.
    """
    async def _do():
        client = _get_client(output)
        async with client:
            try:
                return await client._call(
                    "get_persona",
                    {"user_id": user_id, "project_id": project_id},
                )
            except Exception as exc:
                handle_error("fetch_failed", str(exc), output, EXIT_SERVER_ERROR)

    result = _run(_do())
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result)
        return

    synopsis = result.get("synopsis")

    if output == OutputFormat.compact:
        if synopsis is None:
            return
        proj_attr = f' project="{project_id}"' if project_id else ""
        user_attr = f' user="{user_id}"'
        stale_attr = ' stale="true"' if result.get("is_stale") else ""
        print(f"<memoryhub-persona{user_attr}{proj_attr}{stale_attr}>")  # noqa: T201
        print(synopsis.get("content", ""))  # noqa: T201
        print("</memoryhub-persona>")  # noqa: T201
        return

    if synopsis is None:
        console.print(
            f"[yellow]No persona synopsis found for {user_id}.[/yellow]\n"
            f"Run: [bold]memoryhub persona compile --user {user_id}[/bold]"
        )
        return

    is_stale = result.get("is_stale", False)
    title = (
        f"[bold blue]Persona Synopsis v{synopsis.get('version', '?')}[/bold blue]"
        f" — {user_id}  {_stale_badge(is_stale)}"
    )
    subtitle = (
        f"node={synopsis.get('id', '?')[:8]}… · "
        f"compiled {synopsis.get('updated_at', 'unknown')[:10]} · "
        f"{result.get('compiled_fact_count', '?')} facts / {result.get('source_fact_count', '?')} current"
    )
    console.print(Panel(Markdown(synopsis.get("content", "(no content)")), title=title, subtitle=subtitle, border_style="blue"))

    if is_stale:
        console.print(
            "[yellow]Profile is stale — new behavioral facts have been extracted "
            "since the last compile.[/yellow]\n"
            f"Run: [bold]memoryhub persona compile --user {user_id}[/bold]"
        )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@persona_app.command("status")
def status_cmd(
    user_id: str = typer.Option(..., "--user", "-u", help="User ID to check."),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Scope to a project."),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o"),
) -> None:
    """Show persona compilation status: fact count, staleness, version, last compiled."""
    async def _do():
        client = _get_client(output)
        async with client:
            try:
                return await client._call(
                    "get_persona",
                    {"user_id": user_id, "project_id": project_id},
                )
            except Exception as exc:
                handle_error("fetch_failed", str(exc), output, EXIT_SERVER_ERROR)

    result = _run(_do())
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result)
        return

    synopsis = result.get("synopsis")
    is_stale = result.get("is_stale", True)
    source_count = result.get("source_fact_count", 0)
    compiled_count = result.get("compiled_fact_count")

    table = Table(title=f"Persona Status — {user_id}", show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")

    if synopsis:
        table.add_row("Synopsis ID", f"{synopsis.get('id', '?')[:12]}…")
        table.add_row("Version", str(synopsis.get("version", "?")))
        table.add_row("Last compiled", synopsis.get("updated_at", "unknown")[:19].replace("T", " "))
        table.add_row("Compiled from", f"{compiled_count} fact(s)")
    else:
        table.add_row("Synopsis", "[dim]none — run 'persona compile' first[/dim]")

    table.add_row("Current facts", f"{source_count} behavioral dreaming fact(s)")
    table.add_row("Status", _stale_badge(is_stale))

    if is_stale and result.get("stale_reason"):
        table.add_row("Stale reason", result["stale_reason"])

    console.print(table)

    if is_stale:
        console.print(
            f"\n[yellow]Run:[/yellow] [bold]memoryhub persona compile --user {user_id}[/bold]"
        )


# ---------------------------------------------------------------------------
# edit (add user-declared pin)
# ---------------------------------------------------------------------------


@persona_app.command("edit")
def edit_cmd(
    user_id: str = typer.Option(..., "--user", "-u", help="User ID to add a pin for."),
    fact: str = typer.Option(
        ..., "--fact", "-f",
        help=(
            "A user-declared fact that will be pinned permanently in all future "
            "persona compilations. Example: 'I now prefer Rust over Python for systems code.'"
        ),
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o"),
) -> None:
    """Add a user-declared fact that survives persona recompilation.

    Pinned facts are labeled [PINNED] in the compiler prompt and override
    any conflicting inferred facts. Use for preferences the user has explicitly
    stated ("I've switched to X", "I always prefer Y").

    After pinning, run 'persona compile' to incorporate it immediately.
    """
    async def _do():
        client = _get_client(output)
        async with client:
            try:
                return await client._call(
                    "edit_persona",
                    {"action": "add_pin", "user_id": user_id, "content": fact},
                )
            except Exception as exc:
                handle_error("edit_failed", str(exc), output, EXIT_SERVER_ERROR)

    result = _run(_do())
    if result is None:
        return

    if output == OutputFormat.json:
        json_success(result)
        return

    console.print(f"[green]Pin stored:[/green] {result.get('content', fact)}")
    console.print(
        f"[dim]Pin ID: {result.get('pin_id', '?')[:12]}… · "
        f"Run [bold]memoryhub persona compile --user {user_id}[/bold] to apply.[/dim]"
    )
