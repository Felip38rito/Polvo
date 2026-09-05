"""Configuration for the router.

Settings are read from the environment (optionally from a `.env` file loaded
by the caller). See `.env.example`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

import yaml

from .models import (
    ModelSpec,
    ProviderSpec,
    RouterModels,
    ADAPTIVE_TIERS,
)

def _load_dotenv(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

def load_models_yaml(path: Path | None) -> RouterModels | None:
    """Load a model table + classifier config from a YAML file.
    
    Returns None if the file is missing. Raises if the file is malformed or
    references an unknown tier/provider.
    """
    if path is None or not path.exists():
        return None
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Malformed models YAML at {path}: expected a mapping")

    # --- Providers ---
    providers: dict[str, ProviderSpec] = {}
    raw_providers = data.get("providers") or {}
    if not isinstance(raw_providers, dict):
        raise ValueError("'providers' must be a mapping")
    for name, pcfg in raw_providers.items():
        if not isinstance(pcfg, dict) or not pcfg.get("base_url"):
            raise ValueError(f"Provider '{name}' must define a 'base_url'")
        providers[str(name)] = ProviderSpec(
            base_url=str(pcfg["base_url"]).rstrip("/"),
            api_key=str(pcfg["api_key"]) if pcfg.get("api_key") else None,
            api_key_env=str(pcfg.get("api_key_env")) if "api_key_env" in pcfg else None,
        )

    # --- Tiers ---
    tiers: dict[str, ModelSpec] = {}
    raw_tiers = data.get("tiers") or {}
    if not isinstance(raw_tiers, dict):
        raise ValueError("'tiers' must be a mapping")
    for tier_key, spec in raw_tiers.items():
        tier_key = str(tier_key)
        if not isinstance(spec, dict) or not spec.get("model"):
            raise ValueError(f"Tier '{tier_key}' must define a 'model'")
        provider = str(spec.get("provider", "default"))
        if provider not in providers:
            raise ValueError(f"Tier '{tier_key}' references unknown provider '{provider}' in {path}")
        extra_params = spec.get("extra_params", {})
        if not isinstance(extra_params, dict):
            raise ValueError(f"extra_params for tier '{tier_key}' must be a mapping")
        tiers[tier_key] = ModelSpec(
            api_id=str(spec["model"]),
            description=str(spec.get("description", "")),
            provider=provider,
            name=str(spec["name"]) if spec.get("name") else None,
            extra_params=extra_params,
        )

    if not tiers:
        raise ValueError(f"At least one tier must be configured in {path}")

    # --- Classifier ---
    classifier = data.get("classifier") or {}
    if not isinstance(classifier, dict):
        raise ValueError("Classifier config must be a mapping")
    classifier_model = classifier.get("model")
    if not classifier_model:
        raise ValueError(f"Classifier must define a 'model' in {path}")
    classifier_model = str(classifier_model)
    classifier_provider = str(classifier.get("provider", "default"))
    if classifier_provider not in providers:
        raise ValueError(f"Classifier references unknown provider '{classifier_provider}' in {path}")
    min_classify_len = int(classifier.get("min_classify_len", 10))

    # --- Default Tier Derivation ---
    # Smallest configured adaptive tier in axis order
    default_tier = None
    for t in ADAPTIVE_TIERS:
        if t in tiers:
            default_tier = t
            break
    if default_tier is None:
        raise ValueError(f"No adaptive tiers (mini, air, pro, ultra) configured in {path}; needed for default fallback")

    return RouterModels(
        tiers=tiers,
        default_tier=default_tier,
        classifier_model=classifier_model,
        classifier_provider=classifier_provider,
        min_classify_len=min_classify_len,
        providers=providers,
    )

@dataclass
class Settings:
    ollama_api_key: str
    ollama_base_url: str = "https://ollama.com/v1"
    router_host: str = "127.0.0.1"
    router_port: int = 9000
    default_tier: str = "air"
    min_classify_len: int = 10
    require_auth: str = ""
    models: RouterModels = field(default_factory=RouterModels)
    project_root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def from_env(
        cls,
        dotenv_path: Path | None = None,
        default_models_yaml: Path | None = None,
    ) -> "Settings":
        _load_dotenv(dotenv_path)
        key = os.environ.get("OLLAMA_API_KEY", "").strip()
        require_auth = os.environ.get("ROUTER_API_KEY", "").strip()

        yaml_path_raw = os.environ.get("ROUTER_MODELS_YAML", "").strip()
        if yaml_path_raw:
            yaml_path: Path | None = Path(yaml_path_raw)
        else:
            user_cfg = Path.home() / ".config" / "polvo" / "config.yml"
            if user_cfg.exists():
                yaml_path = user_cfg
            else:
                yaml_path = default_models_yaml
        
        models = load_models_yaml(yaml_path) or RouterModels()

        return cls(
            ollama_api_key=key,
            ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "https://ollama.com/v1").rstrip("/"),
            router_host=os.environ.get("ROUTER_HOST", "127.0.0.1"),
            router_port=int(os.environ.get("ROUTER_PORT", "9000") or "9000"),
            default_tier=os.environ.get("ROUTER_DEFAULT_TIER", models.default_tier),
            min_classify_len=int(os.environ.get("ROUTER_MIN_CLASSIFY_LEN", str(models.min_classify_len)) or "10"),
            require_auth=require_auth,
            models=models,
        )

    @property
    def effective_api_key(self) -> str:
        if not self.ollama_api_key:
            raise RuntimeError("OLLAMA_API_KEY is not set")
        return self.ollama_api_key
