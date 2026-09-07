# Claude Code via Polvo — Guia de uso

O Polvo expõe um *shim* do protocolo Anthropic Messages (`/v1/messages`) que
permite ao Claude Code CLI rodar contra qualquer upstream OpenAI-compatível
configurado no router (tiers adaptativos, modelos custom, classificador).

Este guia cobre o setup, o que está traduzido, os caveats conhecidos e o
troubleshooting. Para os detalhes de protocolo, veja
`docs/plans/claude-code-adapter-final.md`.

---

## Quickstart

```bash
# 1. Router no ar
polvo up          # (ou como você normalmente inicia o router)

# 2. Setup automático
polvo agent claude              # opcional: --context-tokens 131072
```

O comando grava em `~/.polvo/.env` (e garante que seu shell profile faz
`source ~/.polvo/.env`):

| Variável | Valor | Por quê |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://127.0.0.1:<port>` | **Sem** `/v1` — o cliente acrescenta `/v1/messages` sozinho |
| `ANTHROPIC_AUTH_TOKEN` | valor de `ROUTER_API_KEY` | Bearer; evita o prompt interativo do `ANTHROPIC_API_KEY` |
| `ANTHROPIC_MODEL` | `adaptive` | Força o roteamento adaptativo (classificador) para cada requisição |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `mini` | Trabalho de fundo/subagentes |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `pro` | Modelo primário |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `ultra` | Tarefas pesadas |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Só tráfego de modelo: mata telemetria e auto-update |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | (opcional, `--context-tokens`) | Janela assumida p/ compaction com IDs desconhecidos |

```bash
# 3. Recarregue o profile (ou abra um terminal novo)
source ~/.zshrc

# 4. Valide
claude
# dentro do CLI: /status → "Anthropic base URL" deve apontar para 127.0.0.1:<port>
```

### Checagem de conflitos

O setup avisa se `~/.claude/settings.json`, `.claude/settings.json` ou
`.claude/settings.local.json` definem variáveis Anthropic no bloco `env` —
**valores no settings file sobrescrevem o shell environment**, então um valor
antigo ali silencia o Polvo. Remova as chaves conflitantes do settings file.

### ⚠️ Segurança

Nunca coloque `ANTHROPIC_AUTH_TOKEN` em `.claude/settings.json` versionado no
repo — só em `~/.polvo/.env` (fora de versionamento) ou no settings pessoal.

---

## O que o shim traduz

Bidirecional, em `src/model_router/anthropic_translate.py`:

- **Requests**: `system` (string ou blocos) → message `system`; `tool_use` →
  `tool_calls`; `tool_result` (que chega dentro de mensagens `user`) → role
  `tool` com `tool_call_id`; `stop_sequences` → `stop`; imagens base64 →
  `image_url`; tools → formato `function` aninhado.
- **Streaming**: SSE do OpenAI → eventos Anthropic (`message_start`,
  `content_block_start/delta/stop`, `message_delta`, `message_stop`), com
  `input_json_delta` para argumentos de tool fragmentados.
- **Keep-alive**: pings a cada 15 s de silêncio do upstream (o cliente
  desconecta streams sem dados por 300 s).
- **Erros**: envelope Anthropic `{"type":"error","error":{...}}` com os tipos
  corretos por status (`rate_limit_error`, `api_error`, …).
- **`POST /v1/messages/count_tokens`**: estimativa (~4 chars/token).

---

## Caveats conhecidos (o que fica indisponível/degradado)

- **`/fast`**: a checagem fala direto com `api.anthropic.com` — reporta
  indisponível atrás de gateway.
- **Remote Control** e ditado por voz: indisponíveis com gateway credential.
- **MCP tool search**: desativado por default fora do host Anthropic
  (`ENABLE_TOOL_SEARCH=true` no cliente para restaurar).
- **Web search**: tool server-side da Anthropic; não existe no upstream —
  perde-se a busca web nativa.
- **Prompt caching**: o cliente envia markers `cache_control`; o hit depende
  do upstream honrá-los.
- **`/model`**: sem preços; IDs desconhecidos compactam com janela assumida
  (corrija com `--context-tokens`).
- **Auto-update do CLI**: desativado por `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.
  Atualize manualmente (`npm i -g @anthropic-ai/claude-code`, brew, ou o
  gerenciador que você usou).

### Comportamento do modelo

Compatibilidade de proxy resolve a **conexão**; a **execução** depende do
modelo seguir o dialeto Anthropic de tool-use. Modelos fracos podem responder
em texto simples e o CLI ignora a ação (o bot "diz" que editou, mas não
altera o arquivo). Prefira modelos de alta capacidade como agente primário e
reserve `mini` para trabalho de fundo.

---

## Troubleshooting

| Sintoma | Causa provável | Correção |
|---|---|---|
| 400 em requests com thinking/betas | beta não suportado pelo upstream | `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` e/ou `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` no shell |
| `/v1/v1/messages` nos logs do router | `/v1` no `ANTHROPIC_BASE_URL` | rode `polvo agent claude` de novo (grava sem o sufixo) |
| 401 ao abrir o CLI | token desalinhado | confira `ROUTER_API_KEY` em `~/.polvo/.env` vs `/status` |
| Cli desconecta em respostas longas | upstream sem keep-alive | já mitigado (pings a cada 15 s); se persistir, verifique proxies intermediários |
| Ferramenta "executada" mas arquivo intocado | modelo fraco fora do dialeto Anthropic | troque a tier (`polvo tier`) por modelo mais forte |
| Setup não surte efeito | settings file sobrescrevendo env | rode `polvo agent claude` e remova as chaves apontadas no warning |

Verificação de ponta a ponta em `tests/test_integration_messages.py`
(uvicorn real + stub de upstream, sockets de verdade — nada bate no
provedor externo).