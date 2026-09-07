"""Tests for the Anthropic Messages shim (/v1/messages + count_tokens).

Covers the smoke tests from docs/plans/claude-code-adapter-final.md §1.4:
streaming SSE with valid framing, tool_use round-trips, non-streaming
translation, count_tokens, and Anthropic error envelopes.
"""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from model_router.config import Settings
from model_router.main import create_app
from model_router.models import ModelSpec, ProviderSpec, RouterModels

from test_proxy import _default_models


def _settings(**kw) -> Settings:
    return Settings(models=_default_models(), **kw)


@pytest.fixture
def client():
    return TestClient(create_app(_settings()))


def _sse_frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _upstream_stream(chunks: list[dict]) -> str:
    body = "".join("data: " + json.dumps(c) + "\n" for c in chunks)
    return body + "data: [DONE]\n\n"


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE stream into (event, payload) tuples, asserting framing."""
    events = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event = None
        data = None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])  # must be valid JSON
        assert event is not None, f"frame without event line: {frame!r}"
        assert data is not None, f"frame without data line: {frame!r}"
        events.append((event, data))
    return events


# --- non-streaming -----------------------------------------------------------

def test_messages_non_stream_returns_anthropic_shape(client, monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["model"] = kw["json"]["model"]
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "choices": [{
                    "message": {"role": "assistant", "content": "olá"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "max_tokens": 64, "messages": [
            {"role": "user", "content": "oi"},
        ]},
    )
    assert r.status_code == 200
    assert seen["model"] == "gemma4:31b"
    obj = r.json()
    assert obj["type"] == "message"
    assert obj["role"] == "assistant"
    assert obj["stop_reason"] == "end_turn"
    assert obj["content"] == [{"type": "text", "text": "olá"}]
    assert obj["usage"]["input_tokens"] == 11
    assert obj["usage"]["output_tokens"] == 7


def test_messages_request_translation(client, monkeypatch):
    """system (string + blocks), tool round-trip, and top-level params."""
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    payload = {
        "model": "mini",
        "max_tokens": 128,
        "temperature": 0.2,
        "top_p": 0.9,
        "stop_sequences": ["STOP"],
        "system": [
            {"type": "text", "text": "You are Hermes.", "cache_control": {"type": "ephemeral"}},
        ],
        "tools": [{
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }],
        "messages": [
            {"role": "user", "content": "read /tmp/x"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "toolu_1", "name": "read_file",
                 "input": {"path": "/tmp/x"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1",
                 "content": [{"type": "text", "text": "file contents"}]},
            ]},
        ],
    }
    r = client.post("/v1/messages", json=payload)
    assert r.status_code == 200
    body = seen["body"]
    assert body["max_tokens"] == 128
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9
    assert body["stop"] == ["STOP"]  # renamed from stop_sequences
    assert "stop_sequences" not in body
    # system block list -> system message, text preserved
    assert body["messages"][0] == {"role": "system", "content": "You are Hermes."}
    # assistant tool_use -> tool_calls
    assert body["messages"][2] == {
        "role": "assistant",
        "content": "Let me check.",
        "tool_calls": [{
            "id": "toolu_1", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "/tmp/x"}'},
        }],
    }
    # user tool_result -> role 'tool' (NOT an empty user message)
    assert body["messages"][3] == {
        "role": "tool", "tool_call_id": "toolu_1", "content": "file contents",
    }
    # Anthropic tools -> nested function tools
    assert body["tools"] == [{
        "type": "function",
        "function": {
            "name": "read_file", "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }]


def test_messages_without_tools_sends_no_tools_key(client, monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    assert "tools" not in seen["body"]  # no tools: null upstream


def test_messages_tool_result_error_flag(client, monkeypatch):
    seen = {}

    async def fake_post(self, url, headers=None, **kw):
        seen["body"] = kw["json"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    payload = {
        "model": "mini",
        "messages": [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "boom", "is_error": True},
            ]},
        ],
    }
    r = client.post("/v1/messages", json=payload)
    assert r.status_code == 200
    assert seen["body"]["messages"][1]["content"] == "[tool error] boom"


# --- streaming ---------------------------------------------------------------

def _fake_stream_send(chunks: list[dict], status_code: int = 200):
    """Monkeypatch target for httpx.AsyncClient.send: returns a streamed SSE
    response built from ``chunks`` and records the request."""
    seen: dict = {}

    async def fake_send(self, request, **kw):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            status_code,
            content=_upstream_stream(chunks).encode(),
            request=httpx.Request("POST", "https://ollama.com/v1/chat/completions"),
        )

    return fake_send, seen


def test_messages_stream_valid_sse_framing(client, monkeypatch):
    """Smoke test §1.4-1: real newlines, parseable JSON, correct event sequence."""
    seen = {}
    chunks = [
        {"choices": [{"index": 0, "delta": {"content": "Olá"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": " mundo"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
    ]
    fake_send, seen = _fake_stream_send(chunks)
    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "max_tokens": 32, "stream": True,
              "messages": [{"role": "user", "content": "oi"}]},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    events = _parse_sse(r.text)  # raises if any frame is malformed
    names = [e for e, _ in events]
    # ping (initial) message_start content_block_start deltas stops message_delta message_stop
    assert names[0] == "ping"
    assert names[1] == "message_start"
    assert "content_block_start" in names
    assert "content_block_delta" in names
    assert names[-1] == "message_stop"
    assert names.count("message_stop") == 1  # exactly one, at the end
    # message_start carries the full envelope
    start = events[1][1]["message"]
    assert start["type"] == "message"
    assert start["role"] == "assistant"
    assert start["stop_reason"] is None
    # text deltas reassemble the message
    text = "".join(d["delta"]["text"] for e, d in events if e == "content_block_delta"
                   and d["delta"]["type"] == "text_delta")
    assert text == "Olá mundo"
    # message_delta carries stop_reason + output usage
    md = next(d for e, d in events if e == "message_delta")
    assert md["delta"]["stop_reason"] == "end_turn"
    assert md["usage"]["output_tokens"] == 3
    # content_block_stop comes with the block index
    cbs = next(d for e, d in events if e == "content_block_stop")
    assert isinstance(cbs["index"], int)


def test_messages_stream_tool_use_roundtrip(client, monkeypatch):
    """Fragmented tool_call arguments coalesce into ONE tool_use block with
    input_json_delta partial_json — the client can reassemble the call."""
    seen = {}
    args1 = '{"pa'  # fragment 1 of {"path": "/tmp/x"}
    args2 = 'th": "/tmp/x"}'  # fragment 2

    def tc_chunk(**tc):
        return {"choices": [{"index": 0, "delta": {"tool_calls": [tc]}}]}

    chunks = [
        tc_chunk(index=0, id="call_1", type="function",
                 function={"name": "read_file", "arguments": args1}),
        tc_chunk(index=0, function={"arguments": args2}),
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    fake_send, seen = _fake_stream_send(chunks)
    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "max_tokens": 32, "stream": True,
              "messages": [{"role": "user", "content": "read it"}]},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    starts = [d for e, d in events if e == "content_block_start"
              and d["content_block"]["type"] == "tool_use"]
    assert len(starts) == 1  # ONE block, not one per fragment
    assert starts[0]["content_block"]["name"] == "read_file"
    partial = "".join(
        d["delta"]["partial_json"] for e, d in events
        if e == "content_block_delta" and d["delta"]["type"] == "input_json_delta"
    )
    assert json.loads(partial) == {"path": "/tmp/x"}  # reassembles to valid JSON
    assert starts[0]["content_block"]["id"] == "call_1"
    md = next(d for e, d in events if e == "message_delta")
    assert md["delta"]["stop_reason"] == "tool_use"
    assert events[-1][0] == "message_stop"


def test_messages_stream_ping_on_idle_upstream(monkeypatch):
    """A silent upstream must produce ping frames, not a dead stream."""
    from model_router import anthropic_translate as at
    monkeypatch.setattr(at, "PING_INTERVAL", 0.01)

    class SlowResp:
        status_code = 200

        def __init__(self):
            self.request = httpx.Request("POST", "https://x/chat/completions")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            await asyncio.sleep(0.05)
            yield "data: " + json.dumps({
                "choices": [{"index": 0, "delta": {"content": "late"}}],
            })
            yield "data: [DONE]"

    async def ping_test():
        frames = []
        async for item in at.translate_stream(SlowResp(), "m"):
            frames.append(item)
        return b"".join(frames).decode()

    text = asyncio.run(ping_test())
    events = _parse_sse(text)
    pings = [e for e, _ in events if e == "ping"]
    assert len(pings) >= 2  # initial ping + keep-alive during the silent gap
    names = [e for e, _ in events]
    assert names[-1] == "message_stop"
    text_deltas = [d for e, d in events
                   if e == "content_block_delta" and d["delta"]["type"] == "text_delta"]
    assert "".join(d["delta"]["text"] for d in text_deltas) == "late"


def test_messages_stream_upstream_error_envelope(client, monkeypatch):
    """Upstream HTTP errors reach the client as Anthropic error envelopes."""
    fake_send, seen = _fake_stream_send([], status_code=429)
    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "max_tokens": 8, "stream": True,
              "messages": [{"role": "user", "content": "oi"}]},
    )
    assert r.status_code == 429
    obj = r.json()
    assert obj["type"] == "error"
    assert obj["error"]["type"] == "rate_limit_error"


def test_messages_non_stream_upstream_error_envelope(client, monkeypatch):
    async def fake_post(self, url, headers=None, **kw):
        return httpx.Response(500, text="upstream boom",
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "messages": [{"role": "user", "content": "oi"}]},
    )
    assert r.status_code == 500
    obj = r.json()
    assert obj["type"] == "error"
    assert obj["error"]["type"] == "api_error"
    assert "upstream boom" in obj["error"]["message"]


# --- count_tokens ------------------------------------------------------------

def test_count_tokens_shape_and_estimate(client):
    r = client.post(
        "/v1/messages/count_tokens",
        json={"model": "mini", "messages": [{"role": "user", "content": "x" * 400}]},
    )
    assert r.status_code == 200
    obj = r.json()
    assert "input_tokens" in obj  # Anthropic field name (not 'count')
    assert obj["input_tokens"] == 100  # 400 chars / 4


def test_count_tokens_counts_tool_payloads(client):
    r = client.post(
        "/v1/messages/count_tokens",
        json={
            "model": "mini",
            "system": "sys",
            "messages": [
                {"role": "user", "content": [
                    {"type": "tool_use", "id": "t1", "name": "f",
                     "input": {"a": "y" * 200}},
                ]},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["input_tokens"] > 40


def test_count_tokens_requires_auth():
    client = TestClient(create_app(_settings(require_auth="router-secret")))
    assert client.post(
        "/v1/messages/count_tokens", json={"messages": []}
    ).status_code == 401
    ok = client.post(
        "/v1/messages/count_tokens",
        json={"messages": []},
        headers={"Authorization": "Bearer router-secret"},
    )
    assert ok.status_code == 200


# --- auth variants -----------------------------------------------------------

def test_messages_accepts_x_api_key(monkeypatch):
    client = TestClient(create_app(_settings(require_auth="router-secret")))

    async def fake_post(self, url, headers=None, **kw):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "messages": [{"role": "user", "content": "oi"}]},
        headers={"x-api-key": "router-secret"},
    )
    assert r.status_code == 200


def test_messages_rejects_bad_key():
    client = TestClient(create_app(_settings(require_auth="router-secret")))
    r = client.post(
        "/v1/messages",
        json={"model": "mini", "messages": [{"role": "user", "content": "oi"}]},
        headers={"x-api-key": "wrong"},
    )
    assert r.status_code == 401
    assert r.json()["type"] == "error"


def test_messages_invalid_json_400(client):
    r = client.post("/v1/messages", content="nope",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["type"] == "error"
