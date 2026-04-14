"""Admin subcommands for managing agents and OAuth clients."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import typer
from rich.console import Console
from rich.table import Table

from memoryhub_cli.config import CONFIG_DIR, load_config

admin_app = typer.Typer(
    name="admin",
    help="Manage agents and OAuth clients.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


def _get_admin_key() -> str:
    """Resolve the admin key from env var or config file."""
    key = os.environ.get("MEMORYHUB_ADMIN_KEY")
    if key:
        return key

    config = load_config()
    key = config.get("admin_key")
    if key:
        return key

    err_console.print(
        "[red]No admin key found.[/red]\n"
        "Set MEMORYHUB_ADMIN_KEY or add 'admin_key' to "
        "~/.config/memoryhub/config.json."
    )
    raise typer.Exit(1)


def _get_auth_url() -> str:
    """Resolve the auth service base URL (without trailing slash)."""
    url = os.environ.get("MEMORYHUB_AUTH_URL")
    if url:
        return url.rstrip("/")

    config = load_config()
    url = config.get("auth_url")
    if url:
        return url.rstrip("/")

    url = config.get("url")
    if url:
        # Fall back to base MCP URL with /admin stripped — assume auth
        # is co-located at the base URL.
        return url.rstrip("/")

    err_console.print(
        "[red]No auth URL found.[/red]\n"
        "Set MEMORYHUB_AUTH_URL, or add 'auth_url' to "
        "~/.config/memoryhub/config.json."
    )
    raise typer.Exit(1)


def _admin_headers(admin_key: str) -> dict[str, str]:
    return {"X-Admin-Key": admin_key}


# ── Commands ─────────────────────────────────────────────────────────────────


@admin_app.command("create-agent")
def create_agent(
    name: str = typer.Argument(..., help="Agent name (used as client_id and client_name)"),
    scopes: str = typer.Option(
        "user,project",
        "--scopes",
        help="Comma-separated default scopes",
    ),
    project_id: str | None = typer.Option(
        None, "--project-id", "-p", help="Project ID to associate with the agent",
    ),
    tenant_id: str = typer.Option(
        "default", "--tenant-id", "-t", help="Tenant ID",
    ),
    write_config: bool = typer.Option(
        False,
        "--write-config",
        help="Write the client_secret to ~/.config/memoryhub/api-key",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Create a new agent (OAuth client).

    The client_secret is shown only once. Save it immediately.
    """
    admin_key = _get_admin_key()
    auth_url = _get_auth_url()
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

    body = {
        "client_id": name,
        "client_name": name,
        "default_scopes": scope_list,
        "tenant_id": tenant_id,
    }

    async def _do():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{auth_url}/admin/clients",
                json=body,
                headers=_admin_headers(admin_key),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = _run(_do())
    except httpx.HTTPStatusError as exc:
        _handle_http_error(exc)
        return

    if json_output:
        console.print_json(json.dumps(data))
        return

    console.print("[green]Agent created successfully.[/green]\n")
    console.print(f"  Client ID:     [bold]{data['client_id']}[/bold]")
    console.print(f"  Client Name:   {data['client_name']}")
    console.print(f"  Tenant:        {data['tenant_id']}")
    console.print(f"  Scopes:        {', '.join(data['default_scopes'])}")
    console.print(f"  Active:        {data['active']}")
    console.print()
    console.print(
        f"  [yellow bold]Client Secret:   {data['client_secret']}[/yellow bold]"
    )
    console.print(
        "\n  [dim]Save this secret now. It will not be shown again.[/dim]"
    )

    if write_config:
        api_key_path = CONFIG_DIR / "api-key"
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        api_key_path.write_text(data["client_secret"])
        api_key_path.chmod(0o600)
        console.print(f"\n  [green]Secret written to {api_key_path}[/green]")


@admin_app.command("list-agents")
def list_agents(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List all registered agents (OAuth clients)."""
    admin_key = _get_admin_key()
    auth_url = _get_auth_url()

    async def _do():
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{auth_url}/admin/clients",
                headers=_admin_headers(admin_key),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = _run(_do())
    except httpx.HTTPStatusError as exc:
        _handle_http_error(exc)
        return

    if json_output:
        console.print_json(json.dumps(data))
        return

    if not data:
        console.print("[dim]No agents registered.[/dim]")
        return

    table = Table(title="Registered Agents")
    table.add_column("Client ID", style="bold")
    table.add_column("Name")
    table.add_column("Active", justify="center")
    table.add_column("Scopes")
    table.add_column("Created", style="dim")

    for agent in data:
        active = "[green]Yes[/green]" if agent.get("active") else "[red]No[/red]"
        scopes = ", ".join(agent.get("default_scopes", []))
        created = str(agent.get("created_at", "-"))[:19]
        table.add_row(
            agent["client_id"],
            agent.get("client_name", "-"),
            active,
            scopes,
            created,
        )

    console.print(table)


@admin_app.command("rotate-secret")
def rotate_secret(
    client_id: str = typer.Argument(..., help="Client ID of the agent"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Rotate the client secret for an agent.

    The new secret is shown only once. Save it immediately.
    """
    admin_key = _get_admin_key()
    auth_url = _get_auth_url()

    async def _do():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{auth_url}/admin/clients/{client_id}/rotate-secret",
                headers=_admin_headers(admin_key),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = _run(_do())
    except httpx.HTTPStatusError as exc:
        _handle_http_error(exc)
        return

    if json_output:
        console.print_json(json.dumps(data))
        return

    console.print(f"[green]Secret rotated for {data['client_id']}.[/green]\n")
    console.print(
        f"  [yellow bold]New Secret:   {data['client_secret']}[/yellow bold]"
    )
    console.print(
        "\n  [dim]Save this secret now. It will not be shown again.[/dim]"
    )


@admin_app.command("disable-agent")
def disable_agent(
    client_id: str = typer.Argument(..., help="Client ID of the agent to disable"),
):
    """Disable an agent (set active=false)."""
    admin_key = _get_admin_key()
    auth_url = _get_auth_url()

    async def _do():
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{auth_url}/admin/clients/{client_id}",
                json={"active": False},
                headers=_admin_headers(admin_key),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = _run(_do())
    except httpx.HTTPStatusError as exc:
        _handle_http_error(exc)
        return

    console.print(
        f"[green]Agent '{data['client_id']}' has been disabled.[/green]"
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _handle_http_error(exc: httpx.HTTPStatusError) -> None:
    """Print a user-friendly error for HTTP failures."""
    status = exc.response.status_code
    try:
        detail = exc.response.json().get("detail", exc.response.text)
    except Exception:
        detail = exc.response.text

    if status == 401:
        err_console.print(
            "[red]Authentication failed.[/red] Check your admin key."
        )
    elif status == 404:
        err_console.print(f"[red]Not found:[/red] {detail}")
    elif status == 409:
        err_console.print(f"[red]Conflict:[/red] {detail}")
    else:
        err_console.print(f"[red]HTTP {status}:[/red] {detail}")

    raise typer.Exit(1)
