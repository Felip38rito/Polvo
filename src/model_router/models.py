from dataclasses import dataclass, field
from typing import Any

# The fixed axis of adaptive tiers. Order matters for default_tier derivation.
ADAPTIVE_TIERS = ("mini", "air", "pro", "ultra")

@dataclass(frozen=True)
class ProviderSpec:
    """A named upstream endpoint a tier (or the classifier) can point at.

    ``base_url`` is the provider's OpenAI-compatible ``/v1`` endpoint.
    ``api_key`` is the key provided inline.
    ``api_key_env`` is the environment variable holding that provider's key.
    """

    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None

    def resolve_api_key(self, fallback: str | None = None) -> str:
        """Resolve the API key from inline value, environment variable, or a provided fallback.
        
        Raises RuntimeError if both inline and env var are set (ambiguity), 
        or if no key is found at all.
        """
        import os
        inline = self.api_key
        env_var = self.api_key_env
        env_val = os.environ.get(env_var) if env_var else None

        if inline and env_val:
            raise RuntimeError(f"Ambiguous API key for provider: both inline and env var '{env_var}' are set.")
        
        res = env_val or inline or fallback
        if res is None:
            raise RuntimeError(f"No API key found for provider: inline is empty, env var '{env_var}' is not set, and no fallback provided.")
        return res

@dataclass(frozen=True)
class ModelSpec:
    api_id: str
    description: str
    # Which named provider (see Settings.providers) serves this tier.
    provider: str = "default"
    # Optional display/route alias. If set, /v1/models advertises this as the
    # model id and the proxy accepts it as an alias for the tier. If None,
    # the tier key (mini/air/pro/ultra) is used. Never affects the classifier's
    # internal key.
    name: str | None = None
    # Arbitrary provider-specific parameters (e.g. reasoning_effort,
    # budget_tokens) merged into the upstream request body for this tier.
    extra_params: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RouterModels:
    """Mounted model table + classifier config for the running router."""

    tiers: dict[str, ModelSpec] = field(default_factory=dict)
    default_tier: str = "air"
    classifier_model: str = "gemma4:31b"
    # Which named provider serves the classifier (defaults to "default").
    classifier_provider: str = "default"
    min_classify_len: int = 10
    # Named upstream endpoints. Each tier's ModelSpec.provider keys into this.
    providers: dict[str, ProviderSpec] = field(default_factory=dict)

    def tier_for_alias(self, alias: str) -> str | None:
        """Resolve a model id, display name, or tier key to a tier key."""
        for tier_key, spec in self.tiers.items():
            if spec.api_id == alias or (spec.name and spec.name == alias) or tier_key == alias:
                return tier_key
        return None

    def provider_for(self, provider_name: str) -> ProviderSpec:
        """Resolve a provider name to its spec."""
        if provider_name not in self.providers:
            raise ValueError(f"Unknown provider '{provider_name}'")
        return self.providers[provider_name]

    def adaptive_tiers(self) -> list[str]:
        """Return currently configured adaptive tiers in axis order."""
        return [t for t in ADAPTIVE_TIERS if t in self.tiers]

    def is_adaptive(self, tier_key: str) -> bool:
        """True if the tier is one of the 4 adaptive ones."""
        return tier_key in ADAPTIVE_TIERS
