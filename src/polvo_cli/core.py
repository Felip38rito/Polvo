"""Shared config I/O for the polvo CLI.

Single source of truth for locating, loading, and saving the user config
(~/.polvo/config.yml). Command modules access these through the ``core``
module (``core.load_config()`` etc.) so tests can point config_path at a
temp file in one place: ``monkeypatch.setattr(core, "config_path", ...)``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def config_path() -> Path:
    """The user config file location: ~/.polvo/config.yml."""
    return Path.home() / ".polvo" / "config.yml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the user config as a dict, tolerating missing/invalid files.

    Returns an empty skeleton (providers/adaptive/custom) when the file is
    missing, unreadable, or not a mapping. Never raises, never prints.
    """
    path = path or config_path()
    if not path.exists():
        return _empty_config()
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return _empty_config()
    return data if isinstance(data, dict) else _empty_config()


def save_config(data: dict[str, Any], path: Path | None = None) -> None:
    """Write the config dict back to disk (creates parent dirs)."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


import yaml
from rich.console import Console
from rich.prompt import Prompt

console = Console()


def required_prompt(prompt: str, password: bool = False) -> str:
    """Prompt the user until a non-empty value is provided (optionally masked)."""
    while True:
        value = Prompt.ask(prompt, password=password)
        if value and value.strip():
            return value.strip()
        console.print("[red]Value cannot be empty. Please enter a value.[/red]")


def env_path() -> Path:
    """The provider keys file: ~/.polvo/.env."""
    return Path.home() / ".polvo" / ".env"


def env_var_name_for(provider_name: str) -> str:
    """Derive an env var name from a provider name ('Cloud Provider' -> CLOUD_PROVIDER_API_KEY)."""
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "_", provider_name).strip("_").upper()
    return f"{slug or 'PROVIDER'}_API_KEY"


def load_env_var(var_name: str, default: str | None = None) -> str | None:
    """Read a variable from the .env file. Returns default if not found."""
    path = env_path()
    if not path.exists():
        return default
    for line in path.read_text().splitlines():
        if line.startswith(f"{var_name}="):
            return line.split("=", 1)[1].strip()
    return default

def save_env_key(var_name: str, value: str, path: Path | None = None) -> None:
    """Insert or replace KEY=value in the .env file (never prints the value)."""
    path = path or env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    new_line = f"{var_name}={value}"
    replaced = False
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key == var_name:
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)
    path.write_text("\n".join(out) + "\n")


def _empty_config() -> dict[str, Any]:
    return {"providers": {}, "adaptive": {}, "custom": {}}