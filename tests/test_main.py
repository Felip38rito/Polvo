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


# --- service lifecycle (via _run_polvoctl stub) ------------------------------

def test_start(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["start"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["start"]]


def test_install_with_port(runner: CliRunner, patch_polvoctl):
    result = runner.invoke(main.app, ["install", "--port", "9001"])
    assert result.exit_code == 0
    assert patch_polvoctl == [["install", "--port", "9001"]]


def test_install_default_port(runner: CliRunner, patch_polvoctl):
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


def test_restart(runner: CliRunner, patch_polvoctl):
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
