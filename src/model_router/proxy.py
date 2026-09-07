"""OpenAI-compatible relay: /v1/chat/completions + /v1/responses + /v1/messages + /v1/models.

The router accepts a request, picks the cheapest adequate tier,
and streams the completion back from an upstream provider under that tier's model id.

/v1/messages serves Anthropic-protocol clients (Claude Code) by translating
between the Messages API and Chat Completions (see anthropic_translate).
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any

import httpx
import importlib.metadata
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import anthropic_translate
from .classify import classify
from .config import Settings
from .models import RouterModels
from . import responses as responses_translate

log = logging.getLogger("model_router.proxy")

router = APIRouter()


def _model_list_payload(models: "RouterModels") -> dict[str, Any]:
    """Advertise the virtual + model ids the router understands.

    Always advertises the 'adaptive' virtual model (if any adaptive tier is
    configured) plus every configured model (adaptive + custom), tagged by type.
    """
    data = []
    if models.has_adaptive():
        data.append(
            {
                "id": "adaptive",
                "object": "model",
                "created": 0,
                "owned_by": "polvo",
                "type": "adaptive",
            }
        )
    for tier_key, spec in models.tiers.items():
        data.append(
            {
                "id": spec.name or tier_key,
                "object": "model",
                "created": 0,
                "owned_by": "polvo",
                "tier": tier_key,
                "model": spec.api_id,
                "type": "adaptive" if models.is_adaptive(tier_key) else "custom",
            }
        )
    return {"object": "list", "data": data}


def _auth_ok(settings: Settings, request: Request) -> bool:
    if not settings.require_auth:
        return True
    # Anthropic clients may send either Authorization: Bearer *** x-api-key.
    auth = request.headers.get("authorization", "")
    if auth and hmac.compare_digest(auth, f"Bearer {settings.require_auth}"):
        return True
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        return hmac.compare_digest(api_key, settings.require_auth)
    return False


_ANTHROPIC_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
}


def _anthropic_error_response(status_code: int, message: str) -> JSONResponse:
    """Render an error in the Anthropic envelope clients of /v1/messages expect."""
    if status_code >= 500:
        error_type = "api_error"
    else:
        error_type = _ANTHROPIC_ERROR_TYPES.get(status_code, "invalid_request_error")
    return JSONResponse(
        status_code=status_code,
        content={"type": "error", "error": {"type": error_type, "message": str(message)}},
    )


@router.get("/v1/models")
async def list_models(request: Request):
    settings: Settings = request.app.state.settings
    if not _auth_ok(settings, request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return _model_list_payload(settings.models)


@router.get("/version")
async def get_version():
    try:
        version = importlib.metadata.version("polvo")
    except importlib.metadata.PackageNotFoundError:
        version = "0.1.0"
    return {"version": version, "name": "Polvo Router"}


@router.get("/api/v1/models")
async def list_models_api_v1(request: Request):
    # Alias for /v1/models
    return await list_models(request)


@router.get("/api/tags")
async def get_tags():
    return []


@router.get("/props")
async def get_props():
    return {}


@router.get("/v1/props")
async def get_props_v1():
    return {}


async def _process_chat(
    request: Request,
    body: dict[str, Any],
    settings: Settings,
    responses_mode: bool = False,
    anthropic_mode: bool = False,
) -> StreamingResponse:
    """Core routing and forwarding logic for all chat-like endpoints."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty list")

    # Classify ONLY the LAST user message — the user's current intent.
    last_user_content: str | None = None
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            last_user_content = content
        elif isinstance(content, list):
            texts = [
                str(c.get("text", ""))
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            if texts:
                last_user_content = "\n".join(texts)

    if last_user_content is not None:
        prompt = last_user_content
    else:
        # No user message (e.g. a tool-call continuation: system + assistant +
        # tool). Classify by the last NON-system message so the system prompt
        # never leaks into the classifier. If only a system message exists,
        # there is nothing meaningful to classify — fall back to the default.
        parts: list[str] = []
        for msg in messages:
            if msg.get("role") == "system":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
        prompt = "\n".join(parts) if parts else ""

    # Sanitize prompt to remove Claude Code metadata and noise that confuse the classifier
    import re
    prompt = re.sub(r"<(session|system-reminder)>.*?</\1>", "", prompt, flags=re.DOTALL)
    prompt = re.sub(r"\[The user attached an image\..*?\]", "", prompt, flags=re.DOTALL)
    prompt = prompt.strip()

    requested_model = body.get("model", "")
    known_tier = settings.models.tier_for_alias(requested_model)
    if known_tier is not None:
        routed_tier = known_tier
    elif requested_model == "adaptive":
        # Explicit 'adaptive' request. Requires at least one adaptive tier.
        if not settings.models.has_adaptive():
            raise HTTPException(
                status_code=400,
                detail="No adaptive tiers configured. Add mini/air/pro/ultra to the 'adaptive' block, or request a custom model by id.",
            )
        routed_tier = await classify(prompt, settings)
    else:
        # Unknown model id — fall back to the classifier (if adaptive exists),
        # else error clearly.
        if not settings.models.has_adaptive():
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model '{requested_model}'. No adaptive tiers configured; request a custom model by id.",
            )
        routed_tier = await classify(prompt, settings)

    routed_spec = settings.models.tiers[routed_tier]
    routed_model = routed_spec.api_id
    provider = settings.models.provider_for(routed_spec.provider)

    snippet = prompt[:50].replace("\n", " ") + "..."
    log.info(
        "Tier=%s Model=%s Provider=%s Prompt=%s",
        routed_tier,
        routed_model,
        provider.base_url,
        snippet,
    )

    upstream_body = dict(body)
    upstream_body.update(routed_spec.extra_params)  # Merge reasoning/sampling params
    upstream_body["model"] = routed_model

    target_url = f"{provider.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider.resolve_api_key()}",
        "Content-Type": "application/json",
    }

    stream = bool(body.get("stream", False))
    upstream_body["stream"] = stream
    # Ask upstream to include usage in the final chunk (needed for metering).
    if stream and (responses_mode or anthropic_mode):
        upstream_body["stream_options"] = {"include_usage": True}

    upstream = getattr(request.app.state, "http_client", None)
    own_client = upstream is None
    if own_client:
        upstream = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0))

    anthropic_stream = anthropic_mode and stream
    if anthropic_stream:
        # Streamed send: forward bytes as they arrive instead of buffering the
        # whole upstream response before the first one reaches the client.
        try:
            upstream_request = upstream.build_request(
                "POST", target_url, headers=headers, json=upstream_body
            )
            response = await upstream.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            if own_client:
                await upstream.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")
    else:
        try:
            response = await upstream.post(target_url, headers=headers, json=upstream_body)
        except httpx.HTTPError as exc:
            if own_client:
                await upstream.aclose()
            raise HTTPException(status_code=502, detail=f"Upstream error: {exc}")

    if response.status_code >= 400:
        if anthropic_stream:
            # A streamed error response must be read before its text is usable.
            await response.aread()
        detail = response.text[:2000]
        if anthropic_stream:
            await response.aclose()
        if own_client:
            await upstream.aclose()
        raise HTTPException(status_code=response.status_code, detail=detail)

    async def passthrough():
        try:
            if responses_mode:
                if stream:
                    async for sse in responses_translate.translate_stream(response, routed_model):
                        yield sse.encode("utf-8")
                else:
                    data = response.json()
                    obj = responses_translate.translate_non_stream(data, routed_model)
                    yield json.dumps(obj).encode("utf-8")
            elif anthropic_mode:
                if stream:
                    try:
                        async for frame in anthropic_translate.translate_stream(
                            response, routed_model
                        ):
                            yield frame
                    finally:
                        await response.aclose()
                else:
                    data = response.json()
                    obj = anthropic_translate.translate_non_stream(data, routed_model)
                    yield json.dumps(obj).encode("utf-8")
            else:
                if stream:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                else:
                    yield response.content
        finally:
            if own_client:
                await upstream.aclose()

    headers_out = {
        "X-Router-Model": routed_model,
        "X-Router-Tier": routed_tier,
    }

    media = "text/event-stream" if stream else "application/json"
    return StreamingResponse(
        passthrough(),
        media_type=media,
        headers=headers_out,
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    settings: Settings = request.app.state.settings
    if not _auth_ok(settings, request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    return await _process_chat(request, body, settings)


@router.post("/v1/responses")
async def responses_shim(request: Request):
    """Translate /v1/responses -> /v1/chat/completions"""
    settings: Settings = request.app.state.settings
    if not _auth_ok(settings, request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    instructions = body.get("instructions", "")
    input_items = body.get("input")
    messages = body.get("messages")

    chat_messages = []
    if instructions:
        chat_messages.append({"role": "system", "content": instructions})

    if isinstance(input_items, list):
        chat_messages.extend(responses_translate.input_items_to_messages(input_items))
    elif isinstance(messages, list):
        chat_messages.extend(messages)

    chat_body = dict(body)
    chat_body["messages"] = chat_messages

    tools = body.get("tools")
    if isinstance(tools, list):
        chat_body["tools"] = responses_translate.translate_tools(tools)
    if "parallel_tool_calls" in body:
        chat_body["parallel_tool_calls"] = body["parallel_tool_calls"]

    if chat_body.get("stream"):
        chat_body["stream_options"] = {"include_usage": True}

    return await _process_chat(request, chat_body, settings, responses_mode=True)


@router.post("/v1/messages")
async def messages_shim(request: Request):
    """Anthropic Messages endpoint for Claude Code and other Anthropic clients."""
    settings: Settings = request.app.state.settings
    if not _auth_ok(settings, request):
        return _anthropic_error_response(401, "Unauthorized")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return _anthropic_error_response(400, "Invalid JSON body")

    if not isinstance(body, dict):
        return _anthropic_error_response(400, "Request body must be a JSON object")

    try:
        chat_body = anthropic_translate.translate_request(body)
        # Force 'adaptive' for all Claude Code requests to override client-side model persistence,
        # unless the requested model is already a known tier or custom model alias.
        original_model = body.get("model", "")
        if settings.models.tier_for_alias(original_model) is None:
            chat_body["model"] = "adaptive"
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return _anthropic_error_response(400, f"Invalid Anthropic request: {exc}")

    try:
        return await _process_chat(request, chat_body, settings, anthropic_mode=True)
    except HTTPException as exc:
        return _anthropic_error_response(exc.status_code, exc.detail)


@router.post("/v1/messages/count_tokens")
async def count_tokens_shim(request: Request):
    """Anthropic count_tokens endpoint (approximate chars/4 estimate)."""
    settings: Settings = request.app.state.settings
    if not _auth_ok(settings, request):
        return _anthropic_error_response(401, "Unauthorized")

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return _anthropic_error_response(400, "Invalid JSON body")

    text = anthropic_translate.request_text(body)
    return JSONResponse(content={"input_tokens": max(1, len(text) // 4)})
