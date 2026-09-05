"""polvo CLI — manage the Polvo Model Router.

Wraps `polvoctl.sh` for service lifecycle and provides config management.
`polvo provider` and `polvo tier` (no subcommand) open interactive wizards;
their non-interactive subcommands (add/list/remove/set) remain for scripts.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from .banner import print_banner
from .config_cmd import list_config, set_tier_model
from .models_cmd import list_models
from .setup import run_setup, setup_provider, setup_tier
from .provider_cmd import list as list_providers, add as add_provider, remove as remove_provider
from .tier_cmd import list as list_tiers, set as set_tier
from .validate import config_problems

app = typer.Typer(
    name="polvo",
    help="Manage the Polvo Model Router: service lifecycle, setup, and config.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
err_console = Console(stderr=True)

# Repo root: src/polvo_cli/main.py -> src -> repo root.
STABLE_HOME = Path.home() / ".polvo"
REPO_DIR = STABLE_HOME if STABLE_HOME.exists() else Path(__file__).resolve().parents[2]
POLVOCTL = REPO_DIR / "polvoctl.sh"


def _find_polvoctl() -> Path:
    if POLVOCTL.exists():
        return POLVOCTL
    found = shutil.which("polvoctl")
    if found:
        return Path(found)
    err_console.print(
        "[red]polvoctl.sh not found.[/red] "
        f"Expected at {POLVOCTL} or on PATH.",
    )
    raise typer.Exit(code=1)


def _run_polvoctl(*args: str) -> None:
    script = _find_polvoctl()
    try:
        proc = subprocess.run(
            [str(script), *args],
            cwd=REPO_DIR,
        )
    except FileNotFoundError:
        err_console.print(f"[red]Could not execute {script}[/red]")
        raise typer.Exit(code=1)
    if proc.returncode != 0:
        raise typer.Exit(code=proc.returncode)


def _require_ready() -> None:
    """Abort with a clear message if the config can't start the router."""
    problems = config_problems()
    if not problems:
        return
    err_console.print("[bold red]Polvo can't start — config is incomplete:[/bold red]")
    for p in problems:
        err_console.print(f"  • {p}")
    err_console.print("\nRun [bold]polvo provider[/bold] and [bold]polvo tier[/bold] to set things up.")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the CLI version."""
    print_banner()
    console.print(f"polvo {__version__}")


@app.command()
def banner() -> None:
    """Show the Polvo banner."""
    print_banner()


@app.command()
def setup(
    section: str | None = typer.Argument(None, help="Setup section (provider|tier)"),
) -> None:
    """Run the interactive setup wizard."""
    run_setup(section)


# --- Provider Group ---------------------------------------------------------
# `polvo provider` with no subcommand opens the interactive wizard.
def _provider_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        setup_provider()


provider_app = typer.Typer(
    help="Manage router providers (interactive wizard with no subcommand).",
    invoke_without_command=True,
    callback=_provider_callback,
    no_args_is_help=False,
)
app.add_typer(provider_app, name="provider")


@provider_app.command("list")
def provider_list() -> None:
    """List all configured providers."""
    list_providers()


@provider_app.command("add")
def provider_add(
    name: str | None = typer.Argument(None, help="Provider name (e.g. 'Ollama Cloud')"),
    base_url: str | None = typer.Option(None, "--url", "-u", help="OpenAI-compatible base URL"),
    api_key: str | None = typer.Option(None, "--key", "-k", help="API key (stored inline)"),
    api_key_env: str | None = typer.Option(None, "--env", "-e", help="Env var holding the API key"),
):
    """Add or update a provider endpoint."""
    if name is None or base_url is None:
        err_console.print("[red]Usage: polvo provider add <name> --url <base_url> (--key <key> | --env <env>)[/red]")
        err_console.print("Example: polvo provider add 'Ollama Cloud' --url https://ollama.com/v1 --env OLLAMA_API_KEY")
        raise typer.Exit(code=1)
    add_provider(name, base_url, api_key, api_key_env)


@provider_app.command("remove")
def provider_remove(name: str):
    """Remove a provider endpoint."""
    remove_provider(name)


# --- Tier Group -------------------------------------------------------------
# `polvo tier` (and alias `polvo tiers`) with no subcommand opens the wizard.
def _tier_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        setup_tier()


tier_app = typer.Typer(
    help="Manage router tiers (interactive wizard with no subcommand).",
    invoke_without_command=True,
    callback=_tier_callback,
    no_args_is_help=False,
)
app.add_typer(tier_app, name="tier")
app.add_typer(tier_app, name="tiers", hidden=True)  # plural alias (funcional, oculto no help)


@tier_app.command("list")
def tier_list() -> None:
    """List all configured tiers."""
    list_tiers()


@tier_app.command("set")
def tier_set(
    tier_key: str | None = typer.Argument(None, help="Tier key (e.g. 'mini', 'pro', or a custom name)"),
    model: str | None = typer.Option(None, "--model", "-m", help="The upstream model ID"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="The name of the configured provider"),
    name: str | None = typer.Option(None, "--name", "-n", help="Optional display name for this tier"),
    effort: str | None = typer.Option(None, "--effort", "-e", help="Reasoning effort (e.g. 'medium', 'high')"),
):
    """Configure or update a specific tier."""
    if tier_key is None or model is None or provider is None:
        err_console.print("[red]Usage: polvo tier set <tier_key> --model <id> --provider <name>[/red]")
        err_console.print("Example: polvo tier set pro --model deepseek-v4-pro --provider 'Ollama Cloud'")
        raise typer.Exit(code=1)
    set_tier(tier_key, model, provider, name, effort)


# --- Legacy/Alias Config ----------------------------------------------------
@app.command()
def config(
    action: str | None = typer.Argument(None, help="'list' or 'set' (default: list)"),
    tier: str = typer.Argument(None, help="Tier key (for 'set')"),
    model: str = typer.Option(None, "--model", "-m", help="Model id (for 'set')"),
) -> None:
    """View or modify the router config (alias for 'tier')."""
    if action is None or action == "list":
        list_config()
    elif action == "set":
        if not tier or not model:
            err_console.print("[red]Usage: polvo config set <tier> --model <id>[/red]")
            raise typer.Exit(code=1)
        set_tier_model(tier, model)
    else:
        err_console.print(f"[red]Unknown config action '{action}'.[/red]")
        raise typer.Exit(code=1)


@app.command()
def models(
    provider: str | None = typer.Argument(None, help="Provider name from the config"),
) -> None:
    """List the models a configured provider offers."""
    if provider is None:
        from .validate import load_config

        data = load_config() or {}
        providers = data.get("providers") or {}
        if not providers:
            err_console.print("[red]No providers configured.[/red] Run [bold]polvo provider[/bold] to add one.")
            raise typer.Exit(code=1)
        err_console.print("[yellow]Usage: polvo models <provider>[/yellow]")
        err_console.print(f"Available providers: {', '.join(providers.keys())}")
        raise typer.Exit(code=1)
    list_models(provider)


@app.command()
def start() -> None:
    """Start the Polvo router service (validates config first)."""
    _require_ready()
    _run_polvoctl("start")


@app.command()
def install(
    port: int = typer.Option(9000, "--port", "-p", help="Port to run the router on"),
) -> None:
    """Generate the service config and load it (start at login)."""
    _require_ready()
    _run_polvoctl("install", "--port", str(port))


@app.command()
def uninstall() -> None:
    """Stop and remove the service config."""
    _run_polvoctl("uninstall")


@app.command()
def stop() -> None:
    """Stop the Polvo router service."""
    _run_polvoctl("stop")


@app.command()
def restart() -> None:
    """Restart the Polvo router service."""
    _require_ready()
    _run_polvoctl("restart")


@app.command()
def status() -> None:
    """Show whether the Polvo router service is running."""
    _run_polvoctl("status")


@app.command()
def logs() -> None:
    """Print the last 100 lines of router logs."""
    _run_polvoctl("logs")


@app.command()
def tail() -> None:
    """Follow the router logs live."""
    _run_polvoctl("tail")


def main() -> None:
    if len(sys.argv) == 1:
        print_banner()
    app()


if __name__ == "__main__":
    main()
