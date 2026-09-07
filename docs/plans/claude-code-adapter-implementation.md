# Plano de Implementação: Claude Code Adapter (Polvo)

Este plano detalha a transformação do Polvo Router em um dublê compatível com o protocolo da Anthropic para permitir que o Claude Code CLI opere sobre a Adaptive Scale do Polvo.

---

## Fase 1: O "Shim" de Protocolo (Backend Router)
O objetivo é fazer o `model_router` falar o dialeto da Anthropic sem quebrar o fluxo de streaming.

### 1.1 Novo Endpoint de Entrada
- **Rota**: Implementar `POST /v1/messages` no `src/model_router/proxy.py`.
- **Intercepção de Headers**: Capturar e repassar `anthropic-beta` e `anthropic-version` para evitar que o cliente detecte o proxy ou recuse a conexão.
- **Tradução de Request (Anthropic $\rightarrow$ OpenAI)**:
    - Mapear o array `system` (Anthropic) para a role `system` (OpenAI).
    - Converter a estrutura de mensagens da Anthropic para o formato de chat da OpenAI.
    - Extrair o `model` da requisição e passar pelo classificador de tiers do Polvo.

### 1.2 Motor de Tradução de Resposta (OpenAI $\rightarrow$ Anthropic)
- **Streaming SSE**: Implementar um generator que converte os chunks da OpenAI para os eventos de SSE da Anthropic (ex: `message_start`, `content_block_start`, `content_block_delta`, `message_stop`).
- **Anti-Buffering**: Garantir que a resposta seja enviada em tempo real. Se o upstream for lento, o proxy deve emitir pings de keep-alive para evitar o watchdog do Claude Code.
- **Tradução de Tool Use (Dialeto)**:
    - Interceptar `tool_calls` da OpenAI.
    - Reescrever a resposta no formato XML/JSON esperado pelo Claude Code (`<tool_code>...`).

### 1.3 Validação de Protocolo (Smoke Test)
- Teste via `curl -N` simulando o payload do Claude Code para garantir que o stream de tokens e as tags de tool-use chegam intactas.

---

## Fase 2: Automação do Setup (CLI)
Uma vez que o router seja compatível, automatizamos a "fiação" no sistema do usuário.

### 2.1 Implementação do Comando `polvo agent claude`
No arquivo `src/polvo_cli/agent_cmd.py`:
- **Injeção de Variáveis**: Salvar em `~/.polvo/.env` via `core.save_env_key`:
    - `ANTHROPIC_BASE_URL`: `http://127.0.0.1:{ROUTER_PORT}/v1`
    - `ANTHROPIC_API_KEY`: Chave do router (default `router`).
    - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: `1` (para matar telemetria/auto-update).
- **Mapeamento de Adaptive Scale**: Configurar as variáveis de alias para que o Claude Code use as tiers do Polvo:
    - `ANTHROPIC_DEFAULT_HAIKU_MODEL` $\rightarrow$ `mini`
    - `ANTHROPIC_DEFAULT_SONNET_MODEL` $\rightarrow$ `pro`
    - `ANTHROPIC_DEFAULT_OPUS_MODEL` $\rightarrow$ `ultra`
- **Persistência de Shell**: Garantir que o `source ~/.polvo/.env` esteja no profile do usuário (`.zshrc`/`.bashrc`), seguindo o padrão já usado no `setup_copilot`.

---

## Fase 3: Verificação e Ajuste Fino

### 3.1 Teste de Integração Real
1. Executar `polvo agent claude`.
2. Abrir novo terminal e rodar `claude`.
3. Comando `/status` para validar se o `Anthropic base URL` está apontando para o Polvo.

### 3.2 Tuning de Behavior
- Se o modelo escolhido na tier (ex: Pro) falhar em fechar tags de tool-use, implementar um "sanitizador" no proxy para forçar o fechamento de tags XML antes de entregar ao cliente.

---

## Resumo de Riscos e Mitigação
| Risco | Mitigação |
| :--- | :--- |
| **Claude Code detecta Proxy** | Repasse verbatim de headers de versão e beta. |
| **Timeout de Stream** | Implementação de pings SSE no loop do generator. |
| **Tool-use ignorado** | Tradutor de dialeto (OpenAI $\rightarrow$ Anthropic XML). |
| **Erro 400 (Extra Inputs)** | Proxy ignora campos desconhecidos no request da Anthropic. |
