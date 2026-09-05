"""Commands for managing Polvo providers.

Providers are upstream OpenAI-compatible endpoints (base_url + API key).
Tiers reference providers by name.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .setup import config_path

console = Console()
err_console = Console(stderr=True)

def _load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"providers": {}, "tiers": {}}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {"providers": {}, "tiers": {}}
    except yaml.YAMLError:
        return {"providers": {}, "tiers": {}}

def _save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))

def list():
    """List all configured providers."""
    data = _load_config()
    providers = data.get("providers") or {}
    
    if not providers:
        console.print("[yellow]No providers configured. Run 'polvo setup provider' to add one.[/yellow]")
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
    name: str = typer.Argument(..., help="Unique name for the provider (e.g. 'Ollama Cloud')"),
    base_url: str = typer.Option(..., "--url", "-u", help="The OpenAI-compatible base URL"),
    api_key: str | None = typer.Option(None, "--key", "-k", help="API key (stored inline)"),
    api_key_env: str | None = typer.Option(None, "--env", "-e", help="Env var holding the API key"),
):
    """Add or update a provider endpoint."""
    if not api_key and not api_key_env:
        err_console.print("[red]Error: You must provide either --key or --env.[/red]")
        raise typer.Exit(code=1)
    
    if api_key and api_key_env:
        err_console.print("[red]Error: Provide either --key OR --env, not both.[/red]")
        raise typer.Exit(code=1)

    data = _load_config()
    providers = data.get("providers") or {}
    
    providers[name] = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "api_key_env": api_key_env,
    }
    # Clean up None values to keep YAML tidy
    providers[name] = {k: v for k, v in providers[name].items() if v is not None}
    
    data["providers"] = providers
    _save_config(data)
    console.print(f"[green]✅ Provider '{name}' configured successfully.[/green]")

def remove(
    name: str = typer.Argument(..., help="Name of the provider to remove"),
):
    """Remove a provider endpoint."""
    data = _load_config()
    providers = data.get("providers") or {}
    tiers = data.get("tiers") or {}

    if name not in providers:
        err_console.print(f"[red]Error: Provider '{name}' not found.[/red]")
        raise typer.Exit(code=1)

    # Check if provider is in use by any tier or the classifier
    in_use = False
    for tier_key, spec in tiers.items():
        if isinstance(spec, dict) and spec.get("provider") == name:
            in_use = True
            break
    
    classifier = data.get("classifier") or {}
    if classifier.get("provider") == name:
        in_use = True

    if in_use:
        err_console.print(f"[red]Error: Provider '{name}' is in use. Reassign tiers first.[/red]")
        raise typer.Exit(code=1)

    del providers[name]
    data["providers"] = providers
    _save_config(data)
    console.print(f"[green]✅ Provider '{name}' removed.[/green]")
