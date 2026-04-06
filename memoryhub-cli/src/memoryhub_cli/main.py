"""MemoryHub CLI — terminal interface for centralized agent memory."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from memoryhub_cli.config import get_connection_params, save_config

app = typer.Typer(
    name="memoryhub",
    help="CLI client for MemoryHub — centralized, governed memory for AI agents.",
    no_args_is_help=True,
)
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
    scope: Optional[str] = typer.Option(None, "--scope", "-s", help="Filter by scope"),
    max_results: int = typer.Option(10, "--max", "-n", help="Maximum results"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Search memories using semantic similarity."""
    client = _get_client()

    async def _do():
        async with client:
            return await client.search(
                query, scope=scope, max_results=max_results,
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
    console.print(f"[dim]{len(result.results)} of {result.total_accessible} accessible[/dim]")


@app.command()
def read(
    memory_id: str = typer.Argument(..., help="Memory UUID"),
    depth: int = typer.Option(0, "--depth", "-d", help="Branch depth to load"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Read a memory by ID."""
    client = _get_client()

    async def _do():
        async with client:
            return await client.read(memory_id, depth=depth)

    memory = _run(_do())

    if json_output:
        console.print_json(memory.model_dump_json())
        return

    console.print(f"[bold]{memory.scope}[/bold] | v{memory.version} | weight {memory.weight:.2f}")
    console.print(f"[dim]ID: {memory.id}[/dim]")
    console.print(f"[dim]Owner: {memory.owner_id}[/dim]")
    console.print()
    console.print(memory.content)

    if memory.branches:
        console.print(f"\n[bold]Branches ({len(memory.branches)}):[/bold]")
        for branch in memory.branches:
            console.print(
                f"  [{branch.branch_type or 'child'}] {branch.stub or branch.content[:60]}"
            )


@app.command()
def write(
    content: str = typer.Argument(None, help="Memory content (reads from stdin if omitted)"),
    scope: str = typer.Option("user", "--scope", "-s", help="Memory scope"),
    weight: float = typer.Option(0.7, "--weight", "-w", help="Priority weight 0.0-1.0"),
    parent_id: Optional[str] = typer.Option(None, "--parent", help="Parent memory ID"),
    branch_type: Optional[str] = typer.Option(None, "--branch-type", help="Branch type"),
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

    async def _do():
        async with client:
            return await client.write(
                content, scope=scope, weight=weight,
                parent_id=parent_id, branch_type=branch_type,
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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Soft-delete a memory and its version chain."""
    if not force:
        confirm = typer.confirm(f"Delete memory {memory_id} and all versions?")
        if not confirm:
            raise typer.Abort()

    client = _get_client()

    async def _do():
        async with client:
            return await client.delete(memory_id)

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
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Show version history for a memory."""
    client = _get_client()

    async def _do():
        async with client:
            return await client.get_history(memory_id, max_versions=max_versions)

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


if __name__ == "__main__":
    app()
