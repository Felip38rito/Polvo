"""Tests for the polvo CLI entrypoint (main.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from polvo_cli import config_cmd, main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def patch_polvoctl(monkeypatch):
    """Stub _run_polvoctl so service commands don't shell out."""
    calls: list[list[str]] = []

    def fake_run(*args: str) -> None:
        calls.append(list(args))

    monkeypatch.setattr(main, "_run_polvoctl", fake_run)
    return calls


# --- version ----------------------------------------------------------------

def test_version(runner: CliRunner):
    result = runner.invoke(main.app, ["version"])
    assert result.exit_code == 0
    assert "polvo" in result.output


# --- config list / set ------------------------------------------------------

def test_config_list(runner: CliRunner, monkeypatch, tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "tiers:\n  mini:\n    model: gemma4:31b\n  air:\n    model: x\n"
        "  pro:\n    model: y\n  ultra:\n    model: z\n"
    )
    monkeypatch.setattr(config_cmd, "config_path", lambda: cfg)
    result = runner.invoke(main.app, ["config", "list"])
    assert result.exit_code == 0
    assert "gemma4:31b" in result.output


def test_config_set_missing_args(runner: CliRunner):
    result = runner.invoke(main.app, ["config", "set", "pro"])
    assert result.exit_code == 1
    assert "Usage" in result.output


def test_config_unknown_action(runner: CliRunner):
    result = runner.invoke(main.app, ["config", "bogus"])
    assert result.exit_code == 1
    assert "Unknown config action" in result.output


def test_config_no_action_lists(runner: CliRunner, monkeypatch, tmp_path: Path):
    """'polvo config' with no action should list, not error."""
    cfg = tmp_path / "config.yml"
    cfg.write_text("tiers:\n  mini:\n    model: gemma4:31b\n")
    monkeypatch.setattr(config_cmd, "config_path", lambda: cfg)
    result = runner.invoke(main.app, ["config"])
    assert result.exit_code == 0
    assert "gemma4:31b" in result.output


def test_models_no_provider_shows_usage(runner: CliRunner, monkeypatch, tmp_path: Path):
    """'polvo models' with no provider should show available providers, not a raw error."""
    from polvo_cli import validate

    cfg = tmp_path / "config.yml"
    cfg.write_text("providers:\n  Ollama Cloud:\n    base_url: https://ollama.com/v1\n")
    monkeypatch.setattr(validate, "config_path", lambda: cfg)
    result = runner.invoke(main.app, ["models"])
    assert result.exit_code == 1
    assert "Usage: polvo models" in result.output
    assert "Ollama Cloud" in result.output


def test_provider_add_no_args_shows_usage(runner: CliRunner):
    result = runner.invoke(main.app, ["provider", "add"])
    assert result.exit_code == 1
    assert "Usage: polvo provider add" in result.output


def test_tier_set_no_args_shows_usage(runner: CliRunner):
    result = runner.invoke(main.app, ["tier", "set"])
    assert result.exit_code == 1
    assert "Usage: polvo tier set" in result.output


# --- service lifecycle (via _run_polvoctl stub) ------------------------------

@pytest.fixture
def ready(monkeypatch):
    """Stub config validation so service commands don't read the real config."""
    monkeypatch.setattr(main, "config_problems", lambda: [])


def test_start(runner: CliRunner, patch_polvoctl, ready):
    result = runner.invoke(main.app, ["start"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["start"]]


def test_install_with_port(runner: CliRunner, patch_polvoctl, ready):
    result = runner.invoke(main.app, ["install", "--port", "9001"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["install", "--port", "9001"]]


def test_install_default_port(runner: CliRunner, patch_polvoctl, ready):
    result = runner.invoke(main.app, ["install"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["install", "--port", "9000"]]


def test_uninstall(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["uninstall"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["uninstall"]]


def test_stop(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["stop"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["stop"]]


def test_restart(runner: CliRunner, patch_polvoctl, ready):
    result = runner.invoke(main.app, ["restart"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["restart"]]


def test_status(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["status"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["status"]]


def test_logs(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["logs"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["logs"]]


def test_tail(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["tail"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["tail"]]


# --- _run_polvoctl error handling --------------------------------------------

def test_run_polvoctl_nonzero_exit(monkeypatch):
    class FakeProc:
        returncode = 3

    monkeypatch.setattr(main, "_find_polvoctl", lambda: Path("/fake/polvoctl.sh"))
    monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: FakeProc())
    with pytest.raises(typer.Exit) as exc:
        main._run_polvoctl("status")
    assert exc.value.exit_code == 3


def test_run_polvoctl_file_not_found(monkeypatch):
    monkeypatch.setattr(main, "_find_polvoctl", lambda: Path("/fake/polvoctl.sh"))
    monkeypatch.setattr(
        main.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )
    with pytest.raises(typer.Exit) as exc:
        main._run_polvoctl("status")
    assert exc.value.exit_code == 1


# --- _find_polvoctl ----------------------------------------------------------

def test_find_polvoctl_missing_raises(monkeypatch):
    monkeypatch.setattr(main, "POLVOCTL", Path("/nonexistent/polvoctl.sh"))
    monkeypatch.setattr(main.shutil, "which", lambda _: None)
    with pytest.raises(typer.Exit) as exc:
        main._find_polvoctl()
    assert exc.value.exit_code == 1


# --- config validation on start ----------------------------------------------

def test_start_blocks_when_config_incomplete(runner: CliRunner, patch_polvoctl, monkeypatch):
    monkeypatch.setattr(
        main, "config_problems", lambda: ["No providers configured. Run 'polvo provider' to add one."]
    )
    result = runner.invoke(main.app, ["start"])
    assert result.exit_code == 1
    assert "can't start" in result.output
    assert "No providers configured" in result.output
    assert patch_polvoctl == []  # never reached polvoctl


def test_install_blocks_when_config_incomplete(runner: CliRunner, patch_polvoctl, monkeypatch):
    monkeypatch.setattr(
        main, "config_problems", lambda: ["No tiers configured. Run 'polvo tier' to add one."]
    )
    result = runner.invoke(main.app, ["install"])
    assert result.exit_code == 1
    assert "can't start" in result.output
    assert patch_polvoctl == []


# --- provider / tier wizards (no subcommand) ---------------------------------

def test_provider_no_subcommand_opens_wizard(runner: CliRunner, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main, "setup_provider", lambda: called.update(n=1))
    result = runner.invoke(main.app, ["provider"])
    assert result.exit_code == 0
    assert called["n"] == 1


def test_tier_no_subcommand_opens_wizard(runner: CliRunner, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main, "setup_tier", lambda: called.update(n=1))
    result = runner.invoke(main.app, ["tier"])
    assert result.exit_code == 0
    assert called["n"] == 1


def test_tiers_plural_alias_opens_wizard(runner: CliRunner, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(main, "setup_tier", lambda: called.update(n=1))
    result = runner.invoke(main.app, ["tiers"])
    assert result.exit_code == 0
    assert called["n"] == 1


def test_provider_subcommand_still_works(runner: CliRunner, monkeypatch):
    """'polvo provider list' must NOT open the wizard."""
    called = {"n": 0}
    monkeypatch.setattr(main, "setup_provider", lambda: called.update(n=1))
    monkeypatch.setattr(main, "list_providers", lambda: None)
    result = runner.invoke(main.app, ["provider", "list"])
    assert result.exit_code == 0
    assert called["n"] == 0
