"""Config validation for the polvo CLI.

Centralizes the "is the router ready to start?" checks so `polvo start`,
the onboarding flow (bare `polvo`), and the interactive wizards share them.
Also hosts provider-usage checks shared by the removal paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import core


def load_config(path: Path | None = None) -> dict | None:
    """Load the user config as a dict, or None if missing/invalid.

    Unlike core.load_config (which returns an empty skeleton), this returns
    None so callers can distinguish "no config" / "broken config" from
    "empty config" and message accordingly.
    """
    path = path or core.config_path()
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
    path = path or core.config_path()
    if not path.exists():
        problems.append("No config found. Run 'polvo provider' to add your first provider.")
        return problems

    data = load_config(path)
    if data is None:
        problems.append(
            f"Config at {path} is malformed (invalid YAML or not a mapping). "
            "Fix or remove it, then run 'polvo provider'."
        )
        return problems

    providers = data.get("providers") or {}
    if not isinstance(providers, dict) or not providers:
        problems.append("No providers configured. Run 'polvo provider' to add one.")

    adaptive = data.get("adaptive") or {}
    custom = data.get("custom") or {}
    if not isinstance(adaptive, dict) or not isinstance(custom, dict):
        problems.append("Config is malformed: 'adaptive' and 'custom' must be mappings.")
    elif not adaptive and not custom:
        problems.append("No models configured. Run 'polvo tier' to add adaptive tiers or custom models.")

    classifier = data.get("classifier") or {}
    if not isinstance(classifier, dict) or not classifier.get("model"):
        problems.append("Classifier has no model. Run 'polvo tier' to configure it.")

    return problems


def is_ready(path: Path | None = None) -> bool:
    """True if the config is complete enough to start the router."""
    return not config_problems(path)


def provider_in_use(data: dict[str, Any], name: str) -> bool:
    """True if any adaptive tier, custom model, or the classifier uses the provider."""
    for block in ("adaptive", "custom"):
        for spec in (data.get(block) or {}).values():
            if isinstance(spec, dict) and spec.get("provider") == name:
                return True
    classifier = data.get("classifier") or {}
    return isinstance(classifier, dict) and classifier.get("provider") == name