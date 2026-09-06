"""Tests for the agent setup commands in Polvo CLI."""
from __future__ import annotations

import json
import re
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


# --- claude code setup ---------------------------------------------------------

def test_setup_claude_saves_env_vars(monkeypatch):
    monkeypatch.setattr(core, "load_env_var",
                        lambda var, default=None: "9000" if var == "ROUTER_PORT" else default)
    saved = {}
    monkeypatch.setattr(core, "save_env_key", lambda var, val, path=None: saved.update({var: val}))
    monkeypatch.setattr("polvo_cli.agent_cmd._warn_claude_settings_conflicts", lambda: None)
    monkeypatch.setattr("polvo_cli.agent_cmd._ensure_shell_source", lambda: True)

    agent_cmd.setup_claude_code()

    assert saved["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"
    assert saved["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "mini"
    assert saved["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "pro"
    assert saved["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "ultra"
    assert saved["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in saved


def test_setup_claude_base_url_has_no_v1_suffix(monkeypatch):
    """Regression: '/v1' in ANTHROPIC_BASE_URL yields /v1/v1/messages — the
    client appends the path itself."""
    monkeypatch.setattr(core, "load_env_var",
                        lambda var, default=None: "9000" if var == "ROUTER_PORT" else default)
    saved = {}
    monkeypatch.setattr(core, "save_env_key", lambda var, val, path=None: saved.update({var: val}))
    monkeypatch.setattr("polvo_cli.agent_cmd._warn_claude_settings_conflicts", lambda: None)
    monkeypatch.setattr("polvo_cli.agent_cmd._ensure_shell_source", lambda: True)

    agent_cmd.setup_claude_code()

    assert not saved["ANTHROPIC_BASE_URL"].rstrip("/").endswith("/v1")


def test_setup_claude_saves_auth_token(monkeypatch):
    monkeypatch.setattr(core, "load_env_var",
                        lambda var, default=None: "router" if var == "ROUTER_API_KEY" else "9000")
    saved = {}
    monkeypatch.setattr(core, "save_env_key", lambda var, val, path=None: saved.update({var: val}))
    monkeypatch.setattr("polvo_cli.agent_cmd._warn_claude_settings_conflicts", lambda: None)
    monkeypatch.setattr("polvo_cli.agent_cmd._ensure_shell_source", lambda: True)

    agent_cmd.setup_claude_code()

    assert saved["ANTHROPIC_AUTH_TOKEN"] == "router"
    assert "ANTHROPIC_API_KEY" not in saved  # AUTH_TOKEN, not API_KEY


def test_setup_claude_context_tokens_option(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)
    saved = {}
    monkeypatch.setattr(core, "save_env_key", lambda var, val, path=None: saved.update({var: val}))
    monkeypatch.setattr("polvo_cli.agent_cmd._warn_claude_settings_conflicts", lambda: None)
    monkeypatch.setattr("polvo_cli.agent_cmd._ensure_shell_source", lambda: True)

    agent_cmd.setup_claude_code(context_tokens=200000)

    assert saved["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "200000"


def test_setup_claude_ensures_shell_profile(monkeypatch):
    monkeypatch.setattr(core, "load_env_var", lambda var, default=None: default)
    monkeypatch.setattr(core, "save_env_key", lambda var, val, path=None: None)
    monkeypatch.setattr("polvo_cli.agent_cmd._warn_claude_settings_conflicts", lambda: None)
    called = {}
    monkeypatch.setattr("polvo_cli.agent_cmd._ensure_shell_source", lambda: called.update(x=True) or True)

    agent_cmd.setup_claude_code()
    assert called.get("x")


def test_warn_claude_settings_conflicts_detects_env_block(tmp_path, monkeypatch, capsys):
    settings = tmp_path / ".claude"
    settings.mkdir()
    (settings / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://old-proxy.example.com"}})
    )
    monkeypatch.setattr(agent_cmd.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    agent_cmd._warn_claude_settings_conflicts()

    out = capsys.readouterr().err
    # Rich wraps lines and emits ANSI codes — normalize before matching.
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", out).split())
    assert "ANTHROPIC_BASE_URL" in plain
    assert "override the shell environment" in plain


def test_warn_claude_settings_conflicts_silent_when_clean(tmp_path, monkeypatch, capsys):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"env": {"OTHER_VAR": "x"}}))
    monkeypatch.setattr(agent_cmd.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    agent_cmd._warn_claude_settings_conflicts()

    out = capsys.readouterr().err
    plain = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", out).split())
    assert "override the shell environment" not in plain


def test_warn_claude_settings_conflicts_tolerates_broken_json(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json")
    monkeypatch.setattr(agent_cmd.Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    agent_cmd._warn_claude_settings_conflicts()  # must not raise


def test_agent_claude_cli_end_to_end(tmp_path):
    """Dry run of `polvo agent claude` in a subprocess with a temp HOME —
    validates the real CLI wiring (Typer command, env file, shell profile)
    without touching the user's actual ~/.polvo/.env or ~/.zshrc."""
    import os
    import subprocess
    import sys

    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("# existing profile\n")

    env = {
        **{k: v for k, v in os.environ.items() if k != "ROUTER_PORT"},
        "HOME": str(home),
        "SHELL": "/bin/zsh",
    }
    polvo = Path(sys.executable).parent / "polvo"
    result = subprocess.run(
        [str(polvo), "agent", "claude"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    env_file = (home / ".polvo" / ".env").read_text()
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:9000" in env_file
    assert "ANTHROPIC_AUTH_TOKEN=router" in env_file
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL=pro" in env_file
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1" in env_file

    zshrc = (home / ".zshrc").read_text()
    assert "source ~/.polvo/.env" in zshrc
