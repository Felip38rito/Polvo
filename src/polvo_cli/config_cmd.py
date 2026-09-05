"""Config management commands for the polvo CLI.

View and modify the router config without re-running setup.
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
# Console that writes to stderr, for error messages.
err_console = Console(stderr=True)


def _load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the user config, raising a helpful error if missing/invalid."""
    path = path or config_path()
    if not path.exists():
        err_console.print(
            f"[red]No config found at {path}.[/red]\n"
            "Run [bold]polvo setup[/bold] to create one.",
        )
        raise typer.Exit(code=1)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        err_console.print(f"[red]Invalid YAML in {path}:[/red] {exc}")
        raise typer.Exit(code=1)
    if not isinstance(data, dict):
        err_console.print(f"[red]Config at {path} is not a mapping.[/red]")
        raise typer.Exit(code=1)
    return data


def _save_config(data: dict[str, Any], path: Path | None = None) -> None:
    """Write the config dict back to disk."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def list_config() -> None:
    """Print a table of model -> name -> model -> provider."""
    data = _load_config()
    adaptive = data.get("adaptive") or {}
    custom = data.get("custom") or {}
    providers = data.get("providers") or {}

    table = Table(title="Polvo Config")
    table.add_column("Key", style="bold")
    table.add_column("Custom Name")
    table.add_column("Model ID", min_width=24, overflow="fold")
    table.add_column("Provider")
    table.add_column("Type")
    table.add_column("Extra Params")

    for tier_key, spec in adaptive.items():
        if not isinstance(spec, dict):
            continue
        provider = spec.get("provider", "default")
        extra = spec.get("extra_params") or {}
        extra_str = ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
        table.add_row(
            str(tier_key),
            str(spec.get("name", "")),
            str(spec.get("model", "")),
            str(provider),
            "adaptive",
            extra_str,
        )
    for tier_key, spec in custom.items():
        if not isinstance(spec, dict):
            continue
        provider = spec.get("provider", "default")
        extra = spec.get("extra_params") or {}
        extra_str = ", ".join(f"{k}={v}" for k, v in extra.items()) if extra else ""
        table.add_row(
            str(tier_key),
            str(spec.get("name", "")),
            str(spec.get("model", "")),
            str(provider),
            "custom",
            extra_str,
        )

    console.print(table)
    console.print(f"\nConfig file: {config_path()}")


def set_tier_model(tier: str, model: str) -> None:
    """Update a specific model's id (adaptive or custom)."""
    data = _load_config()
    adaptive = data.get("adaptive") or {}
    custom = data.get("custom") or {}
    if tier in adaptive:
        adaptive[tier]["model"] = model
        data["adaptive"] = adaptive
    elif tier in custom:
        custom[tier]["model"] = model
        data["custom"] = custom
    else:
        err_console.print(
            f"[red]Unknown model '{tier}'.[/red] Valid keys: {', '.join(list(adaptive.keys()) + list(custom.keys()))}",
        )
        raise typer.Exit(code=1)
    _save_config(data)
    console.print(f"[green]✅ Set model '{tier}' to '{model}'[/green]")
