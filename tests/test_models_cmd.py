"""Tests for models_cmd: provider model discovery."""
from __future__ import annotations

from pathlib import Path
import pytest
import typer
import yaml
import httpx
from unittest.mock import MagicMock

from polvo_cli import core, models_cmd
from model_router.models import ProviderSpec

@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return tmp_path / "config.yml"

@pytest.fixture
def patch_config_path(monkeypatch, config_file: Path) -> Path:
    monkeypatch.setattr(core, "config_path", lambda: config_file)
    return config_file

def _seed_provider(config_file: Path, provider_name="Cloud") -> None:
    config_file.write_text(yaml.safe_dump({
        "providers": {provider_name: {"base_url": "https://cloud.com/v1", "api_key_env": "K"}},
        "adaptive": {"mini": {"model": "m1", "provider": provider_name}},
        "custom": {},
        "classifier": {"model": "classifier-model", "provider": provider_name},
    }))

def test_list_models_success(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "model-1"}, {"id": "model-2"}]}
    
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_response)
    monkeypatch.setattr(ProviderSpec, "resolve_api_key", lambda self: "fake-key")

    models_cmd.list_models("Cloud")

def test_list_models_unknown_provider(patch_config_path: Path, config_file: Path):
    _seed_provider(config_file)
    with pytest.raises(typer.Exit) as exc:
        models_cmd.list_models("Ghost")
    assert exc.value.exit_code == 1

def test_list_models_config_missing(monkeypatch):
    monkeypatch.setattr(core, "config_path", lambda: Path("/tmp/non_existent_polvo_config.yml"))
    with pytest.raises(typer.Exit) as exc:
        models_cmd.list_models("Cloud")
    assert exc.value.exit_code == 1

def test_list_models_upstream_http_error(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    
    def raise_error(*a, **k):
        raise httpx.HTTPError("Network fail")
    
    monkeypatch.setattr(httpx, "get", raise_error)
    monkeypatch.setattr(ProviderSpec, "resolve_api_key", lambda self: "fake-//key")
    # Corrected below
    monkeypatch.setattr(ProviderSpec, "resolve_api_key", lambda self: "fake-key")
    
    with pytest.raises(typer.Exit) as exc:
        models_cmd.list_models("Cloud")
    assert exc.value.exit_code == 1

def test_list_models_upstream_api_error(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_response)
    monkeypatch.setattr(ProviderSpec, "resolve_api_key", lambda self: "fake-key")
    
    with pytest.raises(typer.Exit) as exc:
        models_cmd.list_models("Cloud")
    assert exc.value.exit_code == 1

def test_list_models_empty_response(patch_config_path: Path, config_file: Path, monkeypatch):
    _seed_provider(config_file)
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    
    monkeypatch.setattr(httpx, "get", lambda *a, **k: mock_response)
    monkeypatch.setattr(ProviderSpec, "resolve_api_key", lambda self: "fake-key")
    
    models_cmd.list_models("Cloud")
