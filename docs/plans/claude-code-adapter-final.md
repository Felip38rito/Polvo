# Plano Final — Claude Code Adapter (Polvo)

> **Status:** plano consolidado para implementação (nada implementado).
> **Data:** 2026-09-06
> **Objetivo:** transformar o Polvo Router em um dublê compatível com o protocolo Anthropic Messages, para que o Claude Code CLI opere sobre a Adaptive Scale do Polvo em equipamento local.
> **Fontes:** docs oficiais do Claude Code (code.claude.com/docs, set/2026) + plano de implementação do Polvo (`claude-code-adapter-implementation.md`).
> **Histórico:** consolidação de `claude-code-custom-provider-proxy.md` (spec de referência, verificada contra docs oficiais) e `claude-code-adapter-implementation.md` (roteiro de implementação), com as correções indicadas na comparação.

---

## 0. Arquitetura alvo

```
┌──────────────┐   Anthropic Messages    ┌──────────────────────┐   OpenAI-format    ┌─────────────────┐
│ Claude Code  │ ──────────────────────► │  Polvo Router        │ ─────────────────► │ Adaptive Scale  │
│ CLI          │  POST /v1/messages      │  (shim de protocolo) │  /v1/chat/...      │ (mini/pro/ultra)│
└──────────────┘ ◄────────────────────── └────────────────────── ┘ ◄───────────────── └─────────────────┘
                 SSE verbatim, tool_use      tradução bidirecional      chunks streaming
```

Contrato externo (Claude Code ↔ Polvo Router): **formato Anthropic Messages, exato**.
Contrato interno (Polvo Router ↔ upstream): formato atual do Polvo (OpenAI-style).

**Princípio central:** o shim nunca deve inventar ou "melhorar" o protocolo — repassar
verbatim o que entende, traduzir o que precisa traduzir, e deixar o corpo de erro
chegar intacto ao cliente.

---

## Fase 1 — O "Shim" de Protocolo (Backend Router)

### 1.1 Novo endpoint de entrada (`src/model_router/proxy.py`)

- **Rota:** `POST /v1/messages`. Os requests chegam como
  `/v1/messages?beta=true` — **case pelo path, não pela URL completa**.
- **Rotas auxiliares:**
  - `POST /v1/messages/count_tokens` — implementar (sem ele o fallback conta via o
    próprio messages, gastando tokens/latência). Alternativa mínima: proxy pass-through
    com contagem heurística; registrar a decisão.
  - `GET /v1/models` — opcional, usado apenas para model discovery
    (`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` no cliente).
  - `HEAD /api/hello` — probe best-effort do cliente; pode ser rejeitado com 404.
- **Headers a repassar verbatim (nunca filtrar/allowlistar):**
  - `anthropic-beta` — o conjunto muda a cada release do CLI; **repassar a linha
    inteira sem parse**. Filtrar valores quebra auth de subscription com 401 e pode
    romper pares capability↔campo.
  - `anthropic-version` — hoje `2023-06-01`; repassar sem reescrever.
- **Headers consumíveis (atribuição/roteamento):**
  `x-claude-code-session-id`, `x-claude-code-agent-id`, `x-claude-code-parent-agent-id`
  — podem ser usados para métricas/roteamento por agente; não são obrigatórios de devolver.
- **Autenticação:** aceitar `Authorization: Bearer` (do `ANTHROPIC_AUTH_TOKEN` do
  cliente) **e** `x-api-key` (do `ANTHROPIC_API_KEY`) — não depender de um só estilo.

### 1.2 Tradução de request (Anthropic → OpenAI)

- `system` (array com blocos, possivelmente marcados com `cache_control`) → role `system`.
  **Preservar o texto integral** — não reordenar nem descartar blocos.
- Array `messages` (roles `user`/`assistant`, blocos `text`/`tool_use`/`tool_result`)
  → formato de chat OpenAI:
  - `tool_use` (assistant) → mensagem com `tool_calls`.
  - `tool_result` (user) → mensagem role `tool` com o `tool_use_id` correspondente.
- **Array `tools` do request → funções OpenAI.** Campo essencial: cada tool da Anthropic
  (`name`, `description`, `input_schema`) vira uma function OpenAI
  (`name`, `description`, `parameters`). Sem isso o uso agêntico não funciona — é o
  caminho de ida que habilita o caminho de volta (§1.3).
- `model` → extrair e passar pelo classificador de tiers do Polvo.
- **Corpo:** inspecionar sem reescrever. Não descartar campos desconhecidos
  (`cache_control`, `metadata`, campos de capability) — campos de capability viajam em
  pares com headers; remover só um lado gera `400` duro. Se um campo for incompatível
  com o upstream, traduzir ou descartar **o par inteiro** (header + campo), nunca metade.

### 1.3 Tradução de resposta (OpenAI → Anthropic) — streaming SSE

- **Generator de tradução de chunks:** OpenAI deltas → eventos Anthropic:
  `message_start` → `content_block_start` → `content_block_delta`* →
  (`content_block_stop`) → `message_delta` → `message_stop`.
- **Streaming obrigatório:** enviar conforme chega; **bufferizar a resposta inteira
  trava o cliente**. Repassar também comentários SSE.
- **Pings de keep-alive:** se o upstream for lento, emitir `event: ping` — há um
  watchdog no cliente que aborta streams silenciosos por 300 s (pausas longas de
  thinking produzem apenas pings). Um tradutor de upstream não-streaming **precisa**
  emitir pings próprios.
- **Tool use — formato correto:** traduzir `tool_calls` da OpenAI em
  **blocos de conteúdo `tool_use` da Anthropic** (`{"type": "tool_use", "id", "name",
  "input"}` com `input` em JSON), emitidos via `content_block_start`/`content_block_delta`
  (`input_json_delta`) /`content_block_stop`.
  - ⚠️ Correção sobre o plano anterior: o Claude Code **não** espera tags XML
    (`<tool_code>...`); espera blocos `tool_use` nativos. A tradução abaixo disso
    elimina a necessidade do "sanitizador de tags" previsto antes.
- **Erros:** encaminhar o **corpo de erro do upstream sem reescrever** — o retry
  capability-rejection do cliente casa com o texto do erro. Status code e payload
  devem chegar intactos.

### 1.4 Validação de protocolo (smoke tests)

1. `curl -N $BASE_URL/v1/messages` com payload contendo `tools` + `messages` →
   verificar SSE de tokens e blocos `tool_use` íntegros, streaming incremental.
2. Request com `stream: false` → resposta única válida no formato Messages.
3. Request forçando erro do upstream → verificar que o corpo de erro chega intacto.
4. `POST /v1/messages/count_tokens` → resposta no formato esperado.
5. Carga lenta simulada (upstream pausado >300 s) → verificar pings evitando watchdog.

---

## Fase 2 — Automação do Setup (CLI)

### 2.1 Comando `polvo agent claude` (`src/polvo_cli/agent_cmd.py`)

Salvar em `~/.polvo/.env` via `core.save_env_key`:

| Variável | Valor | Nota |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:{ROUTER_PORT}` | ⚠️ **Sem `/v1`** — o cliente anexa `/v1/messages`; com `/v1` no fim os requests caem em `/v1/v1/messages`. O smoke test documentado é `curl $ANTHROPIC_BASE_URL/v1/messages`. |
| `ANTHROPIC_AUTH_TOKEN` | chave do router (default `router`) | Preferir `ANTHROPIC_AUTH_TOKEN` a `ANTHROPIC_API_KEY`: vai como `Authorization: Bearer` e não pede o prompt de aprovação interativa que o `ANTHROPIC_API_KEY` pede na primeira sessão. |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `mini` | Resolve o alias `haiku` **e** todo trabalho de fundo classe-haiku. (`ANTHROPIC_SMALL_FAST_MODEL` é deprecado.) |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `pro` | Alias `sonnet` (e `opusplan`). |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `ultra` | Alias `opus`. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Mata telemetria/versões; **desliga auto-update — planejar atualização manual do CLI**. |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | janela real da tier menor | Corrige o compact de modelos desconhecidos (a validação de nome é desativada atrás de `ANTHROPIC_BASE_URL`). |
| `API_TIMEOUT_MS` | opcional | Default 600000 (10 min); ajustar se tiers lentas forem comuns. |

Mapeamento da Adaptive Scale: `haiku`→`mini`, `sonnet`→`pro`, `opus`→`ultra` (conforme
plano do Polvo).

**Persistência:** garantir `source ~/.polvo/.env` no profile do usuário
(`.zshrc`/`.bashrc`), seguindo o padrão já usado no `setup_copilot`.

⚠️ **Pegadinha de precedência:** entradas do bloco `env` em settings files do Claude
Code **sobrescrevem** o shell. Como o Polvo injeta via shell, instruir o usuário a não
ter esses valores em `~/.claude/settings.json`/settings do projeto, ou o Polvo validar
e avisar durante o setup.

⚠️ **Nunca** escrever a credencial em `.claude/settings.json` (arquivo versionado do projeto).

---

## Fase 3 — Verificação e Ajuste Fino

### 3.1 Teste de integração real

1. `polvo agent claude` → setup gravado.
2. Novo terminal (profile recarregado) → `claude`.
3. `/status` → validar "Anthropic base URL" apontando para o Polvo e o credential em uso.
4. Sessão interativa mínima: uma edição de arquivo (valida tool use + streaming de ponta a ponta).
5. Testar subagente/tarefa de fundo (valida roteamento via alias `haiku`→`mini`).

### 3.2 Tuning de behavior (comportamental, não protocolar)

- Compatibilidade de proxy resolve a **conexão**; a **execução** depende do modelo
  seguir o formato Anthropic de tool-use. Modelos fracos podem responder em texto
  simples/OutAI-style e o CLI ignora a ação (o bot "fala" que editou, mas não altera o arquivo).
- Preferir modelos de alta capacidade para a função de agente primário; evitar
  modelos "mini"/experimentais como agente primário (reservar `mini` para trabalho de fundo).
- Se um modelo falhar em produzir `tool_use` válido, o ponto de correção é o modelo
  escolhido na tier ou um ajuste fino no tradutor (§1.3), **não** um sanitizador de
  tags XML.

---

## Mitigações de erro conhecidas (definir no cliente, não no proxy)

| Erro observado | Mitigação (lado do cliente, via `~/.polvo/.env`) |
|---|---|
| `400 Extra inputs are not permitted` / `context_management` | `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` |
| `400 Input tag 'adaptive'` | `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` |
| Cache por corpo de request em builds < v2.1.181 | `CLAUDE_CODE_ATTRIBUTION_HEADER=0` |

Essas flags devem entrar no setup do `polvo agent claude` **sob demanda**: o comando
detecta o erro no primeiro uso e oferece ativar. A alternativa anterior ("o proxy ignora
campos desconhecidos") foi descartada — arrisca romper os pares capability↔campo.

---

## Caveats documentados (o que fica indisponível/degradado)

- **`/fast`**: checagem chama `api.anthropic.com` diretamente — reporta indisponível
  atrás de gateway (`CLAUDE_CODE_SKIP_FAST_MODE_ORG_CHECK=1` para o caso bearer-token).
- **Remote Control** e ditado por voz: indisponíveis com gateway credential; superpous
  Slack/web sempre usam a API da Anthropic.
- **MCP tool search**: desativado por default em host não-Anthropic
  (`ENABLE_TOOL_SEARCH=true` no cliente para restaurar).
- **Prompt caching**: o cliente envia markers `cache_control`; o hit depende do
  upstream honrá-los — o shim deve repassá-los (§1.2), mas o Polvo decide se explora.
- **Web search**: tool server-side da Anthropic; em upstream Polvo essa capability
  falha — aceitar a perda ou implementar no adapter.
- **`/model`**: sem preços; IDs desconhecidos compactam com janela assumida (corrigido
  por `CLAUDE_CODE_MAX_CONTEXT_TOKENS`). Opcional: `ANTHROPIC_CUSTOM_MODEL_OPTION`
  para aparecer tiers no picker.

---

## Resumo de riscos e mitigação

| Risco | Mitigação |
| :--- | :--- |
| **Cliente detecta/recusa proxy** | Repasse verbatim de `anthropic-beta` e `anthropic-version` (sem allowlist). |
| **Timeout de stream** | Pings SSE no generator; nunca buffere a resposta inteira. |
| **Tool-use ignorado** | Tradução bidirecional correta: `tools` (request) ↔ functions; `tool_calls` ↔ blocos `tool_use` (resposta). Sem tags XML. |
| **Path duplicado** | `ANTHROPIC_BASE_URL` sem `/v1`; case pelo path `/v1/messages`. |
| **Erro 400 (Extra Inputs / adaptive)** | Flags no cliente (`DISABLE_EXPERIMENTAL_BETAS`, `DISABLE_ADAPTIVE_THINKING`), ativas sob demanda. Nunca descartar campos no proxy. |
| **Compact errado / janela de contexto** | `CLAUDE_CODE_MAX_CONTEXT_TOKENS` por tier. |
| **Setup sobrescrito por settings files** | Validar no `polvo agent claude` que não há `env` conflitante em `~/.claude/settings.json` ou settings do projeto. |
| **CLI desatualizado** | Auto-update desligado por `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` — documentar path de atualização manual. |

---

## Checklist de implementação

1. [ ] `POST /v1/messages` em `src/model_router/proxy.py` (case pelo path).
2. [ ] Tradução de request: `system`, `messages`, **`tools`** (Anthropic→OpenAI).
3. [ ] Generator SSE OpenAI→Anthropic (eventos `message_*`/`content_block_*`).
4. [ ] Tradução de `tool_calls` → blocos `tool_use` (JSON `input`).
5. [ ] Pings keep-alive no stream (watchdog 300 s).
6. [ ] Repasse verbatim de `anthropic-beta`/`anthropic-version`; corpo de erro intacto.
7. [ ] `POST /v1/messages/count_tokens` (ou registrar fallback).
8. [ ] Opcional: `GET /v1/models` para model discovery.
9. [ ] Smoke tests do §1.4.
10. [ ] `polvo agent claude`: env vars da tabela §2.1 (**base URL sem `/v1`**,
        `ANTHROPIC_AUTH_TOKEN`, aliases mini/pro/ultra, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`).
11. [ ] Persistência no profile do usuário (padrão `setup_copilot`) + checagem de
        settings files conflitantes.
12. [ ] Flags de mitigação sob demanda (tabela §"Mitigações").
13. [ ] Teste de integração do §3.1 (incl. `/status` e edição de arquivo real).
14. [ ] Documentar caveats e path de atualização manual do CLI.

---

## Referências

- Gateway protocol: https://code.claude.com/docs/en/llm-gateway-protocol
- Gateway overview: https://code.claude.com/docs/en/llm-gateway
- Gateway connect (troubleshooting): https://code.claude.com/docs/en/llm-gateway-connect
- Env vars: https://code.claude.com/docs/en/env-vars
- Model config: https://code.claude.com/docs/en/model-config
- Settings: https://code.claude.com/docs/en/settings
- Fast mode: https://code.claude.com/docs/en/fast-mode