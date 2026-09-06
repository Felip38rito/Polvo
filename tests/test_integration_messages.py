"""End-to-end integration: real uvicorn router + stub upstream, over TCP.

TestClient bypasses the network stack; these tests exercise the smoke tests
from docs/plans/claude-code-adapter-final.md §1.4 the way curl -N would:
actual sockets, actual chunked SSE, actual headers.
"""
from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from model_router.config import Settings
from model_router.main import create_app
from model_router.models import ModelSpec, ProviderSpec, RouterModels


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make_upstream() -> FastAPI:
    """Minimal OpenAI-compatible upstream: streaming + non-streaming chat."""
    app = FastAPI()

    def _sse(payload: dict) -> str:
        return "data: " + json.dumps(payload) + "\n\n"

    @app.post("/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        if body.get("model") == "boom":
            return JSONResponse({"error": "upstream says no"}, status_code=429)
        if body.get("stream"):
            async def gen():
                yield _sse({"choices": [{"index": 0, "delta": {"content": "Olá"},
                                         "finish_reason": None}]})
                yield _sse({"choices": [{"index": 0, "delta": {"content": " mundo"},
                                         "finish_reason": None}]})
                yield _sse({"choices": [{"index": 0, "delta": {},
                                         "finish_reason": "stop"}]})
                yield _sse({"choices": [],
                            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse({
            "choices": [{"message": {"role": "assistant", "content": "Olá"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        })

    return app


def _serve(app: FastAPI) -> tuple[uvicorn.Server, int]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start in time"
    return server, port


@pytest.fixture(scope="module")
def base_url():
    upstream, upstream_port = _serve(_make_upstream())
    models = RouterModels(
        tiers={
            "mini": ModelSpec("gemma4:31b", "fast"),
            # Routes to the stub's error path (model "boom" -> 429).
            "fail": ModelSpec("boom", "always fails", provider="errprov"),
        },
        default_tier="mini",
        providers={
            "default": ProviderSpec(f"http://127.0.0.1:{upstream_port}",
                                    api_key="upstream-key"),
            "errprov": ProviderSpec(f"http://127.0.0.1:{upstream_port}",
                                    api_key="upstream-key"),
        },
    )
    router, router_port = _serve(create_app(Settings(models=models, require_auth="router-secret")))
    yield f"http://127.0.0.1:{router_port}"
    router.should_exit = True
    upstream.should_exit = True


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event = data = None
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        assert event is not None and data is not None, f"malformed frame: {frame!r}"
        events.append((event, data))
    return events


def test_streaming_over_real_socket(base_url):
    """§1.4-1: streamed /v1/messages over a real socket with valid SSE framing."""
    payload = {
        "model": "mini",
        "max_tokens": 64,
        "stream": True,
        "messages": [{"role": "user", "content": "oi"}],
    }
    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST", f"{base_url}/v1/messages", json=payload,
            headers={"x-api-key": "router-secret"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["x-router-tier"] == "mini"
            text = "".join(response.iter_text())

    events = _parse_sse(text)
    names = [e for e, _ in events]
    assert names[-1] == "message_stop"
    assert names.count("message_stop") == 1
    text_out = "".join(
        d["delta"]["text"] for e, d in events
        if e == "content_block_delta" and d["delta"]["type"] == "text_delta"
    )
    assert text_out == "Olá mundo"
    md = next(d for e, d in events if e == "message_delta")
    assert md["delta"]["stop_reason"] == "end_turn"
    assert md["usage"]["output_tokens"] == 3


def test_non_streaming_over_real_socket(base_url):
    """§1.4-2: stream:false returns an Anthropic Messages response."""
    r = httpx.post(
        f"{base_url}/v1/messages",
        json={"model": "mini", "max_tokens": 64,
              "messages": [{"role": "user", "content": "oi"}]},
        headers={"x-api-key": "router-secret"},
        timeout=30,
    )
    assert r.status_code == 200
    obj = r.json()
    assert obj["type"] == "message"
    assert obj["role"] == "assistant"
    assert obj["content"] == [{"type": "text", "text": "Olá"}]
    assert obj["usage"] == {"input_tokens": 5, "output_tokens": 3}
    assert obj["stop_reason"] == "end_turn"


def test_upstream_error_envelope_over_real_socket(base_url):
    """§1.4-3: upstream errors surface in the Anthropic error envelope."""
    r = httpx.post(
        f"{base_url}/v1/messages",
        json={"model": "fail", "max_tokens": 8,
              "messages": [{"role": "user", "content": "oi"}]},
        headers={"x-api-key": "router-secret"},
        timeout=30,
    )
    assert r.status_code == 429
    obj = r.json()
    assert obj["type"] == "error"
    assert obj["error"]["type"] == "rate_limit_error"
    assert "upstream says no" in obj["error"]["message"]


def test_auth_enforced_over_real_socket(base_url):
    r = httpx.post(
        f"{base_url}/v1/messages",
        json={"model": "mini", "messages": [{"role": "user", "content": "oi"}]},
        timeout=30,
    )
    assert r.status_code == 401
    assert r.json()["type"] == "error"


def test_count_tokens_over_real_socket(base_url):
    """§1.4-4: count_tokens answers in the Anthropic shape."""
    r = httpx.post(
        f"{base_url}/v1/messages/count_tokens",
        json={"model": "mini", "messages": [{"role": "user", "content": "x" * 400}]},
        headers={"x-api-key": "router-secret"},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.json() == {"input_tokens": 100}


def test_models_advertised_over_real_socket(base_url):
    r = httpx.get(f"{base_url}/v1/models", headers={"x-api-key": "router-secret"},
                  timeout=30)
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert "mini" in ids