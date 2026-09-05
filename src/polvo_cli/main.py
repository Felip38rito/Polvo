"""polvo CLI — manage the Polvo Model Router.

Wraps `polvoctl.sh` for service lifecycle and provides config management.
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
from .setup import run_setup
from .provider_cmd import list as list_providers, add as add_provider, remove as remove_provider
from .tier_cmd import list as list_tiers, set as set_tier

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


# --- Provider Group ---
provider_app = typer.Typer(help="Manage router providers.")
app.add_typer(provider_app, name="provider")

@provider_app.command("list")
def provider_list() -> None:
    """List all configured providers."""
    list_providers()

@provider_app.command("add")
def provider_add(
    name: str,
    base_url: str = typer.Option(..., "--url", "-u"),
    api_key: str | None = typer.Option(None, "--key", "-k"),
    api_key_env: str | None = typer.Option(None, "--env", "-e"),
):
    """Add or update a provider endpoint."""
    add_provider(name, base_url, api_key, api_key_env)

@provider_app.command("remove")
def provider_remove(name: str):
    """Remove a provider endpoint."""
    remove_provider(name)


# --- Tier Group ---
tier_app = typer.Typer(help="Manage router tiers.")
app.add_typer(tier_app, name="tier")

@tier_app.command("list")
def tier_list() -> None:
    """List all configured tiers."""
    list_tiers()

@tier_app.command("set")
def tier_set(
    tier_key: str,
    model: str = typer.Option(..., "--model", "-m"),
    provider: str = typer.Option(..., "--provider", "-p"),
    name: str | None = typer.Option(None, "--name", "-n"),
    effort: str | None = typer.Option(None, "--effort", "-e"),
):
    """Configure or update a specific tier."""
    set_tier(tier_key, model, provider, name, effort)


# --- Legacy/Alias Config ---
@app.command()
def config(
    action: str = typer.Argument(..., help="'list' or 'set'"),
    tier: str = typer.Argument(None, help="Tier key (for 'set')"),
    model: str = typer.Option(None, "--model", "-m", help="Model id (for 'set')"),
) -> None:
    """View or modify the router config (alias for 'tier')."""
    if action == "list":
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
    provider: str = typer.Argument(..., help="Provider name from the config"),
) -> None:
    """List the models a configured provider offers."""
    list_models(provider)


@app.command()
def start() -> None:
    """Start the Polvo router service."""
    _run_polvoctl("start")


@app.command()
def install(
    port: int = typer.Option(9000, "--port", "-p", help="Port to run the router on"),
) -> None:
    """Generate the service config and load it (start at login)."""
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
