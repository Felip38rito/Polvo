"""Hybrid router classifier.

The tier decision is fundamentally QUALITATIVE — it depends on intent, scope,
and context, not surface keywords. So the LLM is the PRIMARY decider, and the
deterministic layer is reduced to the two things it can do reliably:

1. An explicit model override in the prompt ("use deepseek-v4-pro") — always wins.
2. Obviously-trivial chatter (very short prompts) — routed to default_tier to save a
   round-trip.

Everything else is deferred to the LLM, which returns a strict
JSON decision. On any error the classifier degrades to the default tier —
it never fails the request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from .models import RouterModels

log = logging.getLogger("model_router.classify")

# Classification is on the critical path of every request, so keep the upstream
# call fast: a short total timeout with a couple of quick retries to transient
# failures is better than letting each request hang for 30s before falling back.
_CLASSIFY_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# max_tokens must leave headroom for the JSON decision even if the model emits a
# little preamble before it; 120 was truncating the JSON and causing parse
# failures. 256 keeps the reply cheap but safe.
_CLASSIFY_MAX_TOKENS = 256
# Transient HTTP statuses worth retrying (server-side/upstream blips).
_RETRY_STATUS = {500, 502, 503, 504}
# Attempts total (1 initial + up to 2 retries).
_RETRY_ATTEMPTS = 3

# Explicit model override wins over everything: "use deepseek-v4-pro", etc.
_OVERRIDE_WORDS_RE = re.compile(r"\b[a-z0-9_.:\-]+\b", re.IGNORECASE)

def _model_override(prompt: str, models: RouterModels) -> str | None:
    # Map each tier's api id -> tier key. Users reference the bare model name
    # ("deepseek-v4-pro"), while the api id carries a version suffix
    # ("deepseek-v4-pro:0813"), so BOTH the full id and its base are matched.
    lookup: dict[str, str] = {}
    for tier_key, spec in models.tiers.items():
        lookup[spec.api_id.lower()] = tier_key
        lookup[spec.api_id.split(":", 1)[0].lower()] = tier_key
        if spec.name:
            lookup[spec.name.lower()] = tier_key
    for token in _OVERRIDE_WORDS_RE.findall(prompt):
        tier = lookup.get(token.lower())
        if tier is not None:
            return tier
    return None

def deterministic_tier(prompt: str, min_classify_len: int = 10, models: RouterModels | None = None) -> str | None:
    """Decide only the obvious cases; return None to defer to the LLM.

    Two deterministic decisions, nothing more:

    1. Explicit model/tier override — always wins, even for short prompts.
    2. Very short prompt (trivial chatter) — default_tier.

    Everything else returns None so the LLM makes the qualitative call.
    """
    models = models or RouterModels()

    # 1. Explicit override wins over everything, including the length check.
    override = _model_override(prompt, models)
    if override is not None:
        return override

    # 2. Trivial chatter: too short to be a real task.
    if len(prompt) < min_classify_len and models.default_tier is not None:
        return models.default_tier

    # 3. Defer to the LLM for the qualitative decision.
    return None

def build_llm_system(models: "RouterModels") -> str:
    """Build the classifier system prompt from the tier table.

    The escalation axis and output format are fixed; only the per-tier
    descriptions are injected from the config (customized or default).
    """
    tier_lines = "\n".join(
        f"- {t} = {models.tiers[t].description}" for t in models.adaptive_tiers()
    )
    return f"""You are a model router. Pick the most appropriate model tier for the user's request.

Reply with ONLY a single JSON object, no commentary, no preamble, no markdown blocks. 
If you add any text outside the JSON, the system will fail.

Format: {{"model": "<tier>", "reason": "<short>"}}

Tier definitions:
{tier_lines}

Decide by what EXECUTING the request requires, using this escalation axis:
1. mini -> air: file scope. Single-file/mechanical work stays in mini; multi-file features and routine integrations move to air.
2. air -> pro: clarity of path. If the implementation path is clear, it stays in air; if the solution must be discovered (analysis, debugging, design), it escalates to pro.
3. pro -> ultra: scope. A hard but contained problem stays in pro; only whole-system synthesis or "impossible" problems reach ultra.

Examples:
{{"model": "mini", "reason": "simple greeting"}}
{{"model": "air", "reason": "implementing a feature across multiple files"}}
{{"model": "pro", "reason": "deep debugging, root-cause analysis required"}}
{{"model": "ultra", "reason": "whole-codebase refactor, deep synthesis required"}}"""

def _extract_json_object(text: str) -> dict | None:
    """Robustly extract the first top-level JSON object from a model reply."""
    if not text:
        return None
    start = text.find("{")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None

async def _classify_once(
    *,
    api_key: str,
    base_url: str,
    classifier_model: str,
    prompt: str,
    system_prompt: str,
    client: httpx.AsyncClient,
) -> httpx.Response:
    """Issue a single classifier request to the upstream."""
    body = {
        "model": classifier_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt[:4000]},
        ],
        "temperature": 0,
        "max_tokens": _CLASSIFY_MAX_TOKENS,
        "stream": False,
        "format": "json",
    }
    resp = await client.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
    )
    return resp

async def _parse_tier_response(resp: httpx.Response, models: "RouterModels") -> str | None:
    """Parse a classifier HTTP response into a tier key, or None on any failure."""
    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/json":
        log.warning("LLM classifier got non-JSON content-type %r (status %s); defaulting", ctype, resp.status_code)
        return None

    raw = resp.text
    if not raw or not raw.strip():
        log.warning("LLM classifier returned empty body (status %s); defaulting", resp.status_code)
        return None

    try:
        data = resp.json()
    except json.JSONDecodeError:
        snippet = raw[:200].replace("\n", " ")
        log.warning("LLM classifier returned invalid JSON (status %s): %r; defaulting", resp.status_code, snippet)
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        log.warning("LLM classifier response missing choices/message/content; defaulting")
        return None

    if not content or not str(content).strip():
        log.warning("LLM classifier returned empty content (status %s); defaulting", resp.status_code)
        return None

    obj = _extract_json_object(str(content))
    if obj is None:
        log.warning("LLM classifier reply had no parseable JSON object: %r; defaulting", str(content)[:200])
        return None

    candidate = str(obj.get("model", "")).strip().lower()
    
    # LOG THE CLASSIFIER DECISION FOR THE TAIL
    log.info("CLASSIFIER_DECISION: prompt=%s | response=%s | picked=%s", 
              "[MASKED]", str(obj), candidate)

    if models.is_adaptive(candidate):
        return candidate
    log.warning("LLM classifier returned unknown or non-adaptive tier %r", candidate)
    return None

async def llm_tier(
    prompt: str,
    models: "RouterModels",
    *,
    api_key: str,
    base_url: str,
    classifier_model: str = "gemma4:31b",
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Classify via a cheap LLM, with retry on transient failures."""
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=_CLASSIFY_TIMEOUT)

    last_exc: Exception | None = None
    try:
        for attempt in range(_RETRY_ATTEMPTS):
            if attempt > 0:
                delay = 0.1 * (2 ** (attempt - 1)) + (0.05 * attempt)
                await asyncio.sleep(delay)
            try:
                resp = await _classify_once(
                    api_key=api_key,
                    base_url=base_url,
                    classifier_model=classifier_model,
                    prompt=prompt,
                    system_prompt=build_llm_system(models),
                    client=client,
                )
                if resp.status_code in _RETRY_STATUS:
                    log.warning("LLM classifier upstream %s on attempt %d; retrying", resp.status_code, attempt + 1)
                    last_exc = httpx.HTTPStatusError(f"status {resp.status_code}", request=resp.request, response=resp)
                    continue
                resp.raise_for_status()
                tier = await _parse_tier_response(resp, models)
                return tier
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                log.warning("LLM classifier transport error on attempt %d: %s", attempt + 1, exc)
                continue
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                log.warning("LLM classifier HTTP %s (%s); defaulting", exc.response.status_code, exc)
                break
    finally:
        if own_client:
            await client.aclose()

    log.warning("LLM classifier failed (%s); defaulting", last_exc)
    return None

async def classify(
    prompt: str,
    settings: Any,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Full hybrid path. Deterministic (override/trivial) first, LLM primary,
    default last.
    """
    det = deterministic_tier(prompt, settings.min_classify_len, settings.models)
    if det is not None:
        return det
    classifier_provider = settings.models.provider_for(settings.models.classifier_provider)
    llm = await llm_tier(
        prompt,
        models=settings.models,
        api_key=classifier_provider.resolve_api_key(),
        base_url=classifier_provider.base_url,
        classifier_model=settings.models.classifier_model,
        client=client,
    )
    if llm is not None:
        return llm
    if settings.models.default_tier is None:
        raise RuntimeError("Classifier failed and no adaptive tier is configured to fall back to.")
    return settings.models.default_tier
