# Code Review — Fase 1 do plano `docs/plans/claude-code-adapter-final.md`

> **Alvo:** shim de protocolo Anthropic no Polvo Router (`src/model_router/proxy.py`, diff não commitado na branch `feature/claude-code-adapter`).
> **Data:** 2026-09-06
> **Método:** 8 ângulos de busca (3 correção + 3 limpeza + altitude + convenções) × 6 candidatos → verificação 1-voto (recall-biased) → 10 findings.
> **Nota:** nenhum CLAUDE.md existe (repo ou usuário) — ângulo de convenções sem resultado.

## Resumo

O shim não funciona ponta a ponta: a tradução SSE emite frames malformados (`\n`/`\"` literais em vez de newline/aspas reais — verificado executando os literais), tool results nunca são traduzidos (branch `role == "tool"` é código morto), e o schema dos eventos desvia do protocolo Anthropic em cinco pontos. O caminho streaming ainda quebra com KeyError→500 em configs sem tier `mini`. Non-streaming devolve JSON OpenAI cru, e `count_tokens` responde shape inventado sem checagem de auth. Nenhum teste cobre os novos endpoints.

## Findings (10, do mais severo ao menos)

```json
[
  {
    "file": "src/model_router/proxy.py",
    "line": 409,
    "summary": "SSE events are built with double-escaped byte/f-strings (\\n, \\\"), so frames contain literal backslash-n/backslash-quote instead of real newlines and quotes — the stream has no valid SSE framing and no parseable JSON.",
    "failure_scenario": "Any streaming POST /v1/messages: the bytes emitted are literally 'event: message_start\\ndata: {\\\"type\\\": \\\"message\\\"}\\n\\n' with two-character \\n sequences (verified by executing the literal). An SSE client splits frames on real blank lines, so the entire stream arrives as one unterminated line and zero events are ever dispatched; Claude Code renders nothing. Same defect at lines 418, 422, 424, 430, 431, 432, 444 — only line 400's message_stop is correctly escaped."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 309,
    "summary": "tool_result blocks inside user messages are silently dropped: the user branch joins only type=='text' blocks, and the role=='tool' branch at line 343 is dead code because the Anthropic Messages API never sends role 'tool'.",
    "failure_scenario": "Claude Code runs one tool round-trip: assistant tool_use → user tool_result. The translator emits {\"role\":\"user\",\"content\":\"\"} and no OpenAI role:'tool' message, so the upstream sees assistant tool_calls followed by an empty user turn — OpenAI-compatible providers reject this (tool_calls must be followed by tool messages) or the model never sees the tool output and re-emits the same tool_use forever. Every agentic loop breaks on the second turn."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 418,
    "summary": "Even with escaping fixed, the emitted events are schema-nonconformant: message_start is {\"type\":\"message\"} instead of the {\"type\":\"message_start\",\"message\":{id,role,usage,...}} envelope, content_block_start lacks the index/content_block wrapper, input_json_delta uses \"delta\" instead of \"partial_json\", and message_delta (stop_reason + usage) is never emitted, plus message_stop is sent twice (line 400 and the line-444 safeguard).",
    "failure_scenario": "A corrected-framing client still fails: json.loads on data: {\"type\": \"message\"} gives no message.id/usage; tool arguments arrive empty because 'delta' is ignored (the SDK reads 'partial_json'); with no message_delta/stop_reason the turn never terminates cleanly; the double message_stop is a protocol violation that aborts the stream."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 415,
    "summary": "The translator has no per-block state: it emits a content_block_start/delta/stop triplet for every delta chunk, so OpenAI's fragmented tool-call arguments (the exact case responses.py translate_stream coalesces) become dozens of separate one-character tool_use blocks, and tc['function']['name'] raises KeyError on argument-only deltas which the broad except at line 439 silently swallows.",
    "failure_scenario": "A streamed tool call whose arguments arrive across 20 chunks (standard OpenAI streaming) produces 20 independent closed tool_use blocks with no accumulated JSON — the client cannot reassemble one tool call; each argument-only delta (no function.name) throws KeyError and its fragment is dropped with only a log line, so tool input is truncated. Text behaves the same per token, tripling event volume."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 515,
    "summary": "The non-streaming /v1/messages path calls _process_chat with no response transformer and returns the raw OpenAI chat.completion JSON (choices[].message) instead of an Anthropic Messages response.",
    "failure_scenario": "A client sends stream:false (plan smoke test §1.4-2). The passthrough at lines 201-206 yields the upstream OpenAI body with media_type application/json; the Anthropic client cannot deserialize it (no id/type/content[]/stop_reason/usage) — every non-streaming request breaks, and usage metering is lost."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 478,
    "summary": "The hardcoded fallback tier \"mini\" is indexed into settings.models.tiers even though config.py only creates tiers present in the YAML, producing a KeyError → unhandled 500 instead of _process_chat's clean 400.",
    "failure_scenario": "router config with only air/pro tiers (or only custom models) and a client request with an unknown model id and stream:true: tier_for_alias returns None, has_adaptive() is False, routed_tier becomes the literal 'mini', and tiers['mini'] raises KeyError — 500 Internal Server Error where /v1/chat/completions returns 400 'No adaptive tiers configured.'"
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 377,
    "summary": "_translate_anthropic_request whitelists only messages/tools/model/stream, dropping max_tokens, temperature, top_p, stop_sequences and every other top-level Anthropic request field.",
    "failure_scenario": "Claude Code always sends max_tokens on /v1/messages; upstreams that require it reject the request with 400, and any request-level temperature/top_p/stop_sequences is silently ignored for every Anthropic-protocol call even though dict(body) forwarding (lines 160/483) would have passed them through. Only per-tier extra_params can compensate, and only statically."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 379,
    "summary": "The translator always emits \"tools\": openai_tools if openai_tools else None, so every request without tools is forwarded upstream with an explicit tools: null key (both the streaming path and the non-streaming path through _process_chat).",
    "failure_scenario": "A plain prompt with no tools is POSTed upstream as {..., \"tools\": null}. Strict OpenAI-compatible upstreams (OpenAI, vLLM, OpenRouter) reject a null tools array with 400/422, so non-tool requests fail through /v1/messages while the same prompt via /v1/chat/completions succeeds."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 518,
    "summary": "count_tokens_shim is the only router endpoint without the _auth_ok check, and it returns a fabricated {\"count\": 0, \"message\": ...} instead of the Anthropic shape {\"input_tokens\": N}.",
    "failure_scenario": "With ROUTER_API_KEY set, an unauthenticated caller gets 200 from /v1/messages/count_tokens, bypassing the auth invariant every other route enforces. Legitimate Claude Code calls always read 0 (the field name is wrong anyway), so context-window budgeting under-reports and overflows surface only as mid-task upstream context-length errors."
  },
  {
    "file": "src/model_router/proxy.py",
    "line": 495,
    "summary": "The streaming path awaits upstream.post(...), which buffers the entire upstream response before any byte is forwarded, and emits no SSE keep-alive pings — both explicitly forbidden by plan §1.3 given Claude Code's 300s silent-stream watchdog.",
    "failure_scenario": "An upstream that takes >300s before its first chunk (long prefill or extended thinking, which produces only pings from real Anthropic) leaves the router blocked inside await upstream.post() with nothing on the wire; Claude Code's watchdog aborts the stream and the turn dies. Alternative: upstream.stream('POST', ...) + aiter_lines, and emit 'event: ping' on read timeouts. (Also: the response is never aclose()d when reusing the app-level http_client, leaking a pooled connection per streamed turn.)"
  }
]
```

## Achados adicionais (cortados pelo limite de 10 — limpeza/altitude, sem crash)

- **Duplicação de `_process_chat`:** o branch streaming de `messages_shim` copia ~35 linhas de roteamento/chamada/cleanup em vez de adicionar um parâmetro de transformador de resposta ao lado do flag `responses_mode` existente. A cópia já divergiu: 500 cru em vez do wrap 502 (linhas 180-183), headers `X-Router-Model`/`X-Router-Tier` ausentes, sem truncamento `[:2000]` do corpo de erro, e o corpo de erro upstream vai embrulhado em `{"detail": ...}` (não verbatim, contrariando §1.3).
- **Diário de design:** as linhas 460-474 são um bloco de comentários narrando um plano abandonado ("To keep it DRY, I'll modify _process_chat slightly in a real scenario... Actually, a better way...") — 15 linhas que enganam o leitor.
- **Parâmetro morto:** `routed_model` em `_translate_openai_to_anthropic_stream` nunca é usado.
- **Reimplementação:** o loop de tradução de tools duplica `responses_translate.translate_tools` (sem a validação defensiva dele); o flatten de blocos duplica `_extract_text_from_parts`.
- **Sem testes:** zero cobertura de `/v1/messages` e `/v1/messages/count_tokens` — os 22 testes de `tests/test_proxy.py` cobrem só os outros endpoints, então nada acima é pego pelo CI.
- **Candidato refutado:** o TypeError alegado em `proxy.py:475` (join sobre `content: None` de mensagens assistant) não ocorre — a comprehension filtra `m["role"] == "user"`, e toda mensagem user traduzida tem conteúdo `str`.

## Sugestão de correção estrutural (altitude)

Adicionar um parâmetro `response_transformer` (ou flag `anthropic_mode`) a `_process_chat` — o mesmo mecanismo do `responses_mode` — e construir cada evento SSE como dict + `json.dumps` num único helper `emit()`, portando o state machine de blocos de `responses_translate.translate_stream` (coalescing de argumentos fragmentados por `index`, contagem de uso, pings). Isso elimina a duplicação e a classe inteira de bugs de escaping.