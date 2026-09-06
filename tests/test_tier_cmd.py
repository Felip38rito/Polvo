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


def test_setup_tier_adds_custom(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["done"])
    prompt_answers = iter([])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    # To test adding a custom model, we should use custom_cmd.setup_custom
    from polvo_cli import custom_cmd
    # We need to mock prompts for custom_cmd.setup_custom too
    # The current setup_custom flow: Action (add/list/done) -> if add: Key -> Provider -> Model -> Name -> Reasoning
    custom_action = iter(["add", "done"])
    custom_prompts = iter(["meu-modelo", "1", "my-custom-model", "Meu Modelo", "no"])
    
    def custom_fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(custom_action)
        return next(custom_prompts)
    
    monkeypatch.setattr(custom_cmd.Prompt, "ask", custom_fake_ask)
    
    custom_cmd.setup_custom()
    data = yaml.safe_load(config_file.read_text())
    assert data["custom"]["meu-modelo"]["model"] == "my-custom-model"
    assert data["custom"]["meu-modelo"]["provider"] == "Cloud"


def test_setup_tier_adds_classifier(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    action_answers = iter(["done"])
    prompt_answers = iter([])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(tier_cmd.Prompt, "ask", fake_ask)
    monkeypatch.setattr(tier_cmd.Confirm, "ask", lambda *a, **k: False)

    # We need to trigger just the classifier part. Since setup_tier does adaptive then classifier,
    # we must provide answers for the 4 adaptive tiers first.
    # 4 tiers * (provider, model) = 8 answers.
    # Then the classifier prompts: provider, model.
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

    tier_cmd.setup_tier()
    data = yaml.safe_load(config_file.read_text())
    assert data["classifier"]["model"] == "minimax/minimax-m3:free"
    assert data["classifier"]["provider"] == "Cloud"


# --- set -----------------------------------------------------------------------

def test_set_missing_args_shows_usage(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set_tier("pro", None, "Cloud", None, None)
    assert exc.value.exit_code == 1


def test_set_unknown_provider_exits(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        tier_cmd.set_tier("pro", "m", "Ghost", None, None)
    assert exc.value.exit_code == 1


def test_set_writes_adaptive_tier(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set_tier("pro", "my-pro-model", "Cloud", "Pro Tier", None)
    data = yaml.safe_load(config_file.read_text())
    assert data["adaptive"]["pro"] == {"model": "my-pro-model", "provider": "Cloud", "name": "Pro Tier"}


def test_set_writes_custom_model(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    # Since it's in tier_cmd, let's assume the test wants to check the 
    # logic for custom models if it was still there, but now we should
    # probably call the custom_cmd if the test was intended for custom models.
    # However, looking at the existing test, it called tier_cmd.set.
    # We'll redirect this to custom_cmd.set_custom to keep the test's intent.
    from polvo_cli import custom_cmd
    custom_cmd.set_custom("meu-modelo", "my-model", "Cloud", None, "high")
    data = yaml.safe_load(config_file.read_text())
    assert data["custom"]["meu-modelo"]["model"] == "my-model"
    assert data["custom"]["meu-modelo"]["extra_params"] == {"reasoning_effort": "high"}


def test_set_adaptive_key_never_goes_to_custom(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    tier_cmd.set_tier("mini", "m", "Cloud", None, None)
    data = yaml.safe_load(config_file.read_text())
    assert "mini" in data["adaptive"]
    assert "mini" not in (data.get("custom") or {})