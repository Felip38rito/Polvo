"""Commands for managing Polvo adaptive tiers.

Adaptive tiers are the fixed axis (mini, air, pro, ultra) — the classifier
only ever picks among these.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import core
from model_router.models import ADAPTIVE_TIERS

console = Console()
err_console = Console(stderr=True)

# Tier descriptions for onboarding guide
TIER_DESCRIPTIONS = {
    "mini": "Trivial and mechanical tasks, simple chatter, and fast responses.",
    "air": "Day-to-day implementation, general coding assistance, and standard tasks.",
    "pro": "Hard debugging, complex refactors, and deep logical reasoning.",
    "ultra": "Whole-architecture synthesis, adversarial analysis, and deep research.",
}


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


def setup_tier() -> None:
    """Wizard for configuring adaptive tiers."""
    console.print(Panel("[bold cyan]Model Setup[/bold cyan]\nConfigure the adaptive routing scale."))

    data = core.load_config()
    providers = data.get("providers") or {}

    if not providers:
        console.print("[bold red]Error: No providers configured.[/bold red]")
        console.print("Please run [bold]polvo provider[/bold] first.")
        return

    # Start with the guided onboarding flow
    _run_tier_onboarding(data, providers)
    
    # After onboarding, offer the action menu for fine-tuning
    console.print("\n[dim]Tiers configured. You can now manage them or exit.[/dim]")
    while True:
        action = Prompt.ask(
            "Action (list/done)",
            choices=["list", "done"],
            default="done",
        )

        if action == "done":
            break
        elif action == "list":
            _list_adaptive_tiers(data)


def _run_tier_onboarding(data: dict, providers: dict) -> None:
    """Guided setup for the 4 adaptive tiers and the classifier."""
    console.print("\n[bold]The Polvo Adaptive Scale[/bold]")
    console.print("Polvo uses four tiers to match the model's power to the task's complexity.")
    
    provider_names = list(providers.keys())

    # 1. Setup the 4 Adaptive Tiers
    for tier in ADAPTIVE_TIERS:
        desc = TIER_DESCRIPTIONS.get(tier, "")
        console.print(f"\n[bold cyan]{tier.upper()}[/bold cyan]: {desc}")
        
        provider = _get_provider_by_selection(f"Which provider serves {tier}?", providers)
        model = core.required_prompt(f"Model ID for {tier}")
        
        spec = {"model": model, "provider": provider}
        adaptive = data.get("adaptive") or {}
        adaptive[tier] = spec
        data["adaptive"] = adaptive
        core.save_config(data)

    # 2. Setup the Classifier
    console.print("\n[bold]The Classifier[/bold]")
    console.print("Finally, pick the lightweight model that reads each request and decides which tier to route it to.")
    console.print("[dim]Tip: this should be a small, fast, cheap model — it only classifies, it never answers.[/dim]")
    
    provider = _get_provider_by_selection("Which provider serves the classifier?", providers)
    model = core.required_prompt("Model ID for the classifier")
    
    classifier = data.get("classifier") or {}
    classifier["model"] = model
    classifier["provider"] = provider
    data["classifier"] = classifier
    core.save_config(data)
    console.print("[green]✅ Adaptive routing configured successfully![/green]")


def _list_adaptive_tiers(data: dict) -> None:
    """Displays currently configured adaptive tiers."""
    adaptive = data.get("adaptive") or {}
    if not adaptive:
        console.print("[yellow]No adaptive tiers configured yet.[/yellow]")
        return
    console, _ = (console, None) # fix local scope
    console.print("[bold]Adaptive Tiers:[/bold]")
    for key, spec in adaptive.items():
        console.print(f"  • [bold]{key}[/bold]: {spec.get('model')} via {spec.get('provider')}")
    classifier = data.get("classifier") or {}
    if classifier.get("model"):
        console.print("[bold]Classifier:[/bold]")
        console.print(f"  • {classifier['model']} via {classifier.get('provider', 'default')}")


def list_tiers() -> None:
    """List all adaptive tiers."""
    data = core.load_config()
    _list_adaptive_tiers(data)


def set_tier(
    tier_key: str | None = typer.Argument(None, help="Tier key (mini, air, pro, ultra)"),
    model: str | None = typer.Option(None, "--model", "-m", help="The upstream model ID"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="The name of the configured provider"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional display name for this tier"),
    effort: str | None = typer.Option(None, "--effort", "-e", help="Reasoning effort (e.g. 'medium', 'high')"),
) -> None:
    """Configure or update an adaptive tier."""
    if tier_key is None or model is None or provider is None:
        err_console.print("[red]Usage: polvo tier set <tier_key> --model <id> --provider <name>[/red]")
        err_console.print("Example: polvo tier set pro --model deepseek-v4-pro --provider 'Cloud Provider'")
        raise typer.Exit(code=1)

    if tier_key not in ADAPTIVE_TIERS:
        err_console.print(f"[red]Invalid tier '{tier_key}'. Must be one of: {', '.join(ADAPTIVE_TIERS)}[/red]")
        raise typer.Exit(code=1)

    data = core.load_config()
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

    adaptive = data.get("adaptive") or {}
    adaptive[tier_key] = spec
    data["adaptive"] = adaptive
    core.save_config(data)
    console.print(f"[green]✅ Adaptive tier '{tier_key}' configured successfully.[/green]")
