"""Tests for provider_cmd: interactive wizard + add/list/remove commands."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml

from polvo_cli import core, provider_cmd


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.yml"


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    return tmp_path / ".env"


@pytest.fixture
def patch_config_path(monkeypatch, config_file: Path, env_file: Path) -> Path:
    monkeypatch.setattr(core, "config_path", lambda: config_file)
    monkeypatch.setattr(core, "env_path", lambda: env_file)
    return config_file


def _fake_prompts(monkeypatch, answers: list[str]):
    """Feed Prompt.ask from a list (in order), regardless of prompt text."""
    it = iter(answers)

    def fake_ask(prompt, *a, **k):
        return next(it)

    monkeypatch.setattr(provider_cmd.Prompt, "ask", fake_ask)


# --- setup_provider wizard -----------------------------------------------------

def test_setup_provider_adds_and_saves(patch_config_path: Path, config_file: Path, env_file: Path, monkeypatch):
    # Wizard loop: action "add" -> name/url/key -> action "done".
    _fake_prompts(monkeypatch, ["add", "MyCloud", "https://cloud.com/v1", "sk-secret", "done"])

    provider_cmd.setup_provider()
    data = yaml.safe_load(config_file.read_text())
    assert data["providers"]["MyCloud"]["base_url"] == "https://cloud.com/v1"
    # Key must land in .env as a derived var, never inline in config.yml.
    assert data["providers"]["MyCloud"]["api_key_env"] == "MYCLOUD_API_KEY"
    assert "api_key" not in data["providers"]["MyCloud"]
    assert "MYCLOUD_API_KEY=sk-secret" in env_file.read_text()


def test_setup_provider_key_hidden_in_config(patch_config_path: Path, config_file: Path, env_file: Path, monkeypatch):
    """The raw key must never appear in config.yml (masked input + .env only)."""
    _fake_prompts(monkeypatch, ["add", "Cloud", "https://cloud.com/v1", "sk-super-secret", "done"])

    provider_cmd.setup_provider()
    assert "sk-super-secret" not in config_file.read_text()
    assert "sk-super-secret" in env_file.read_text()
    assert "CLOUD_API_KEY=sk-super-secret" in env_file.read_text()


def test_env_var_name_derivation():
    assert core.env_var_name_for("Cloud Provider") == "CLOUD_PROVIDER_API_KEY"
    assert core.env_var_name_for("ollama-cloud") == "OLLAMA_CLOUD_API_KEY"
    assert core.env_var_name_for("  Weird &* Name!!  ") == "WEIRD_NAME_API_KEY"


def test_save_env_key_inserts_and_replaces(env_file: Path, monkeypatch):
    monkeypatch.setattr(core, "env_path", lambda: env_file)
    core.save_env_key("A_KEY", "first")
    core.save_env_key("B_KEY", "other")
    core.save_env_key("A_KEY", "second")  # replace in place
    text = env_file.read_text()
    assert "A_KEY=first" not in text
    assert "A_KEY=second" in text
    assert "B_KEY=other" in text


def test_save_env_key_preserves_other_lines(env_file: Path, monkeypatch):
    monkeypatch.setattr(core, "env_path", lambda: env_file)
    env_file.write_text("# comment\nFOO=bar\n")
    core.save_env_key("NEW_KEY", "v")
    text = env_file.read_text()
    assert "# comment" in text
    assert "FOO=bar" in text
    assert "NEW_KEY=v" in text


def test_setup_provider_remove_in_use_blocked(patch_config_path: Path, config_file: Path, monkeypatch):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {"mini": {"model": "m", "provider": "Cloud"}},
        "custom": {},
    }))
    _fake_prompts(monkeypatch, ["remove", "Cloud", "done"])

    provider_cmd.setup_provider()
    data = yaml.safe_load(config_file.read_text())
    assert "Cloud" in data["providers"]  # still there — in use


def test_setup_provider_remove_unused(patch_config_path: Path, config_file: Path, monkeypatch):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
    }))
    _fake_prompts(monkeypatch, ["remove", "Cloud", "done"])

    provider_cmd.setup_provider()
    data = yaml.safe_load(config_file.read_text())
    assert "Cloud" not in data["providers"]


# --- add (script surface) ------------------------------------------------------

def test_add_requires_key_or_env(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        provider_cmd.add("Cloud", "https://cloud.com/v1", None, None)
    assert exc.value.exit_code == 1


def test_add_rejects_key_and_env(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        provider_cmd.add("Cloud", "https://cloud.com/v1", "sk-x", "ENV")
    assert exc.value.exit_code == 1


def test_add_writes_provider(patch_config_path: Path, config_file: Path):
    provider_cmd.add("Cloud", "https://cloud.com/v1/", None, "MY_ENV")
    data = yaml.safe_load(config_file.read_text())
    assert data["providers"]["Cloud"] == {
        "base_url": "https://cloud.com/v1",
        "api_key_env": "MY_ENV",
    }


# --- remove --------------------------------------------------------------------

def test_remove_unknown_provider_exits(patch_config_path: Path):
    with pytest.raises(typer.Exit) as exc:
        provider_cmd.remove("Ghost")
    assert exc.value.exit_code == 1


def test_remove_in_use_provider_exits(patch_config_path: Path, config_file: Path):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://c/v1", "api_key_env": "K"}},
        "adaptive": {"mini": {"model": "m", "provider": "Cloud"}},
        "custom": {},
    }))
    with pytest.raises(typer.Exit) as exc:
        provider_cmd.remove("Cloud")
    assert exc.value.exit_code == 1
    assert "Cloud" in yaml.safe_load(config_file.read_text())["providers"]


def test_remove_removes_unused_provider(patch_config_path: Path, config_file: Path):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://c/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
    }))
    provider_cmd.remove("Cloud")
    assert "Cloud" not in yaml.safe_load(config_file.read_text())["providers"]


def test_remove_blocked_by_classifier_usage(patch_config_path: Path, config_file: Path):
    config_file.write_text(yaml.safe_dump({
        "providers": {"Cloud": {"base_url": "https://c/v1", "api_key_env": "K"}},
        "adaptive": {},
        "custom": {},
        "classifier": {"model": "m", "provider": "Cloud"},
    }))
    with pytest.raises(typer.Exit):
        provider_cmd.remove("Cloud")