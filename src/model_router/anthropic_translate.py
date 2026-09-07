"""Translation between the Anthropic Messages API and Chat Completions.

Claude Code (and other Anthropic-protocol clients) speak the Messages API:
``POST /v1/messages`` with a block-based content model and a typed SSE event
stream (``message_start`` / ``content_block_*`` / ``message_delta`` /
``message_stop``). This module translates between that protocol and the Chat
Completions format the upstream providers speak, so the router can serve
Claude Code while still talking Chat Completions upstream.

Protocol reference: https://code.claude.com/docs/en/llm-gateway-protocol
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any, AsyncGenerator

import httpx

# Emit a keep-alive ping when the upstream is silent for this long: the client
# aborts streams that are silent for 300 s (long thinking pauses produce only
# pings on the real Anthropic API).
PING_INTERVAL = 15.0


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    """Encode one SSE frame with REAL newlines — an SSE client splits frames
    on blank lines and parses the data line as JSON."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode("utf-8")


def _content_to_text(content: Any) -> str:
    """Plain text from a Messages content value (string or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(t for t in texts if t)
    return ""


def _tool_input_to_arguments(tool_input: Any) -> str:
    """Anthropic tool_use carries a JSON object; Chat Completions wants a string."""
    if isinstance(tool_input, str):
        return tool_input
    return json.dumps(tool_input or {})


def _translate_tools(tools: Any) -> list[dict[str, Any]]:
    """Anthropic ``tools`` (name/description/input_schema) -> Chat nested form.

    Anthropic server-side tools (web_search etc.) carry no input_schema and
    cannot be replayed upstream — skip them.
    """
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict) or "input_schema" not in tool:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return out


def _translate_tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    return None


def translate_request(body: dict[str, Any]) -> dict[str, Any]:
    """Translate an Anthropic Messages request into a Chat Completions body."""
    messages: list[dict[str, Any]] = []

    system = body.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = _content_to_text(system)
        if text:
            messages.append({"role": "system", "content": text})

    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")

        if role == "assistant":
            texts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            if isinstance(content, str):
                if content:
                    texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        texts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block.get("id") or _generate_id("toolu"),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": _tool_input_to_arguments(block.get("input")),
                            },
                        })
                    # thinking / redacted_thinking blocks cannot be replayed
                    # upstream in Chat format — drop them.
            message: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            if tool_calls:
                message["tool_calls"] = tool_calls
            messages.append(message)

        elif role == "user":
            if isinstance(content, str):
                if content:
                    messages.append({"role": "user", "content": content})
                continue
            if not isinstance(content, list):
                continue
            # A user turn may carry tool_result blocks (role 'tool' does not
            # exist in the Messages API). Each becomes its own Chat 'tool'
            # message, which must immediately follow the assistant tool_calls
            # turn — so pending user text is flushed BEFORE the tool results.
            holder: dict[str, list] = {"texts": [], "images": []}

            def flush_user() -> None:
                texts = "\n".join(holder["texts"])
                if holder["images"] and texts:
                    parts: list[dict[str, Any]] = [{"type": "text", "text": texts}]
                    parts += [{"type": "image_url", "image_url": {"url": u}} for u in holder["images"]]
                    messages.append({"role": "user", "content": parts})
                elif holder["images"]:
                    messages.append({"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": u}} for u in holder["images"]
                    ]})
                elif texts:
                    messages.append({"role": "user", "content": texts})
                holder["texts"], holder["images"] = [], []

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_result":
                    flush_user()
                    result = block.get("content", "")
                    text = result if isinstance(result, str) else _content_to_text(result)
                    if block.get("is_error"):
                        text = f"[tool error] {text}" if text else "[tool error]"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": text,
                    })
                elif btype == "text" and block.get("text"):
                    holder["texts"].append(block["text"])
                elif btype == "image":
                    source = block.get("source") or {}
                    if source.get("type") == "base64" and source.get("data"):
                        media = source.get("media_type", "image/png")
                        holder["images"].append(f"data:{media};base64,{source['data']}")
            flush_user()

    out: dict[str, Any] = {"model": body.get("model", ""), "messages": messages}

    if body.get("max_tokens") is not None:
        out["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    # Anthropic calls it stop_sequences; Chat Completions calls it stop.
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    if body.get("stream") is not None:
        out["stream"] = bool(body["stream"])

    tools = _translate_tools(body.get("tools"))
    if tools:
        out["tools"] = tools
    tool_choice = _translate_tool_choice(body.get("tool_choice"))
    if tool_choice is not None:
        out["tool_choice"] = tool_choice

    return out


def request_text(body: dict[str, Any]) -> str:
    """Concatenate the textual payload of a Messages request (token estimate)."""
    parts: list[str] = []
    system = body.get("system")
    if isinstance(system, str):
        parts.append(system)
    elif isinstance(system, list):
        parts.append(_content_to_text(system))
    for msg in body.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        parts.append(_content_to_text(content))
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    parts.append(json.dumps(block.get("input", {})))
                elif block.get("type") == "tool_result":
                    result = block.get("content", "")
                    parts.append(result if isinstance(result, str) else _content_to_text(result))
    return "\n".join(p for p in parts if p)


_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
}


def _map_stop_reason(finish_reason: str | None) -> str:
    return _STOP_REASON_MAP.get(finish_reason or "stop", "end_turn")


def _normalize_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0),
        "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0),
    }


def translate_non_stream(chat_completion: dict[str, Any], model: str) -> dict[str, Any]:
    """Translate a non-streaming Chat Completions JSON into a Messages response."""
    choices = chat_completion.get("choices") or []
    message: dict[str, Any] = (choices[0].get("message") or {}) if choices else {}

    content: list[dict[str, Any]] = []
    text = message.get("content")
    if isinstance(text, list):
        text = _content_to_text(text)
    if text:
        content.append({"type": "text", "text": text})
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments")
        if isinstance(raw_args, str):
            try:
                tool_input: Any = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                tool_input = {}
        else:
            tool_input = raw_args or {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id") or _generate_id("toolu"),
            "name": fn.get("name", ""),
            "input": tool_input,
        })

    finish_reason = choices[0].get("finish_reason") if choices else None
    return {
        "id": _generate_id("msg"),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": _map_stop_reason(finish_reason),
        "stop_sequence": None,
        "usage": _normalize_usage(chat_completion.get("usage")),
    }


async def _lines_with_pings(
    response: httpx.Response, interval: float
) -> AsyncGenerator[Any, None]:
    """Yield upstream SSE lines, yielding ``None`` (a ping tick) whenever the
    upstream is silent for ``interval`` seconds.

    The reads happen in a dedicated task so an idle timeout can inject a ping
    without cancelling the in-flight ``aiter_lines`` read (cancelling that
    generator's ``__anext__`` would tear the stream down).
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            async for line in response.aiter_lines():
                queue.put_nowait(line)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # mid-stream transport errors surface as truncated output
        finally:
            queue.put_nowait(_EOF)

    task = asyncio.get_running_loop().create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except asyncio.TimeoutError:
                yield None
                continue
            if item is _EOF:
                return
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


_EOF = object()


async def translate_stream(
    upstream_response: httpx.Response, model: str
) -> AsyncGenerator[bytes, None]:
    """Translate a Chat Completions SSE stream into Anthropic Messages SSE.

    State machine: one open content block at a time (text or tool_use),
    keyed by the upstream tool_call index; blocks close implicitly when a new
    one starts, on ``finish_reason``, or on EOF. Emits exactly one
    ``message_delta`` + ``message_stop`` per stream.
    """
    message_id = _generate_id("msg")
    yield _sse("ping", {"type": "ping"})
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    next_block = 0
    # Live block: {"kind": "text"|"tool", "block_index", "text"/"args", ...}
    current: dict[str, Any] | None = None
    stopped = False
    finish_reason: str | None = None
    usage: dict[str, Any] = {}

    def open_block(kind: str, tool_index: int = 0, call_id: str = "", name: str = "") -> bytes:
        nonlocal current, next_block
        if kind == "text":
            block: dict[str, Any] = {"type": "text", "text": ""}
        else:
            block = {
                "type": "tool_use",
                "id": call_id or _generate_id("toolu"),
                "name": name,
                "input": {},
            }
        current = {
            "kind": kind,
            "block_index": next_block,
            "tool_index": tool_index,
            "text": "",
            "args": "",
        }
        event = _sse("content_block_start", {
            "type": "content_block_start",
            "index": next_block,
            "content_block": block,
        })
        next_block += 1
        return event

    def close_block() -> bytes:
        nonlocal current
        if current is None:
            return b""
        event = _sse("content_block_stop", {
            "type": "content_block_stop",
            "index": current["block_index"],
        })
        current = None
        return event

    def finalize() -> bytes:
        nonlocal stopped
        if stopped:
            return b""
        stopped = True
        out = close_block()
        out += _sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": _map_stop_reason(finish_reason), "stop_sequence": None},
            "usage": {"output_tokens": _normalize_usage(usage)["output_tokens"]},
        })
        out += _sse("message_stop", {"type": "message_stop"})
        return out

    async for item in _lines_with_pings(upstream_response, PING_INTERVAL):
        if item is None:
            yield _sse("ping", {"type": "ping"})
            continue
        if not isinstance(item, str):
            continue
        line = item
        if not line.strip() or line.startswith(":") or not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]

        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}

        # ---- tool calls (arguments may be fragmented across chunks) ----
        for tc in delta.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            tool_index = tc.get("index", 0)
            fn = tc.get("function") or {}
            arg_piece = fn.get("arguments") or ""
            if current is None:
                yield open_block(
                    "tool",
                    tool_index=tool_index,
                    call_id=tc.get("id") or "",
                    name=fn.get("name") or "",
                )
            elif current["kind"] != "tool" or current["tool_index"] != tool_index:
                yield close_block()
                yield open_block(
                    "tool",
                    tool_index=tool_index,
                    call_id=tc.get("id") or "",
                    name=fn.get("name") or "",
                )
            if arg_piece:
                current["args"] += arg_piece
                yield _sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": current["block_index"],
                    "delta": {"type": "input_json_delta", "partial_json": arg_piece},
                })

        # ---- text ----
        content_piece = delta.get("content")
        if content_piece:
            if current is None:
                yield open_block("text")
            elif current["kind"] != "text":
                yield close_block()
                yield open_block("text")
            current["text"] += content_piece
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": current["block_index"],
                "delta": {"type": "text_delta", "text": content_piece},
            })

        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    yield finalize()