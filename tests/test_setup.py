"""Tests for the polvo setup wizard (section-based, autosave)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from polvo_cli import setup


# --- config_path ------------------------------------------------------------

def test_config_path_points_to_user_config(monkeypatch):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: Path("/tmp/fake-home"))
    assert setup.config_path() == Path("/tmp/fake-home") / ".config" / "polvo" / "config.yml"


# --- _load_config / _save_config ---------------------------------------------

def test_load_config_missing_returns_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(setup, "config_path", lambda: tmp_path / "nope.yml")
    assert setup._load_config() == {"providers": {}, "adaptive": {}, "custom": {}}


def test_load_config_invalid_yaml_returns_empty(monkeypatch, tmp_path: Path):
    bad = tmp_path / "bad.yml"
    bad.write_text("adaptive: [unclosed")
    monkeypatch.setattr(setup, "config_path", lambda: bad)
    assert setup._load_config() == {"providers": {}, "adaptive": {}, "custom": {}}


def test_save_config_writes_yaml(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    monkeypatch.setattr(setup, "config_path", lambda: target)
    setup._save_config({"providers": {}, "adaptive": {}, "custom": {}})
    assert target.exists()
    assert yaml.safe_load(target.read_text()) == {"providers": {}, "adaptive": {}, "custom": {}}


# --- _required_prompt --------------------------------------------------------

def test_required_prompt_rejects_blank(monkeypatch):
    calls = iter(["", "   ", "real-value"])
    monkeypatch.setattr(setup.Prompt, "ask", lambda prompt: next(calls))
    assert setup._required_prompt("anything") == "real-value"


def test_required_prompt_strips_whitespace(monkeypatch):
    monkeypatch.setattr(setup.Prompt, "ask", lambda prompt: "  padded  ")
    assert setup._required_prompt("anything") == "padded"


# --- setup_provider ----------------------------------------------------------

def test_setup_provider_adds_and_saves(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    monkeypatch.setattr(setup, "config_path", lambda: target)
    # Actions: list (empty), add, done
    action_answers = iter(["list", "add", "done"])
    prompt_answers = iter([
        "MyCloud",                # provider name
        "https://cloud.com/v1",   # base_url
        "MYCLOUD_API_KEY",        # env var
    ])
    confirm_answers = iter([False])  # not inline key -> env var

    monkeypatch.setattr(setup.Prompt, "ask", lambda prompt, **k: next(prompt_answers))
    monkeypatch.setattr(setup.Confirm, "ask", lambda *a, **k: next(confirm_answers))
    # Route the action prompt separately: it contains "(add/list/remove/done)"
    real_prompt = setup.Prompt.ask
    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return real_prompt(prompt, *a, **k)
    monkeypatch.setattr(setup.Prompt, "ask", fake_ask)

    setup.setup_provider()
    data = yaml.safe_load(target.read_text())
    assert data["providers"]["MyCloud"]["base_url"] == "https://cloud.com/v1"
    assert data["providers"]["MyCloud"]["api_key_env"] == "MYCLOUD_API_KEY"


def test_setup_provider_inline_key(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    monkeypatch.setattr(setup, "config_path", lambda: target)
    action_answers = iter(["add", "done"])
    prompt_answers = iter(["Cloud", "https://cloud.com/v1", "sk-secret"])
    confirm_answers = iter([True])  # inline key

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)
    monkeypatch.setattr(setup.Prompt, "ask", fake_ask)
    monkeypatch.setattr(setup.Confirm, "ask", lambda *a, **k: next(confirm_answers))

    setup.setup_provider()
    data = yaml.safe_load(target.read_text())
    assert data["providers"]["Cloud"]["api_key"] == "sk-secret"
    assert "api_key_env" not in data["providers"]["Cloud"]


# --- setup_tier --------------------------------------------------------------

def test_setup_tier_requires_existing_provider(monkeypatch, tmp_path: Path):
    """With no providers, tier setup must bail and tell the user to add one first."""
    target = tmp_path / "config.yml"
    target.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    monkeypatch.setattr(setup, "config_path", lambda: target)

    # If we reach an action prompt, the guard failed. No actions should be asked.
    calls = {"n": 0}
    def unexpected(prompt, *a, **k):
        calls["n"] += 1
        return "done"
    monkeypatch.setattr(setup.Prompt, "ask", unexpected)

    setup.setup_tier()
    # We should never have prompted for an action (guard bails immediately).
    assert calls["n"] == 0
    data = yaml.safe_load(target.read_text())
    assert data["adaptive"] == {}
    assert data["custom"] == {}


def test_setup_tier_adds_adaptive_with_existing_provider(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    target.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
    }))
    monkeypatch.setattr(setup, "config_path", lambda: target)

    action_answers = iter(["adaptive", "done"])
    prompt_answers = iter(["pro", "Cloud", "my-pro-model", "Pro Tier"])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(setup.Prompt, "ask", fake_ask)
    # No reasoning effort (extra_params) — Confirm returns False.
    monkeypatch.setattr(setup.Confirm, "ask", lambda *a, **k: False)

    setup.setup_tier()
    data = yaml.safe_load(target.read_text())
    assert data["adaptive"]["pro"]["model"] == "my-pro-model"
    assert data["adaptive"]["pro"]["provider"] == "Cloud"
    assert data["adaptive"]["pro"]["name"] == "Pro Tier"


def test_setup_tier_adds_custom_with_existing_provider(monkeypatch, tmp_path: Path):
    target = tmp_path / "config.yml"
    target.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
    }))
    monkeypatch.setattr(setup, "config_path", lambda: target)

    action_answers = iter(["custom", "done"])
    prompt_answers = iter(["meu-modelo", "Cloud", "my-custom-model", "Meu Modelo"])

    def fake_ask(prompt, *a, **k):
        if "Action" in prompt:
            return next(action_answers)
        return next(prompt_answers)

    monkeypatch.setattr(setup.Prompt, "ask", fake_ask)
    monkeypatch.setattr(setup.Confirm, "ask", lambda *a, **k: False)

    setup.setup_tier()
    data = yaml.safe_load(target.read_text())
    assert data["custom"]["meu-modelo"]["model"] == "my-custom-model"
    assert data["custom"]["meu-modelo"]["provider"] == "Cloud"


# --- run_setup ---------------------------------------------------------------

def test_run_setup_unknown_section_errors(monkeypatch):
    monkeypatch.setattr(setup, "setup_provider", lambda: None)
    monkeypatch.setattr(setup, "setup_tier", lambda: None)
    monkeypatch.setattr(setup.Console, "print", lambda self, *a, **k: None)
    # Unknown section: prints a message, calls no wizard.
    setup.run_setup("bogus")


def test_run_setup_provider_section_only(monkeypatch):
    called = {"provider": False, "tier": False}
    monkeypatch.setattr(setup, "setup_provider", lambda: called.update(provider=True))
    monkeypatch.setattr(setup, "setup_tier", lambda: called.update(tier=True))
    setup.run_setup("provider")
    assert called["provider"] is True
    assert called["tier"] is False


def test_run_setup_full_runs_both(monkeypatch):
    called = {"provider": False, "tier": False}
    monkeypatch.setattr(setup, "setup_provider", lambda: called.update(provider=True))
    monkeypatch.setattr(setup, "setup_tier", lambda: called.update(tier=True))
    setup.run_setup()
    assert called["provider"] is True
    assert called["tier"] is True
