"""Interactive setup flow for the Polvo Model Router.

Guides the user through configuring providers and tiers via a section-based wizard.
Each section performs autosave to the config file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from model_router.models import ADAPTIVE_TIERS

console = Console()


def config_path() -> Path:
    """The user config file location: ~/.config/polvo/config.yml."""
    return Path.home() / ".config" / "polvo" / "config.yml"


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

def _required_prompt(prompt: str) -> str:
    while True:
        value = Prompt.ask(prompt)
        if value and value.strip():
            return value.strip()
        console.print("[red]Value cannot be empty. Please enter a value.[/red]")

def setup_provider() -> None:
    """Wizard for configuring providers."""
    console.print(Panel("[bold cyan]Provider Setup[/bold cyan]\nManage your upstream OpenAI-compatible endpoints."))
    
    data = _load_config()
    providers = data.get("providers") or {}
    
    while True:
        action = Prompt.ask(
            "Action (add/list/remove/done)", 
            choices=["add", "list", "remove", "done"], 
            default="list"
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
            name = _required_prompt("Provider name")
            url = _required_prompt("Base URL (e.g. https://ollama.com/v1)")
            
            use_inline = Confirm.ask("Provide API key directly (inline) instead of an env var?", default=False)
            if use_inline:
                key = _required_prompt("API key")
                spec = {"base_url": url.rstrip("/"), "api_key": key}
            else:
                env = _required_prompt("Env var holding the API key (e.g. OLLAMA_API_KEY)")
                spec = {"base_url": url.rstrip("/"), "api_key_env": env}
            
            providers[name] = spec
            data["providers"] = providers
            _save_config(data)
            console.print(f"[green]✅ Provider '{name}' saved.[/green]")
        elif action == "remove":
            name = Prompt.ask("Provider name to remove")
            if name in providers:
                # Simple check: is it used in tiers?
                tiers = data.get("tiers") or {}
                in_use = any(spec.get("provider") == name for spec in tiers.values() if isinstance(spec, dict))
                if in_use:
                    console.print(f"[red]Cannot remove '{name}': it is used by one or more tiers.[/red]")
                else:
                    del providers[name]
                    data["providers"] = providers
                    _save_config(data)
                    console.print(f"[green]✅ Provider '{name}' removed.[/green]")
            else:
                console.print(f"[red]Provider '{name}' not found.[/red]")

def setup_tier() -> None:
    """Wizard for configuring tiers."""
    console.print(Panel("[bold cyan]Tier Setup[/bold cyan]\nConfigure the models used for different cognitive loads."))
    
    data = _load_config()
    providers = data.get("providers") or {}
    tiers = data.get("tiers") or {}
    
    if not providers:
        console.print("[bold red]Error: No providers configured.[/bold red]")
        console.print("Please run [bold]polvo setup provider[/bold] first.")
        return

    while True:
        action = Prompt.ask(
            "Action (add/list/done)", 
            choices=["add", "list", "done"], 
            default="list"
        )
        
        if action == "done":
            break
        elif action == "list":
            if not tiers:
                console.print("[yellow]No tiers configured yet.[/yellow]")
            else:
                for key, spec in tiers.items():
                    if isinstance(spec, dict):
                        console.print(f"• [bold]{key}[/bold]: {spec.get('model')} via {spec.get('provider')}")
        elif action == "add":
            tier_key = _required_prompt("Tier key (e.g. 'mini', 'pro', or a custom name)")
            
            # Only show and allow existing providers
            provider_names = list(providers.keys())
            console.print(f"Available providers: {', '.join(provider_names)}")
            provider = Prompt.ask("Choose provider", choices=provider_names)
            
            model = _required_prompt(f"Model ID for {tier_key}")
            name = Prompt.ask(f"Display name for {tier_key} (optional)", default=tier_key)
            
            spec = {
                "model": model,
                "provider": provider,
                "name": name,
            }
            
            # Optional reasoning effort
            if Confirm.ask("Add reasoning effort (extra_params)?", default=False):
                effort = Prompt.ask("Value (e.g. 'medium', 'high')")
                spec["extra_params"] = {"reasoning_effort": effort}
            
            tiers[tier_key] = spec
            data["tiers"] = tiers
            _save_config(data)
            console.print(f"[green]✅ Tier '{tier_key}' saved.[/green]")

def run_setup(section: str | None = None) -> None:
    """Main entry point for the interactive setup wizard."""
    console.print(Panel("[bold green]Polvo Setup[/bold green]\nConfigure your model router: providers and tiers."))
    
    if section == "provider":
        setup_provider()
    elif section == "tier":
        setup_tier()
    elif section:
        console.print(f"[red]Unknown setup section '{section}'.[/red]")
        console.print("Valid sections: provider, tier")
        return
    else:
        # Full wizard
        setup_provider()
        setup_tier()
        console.print("\n[bold green]✨ Setup complete![/bold green]")
        console.print("Run [bold]polvo start[/bold] to launch the router.")
