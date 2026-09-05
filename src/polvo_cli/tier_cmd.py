"""Commands for managing Polvo models (adaptive tiers + custom models).

Adaptive tiers are the fixed axis (mini, air, pro, ultra) — the classifier
only ever picks among these. Custom models are any extra models the user
wants available; they route by explicit id but are never chosen by the
classifier.
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
        return {"providers": {}, "adaptive": {}, "custom": {}}
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {"providers": {}, "adaptive": {}, "custom": {}}
    except yaml.YAMLError:
        return {"providers": {}, "adaptive": {}, "custom": {}}


def _save_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def list():
    """List all configured models (adaptive + custom)."""
    data = _load_config()
    adaptive = data.get("adaptive") or {}
    custom = data.get("custom") or {}

    if not adaptive and not custom:
        console.print("[yellow]No models configured. Run 'polvo tier' to add some.[/yellow]")
        return

    table = Table(title="Polvo Models")
    table.add_column("Key", style="bold")
    table.add_column("Name")
    table.add_column("Model ID")
    table.add_column("Provider")
    table.add_column("Type")

    for key, spec in adaptive.items():
        if not isinstance(spec, dict):
            continue
        table.add_row(
            str(key),
            str(spec.get("name", "")),
            str(spec.get("model", "")),
            str(spec.get("provider", "")),
            "adaptive",
        )
    for key, spec in custom.items():
        if not isinstance(spec, dict):
            continue
        table.add_row(
            str(key),
            str(spec.get("name", "")),
            str(spec.get("model", "")),
            str(spec.get("provider", "")),
            "custom",
        )

    console.print(table)


def set(
    tier_key: str | None = typer.Argument(None, help="Model key (adaptive: mini/air/pro/ultra, or a custom name)"),
    model: str | None = typer.Option(None, "--model", "-m", help="The upstream model ID"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="The name of the configured provider"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional display name for this model"),
    effort: str | None = typer.Option(None, "--effort", "-e", help="Reasoning effort (e.g. 'medium', 'high')"),
):
    """Configure or update a model (adaptive tier or custom)."""
    if tier_key is None or model is None or provider is None:
        err_console.print("[red]Usage: polvo tier set <key> --model <id> --provider <name>[/red]")
        err_console.print("Example: polvo tier set pro --model deepseek-v4-pro --provider 'Ollama Cloud'")
        err_console.print("Example: polvo tier set meu-modelo --model some-id --provider 'Ollama Cloud'")
        raise typer.Exit(code=1)

    data = _load_config()
    providers = data.get("providers") or {}

    if provider not in providers:
        err_console.print(f"[red]Error: Provider '{provider}' not found.[/red]")
        err_console.print("Run 'polvo provider list' to see available providers.")
        raise typer.Exit(code=1)

    spec = {"model": model, "provider": provider, "name": name}

    extra_params = {}
    if effort:
        extra_params["reasoning_effort"] = effort
    if extra_params:
        spec["extra_params"] = extra_params

    spec = {k: v for k, v in spec.items() if v is not None}

    if tier_key in ADAPTIVE_TIERS:
        adaptive = data.get("adaptive") or {}
        adaptive[tier_key] = spec
        data["adaptive"] = adaptive
        _save_config(data)
        console.print(f"[green]✅ Adaptive tier '{tier_key}' configured successfully.[/green]")
    else:
        custom = data.get("custom") or {}
        custom[tier_key] = spec
        data["custom"] = custom
        _save_config(data)
        console.print(f"[green]✅ Custom model '{tier_key}' configured successfully.[/green]")
