"""Commands for automating the setup of agents to use Polvo.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from . import core
from . import codex_config

console = Console()
err_console = Console(stderr=True)


def _run_cmd(args: list[str], cwd: str | None = None) -> bool:
    """Run a system command and return whether it succeeded."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
        return res.returncode == 0
    except FileNotFoundError:
        return False


def setup_hermes() -> None:
    """Automated setup for Hermes Agent to use Polvo."""
    port = core.load_env_var("ROUTER_PORT", "9000")
    api_url = f"http://127.0.0.1:{port}/v1"

    console.print(
        Panel(f"[bold cyan]Hermes Agent Setup[/bold cyan]\nConfiguring Hermes to route through Polvo on port {port}.\n")
    )

    commands = [
        ["hermes", "config", "set", "providers.router.api", api_url],
        ["hermes", "config", "set", "providers.router.name", "Polvo"],
        ["hermes", "config", "set", "providers.router.default_model", "adaptive"],
        ["hermes", "config", "set", "model.provider", "router"],
        ["hermes", "config", "set", "model.default_model", "adaptive"],
        ["hermes", "config", "set", "model.aliases.mini", "router/mini"],
        ["hermes", "config", "set", "model.aliases.air", "router/air"],
        ["hermes", "config", "set", "model.aliases.pro", "router/pro"],
        ["hermes", "config", "set", "model.aliases.ultra", "router/ultra"],
    ]

    failed = 0
    for cmd in commands:
        if not _run_cmd(cmd):
            failed += 1
            err_console.print(f"[red]Failed to execute: {' '.join(cmd)}[/red]")

    if failed == 0:
        console.print("[bold green]✅ Hermes Agent configured successfully![/bold green]")
        console.print("Run [bold]hermes model[/bold] to see the Polvo tiers.")
    else:
        err_console.print(f"[yellow]Setup finished with {failed} failed command(s).[/yellow]")


def setup_opencode() -> None:
    """Automated setup for OpenCode to use Polvo (syncs tiers snapshot)."""
    console.print(
        Panel("[bold cyan]OpenCode Setup[/bold cyan]\nSyncing Polvo tiers into the OpenCode config.\n")
    )

    candidates = [
        Path.home() / ".polvo" / "sync-opencode.py",
        Path.home() / "Developer/polvo" / "sync-opencode.py",
    ]
    script = next((p for p in candidates if p.exists()), None)

    if script is None:
        err_console.print("[red]Error: sync-opencode.py not found.[/red]")
        err_console.print("Looked in ~/.polvo and ~/Developer/polvo.")
        raise typer.Exit(code=1)

    if _run_cmd(["python3", str(script)]):
        console.print("[bold green]✅ OpenCode synced successfully![/bold green]")
    else:
        err_console.print("[red]Failed to sync OpenCode config.[/red]")
        raise typer.Exit(code=1)


def setup_codex() -> None:
    """Automated setup for Codex CLI to use Polvo."""
    port = core.load_env_var("ROUTER_PORT", "9000")
    console.print(
        Panel(f"[bold cyan]Codex CLI Setup[/bold cyan]\nConfiguring Codex to route through Polvo on port {port}.\n")
    )

    try:
        codex_config.write_codex_config(port)
        console.print("[bold green]✅ Codex CLI configured successfully![/bold green]")
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        err_console.print(f"[red]Unexpected error configuring Codex: {e}[/red]")
        raise typer.Exit(code=1)


def setup_copilot() -> None:
    """Automated setup for Copilot CLI to use Polvo via .polvo/.env."""
    port = core.load_env_var("ROUTER_PORT", "9000")
    api_key = core.load_env_var("ROUTER_API_KEY", "router")
    api_url = f"http://127.0.0.1:{port}/v1"

    console.print(
        Panel(f"[bold cyan]Copilot CLI Setup[/bold cyan]\nConfiguring Copilot via .polvo/.env.\n")
    )

    # 1. Store the Copilot variables in ~/.polvo/.env
    copilot_vars = {
        "COPILOT_PROVIDER_BASE_URL": api_url,
        "COPILOT_PROVIDER_API_KEY": api_key,
        "COPILOT_MODEL": "adaptive",
    }
    
    for var, val in copilot_vars.items():
        core.save_env_key(var, val)

    # 2. Add the source marker to the shell profile
    shell = os.environ.get("SHELL", "")
    profile_path = None
    if "zsh" in shell:
        profile_path = Path.home() / ".zshrc"
    elif "bash" in shell:
        profile_path = Path.home() / ".bashrc"
    
    if not profile_path or not profile_path.exists():
        profile_path = Path.home() / ".zshrc"
        if not profile_path.exists():
            err_console.print("[red]Could not detect shell profile (.zshrc/.bashrc).[/red]")
            console.print(f"Please add this line to your shell config: [bold]source ~/.polvo/.env[/bold]")
            return

    source_line = "source ~/.polvo/.env"
    try:
        content = profile_path.read_text()
        if source_line not in content:
            with open(profile_path, "a") as f:
                f.write(f"\n# Polvo environment variables\n{source_line}\n")
            console.print(f"[bold green]✅ Added source marker to {profile_path}[/bold green]")
        else:
            console.print("[bold green]✅ Shell profile already configured to source .polvo/.env[/bold green]")
        
        console.print(f"\n[bold yellow]IMPORTANT:[/bold yellow] Please run [bold]source {profile_path}[/bold] or restart your terminal.")
    except Exception as e:
        err_console.print(f"[red]Failed to update shell profile: {e}[/red]")
        raise typer.Exit(code=1)

agent_app = typer.Typer(
    help="Automate the setup of agents to use Polvo as their model provider.",
)

@agent_app.command("hermes")
def agent_hermes() -> None:
    """Setup Polvo for Hermes Agent."""
    setup_hermes()

@agent_app.command("opencode")
def agent_opencode() -> None:
    """Setup Polvo for OpenCode."""
    setup_opencode()

@agent_app.command("codex")
def agent_codex() -> None:
    """Setup Polvo for Codex CLI."""
    setup_codex()

@agent_app.command("copilot")
def agent_copilot() -> None:
    """Setup Polvo for Copilot CLI."""
    setup_copilot()
