"""Tests for the polvo CLI entrypoint (main.py)."""
from __future__ import annotations

from pathlib import Path
import pytest
import typer
import yaml
from typer.testing import CliRunner

from polvo_cli import core, main

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

# --- models usage ------------------------------------------------------------

def test_models_no_provider_shows_usage(runner: CliRunner, monkeypatch, tmp_path: Path):
    """'polvo models' with no provider should show available providers, not a raw error."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({
        "providers": {"Ollama Cloud": {"base_url": "https://ollama.com/v1"}},
    }))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    result = runner.invoke(main.app, ["models"])
    assert result.exit_code == 1
    assert "Available providers: Ollama Cloud" in result.output

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
    assert "No tiers configured" in result.output
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

# --- Onboarding Flow (Bare `polvo`) --------------------------------------------

def test_bare_polvo_shows_overview_when_ready(runner: CliRunner, monkeypatch, tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({
        "providers": {"A": {"base_url": "x"}},
        "adaptive": {"mini": {"model": "m", "provider": "A"}},
        "classifier": {"model": "c", "provider": "A"},
    }))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    result = runner.invoke(main.app, [])
    assert result.exit_code == 0
    assert "config ready" in result.output
    assert "Providers:   A" in result.output

def test_bare_polvo_triggers_wizard_when_missing_provider(runner: CliRunner, monkeypatch, tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    called = {"add_first_provider": 0}

    def fake_add_first():
        called["add_first_provider"] += 1
        raise typer.Exit(code=0)

    monkeypatch.setattr(main, "add_first_provider", fake_add_first)
    result = runner.invoke(main.app, [])
    assert called["add_first_provider"] == 1
    assert result.exit_code == 0
    assert "You don't have providers yet" in result.output

def test_bare_polvo_overview_when_not_ready(runner: CliRunner, monkeypatch, tmp_path: Path):
    """Test _print_overview called with ready=False."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({
        "providers": {"A": {"base_url": "x"}},
        "adaptive": {},
        "classifier": {},
    }))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    monkeypatch.setattr(main, "config_problems", lambda: ["Missing tiers"])
    monkeypatch.setattr(main, "setup_tier", lambda: None)
    
    result = runner.invoke(main.app, [])
    assert "Current config:" in result.output
    assert "Providers:   A" in result.output

def test_bare_polvo_full_onboarding_flow(runner: CliRunner, monkeypatch, tmp_path: Path):
    """Test the sequence: Providers -> Tiers -> Start."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    
    def mock_add_first():
        core.save_config({"providers": {"Cloud": {}}, "adaptive": {}, "custom": {}})
    def mock_setup_tier():
        core.save_config({
            "providers": {"Cloud": {}}, 
            "adaptive": {"mini": {"model": "m", "provider": "Cloud"}},
            "classifier": {"model": "c", "provider": "Cloud"}
        })

    monkeypatch.setattr(main, "add_first_provider", mock_add_first)
    monkeypatch.setattr(main, "setup_tier", mock_setup_tier)
    monkeypatch.setattr(main, "_run_polvoctl", lambda *a: None)
    
    # Fix the mock for typer.confirm to avoid the "Aborted" error
    # We need to handle both calls: 1. "add another provider?" (No), 2. "Start the router?" (Yes)
    confirm_calls = iter([False, True])
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: next(confirm_calls))
    
    result = runner.invoke(main.app, [])
    assert result.exit_code == 0
    assert "Config complete!" in result.output

def test_bare_polvo_still_incomplete(runner: CliRunner, monkeypatch, tmp_path: Path):
    """Test onboarding fails if config is still broken."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(yaml.safe_dump({"providers": {}, "adaptive": {}, "custom": {}}))
    monkeypatch.setattr(core, "config_path", lambda: cfg)
    
    monkeypatch.setattr(main, "add_first_provider", lambda: None)
    monkeypatch.setattr(main, "setup_tier", lambda: None)
    monkeypatch.setattr(main, "config_problems", lambda: ["Still broken"])
    
    # Mock confirm to avoid "Aborted"
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    
    result = runner.invoke(main.app, [])
    assert result.exit_code == 1
    assert "Config is still incomplete" in result.output
    assert "Still broken" in result.output
