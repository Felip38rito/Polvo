"""Commands for managing Polvo tiers.

Tiers are model specifications tied to a provider.
The system supports 4 adaptive tiers (mini, air, pro, ultra) and any number of extra tiers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .setup import config_path
from model_router.models import ADAPTIVE_TIERS

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
    """List all configured tiers."""
    data = _load_config()
    tiers = data.get("tiers") or {}
    
    if not tiers:
        console.print("[yellow]No tiers configured. Run 'polvo setup tier' to add some.[/yellow]")
        return

    table = Table(title="Polvo Tiers")
    table.add_column("Key", style="bold")
    table.add_column("Name")
    table.add_column("Model ID")
    table.add_column("Provider")
    table.add_column("Type")

    for key, spec in tiers.items():
        if not isinstance(spec, dict):
            continue
        t_type = "adaptive" if key in ADAPTIVE_TIERS else "extra"
        table.add_row(
            str(key),
            str(spec.get("name", "")),
            str(spec.get("model", "")),
            str(spec.get("provider", "")),
            t_type,
        )
    
    console.print(table)

def set(
    tier_key: str = typer.Argument(..., help="Tier key (e.g. 'mini', 'pro', or a custom name)"),
    model: str = typer.Option(..., "--model", "-m", help="The upstream model ID"),
    provider: str = typer.Option(..., "--provider", "-p", help="The name of the configured provider"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional display name for this tier"),
    reasoning_effort: str | None = typer.Option(None, "--effort", "-e", help="Reasoning effort (e.g. 'medium', 'high')"),
):
    """Configure or update a specific tier."""
    data = _load_config()
    providers = data.get("providers") or {}
    
    if provider not in providers:
        err_console.print(f"[red]Error: Provider '{provider}' not found.[/red]")
        err_console.print("Run 'polvo provider list' to see available providers.")
        raise typer.Exit(code=1)

    tiers = data.get("tiers") or {}
    
    # Prepare spec
    spec = {
        "model": model,
        "provider": provider,
        "name": name,
    }
    
    # Handle extra_params (reasoning_effort is the most common)
    extra_params = {}
    if reasoning_effort:
        extra_params["reasoning_effort"] = reasoning_effort
    
    if extra_params:
        spec["extra_params"] = extra_params
        
    # Clean None values
    spec = {k: v for k, v in spec.items() if v is not None}
    
    tiers[tier_key] = spec
    data["tiers"] = tiers
    _save_config(data)
    
    t_type = "adaptive" if tier_key in ADAPTIVE_TIERS else "extra"
    console.print(f"[green]✅ {t_type.capitalize()} tier '{tier_key}' configured successfully.[/green]")
