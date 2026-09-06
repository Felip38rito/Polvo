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

# --- _get_provider_by_selection tests --------------------------------------------

def test_get_provider_no_providers(monkeypatch):
    # We mock the providers dict passed to the helper
    with pytest.raises(RuntimeError, match="No providers configured"):
        tier_cmd._get_provider_by_selection("Test", {})

def test_get_provider_single_provider_default(monkeypatch):
    providers = {"Cloud": {}}
    # Mock Prompt.ask to return empty string (Enter)
    monkeypatch.setattr(tier_cmd.Prompt, "ask", lambda *a, **k: "")
    assert tier_cmd._get_provider_by_selection("Test", providers) == "Cloud"

def test_get_provider_invalid_then_valid(monkeypatch):
    providers = {"Cloud": {}}
    # Return invalid choice first, then valid one
    answers = iter(["invalid", "1"])
    monkeypatch.setattr(tier_cmd.Prompt, "ask", lambda *a, **k: next(answers))
    assert tier_cmd._get_provider_by_selection("Test", providers) == "Cloud"

# --- setup_tier wizard -----------------------------------------------------------

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

def test_setup_tier_adds_adaptive(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["done"])
    prompt_answers = iter([
        "1", "model-mini", 
        "1", "model-air", 
        "1", "model-pro", 
        "1", "model-ultra", 
        "1", "model-classifier"
    ])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"]["model"] == "model-pro"
    assert data["adaptive"]["pro"]["provider"] == "Cloud"

def test_setup_tier_action_list(patch_config_path: Path, config_file: Path, monkeypatch, capsys):
    _seed_provider(config_file)
    # sequence: onboarding answers -> Action='list' -> Action='done'
    prompt_answers = iter([
        "1", "model-mini", "1", "model-air", "1", "model-pro", "1", "model-ultra", "1", "model-classifier",
        "list", "done"
    ])

    def fake_ask(prompt, *a, **k):
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    tier_cmd.setup_tier()
    captured = capsys.readouterr()
    assert "Adaptive Tiers:" in captured.out

def test_setup_tier_adds_classifier(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["done"])
    full_prompt_answers = iter([
        "1", "model-mini", 
        "1", "model-air", 
        "1", "model-pro", 
        "1", "model-ultra", 
        "1", "minimax/minimax-m3:free"
    ])
    
    def real_fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(full_prompt_answers)
        
    monkeypatch.setattr(tier_cmd.Prompt, "ask", real_fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["classifier"]["model"] == "minimax/minimax-m3:free"
    assert data["classifier"]["provider"] == "Cloud"

# --- list_tiers ----------------------------------------------------------------

def test_list_tiers_empty(patch_config_path: Path, config_file: Path, capsys):
    config_file.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    tier_cmd.list_tiers()
    captured = capsys.readouterr()
    assert "No adaptive tiers configured yet" in captured.out

def test_list_tiers_populated(patch_config_path: Path, config_file: Path, capsys):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {}},
        "adaptive": {"mini": {"model": "m1", "provider": "Cloud"}},
        "classifier": {"model": "c1", "provider": "Cloud"}
    }))
    tier_cmd.list_tiers()
    captured = capsys.readouterr()
    assert "Adaptive Tiers:" in captured.out
    assert "mini" in captured.out
    assert "Classifier:" in captured.out
    assert "c1" in captured.out

# --- set_tier ------------------------------------------------------------------

def test_set_missing_args_shows_usage(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set_tier("pro", None, "Cloud", None, None)
    assert exc.value.exit_code == 1

def test_set_unknown_provider_exits(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set_tier("pro", "m", "Ghost", None, None)
    assert exc.value.exit_code == 1

def test_set_invalid_tier_key_exits(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set_tier("invalid-tier", "m", "Cloud", None, None)
    assert exc.value.exit_code == 1

def test_set_writes_adaptive_tier(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set_tier("pro", "my-pro-model", "Cloud", "Pro Tier", None)
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"] == {"model": "my-pro-model", "provider": "Cloud", "name": "Pro Tier"}

def test_set_tier_with_effort(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set_tier("pro", "my-pro-model", "Cloud", None, "high")
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"]["extra_params"] == {"reasoning_effort": "high"}
