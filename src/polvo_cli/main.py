"""polvo CLI — manage the Polvo Model Router.

Bare `polvo` runs an onboarding flow: it walks through whatever is missing
(providers -> models -> classifier) and offers to start the router. Once the
config is complete it prints an overview instead. `polvo provider` and
`polvo tier` (no subcommand) open interactive wizards; their non-interactive
subcommands (add/list/remove/set) remain for scripts.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from . import __version__, core
from .banner import print_banner
from .models_cmd import list_models
from .provider_cmd import (
    add as add_provider,
    add_first_provider,
    list_providers as list_providers,
    remove as remove_provider,
    setup_provider,
)
from .tier_cmd import (
    list_tiers as list_tiers,
    set_tier as set_tier,
    setup_tier,
)
from .custom_cmd import (
    list_custom as list_custom,
    set_custom as set_custom,
    setup_custom,
)
from .agent_cmd import (
    agent_app,
)
from .validate import config_problems

app = typer.Typer(
    name="polvo",
    help="Manage the Polvo Model Router: service lifecycle, setup, and config.",
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


def _print_overview(data: dict, ready: bool = True) -> None:
    """Compact summary of the current config (shown by bare `polvo`)."""
    providers = list((data.get("providers") or {}).keys())
    adaptive = list((data.get("adaptive") or {}).keys())
    custom = list((data.get("custom") or {}).keys())
    classifier = data.get("classifier") or {}

    if ready:
        console.print("[bold]Polvo router — config ready.[/bold]\n")
    else:
        console.print("[bold]Current config:[/bold]\n")
    console.print(f"  Providers:   {', '.join(providers) or '—'}")
    models_str = ", ".join(adaptive) or "—"
    if custom:
        models_str += f"  (+{len(custom)} custom: {', '.join(custom)})"
    console.print(f"  Models:      {models_str}")
    if classifier.get("model"):
        console.print(f"  Classifier:  {classifier['model']} via {classifier.get('provider', 'default')}")
    console.print()
    if ready:
        console.print("  [dim]polvo status      service state[/dim]")
        console.print("  [dim]polvo start       start the router[/dim]")
        console.print("  [dim]polvo stop        stop the router[/dim]")
        console.print("  [dim]polvo restart     restart the router[/dim]")
        console.print("  [dim]polvo provider    manage providers[/dim]")
        console.print("  [dim]polvo tier        manage models[/dim]")
        console.print("  [dim]polvo logs        recent router logs[/dim]")


def _run_onboarding() -> None:
    """Bare `polvo`: guide the user through whatever the config is missing."""
    data = core.load_config()
    problems = config_problems()

    if not problems:
        _print_overview(data)
        return

    console.print("[bold]Welcome to Polvo![/bold] Let's get your router ready.\n")

    if not data.get("providers"):
        console.print("[yellow]You don't have providers yet.[/yellow]")
        console.print("Starting configuration of your first provider...\n")
        add_first_provider()
        data = core.load_config()

        while typer.confirm("Would you like to add another provider before configuring models?", default=False):
            add_first_provider()
            data = core.load_config()
    else:
        # Providers already exist — show current config before continuing.
        _print_overview(data, ready=False)

    if not (data.get("adaptive") or data.get("custom")) or not (data.get("classifier") or {}).get("model"):
        setup_tier()
        data = core.load_config()

    problems = config_problems()
    if problems:
        err_console.print("\n[bold red]Config is still incomplete:[/bold red]")
        for p in problems:
            err_console.print(f"  • {p}")
        err_console.print("\nRun [bold]polvo provider[/bold] or [bold]polvo tier[/bold] to finish setup.")
        raise typer.Exit(code=1)

    console.print("\n[bold green]✨ Config complete![/bold green]")
    if typer.confirm("Start the router now?", default=True):
        _run_polvoctl("start")
    else:
        console.print("Run [bold]polvo start[/bold] whenever you're ready.")


@app.callback(invoke_without_command=True)
def _root_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        print_banner()
        _run_onboarding()


@app.command()
def version() -> None:
    """Print the CLI version."""
    print_banner()
    console.print(f"polvo {__version__}")


@app.command()
def banner() -> None:
    """Show the Polvo banner."""
    print_banner()


# --- Provider Group ---------------------------------------------------------
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
    name: str | None = typer.Argument(None, help="Provider name (e.g. 'Cloud Provider')"),
    base_url: str | None = typer.Option(None, "--url", "-u", help="OpenAI-compatible base URL"),
    api_key: str | None = typer.Option(None, "--key", "-k", help="API key (stored inline)"),
    api_key_env: str | None = typer.Option(None, "--env", "-e", help="Env var holding the API key"),
):
    """Add or update a provider endpoint."""
    if name is None or base_url is None:
        err_console.print("[red]Usage: polvo provider add <name> --url <base_url> (--key <key> | --env <env>)[/red]")
        err_console.print("Example: polvo provider add 'Cloud Provider' --url https://api.provider.com/v1 --env PROVIDER_API_KEY")
        raise typer.Exit(code=1)
    add_provider(name, base_url, api_key, api_key_env)


@provider_app.command("remove")
def provider_remove(name: str):
    """Remove a provider endpoint."""
    remove_provider(name)


# --- Tier Group -------------------------------------------------------------
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
app.add_typer(tier_app, name="tiers", hidden=True)
app.add_typer(agent_app, name="agent")


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
        err_console.print("Example: polvo tier set pro --model deepseek-v4-pro --provider 'Cloud Provider'")
        raise typer.Exit(code=1)
    set_tier(tier_key, model, provider, name, effort)


@app.command()
def models(
    provider: str | None = typer.Argument(None, help="Provider name from the config"),
) -> None:
    """List the models a configured provider offers."""
    if provider is None:
        data = core.load_config()
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
    app()


if __name__ == "__main__":
    main()