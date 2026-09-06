"""Tests for custom_cmd: managing non-adaptive model routes."""
from __future__ import annotations

from pathlib import Path
import pytest
import typer
import yaml
from unittest.mock import MagicMock, patch

from polvo_cli import core, custom_cmd
from model_router.models import ADAPTIVE_TIERS

@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.yml"

@pytest.fixture
def patch_config_path(monkeypatch, config_file: Path) -> Path:
    monkeypatch.setattr(core, "config_path", lambda: config_file)
    return config_file

def _seed_config(config_file: Path, providers=None, custom=None):
    providers = providers or {"Cloud": {"base_url": "https://c.com", "api_key_env": "K"}}
    custom = custom or {}
    config_file.write_text(yaml.safe_dump({
        "providers": providers,
        "adaptive": {"mini": {"model": "m1", "provider": "Cloud"}},
        "custom": custom,
    }))

def test_list_custom_empty(patch_config_path: Path, config_file: Path, capsys):
    _seed_config(config_file, custom={})
    custom_cmd.list_custom()
    captured = capsys.readouterr()
    assert "No custom models configured yet" in captured.out

def test_list_custom_populated(patch_config_path: Path, config_file: Path, capsys):
    _seed_config(config_file, custom={"my-model": {"model": "gpt-4", "provider": "Cloud"}})
    custom_cmd.list_custom()
    captured = capsys.readouterr()
    assert "Custom Models:" in captured.out
    assert "my-model" in captured.out
    assert "gpt-4" in captured.out

def test_set_custom_success(patch_config_path: Path, config_file: Path, capsys):
    _seed_config(config_file)
    # Call with explicit values to avoid Typer OptionInfo objects in tests
    custom_cmd.set_custom("my-model", model="gpt-4", provider="Cloud")
    captured = capsys.readouterr()
    assert "configured successfully" in captured.out
    
    data = yaml.safe_load(config_file.read_text())
    assert "my-model" in data["custom"]
    assert data["custom"]["my-model"]["model"] == "gpt-4"

def test_set_custom_missing_args(patch_config_path: Path, config_file: Path):
    with pytest.raises(typer.Exit) as exc:
        custom_cmd.set_custom(None, None, None)
    assert exc.value.exit_code == 1

def test_set_custom_adaptive_collision(patch_config_path: Path, config_file: Path):
    _seed_config(config_file)
    tier = ADAPTIVE_TIERS[0]
    with pytest.raises(typer.Exit) as exc:
        custom_cmd.set_custom(tier, model="gpt-4", provider="Cloud")
    assert exc.value.exit_code == 1

def test_set_custom_unknown_provider(patch_config_path: Path, config_file: Path):
    _seed_config(config_file)
    with pytest.raises(typer.Exit) as exc:
        custom_cmd.set_custom("my-model", model="gpt-4", provider="Ghost")
    assert exc.value.exit_code == 1

def test_set_custom_with_effort(patch_config_path: Path, config_file: Path):
    _seed_config(config_file)
    custom_cmd.set_custom("my-model", model="gpt-4", provider="Cloud", effort="high")
    
    data = yaml.safe_load(config_file.read_text())
    assert data["custom"]["my-model"]["extra_params"]["reasoning_effort"] == "high"

def test_setup_custom_no_providers(patch_config_path: Path, config_file: Path, capsys):
    config_file.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    custom_cmd.setup_custom()
    captured = capsys.readouterr()
    assert "Error: No providers configured" in captured.out

def test_setup_custom_wizard_done(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_config(config_file)
    monkeypatch.setattr("polvo_cli.custom_cmd.Prompt.ask", lambda *a, **k: "done")
    custom_cmd.setup_custom()

def test_setup_custom_wizard_add_adaptive_collision(patch_config_path: Path, config_file: Path, monkeypatch, capsys):
    _seed_config(config_file)
    answers = ["add", "mini", "done"]
    def mock_ask(*a, **k):
        return answers.pop(0) if answers else "done"
    monkeypatch.setattr("polvo_cli.custom_cmd.Prompt.ask", mock_ask)
    monkeypatch.setattr("polvo_cli.custom_cmd.core.required_prompt", mock_ask)
    custom_cmd.setup_custom()
    captured = capsys.readouterr()
    assert "is an adaptive tier name" in captured.out
