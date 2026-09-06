"""Commands for managing custom models in Polvo."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from . import core
from model_router.models import ADAPTIVE_TIERS

console = Console()
err_console = Console(stderr=True)


def _get_provider_by_selection(prompt_text: str, providers: dict) -> str:
    """Helper to select a provider by number or name."""
    provider_names = list(providers.keys())
    if not provider_names:
        raise RuntimeError("No providers configured.")

    if len(provider_names) == 1:
        console.print(f"  [dim]Only one provider available: {provider_names[0]} (Press Enter to use it)[/dim]")

    options = [f"{i+1}. {name}" for i, name in enumerate(provider_names)]
    options_str = ", ".join(options)

    choice = Prompt.ask(f"{prompt_text} ({options_str})")

    if not choice and len(provider_names) == 1:
        return provider_names[0]

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(provider_names):
            return provider_names[idx]

    if choice in provider_names:
        return choice

    console.print(f"[red]Invalid selection. Please choose a number (1-{len(provider_names)}) or a valid provider name.[/red]")
    return _get_provider_by_selection(prompt_text, providers)


def setup_custom() -> None:
    """Wizard for configuring custom models."""
    console.print(Panel("[bold cyan]Custom Model Setup[/bold cyan]\nAdd models that can be routed to by explicit ID."))

    data = core.load_config()
    providers = data.get("providers") or {}

    if not providers:
        console.print("[bold red]Error: No providers configured.[/bold red]")
        console.print("Please run [bold]polvo provider[/bold] first.")
        return

    while True:
        action = Prompt.ask(
            "Action (add/list/done)",
            choices=["add", "list", "done"],
            default="done",
        )

        if action == "done":
            break
        elif action == "list":
            _list_custom_models(data)
        elif action == "add":
            _add_custom(data, providers)


def _list_custom_models(data: dict) -> None:
    """Displays currently configured custom models."""
    custom = data.get("custom") or {}
    if not custom:
        console.print("[yellow]No custom models configured yet.[/yellow]")
        return
    console.print("[bold]Custom Models:[/bold]")
    for key, spec in custom.items():
        console.print(f"  • [bold]{key}[/bold]: {spec.get('model')} via {spec.get('provider')}")


def _add_custom(data: dict, providers: dict) -> None:
    """Add/update a custom model."""
    custom = data.get("custom") or {}
    tier_key = core.required_prompt("Custom model key (any name)")
    if tier_key in ADAPTIVE_TIERS:
        console.print(f"[red]'{tier_key}' is an adaptive tier name. Use [bold]polvo tier[/bold] for it.[/red]")
        return

    provider = _get_provider_by_selection("Which provider serves this model?", providers)

    model = core.required_prompt(f"Model ID for {tier_key}")
    name = Prompt.ask(f"Display name for {tier_key} (optional)", default=tier_key)

    spec = {"model": model, "provider": provider, "name": name}

    if Confirm.ask("Add reasoning effort (extra_params)?", default=False):
        effort = Prompt.ask("Value (e.g. 'medium', 'high')")
        spec["extra_params"] = {"reasoning_effort": effort}

    custom[tier_key] = spec
    data["custom"] = custom
    core.save_config(data)
    console.print(f"[green]✅ Custom model '{tier_key}' saved.[/green]")


def list_custom() -> None:
    """List all custom models."""
    data = core.load_config()
    _list_custom_models(data)


def set_custom(
    tier_key: str | None = typer.Argument(None, help="Model key (custom name)"),
    model: str | None = typer.Option(None, "--model", "-m", help="The upstream model ID"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="The name of the configured provider"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional display name for this model"),
    effort: str | None = typer.Option(None, "--effort", "-e", help="Reasoning effort (e.g. 'medium', 'high')"),
) -> None:
    """Configure or update a custom model."""
    # Resolve Typer Option/Argument defaults if function is called directly (e.g. in tests)
    def resolve(v):
        # Typer Option/Argument objects have a .default attribute
        if hasattr(v, "default") and not isinstance(v, (str, int, float, bool, type(None))):
            return v.default
        # Also check for .info.default just in case
        if hasattr(v, "info") and hasattr(v.info, "default"):
            return v.info.default
        return v

    t_key = resolve(tier_key)
    m_val = resolve(model)
    p_val = resolve(provider)
    n_val = resolve(name)
    e_val = resolve(effort)

    if t_key is None or m_val is None or p_val is None:
        err_console.print("[red]Usage: polvo custom set <key> --model <id> --provider <name>[/red]")
        err_console.print("Example: polvo custom set my-model --model some-id --provider 'Cloud Provider'")
        raise typer.Exit(code=1)

    if t_key in ADAPTIVE_TIERS:
        err_console.print(f"[red]'{t_key}' is an adaptive tier name. Use [bold]polvo tier[/bold] for it.[/red]")
        raise typer.Exit(code=1)

    data = core.load_config()
    providers = data.get("providers") or {}

    if p_val not in providers:
        err_console.print(f"[red]Error: Provider '{p_val}' not found.[/red]")
        err_console.print("Run 'polvo provider list' to see available providers.")
        raise typer.Exit(code=1)

    spec = {"model": m_val, "provider": p_val, "name": n_val}

    extra_params = {}
    if isinstance(e_val, str) and e_val:
        extra_params["reasoning_effort"] = e_val
    if extra_params:
        spec["extra_params"] = extra_params

    final_spec = {k: v for k, v in spec.items() if v is not None}

    custom = data.get("custom") or {}
    custom[t_key] = final_spec
    data["custom"] = custom
    core.save_config(data)
    console.print(f"[green]✅ Custom model '{t_key}' configured successfully.[/green]")
