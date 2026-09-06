# Plano — Claude Code com provedor próprio via proxy (equipamento local)

> **Status:** plano de referência (nada implementado).
> **Data:** 2026-09-06
> **Fonte:** documentação oficial do Claude Code (code.claude.com/docs), verificada em setembro/2026.
> **Contexto:** executar o Claude Code CLI contra um provedor self-hosted (Ollama / GLM / vLLM etc.) atrás de um gateway próprio, em vez da API da Anthropic. Setup atual usa endpoint em nuvem (`glm-5.3-flash:cloud`); o objetivo é trazer isso para o equipamento local.

---

## 1. Conceito fundamental

O Claude Code **só fala o formato Anthropic Messages**. Ele nunca envia requisições no
formato OpenAI (`/v1/chat/completions`). Logo, qualquer backend (Ollama, GLM, vLLM,
LiteLLM, etc.) precisa ficar atrás de um **gateway que exponha `/v1/messages`** e
traduza para o formato do upstream.

- Formatos de API suportados nativamente pelo cliente: **Anthropic Messages**,
  Amazon Bedrock InvokeModel, Google Cloud Agent Platform `rawPredict`.
  (https://code.claude.com/docs/en/llm-gateway-protocol)
- **Posição oficial da Anthropic:** rotear o Claude Code para modelos não-Claude via
  gateway *funciona*, mas **não é suportado** ("Anthropic doesn't endorse, maintain,
  or audit third-party gateway products"). Espere ajustes ocasionais a cada release
  (novos beta headers/campos aparecem e o proxy precisa acompanhar).
  (https://code.claude.com/docs/en/llm-gateway)

---

## 2. Variáveis de ambiente (nomes atuais, verificados)

### 2.0 Requisito de Capacidade do Modelo (Behavioral Mimicry)
**Importante:** A compatibilidade do proxy resolve a conexão (protocolo), mas não a execução (comportamento).
- **Mimetismo de Dialeto:** O Claude Code espera que o modelo responda rigorosamente no formato de tool-use da Anthropic. Modelos menos capazes podem responder no formato OpenAI ou texto simples, o que fará com que o CLI ignore a ação (o bot "fala" que editou, mas não altera o arquivo).
- **Seguimento de System Prompt:** O cliente envia instruções complexas de orquestração. Apenas modelos de alta performance (Tiers Pro/Ultra) tendem a mimetizar o comportamento do Claude com precisão suficiente para evitar a degradação da experiência.
- **Conclusão:** Para estabilidade total, recomenda-se evitar modelos "mini" ou experimentais para a função de agente primário do Claude Code.

### 2.1 Roteamento e autenticação

| Variável | Função |
|---|---|
| `ANTHROPIC_BASE_URL` | Endpoint do gateway. Efeitos colaterais em host não-Anthropic: MCP tool search desativado por default (reabilitar com `ENABLE_TOOL_SEARCH=true`); Remote Control desativado (v2.1.196+). |
| `ANTHROPIC_AUTH_TOKEN` | Enviado como `Authorization: Bearer <valor>`. **Recomendado** quando o tipo de credencial é desconhecido. |
| `ANTHROPIC_API_KEY` | Enviado como `x-api-key`. Sobrescreve login cla.ai; no modo interativo pede aprovação única (se recusada, reabilitar via `/config` → "Use custom API key"); em `-p` é sempre usada. |
| `ANTHROPIC_CUSTOM_HEADERS` | Headers extras, pares `Name: Value` separados por `\n` em blocos `env` (v2.1.227+). |
| `ANTHROPIC_BETAS` | Valores extras de `anthropic-beta`, separados por vírgula. |

### 2.2 Seleção / alias de modelos

| Variável | Função |
|---|---|
| `ANTHROPIC_MODEL` | Modelo da sessão. |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Resolve o alias `haiku` **e** todo trabalho de fundo classe-haiku. `ANTHROPIC_SMALL_FAST_MODEL` está **deprecado** em favor deste. |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` / `_OPUS_MODEL` / `_FABLE_MODEL` | Resolvem os aliases `sonnet`/`opus`/`fable` (e `opusplan`). |
| `ANTHROPIC_DEFAULT_MODEL` | Modelo default de novas sessões (v2.1.236+). |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` (+ `_NAME`, `_DESCRIPTION`) | Adiciona um modelo do gateway ao picker `/model` (ID isento de validação). |
| `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` | Popula `/model` a partir de `GET /v1/models?limit=1000` do gateway (mantém só IDs contendo `claude`/`anthropic`; cache em `~/.claude/cache/gateway-models.json`). |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Modelo default de subagentes/teammates (`_FORCE` sobrescreve escolha por invocação). |

Cada `ANTHROPIC_DEFAULT_*_MODEL` tem companheiros opcionais `_NAME`, `_DESCRIPTION` e
`_SUPPORTED_CAPABILITIES` — porém **`_SUPPORTED_CAPABILITIES` não tem efeito atrás de
`ANTHROPIC_BASE_URL`** (funciona apenas com `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`/`_MANTLE`).

### 2.3 Timeouts e tráfego

| Variável | Função |
|---|---|
| `API_TIMEOUT_MS` | Timeout de requisição; default 600000 (10 min). |
| `API_FORCE_IDLE_TIMEOUT` | Controla o timeout de 5 min de corpo ocioso; unset = ativo em provedores que não sejam a API direta Anthropic. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` | Presença apenas (qualquer valor não vazio). Mata auto-update, telemetria e checagens de versão — útil porque o gateway só carrega tráfego de modelo. **Desliga auto-update: planejar atualização manual.** |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | Corrige o compact de modelos desconhecidos (assumem janela default). |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | Teto de output. |
| `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` | TTL do cache do `apiKeyHelper` (default 5 min). |

### 2.4 Correções de erro comuns atrás de proxy (schema bridging)

| Erro observado | Variável de mitigação |
|---|---|
| `400 Extra inputs are not permitted` / `context_management` | `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` |
| `400 Input tag 'adaptive'` | `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` |
| Cache por corpo de requisição em builds < v2.1.181 | `CLAUDE_CODE_ATTRIBUTION_HEADER=0` (remove bloco de atribuição do system prompt) |

---

## 3. Onde definir a configuração (precedência)

- **Locais possíveis:** bloco `env` de qualquer settings file; `apiKeyHelper` (qualquer
  settings file); variáveis de shell.
- **Precedência entre arquivos (maior vence):** managed settings → `--settings` →
  `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`.
- **Settings file vence shell:** cada entrada do bloco `env` é escrita no processo,
  substituindo o valor herdado do shell.
- ⚠️ **Nunca colocar credencial em `.claude/settings.json`** (arquivo versionado).
- ⚠️ Bloco `env` no settings do projeto só se aplica *após* o wizard de primeira execução
  e o prompt de trust — para evitar prompt de login na primeira execução, usar shell,
  `~/.claude/settings.json` ou managed settings.
- **`apiKeyHelper`:** comando que imprime a credencial; enviado em **ambos** os headers
  (`Authorization: Bearer` e `x-api-key`), o que o torna compatível com qualquer estilo.
  Ideal para credenciais em vault/rotativas.
- **Validação:** `/status` dentro do Claude Code mostra "Anthropic base URL" e o
  credential em uso. Smoke test documentado: `curl` em `$ANTHROPIC_BASE_URL/v1/messages`.

---

## 4. Requisitos do endpoint do proxy (a parte que mais quebra)

Especificação completa: https://code.claude.com/docs/en/llm-gateway-protocol

1. **Formato:** `POST /v1/messages` — os requests chegam como
   `/v1/messages?beta=true`; **case pelo path, não pela URL completa**.
   Opcional: `POST /v1/messages/count_tokens` (sem ele, o fallback conta via o próprio
   messages). `HEAD /api/hello` é um probe best-effort que pode ser rejeitado.
   `/v1/models` é opcional (só para model discovery).
2. **Streaming obrigatório (SSE):** o cliente lê o stream conforme chega; proxy que
   buffera a resposta inteira **trava**. Repassar também eventos `ping` e comentários
   SSE — há um watchdog que aborta streams silenciosos por 300 s (pausas longas de
   thinking produzem apenas pings). Tradutores de upstream não-streaming devem emitir
   pings próprios.
3. **Headers a repassar verbatim:**
   - `anthropic-beta` — **nunca** allowlistar valores individuais (o conjunto muda por
     release; filtrar o capability OAuth quebra auth de subscription com 401).
   - `anthropic-version` — hoje `2023-06-01`.
4. **Credenciais:** `Authorization`/`x-api-key` carregam o credential;
   `x-claude-code-session-id` / `x-claude-code-agent-id` / `x-claude-code-parent-agent-id`
   são headers de atribuição (podem ser consumidos para métricas/roteamento).
5. **Corpo:** repassar `cache_control` e o array `system` **sem alterar** (a remoção
   posicional do bloco de atribuição depende disso); encaminhar corpos de erro
   **modificados** → **sem reescrever** (o retry por capability-rejection casa com o
   texto do erro do upstream). Inspecionar sem reescrever; tratar campos `anthropic-*`
   como listas abertas.
6. **Tool use:** uso agêntico exige que o schema completo de tools passe intacto; os
   capability headers e seus campos no corpo viajam em pares — remover metade gera `400`.
7. **Não existe modo cliente OpenAI:** o Claude Code jamais envia `/v1/chat/completions`.
   Um proxy que aceita Anthropic Messages e repassa para um upstream OpenAI está fazendo
   *schema bridging* — exatamente o modo de falha dos erros `400` de
   `context_management`/`thinking`/`output_config` (https://code.claude.com/docs/en/llm-gateway-connect).

---

## 5. Opções de gateway

- **Claude apps gateway** — gateway self-hosted da própria Anthropic, embarcado no
  binário `claude` (https://code.claude.com/docs/en/claude-apps-gateway). Upstreams:
  Anthropic API, Bedrock, Claude Platform on AWS, Google Cloud Agent Platform, Microsoft
  Foundry. Sai junto com o CLI (sem regras de forwarding a manter). Sem fluxo de
  service-token (não serve para CI). **Limitação para este caso:** não roteia para
  backends como Ollama/GLM.
- **Terceiros (LiteLLM, claude-code-router, Portkey, Kong, Cloudflare AI Gateway…):**
  os docs **não endossam nem listam** vendors; o único requisito é "expor um formato de
  API suportado". Status atual do endpoint Anthropic-compat do Ollama **não verificado**
  (fetch externo negado na sessão de pesquisa) — conferir o changelog do Ollama.
- **Gateway próprio** — para este plano (equipamento próprio + backend GLM/Ollama), a
  opção recomendada: um processo local que exponha `/v1/messages` com SSE e traduza
  para o backend escolhido.

---

## 6. Caveats documentados com `ANTHROPIC_BASE_URL` / backend não-Claude

- **`/fast`:** a checagem de disponibilidade chama `api.anthropic.com` diretamente (não
  o base URL); com egress bloqueado ou chave de gateway, reporta fast mode indisponível.
  `CLAUDE_CODE_SKIP_FAST_MODE_ORG_CHECK=1` para o caso bearer-token
  (https://code.claude.com/docs/en/fast-mode).
- **`/model`:** validação de nome é desativada atrás de `ANTHROPIC_BASE_URL` (qualquer
  string passa); sem preços; IDs desconhecidos compactam com janela assumida (corrigir
  com `CLAUDE_CODE_MAX_CONTEXT_TOKENS`).
- **Remote Control e ditado por voz:** indisponíveis com gateway credential ativo;
  Remote Control também desativado com `ANTHROPIC_BASE_URL` não-Anthropic (v2.1.196+).
  Superfícies Slack/web sempre usam a API da Anthropic, independente do env.
- **MCP tool search** desativado por default em host não-first-party
  (`ENABLE_TOOL_SEARCH=true` para restaurar); **fine-grained tool streaming** off por
  default atrás de base URL custom (ligar com `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`).
- **Prompt caching:** o cliente envia markers `cache_control` de qualquer forma; o hit
  depende do upstream honrá-los. Com cache por corpo de request em builds < v2.1.181,
  usar `CLAUDE_CODE_ATTRIBUTION_HEADER=0` (o bloco é estável por conversa desde então).
- **Web search:** tool server-side da Anthropic; em upstream não-Anthropic o proxy
  precisa implementá-la ou a capability falha (inferido dos docs da API, flagged como tal).
- **Subagentes** continuam funcionando; atribuir tráfego via `x-claude-code-agent-id`
  e rotear modelo via `CLAUDE_CODE_SUBAGENT_MODEL`.
- **Model aliases** (haiku/sonnet/opus) precisam ser mapeados explicitamente, senão o
  trabalho de fundo quebra ou usa IDs que o backend não conhece.

---

## 7. Configuração alvo (proposta, pendente de definição do backend)

```json
// ~/.claude/settings.json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:PORTA_DO_GATEWAY",
    "ANTHROPIC_AUTH_TOKEN": "TOKEN_DO_GATEWAY",
    "ANTHROPIC_MODEL": "MODELO_PRINCIPAL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "MODELO_PEQUENO",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "JANELA_DO_MODELO"
  }
}
```

Placeholders a preencher depois de decidir backend/porta/gateway (ver §8).

---

## 8. Checklist de implementação (a executar em outro momento)

1. [ ] Decidir backend local (Ollama / GLM local / vLLM) e modelo(s) — principal e "pequeno".
2. [ ] Escolher/instalar o gateway que expõe `/v1/messages` com SSE (LiteLLM
       passthrough Anthropic, claude-code-router, ou adapter próprio). Verificar se o
       Ollama atual já expõe endpoint Anthropic-compat nativo.
3. [ ] Subir o gateway em localhost:porta e validar com:
       `curl -N $BASE_URL/v1/messages` (streaming + tool use de amostra).
4. [ ] Verificar que o gateway repassa verbatim: `anthropic-beta`, `anthropic-version`,
       `cache_control`, array `system`, corpos de erro.
5. [ ] Preencher `~/.claude/settings.json` conforme §7 (sem credencial em settings do projeto).
6. [ ] Rodar `claude` → conferir `/status` (base URL + credential corretos).
7. [ ] Teste mínimo: sessão interativa com uma edição de arquivo (valida tool use + streaming).
8. [ ] Se surgir `400 context_management`/`adaptive`: aplicar as flags do §2.4.
9. [ ] Mapear aliases de modelo (`ANTHROPIC_DEFAULT_*_MODEL`) e definir
       `CLAUDE_CODE_MAX_CONTEXT_TOKENS` conforme a janela real do backend.
10. [ ] Opcional: `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` ou
        `ANTHROPIC_CUSTOM_MODEL_OPTION` para popular `/model`.
11. [ ] Planejar path de atualização manual do CLI (por causa de
        `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`).

---

## 9. Referências

- Gateway protocol (especificação de compatibilidade): https://code.claude.com/docs/en/llm-gateway-protocol
- Visão geral de gateways: https://code.claude.com/docs/en/llm-gateway
- Troubleshooting de conexão a gateway: https://code.claude.com/docs/en/llm-gateway-connect
- Variáveis de ambiente: https://code.claude.com/docs/en/env-vars
- Configuração de modelos: https://code.claude.com/docs/en/model-config
- Settings files: https://code.claude.com/docs/en/settings
- Claude apps gateway: https://code.claude.com/docs/en/claude-apps-gateway
- Fast mode: https://code.claude.com/docs/en/fast-mode
- Third-party integrations: https://code.claude.com/docs/en/third-party-integrations