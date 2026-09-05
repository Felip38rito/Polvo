"""Config validation for the polvo CLI.

Centralizes the "is the router ready to start?" checks so both `polvo start`
and the interactive wizards can share them. Each check returns a human-readable
problem string (or None if that check passes); the caller decides how to
surface them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .setup import config_path


def load_config(path: Path | None = None) -> dict[str, Any] | None:
    """Load the user config as a dict, or None if missing/invalid.

    Unlike the per-command `_load_config` helpers, this never raises and never
    prints — it just returns None so callers can give a consistent message.
    """
    path = path or config_path()
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def config_problems(path: Path | None = None) -> list[str]:
    """Return a list of problems that would prevent the router from starting.

    Empty list = config is complete and ready. Each entry is a plain-English
    problem statement (no rich markup) so callers can render it however they
    like.
    """
    problems: list[str] = []
    data = load_config(path)
    if data is None:
        problems.append("No config found. Run 'polvo provider' to add your first provider.")
        return problems

    providers = data.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        problems.append("No providers configured. Run 'polvo provider' to add one.")

    tiers = data.get("tiers") or {}
    if not isinstance(tiers, dict) or not tiers:
        problems.append("No tiers configured. Run 'polvo tier' to add one.")

    classifier = data.get("classifier") or {}
    if not isinstance(classifier, dict) or not classifier.get("model"):
        problems.append("Classifier has no model. Run 'polvo tier' to configure it.")

    return problems


def is_ready(path: Path | None = None) -> bool:
    """True if the config is complete enough to start the router."""
    return not config_problems(path)
