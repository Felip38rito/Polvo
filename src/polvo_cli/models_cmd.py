"""Provider model discovery for the polvo CLI.

Loads the router config, resolves the named provider's spec (base_url +
api_key), calls GET {base_url}/models, and renders the result as a table.
"""
from __future__ import annotations

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

from .setup import config_path

console = Console()
# Console that writes to stderr, for error messages.
err_console = Console(stderr=True)


class UpstreamError(Exception):
    """The upstream /models endpoint returned an HTTP error status."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _load_router_models() -> "RouterModels":
    """Load the router models from the user config.

    Raises typer.Exit if the config is missing or malformed.
    """
    from model_router.config import load_models_yaml

    path = config_path()
    if not path.exists():
        err_console.print(
            f"[red]No config found at {path}.[/red]\n"
            "Run [bold]polvo setup[/bold] to create one.",
        )
        raise typer.Exit(code=1)
    try:
        models = load_models_yaml(path)
    except (ValueError, yaml.YAMLError) as exc:
        err_console.print(f"[red]Invalid config at {path}:[/red] {exc}")
        raise typer.Exit(code=1)
    if models is None:
        err_console.print(f"[red]No config found at {path}.[/red]")
        raise typer.Exit(code=1)
    return models


def _model_ids(payload: dict) -> list[str]:
    """Extract model ids from an OpenAI-style /models payload."""
    data = payload.get("data") or []
    return [str(m.get("id", "")) for m in data if isinstance(m, dict)]


def fetch_models(provider_name: str) -> list[str]:
    """Fetch the model ids a named provider offers, via GET {base_url}/models."""
    models = _load_router_models()
    providers = models.providers
    if provider_name not in providers:
        err_console.print(
            f"[red]Unknown provider '{provider_name}'.[/red] "
            f"Valid providers: {', '.join(providers.keys())}",
        )
        raise typer.Exit(code=1)
    provider = providers[provider_name]

    try:
        api_key = provider.resolve_api_key()
    except RuntimeError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    url = f"{provider.base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(url, headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        err_console.print(f"[red]Could not reach {url}:[/red] {exc}")
        raise typer.Exit(code=1)

    if response.status_code >= 400:
        raise UpstreamError(response.status_code, response.text[:2000])

    return _model_ids(response.json())


def list_models(provider_name: str) -> None:
    """Print a rich table of the models a provider offers."""
    try:
        model_ids = fetch_models(provider_name)
    except UpstreamError as exc:
        err_console.print(f"[red]Error listing models:[/red] {exc}")
        raise typer.Exit(code=1)

    table = Table(title=f"Models — {provider_name}")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Model ID", style="bold")

    if not model_ids:
        console.print(f"No models returned by provider '{provider_name}'.")
        return
    for i, model_id in enumerate(model_ids, start=1):
        table.add_row(str(i), model_id)

    console.print(table)