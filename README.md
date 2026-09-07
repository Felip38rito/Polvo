<img width="376" alt="polvo" src="https://github.com/user-attachments/assets/853b0bca-a42d-4b1f-b6a9-efb7a8891da6" />



# Polvo

Polvo is a local **OpenAI-compatible proxy** that intelligently routes chat requests to the cheapest model capable of handling the task. By segregating trivial requests from complex reasoning, Polvo allows you to maintain high-tier performance while drastically reducing token costs.

It is **provider-agnostic**: it works with any OpenAI-compatible API (Ollama Cloud, local Ollama, OpenAI, OpenRouter, etc.). You define your providers and map them to an adaptive scale of tiers.

## 🎯 The Problem

In modern AI workflows, you typically face a lose-lose trade-off:
- **Pin to a cheap model** $\rightarrow$ Complex prompts (architecture refactor, race condition debugging) get weak answers, wasting your time.
- **Pin to an expensive model** $\rightarrow$ Every request, even "hello", pays the top-tier price. In agents (Hermes, Claude Code, Cursor) that make dozens of tool calls per task, this burns credits rapidly.

**Polvo breaks this trade-off.** It classifies the intent of every request in real-time and routes it to the cheapest adequate tier.

## 🛠 How it Works

1. **Request Arrival**: A client points its `base_url` at Polvo.
2. **Hybrid Classification**: Polvo determines the required tier:
   - **Deterministic Path**: Instant routing for obvious cases (explicit model overrides or trivial chatter).
   - **LLM Path**: A lightweight model analyzes the prompt's qualitative requirements (intent, scope, context) and returns a strict JSON decision.
   - **Fail-safe**: If classification fails, it defaults to the `air` tier, ensuring the request never breaks.
3. **Adaptive Routing**: The request is forwarded to the upstream provider associated with that tier.
4. **Transparency**: Response headers (`X-Router-Model` and `X-Router-Tier`) reveal exactly which model handled the request.

> **Context Isolation**: Only the last user message is fed to the classifier. System prompts and tool history are ignored to prevent technical context from artificially inflating the required tier.

## 📉 The Adaptive Scale

| Tier | Target Use Case |
|---|---|
| `mini` | Trivial/mechanical tasks, greetings, and simple discussion. |
| `air` | Default day-to-day interaction and routine coding. |
| `pro` | Complex reasoning, deep debugging, design, and concurrency. |
| `ultra` | Whole-system synthesis, "impossible" problems, and adversarial tasks. |

## 🚀 Quick Start

### 1. Installation
Install Polvo with a single command (macOS and Linux):

```bash
curl -LsSf https://raw.githubusercontent.com/Felip38rito/Polvo/stable/install.sh | sh
```

The installer bootstraps `uv`, clones the repo into `~/.polvo`, installs the `polvo` CLI globally, and sets up the background service via `launchd` (macOS) or `systemd` (Linux).

### 2. Guided Onboarding
Run the interactive setup to configure your providers and the adaptive scale:

```bash
polvo
```

### 3. Verification
```bash
polvo status    # Check if the router is running
curl localhost:9000/v1/models  # List advertised tiers
```

## 🤖 Agent Integration

Polvo provides automated setup for popular AI agents. These commands configure the necessary environment variables in `~/.polvo/.env` and update your shell profile automatically.

```bash
polvo agent hermes    # Setup for Hermes Agent
polvo agent claude    # Setup for Claude Code
polvo agent codex     # Setup for Codex CLI
polvo agent copilot   # Setup for Copilot CLI
polvo agent opencode  # Setup for OpenCode
```

### Special Integrations
- **Claude Code**: Polvo forces the `adaptive` model for all `/v1/messages` requests. This overrides client-side model persistence, ensuring the classifier always decides the tier per request.
- **OpenCode**: The `agent opencode` command automates the `sync-opencode.py` process, pushing a snapshot of the router's tiers into the OpenCode configuration.

## ⚙️ Configuration

### Environment Variables
Configure these in `~/.polvo/.env` or your shell profile:

| Var | Default | Description |
|---|---|---|
| `ROUTER_PORT` | `9000` | Port the router binds to. |
| `ROUTER_HOST` | `127.0.0.1` | Bind address. |
| `ROUTER_API_KEY` | (empty) | Optional Bearer token for client authentication. |
| `ROUTER_DEFAULT_TIER` | `air` | Fallback tier if classification fails. |
| `ROUTER_MODELS_YAML` | `router.models.yaml` | Path to the model mapping file. |

### Model Mapping (YAML)
Config is resolved from `ROUTER_MODELS_YAML` $\rightarrow$ `~/.polvo/config.yml` $\rightarrow$ `router.models.yaml` $\rightarrow$ Defaults.

```yaml
default_tier: air

# Upstream endpoints
providers:
  ollama-cloud:
    base_url: https://ollama.com/v1
    api_key_env: OLLAMA_CLOUD_API_KEY
  open-router:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPEN_ROUTER_API_KEY

# The Adaptive Scale (Fixed keys: mini, air, pro, ultra)
adaptive:
  mini:
    model: gemma4:cloud
    description: "trivial/mechanical"
    provider: ollama-cloud
  air:
    model: deepseek-v4-flash:cloud
    description: "day-to-day"
    provider: ollama-cloud
  pro:
    model: minimax-m3:cloud
    description: "complex reasoning"
    provider: ollama-cloud
  ultra:
    model: glm-5.3
    description: "deep synthesis"
    provider: ollama-cloud

# Custom models (not used by classifier, routable by explicit ID)
custom:
  experimental-model:
    model: some-api-id
    provider: ollama-cloud

classifier:
  model: gemma4:cloud
  provider: ollama-cloud
  min_classify_len: 10
```

## 🛠 CLI Reference

### Management
```bash
polvo provider    # Manage upstream providers
polvo tier        # Configure the adaptive scale
polvo custom      # Manage custom model mappings
polvo version     # Check installed version
```

### Service Lifecycle
```bash
polvo start      # Start background service
polvo stop       # Stop background service
polvo restart     # Restart service (apply config changes)
polvo status     # Check service health
polvo logs       # View recent logs
polvo tail       # Follow logs live
```

## 🌐 API & Discovery

Polvo is OpenAI-compatible. To use it with any client, set the **Base URL** to `http://127.0.0.1:9000/v1`.

### Discovery Endpoints
For advanced clients, Polvo supports the following discovery endpoints:
- `GET /v1/models`: List all advertised tiers and models.
- `GET /version`: Returns router version and name.
- `GET /api/tags`, `/props`, `/v1/props`: Support endpoints for gateway discovery.

## 🛡 Security
- **No Secrets in Git**: Provider keys are read from environment variables.
- **Local by Default**: Binds to `127.0.0.1` to prevent external access.
- **Secure Loading**: Uses `yaml.safe_load` to prevent RCE.

## 🧪 Verification
Run the test suite to verify the router logic and translation shims:
```bash
uv run pytest
```
