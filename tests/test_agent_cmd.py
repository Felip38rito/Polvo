"""Tests for the agent setup commands in Polvo CLI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from polvo_cli import agent_cmd, core


def test_setup_hermes_uses_port_from_env(monkeypatch):
    def fake_load(var, default=None):
        return "8080" if var == "ROUTER_PORT" else default

    monkeypatch.setattr(core, "load_env_var", fake_load)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        agent_cmd.setup_hermes()

    api_call = mock_run.call_args_list[0].args[0]
    assert api_call == ["hermes", "config", "set", "providers.router.api", "http://127.0.0.1:8080/v1"]


def test_setup_hermes_defaults_to_9000(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        agent_cmd.setup_hermes()

    api_call = mock_run.call_args_list[0].args[0]
    assert api_call == ["hermes", "config", "set", "providers.router.api", "http://127.0.0.1:9000/v1"]


def test_setup_hermes_provider_name_is_polvo(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        agent_cmd.setup_hermes()

    name_call = mock_run.call_args_list[1].args[0]
    assert name_call == ["hermes", "config", "set", "providers.router.name", "Polvo"]


def test_setup_hermes_sets_active_provider(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        agent_cmd.setup_hermes()

    provider_call = mock_run.call_args_list[3].args[0]
    assert provider_call == ["hermes", "config", "set", "model.provider", "router"]


def test_setup_hermes_reports_failure(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)

    calls = [MagicMock(returncode=0) if i != 1 else MagicMock(returncode=1) for i in range(9)]
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = calls
        agent_cmd.setup_hermes()

    assert mock_run.call_count == 9


def test_setup_opencode_uses_repo_script(monkeypatch):
    with patch("pathlib.Path.exists", return_value=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            agent_cmd.setup_opencode()

    args = mock_run.call_args.args[0]
    assert args[0] == "python3"
    assert "sync-opencode.py" in args[1]


def test_setup_opencode_missing_script_raises():
    with patch("pathlib.Path.exists", return_value=False):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(typer.Exit) as exc:
                agent_cmd.setup_opencode()
    assert exc.value.exit_code == 1
    mock_run.assert_not_called()


def test_setup_copilot_writes_to_env(monkeypatch):
    # Mock env load
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: "9000" if var == "ROUTER_PORT" else "router")
    
    # Mock Path.exists for shell profile and a dummy .env
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=""), \
         patch("pathlib.Path.write_text") as mock_write: # Not used as we use open(..., 'a')
        
        # We need to mock open() because we use 'with open(profile_path, "a")'
        with patch("builtins.open", MagicMock()) as mock_open:
            # Mock save_env_key to avoid touching real ~/.polvo/.env
            with patch("polvo_cli.core.save_env_key") as mock_save_env:
                agent_cmd.setup_copilot()
                
                # Verify all 3 Copilot vars were saved to .env
                assert mock_save_env.call_count == 3
                saved_vars = [call.args[0] for call in mock_save_env.call_args_list]
                assert "COPILOT_PROVIDER_BASE_URL" in saved_vars
                assert "COPILOT_PROVIDER_API_KEY" in saved_vars
                assert "COPILOT_MODEL" in saved_vars
                
                # Verify shell profile was modified
                mock_open.assert_called()


def test_setup_copilot_idempotent_profile(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)
    
    # Mock profile that already has the source line
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="source ~/.polvo/.env\n"), \
         patch("builtins.open") as mock_open:
        
        with patch("polvo_cli.core.save_env_key"):
            agent_cmd.setup_copilot()
            
            # open() should not be called for appending since line exists
            mock_open.assert_not_called()
