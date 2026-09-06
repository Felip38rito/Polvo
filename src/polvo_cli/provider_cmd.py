"""Commands for managing Polvo providers.

Providers are upstream OpenAI-compatible endpoints (base_url + API key).
Tiers reference providers by name.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import core
from .validate import provider_in_use

console = Console()
err_console = Console(stderr=True)


def _prompt_add_provider(data: dict, providers: dict) -> None:
    """Prompt for one provider and save it (shared by wizard + onboarding).

    The API key is masked on input and stored in ~/.polvo/.env under an env
    var derived from the provider name — never inline in config.yml.
    """
    name = core.required_prompt("Provider name")
    url = core.required_prompt("Base URL (e.g. https://api.provider.com/v1)")
    key = core.required_prompt("API key (input hidden)", password=True)

    var = core.env_var_name_for(name)
    core.save_env_key(var, key)

    spec = {"base_url": url.rstrip("/"), "api_key_env": var}
    providers[name] = spec
    data["providers"] = providers
    core.save_config(data)
    console.print(f"[green]✅ Provider '{name}' saved.[/green]")
    console.print(f"[dim]Key stored in {core.env_path()} as {var}.[/dim]")


def add_first_provider() -> None:
    """Onboarding entry: add the first provider directly (no action menu)."""
    data = core.load_config()
    providers = data.get("providers") or {}
    _prompt_add_provider(data, providers)


def setup_provider() -> None:
    """Wizard for configuring providers."""
    console.print(Panel("[bold cyan]Provider Setup[/bold cyan]\nManage your upstream OpenAI-compatible endpoints."))

    data = core.load_config()
    providers = data.get("providers") or {}

    while True:
        action = Prompt.ask(
            "Action (add/list/remove/done)",
            choices=["add", "list", "remove", "done"],
            default="list",
        )

        if action == "done":
            break
        elif action == "list":
            if not providers:
                console.print("[yellow]No providers configured yet.[/yellow]")
            else:
                for name, spec in providers.items():
                    key_type = "inline" if spec.get("api_key") else "env var"
                    console.print(f"• [bold]{name}[/bold]: {spec.get('base_url')} ({key_type})")
        elif action == "add":
            _prompt_add_provider(data, providers)
        elif action == "remove":
            name = Prompt.ask("Provider name to remove")
            if name in providers:
                if provider_in_use(data, name):
                    console.print(f"[red]Cannot remove '{name}': it is used by one or more models.[/red]")
                else:
                    del providers[name]
                    data["providers"] = providers
                    core.save_config(data)
                    console.print(f"[green]✅ Provider '{name}' removed.[/green]")
            else:
                console.print(f"[red]Provider '{name}' not found.[/red]")


def list_providers() -> None:
    """List all configured providers."""
    data = core.load_config()
    providers = data.get("providers") or {}

    if not providers:
        console.print("[yellow]No providers configured. Run 'polvo provider' to add one.[/yellow]")
        return

    table = Table(title="Polvo Providers")
    table.add_column("Name", style="bold")
    table.add_column("Base URL")
    table.add_column("Key Type")

    for name, spec in providers.items():
        key_type = "inline" if spec.get("api_key") else "env var"
        table.add_row(name, spec.get("base_url", ""), key_type)

    console.print(table)


def add(
    name: str = typer.Argument(..., help="Unique name for the provider (e.g. 'Cloud Provider')"),
    base_url: str = typer.Option(..., "--url", "-u", help="The OpenAI-compatible base URL"),
    api_key: str | None = typer.Option(None, "--key", "-k", help="API key (stored inline)"),
    api_key_env: str | None = typer.Option(None, "--env", "-e", help="Env var holding the API key"),
) -> None:
    """Add or update a provider endpoint."""
    if not api_key and not api_key_env:
        err_console.print("[red]Error: You must provide either --key or --env.[/red]")
        raise typer.Exit(code=1)

    if api_key and api_key_env:
        err_console.print("[red]Error: Provide either --key OR --env, not both.[/red]")
        raise typer.Exit(code=1)

    data = core.load_config()
    providers = data.get("providers") or {}

    providers[name] = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "api_key_env": api_key_env,
    }
    # Clean up None values to keep YAML tidy
    providers[name] = {k: v for k, v in providers[name].items() if v is not None}

    data["providers"] = providers
    core.save_config(data)
    console.print(f"[green]✅ Provider '{name}' configured successfully.[/green]")


def remove(
    name: str = typer.Argument(..., help="Name of the provider to remove"),
) -> None:
    """Remove a provider endpoint."""
    data = core.load_config()
    providers = data.get("providers") or {}

    if name not in providers:
        err_console.print(f"[red]Error: Provider '{name}' not found.[/red]")
        raise typer.Exit(code=1)

    if provider_in_use(data, name):
        err_console.print(f"[red]Error: Provider '{name}' is in use. Reassign models first.[/red]")
        raise typer.Exit(code=1)

    del providers[name]
    data["providers"] = providers
    core.save_config(data)
    console.print(f"[green]✅ Provider '{name}' removed.[/green]")