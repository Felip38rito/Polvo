"""Tests for config + model table loading (adaptive + custom design)."""
from pathlib import Path

import pytest
import yaml

from model_router.config import Settings, load_models_yaml
from model_router.models import ModelSpec, RouterModels


# --- load_models_yaml: adaptive + custom -------------------------------------

def test_load_yaml_adaptive_and_custom(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive:
  mini:
    model: m-mini
    provider: p1
  pro:
    model: m-pro
    provider: p1
custom:
  my-special:
    model: m-special
    provider: p1
classifier:
  model: class-m
  provider: p1
""")
    models = load_models_yaml(cfg)
    assert models is not None
    assert set(models.tiers.keys()) == {"mini", "pro", "my-special"}
    assert models.tiers["mini"].api_id == "m-mini"
    assert models.tiers["my-special"].api_id == "m-special"
    # custom subset tracked separately
    assert set(models.custom_models.keys()) == {"my-special"}
    # default_tier derived: smallest adaptive configured
    assert models.default_tier == "mini"


def test_load_yaml_default_tier_derivation_order(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive:
  pro:
    model: m-pro
    provider: p1
  ultra:
    model: m-ultra
    provider: p1
classifier:
  model: class-m
  provider: p1
""")
    models = load_models_yaml(cfg)
    assert models is not None
    # default is the smallest adaptive present (pro < ultra)
    assert models.default_tier == "pro"


def test_load_yaml_missing_returns_none(tmp_path: Path):
    assert load_models_yaml(tmp_path / "nope.yaml") is None


def test_load_yaml_zero_models_raises(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive: {}
custom: {}
classifier:
  model: m
  provider: p1
""")
    with pytest.raises(ValueError, match="At least one model"):
        load_models_yaml(cfg)


def test_load_yaml_custom_only_allowed(tmp_path: Path):
    """A config with only custom models is valid (no adaptive required)."""
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
custom:
  only-extra:
    model: m
    provider: p1
classifier:
  model: c
  provider: p1
""")
    models = load_models_yaml(cfg)
    assert models is not None
    assert models.default_tier is None
    assert models.has_adaptive() is False
    assert models.is_custom("only-extra") is True


def test_load_yaml_unknown_adaptive_tier_raises(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive:
  bogus:
    model: m
    provider: p1
classifier:
  model: c
  provider: p1
""")
    with pytest.raises(ValueError, match="Unknown adaptive tier 'bogus'"):
        load_models_yaml(cfg)


def test_load_yaml_custom_collides_with_adaptive_raises(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
custom:
  mini:
    model: m
    provider: p1
classifier:
  model: c
  provider: p1
""")
    with pytest.raises(ValueError, match="collides with an adaptive tier name"):
        load_models_yaml(cfg)


def test_load_yaml_classifier_model_required(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive:
  mini:
    model: m
    provider: p1
classifier:
  provider: p1
""")
    with pytest.raises(ValueError, match="Classifier must define a 'model'"):
        load_models_yaml(cfg)


def test_load_yaml_unknown_tier_provider_raises(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  p1:
    base_url: https://x.com/v1
adaptive:
  mini:
    model: m
    provider: nope
classifier:
  model: c
  provider: p1
""")
    with pytest.raises(ValueError, match="unknown provider"):
        load_models_yaml(cfg)


def test_load_yaml_multi_provider(tmp_path: Path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("""\
providers:
  default:
    base_url: https://ollama.com/v1
    api_key_env: OLLAMA_API_KEY
  gemini:
    base_url: https://gen.com/v1
    api_key_env: GEMINI_API_KEY
adaptive:
  mini:
    model: gemma4:31b
  air:
    model: deepseek-v4-flash:0731
  pro:
    model: gemini-2.5-pro
    provider: gemini
  ultra:
    model: kimi-k3
classifier:
  model: gemma4:31b
  provider: default
""")
    models = load_models_yaml(cfg)
    assert models is not None
    assert models.tiers["pro"].provider == "gemini"
    assert models.tiers["mini"].provider == "default"
    assert "gemini" in models.providers


# --- no default providers -----------------------------------------------------

def test_router_models_empty_providers_has_no_fallback():
    """No DEFAULT_PROVIDERS anymore — provider_for must raise on unknown."""
    models = RouterModels(tiers={"mini": ModelSpec("x", "d")}, default_tier="mini")
    assert models.providers == {}
    with pytest.raises(ValueError, match="Unknown provider 'nope'"):
        models.provider_for("nope")


# --- Settings.from_env --------------------------------------------------------

def test_settings_from_env_without_models(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("ROUTER_MODELS_YAML", raising=False)
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    env = tmp_path / ".env"
    env.write_text("OLLAMA_API_KEY=secret\nROUTER_PORT=9999\n")
    s = Settings.from_env(env)
    assert s.ollama_api_key == "secret"
    assert s.router_port == 9999
