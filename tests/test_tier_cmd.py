"""Tests for tier_cmd: interactive wizard + set/list commands."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml

from polvo_cli import core, tier_cmd


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.yml"


@pytest.fixture
def patch_config_path(monkeypatch, config_file: Path) -> Path:
    monkeypatch.setattr(core, "config_path", lambda: config_file)
    return config_file


def _seed_provider(config_file: Path) -> None:
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
    }))


# --- setup_tier wizard ---------------------------------------------------------

def test_setup_tier_requires_existing_provider(patch_config_path: Path, config_file: Path, monkeypatch):
    """With no providers, tier setup must bail and tell the user to add one first."""
    config_file.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))

    calls = {"n": 0}
    def unexpected(prompt, *a, **k):
        calls["n"] += 1
        return "done"
    monkeypatch.setattr(tier_cmd.Prompt, "ask", unexpected)

    tier_cmd.setup_tier()
    assert calls["n"] == 0
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"] == {}
    assert data["custom"] == {}


def test_setup_tier_adds_adaptive(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["adaptive", "done"])
    prompt_answers = iter(["pro", "Cloud", "my-pro-model", "Pro Tier"])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"]["model"] == "my-pro-model"
    assert data["adaptive"]["pro"]["provider"] == "Cloud"
    assert data["adaptive"]["pro"]["name"] == "Pro Tier"


def test_setup_tier_adds_custom(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["custom", "done"])
    prompt_answers = iter(["meu-modelo", "Cloud", "my-custom-model", "Meu Modelo"])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["custom"]["meu-modelo"]["model"] == "my-custom-model"
    assert data["custom"]["meu-modelo"]["provider"] == "Cloud"


def test_setup_tier_adds_classifier(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["classifier", "done"])
    prompt_answers = iter(["Cloud", "minimax/minimax-m3:free"])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["classifier"]["model"] == "minimax/minimax-m3:free"
    assert data["classifier"]["provider"] == "Cloud"


# --- set -----------------------------------------------------------------------

def test_set_missing_args_shows_usage(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set("pro", None, "Cloud", None, None)
    assert exc.value.exit_code == 1


def test_set_unknown_provider_exits(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set("pro", "m", "Ghost", None, None)
    assert exc.value.exit_code == 1


def test_set_writes_adaptive_tier(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set("pro", "my-pro-model", "Cloud", "Pro Tier", None)
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"] == {"model": "my-pro-model", "provider": "Cloud", "name": "Pro Tier"}


def test_set_writes_custom_model(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set("meu-modelo", "my-model", "Cloud", None, "high")
    data = yaml.safe_load(config_file.read_text())
    assert data["custom"]["meu-modelo"]["model"] == "my-model"
    assert data["custom"]["meu-modelo"]["extra_params"] == {"reasoning_effort": "high"}


def test_set_adaptive_key_never_goes_to_custom(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set("mini", "m", "Cloud", None, None)
    data = yaml.safe_load(config_file.read_text())
    assert "mini" in data["adaptive"]
    assert "mini" not in (data.get("custom") or {})