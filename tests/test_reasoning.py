"""Regression tests for reasoning-model support (CoT preservation).

Covers the three fixes for reasoning models (deepseek/minimax/glm tiers on
ollama-cloud) whose chain-of-thought used to be dropped or to eat the whole
max_tokens budget:

1. Tier extra_params apply as DEFAULTS — a client-sent reasoning_effort wins.
2. Anthropic `thinking` blocks map to upstream `reasoning_effort`.
3. Upstream `reasoning` is preserved as Anthropic thinking blocks (stream +
   non-stream).
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from model_router.config import Settings
from model_router.main import create_app
from model_router.models import ModelSpec, ProviderSpec, RouterModels

from test_proxy import _default_models
from test_messages_shim import _upstream_stream, _parse_sse, _fake_stream_send


@pytest.fixture
def client():
    from model_router.config import Settings as _S
    from model_router.main import create_app as _app
    return TestClient(_app(_S(models=_default_models())))


# --- Fix 1: client-sent reasoning_effort wins over tier extra_params ---------

def test_client_reasoning_effort_wins_over_tier_default(monkeypatch):
    models = _default_models()
    # Tier 'pro' wants reasoning_effort=high by default.
    models.tiers["pro"].extra_params["reasoning_effort"] = "high"
    models.tiers["pro"].extra_params["budget_tokens"] = 4096
    client = TestClient(create_app(Settings(models=models)))

    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # Client explicitly requests a low effort — must NOT be overridden.
    r = client.post("/v1/chat/completions", json={
        "model": "pro",
        "reasoning_effort": "low",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert seen["body"]["reasoning_effort"] == "low"  # client wins
    assert seen["body"]["budget_tokens"] == 4096      # untouched default still applied


def test_tier_reasoning_effort_applied_when_client_silent(monkeypatch):
    models = _default_models()
    models.tiers["air"].extra_params["reasoning_effort"] = "minimal"
    client = TestClient(create_app(Settings(models=models)))

    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/v1/chat/completions", json={
        "model": "air",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert seen["body"]["reasoning_effort"] == "minimal"  # tier default fills in


# --- Fix 2: thinking.budget_tokens -> reasoning_effort ------------------------

@pytest.mark.parametrize("budget,expected", [
    (1024, "low"),
    (2048, "medium"),
    (6000, "medium"),
    (8192, "high"),
    (16384, "high"),
])
def test_thinking_budget_maps_to_reasoning_effort(client, monkeypatch, budget, expected):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 1024,
        "thinking": {"type": "enabled", "budget_tokens": budget},
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert seen["body"]["reasoning_effort"] == expected


def test_thinking_absent_sends_no_reasoning_effort(client, monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert "reasoning_effort" not in seen["body"]


def test_explicit_reasoning_effort_beats_thinking_budget(client, monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 1024,
        "reasoning_effort": "high",
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    assert seen["body"]["reasoning_effort"] == "high"


# --- Fix 3: upstream reasoning preserved as thinking blocks ------------------

def test_non_stream_reasoning_becomes_thinking_block(client, monkeypatch):
    async def fake_post(self, url, headers=None, **kw):
        return httpx.Response(
            200,
            json={"choices": [{"message": {
                "role": "assistant",
                "content": "final answer",
                "reasoning": "step one, then step two",
            }}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["content"][0] == {
        "type": "thinking", "thinking": "step one, then step two", "signature": "polvo",
    }
    assert data["content"][1] == {"type": "text", "text": "final answer"}


def test_stream_reasoning_deltas_become_thinking_blocks(client, monkeypatch):
    chunks = [
        {"choices": [{"delta": {"reasoning": "think "}}]},
        {"choices": [{"delta": {"reasoning": "hard"}}]},
        {"choices": [{"delta": {"content": "answer"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]

    fake_send, _seen = _fake_stream_send(chunks)
    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 128,
        "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    events = _parse_sse(r.text)
    kinds = [(e, d.get("content_block", {}).get("type")) for e, d in events
             if e == "content_block_start"]
    assert kinds == [("content_block_start", "thinking"), ("content_block_start", "text")]

    thinking_deltas = [d["delta"]["thinking"] for e, d in events
                       if e == "content_block_delta" and d["delta"].get("type") == "thinking_delta"]
    assert thinking_deltas == ["think ", "hard"]

    text_deltas = [d["delta"]["text"] for e, d in events
                   if e == "content_block_delta" and d["delta"].get("type") == "text_delta"]
    assert text_deltas == ["answer"]


def test_stream_reasoning_content_alias_also_handled(client, monkeypatch):
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "cot here"}}]},
        {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]},
    ]

    fake_send, _seen = _fake_stream_send(chunks)
    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)

    r = client.post("/v1/messages", json={
        "model": "mini",
        "max_tokens": 128,
        "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200
    events = _parse_sse(r.text)
    thinking_deltas = [d["delta"]["thinking"] for e, d in events
                       if e == "content_block_delta" and d["delta"].get("type") == "thinking_delta"]
    assert thinking_deltas == ["cot here"]