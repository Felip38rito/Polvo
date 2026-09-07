# Polvo

A local **OpenAI-compatible** proxy that routes each chat request to the
cheapest model that can handle the task. It keeps the expensive models
(`pro`/`ultra`) reserved for prompts that truly need them, and sends
trivial/day-to-day requests to the cheap ones.

It is **provider-agnostic**: it works with any OpenAI-compatible API (Ollama
Cloud, local Ollama, OpenAI, OpenRouter, etc.). You just set the
`base_url` + key of your provider and the tier → model mapping.

## Why Polvo?

The problem Polvo solves is simple and expensive: **paying for a Pro model to
answer "hello"**.

Without a router, you have two bad choices:

- **Pin to the cheap model** → complex prompts (architecture refactor, race
  condition debugging) get weak answers and you waste time.
- **Pin to the expensive model** → every request, even trivial ones, pays the
  top-tier price. In an agent (Hermes, OpenCode, Cursor) that makes dozens of
  tool calls per task, that burns credits for nothing.

Polvo breaks that trade-off: it **classifies the intent** of each request and
routes to the cheapest tier that can handle it. Trivial goes to `mini`,
day-to-day to `air`, and heavy reasoning only then climbs to `pro`/`ultra`.

The result is **expensive-model performance at cheap-model cost** — the same
answer quality, without wasting tokens on prompts that don't need it.

## How it works

1. A client (Hermes, OpenCode, curl, any OpenAI SDK) points its `base_url` at the router.
2. The router reads the prompt and classifies the difficulty (**hybrid** classifier):
   - **Deterministic** only for the obvious: explicit model override ("use
     deepseek-v4-pro") and trivial chatter (greetings/short). Instant, free.
   - **LLM-primary** for everything else: a cheap model returns strict JSON
     with the qualitative tier decision. Tiering is fundamentally qualitative
     (intent, scope, context) — keyword matching can't capture that.
   - **Fail-safe**: LLM error → default `air`. Never breaks the request.
3. The router forwards to the chosen model and streams the response.
   - Headers: `X-Router-Model` (model id) and `X-Router-Tier` (mini/air/pro/ultra).

> **Only the last user message** feeds the classifier. The system prompt and
> tool-call history are ignored in the tier decision — otherwise accumulated
> technical context would saturate everything to `pro`/`ultra`.

## Tiers

| Tier | Use |
|---|---|
| `mini` | trivial/mechanical + discussion |
| `air` (default) | day-to-day |
| `pro` | complex reasoning / coding power / hard debug / refactor / concurrency / public API |
| `ultra` | hardest problems, whole-architecture, deep synthesis, adversarial |

## Requirements

- **macOS or Linux** (the installer auto-detects the OS and uses the native
  service manager: `launchd` on macOS, `systemd` on Linux).
- `curl` and `git` (both preinstalled on macOS and most Linux distros).
- An upstream provider API key (e.g. `OLLAMA_API_KEY`).

> `uv` is **not** required up front — the installer bootstraps it for you if
> it's missing.

## Quick start

Install Polvo with a single command (works on macOS and Linux):

```bash
curl -LsSf https://raw.githubusercontent.com/Felip38rito/Polvo/main/install.sh | sh
```

The installer bootstraps `uv`, clones the repo into `~/.polvo`, installs the `polvo` CLI globally, and sets up the background service.

Then, simply run:

```bash
polvo           # Guided onboarding: Provider -> Tiers -> Classifier
polvo status    # Check if the router is running
curl localhost:9000/v1/models
```

> **Development / from source:** if you already have the repo cloned, you can
> run it directly with `uv sync --extra dev` and
> `PYTHONPATH=src uv run uvicorn model_router.main:app --host 127.0.0.1 --port 9000`,
> or install the CLI in place with `uv tool install .`.

Tests:

```bash
uv run pytest
```

## Using the Polvo CLI

`polvo` is a modern CLI for managing the router: guided setup, service
lifecycle, and config management. It wraps `polvoctl.sh` for service commands.

After installing via the script, `polvo` is a real binary on your `PATH`
(installed to `~/.local/bin` by `uv tool install`), so it works from any
directory:

```bash
polvo version     # confirm it's installed
```

### Guided onboarding

If you run `polvo` without arguments, it detects what is missing from your 
config and guides you through a linear setup:

```bash
polvo
```

The flow is: **Providers** $\rightarrow$ **The Adaptive Scale** $\rightarrow$ **Classifier**.

### Management commands

Once configured, you can manage specific areas:

```bash
polvo provider    # Interactive wizard to add/remove providers
polvo tier        # Interactive wizard for the adaptive scale (mini to ultra)
polvo custom      # Interactive wizard for explicit custom models
```

Non-interactive subcommands are available for scripts:
- `polvo provider add <name> --url <url> --env <VAR>`
- `polvo tier set <key> --model <id> --provider <name>`
- `polvo custom set <key> --model <id> --provider <name>`

### Service lifecycle

```bash
polvo start      # start the router service
polvo stop       # stop it
polvo restart     # restart it
polvo status     # is it running?
polvo logs       # last 100 lines of logs
polvo tail       # follow logs live
```

## Agent Integration

Polvo provides automated setup for popular AI agents. These commands configure the necessary environment variables in `~/.polvo/.env` and update your shell profile.

```bash
polvo agent hermes    # Setup for Hermes Agent
polvo agent claude    # Setup for Claude Code
polvo agent codex     # Setup for Codex CLI
polvo agent copilot   # Setup for Copilot CLI
polvo agent opencode  # Setup for OpenCode
```

> **Note:** For Claude Code, Polvo forces the `adaptive` model to ensure the classifier always decides the tier, overriding any client-side model persistence.

## Environment configuration

| Var | Default | Description |
|---|---|---|
| `OLLAMA_API_KEY` | — | key for the `default` provider (Ollama Cloud) |
| `OLLAMA_BASE_URL` | `https://ollama.com/v1` | base URL for the `default` provider |
| `ROUTER_HOST` | `127.0.0.1` | router bind address |
| `ROUTER_PORT` | `9000` | router port |
| `ROUTER_DEFAULT_TIER` | `air` | last-resort fallback |
| `ROUTER_MIN_CLASSIFY_LEN` | `10` | prompts shorter than this = trivial (`mini`) |
| `ROUTER_API_KEY` | (empty) | if set, clients must send `Authorization: Bearer *** |
| `ROUTER_MODELS_YAML` | `router.models.yaml` | path to a custom models YAML |

> Additional providers (OpenAI, Anthropic, Gemini, …) are configured in the
> YAML `providers:` block and use their **own** env vars (e.g. `OPENAI_API_KEY`,
> `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). `OLLAMA_API_KEY`/`OLLAMA_BASE_URL`
> only back the `default` provider.

## Model configuration (YAML)

Each tier accepts two optional fields:
- `name`: a display/route alias shown in `/v1/models` (e.g. `Fast`). If unset, the tier key is used. The classifier always uses the internal key.
- `description`: overrides the classifier's system prompt for that tier. If unset, the built-in description is used.
- `extra_params`: a mapping of provider-specific parameters (e.g. `reasoning_effort`, `budget_tokens`) merged into the upstream request body for that tier.

Config is resolved from (first match): `ROUTER_MODELS_YAML` env var, `~/.config/polvo/config.yml`, `router.models.yaml` in the repo, then built-in defaults.

```yaml
default_tier: air

# Named upstream endpoints. Each tier (and the classifier) can point at one.
# If you omit this block, a single "default" provider (Ollama Cloud) is used
# and every tier points at it.
providers:
  default:
    base_url: https://ollama.com/v1
    api_key_env: OLLAMA_API_KEY

tiers:
  mini:
    model: gemma4:31b          # provider's real API id
    description: "fast/cheap - discussion + trivial/mechanical"
  air:
    model: deepseek-v4-flash:0731
    description: "default - day-to-day"
  pro:
    model: deepseek-v4-pro:0813
    description: "raw coding power"
  ultra:
    model: kimi-k3
    description: "deep synthesis, whole-architecture"

classifier:
  model: gemma4:31b            # primary LLM decider (JSON decision)
  provider: default            # which provider serves the classifier
  min_classify_len: 10
```

> **IMPORTANT:** use the provider's **raw API ids** (e.g. `deepseek-v4-flash:0731`),
> not tool aliases (e.g. `deepseek-v4-flash:cloud` is a Hermes alias and returns
> 404 on the API). Check the real ids with `curl <base_url>/v1/models`.

> **Multi-provider:** each tier can point at a different provider via
> `provider: <name>`. The classifier can also run on its own provider. This
> lets you, for example, run `air` on Ollama Cloud and `pro` on Gemini/OpenAI/
> Anthropic. Each provider's key is read from its `api_key_env` variable.

## Using it (clients)

### curl

```bash
# List models
curl http://127.0.0.1:9000/v1/models

# Chat (streaming) — note the x-router-model / x-router-tier headers
curl http://127.0.0.1:9000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"adaptive","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

> `model: "adaptive"` is a virtual id that **always** forces classification.
> You can also send a tier name (`mini`, `air`, `pro`, `ultra`) to force that
> tier, or one of the raw upstream api ids (e.g. `deepseek-v4-pro:0813`) — the
> router honors it directly without re-classifying (transparent mode).

### Custom OpenAI Clients (Cursor, etc.)

Point the **Base URL** to `http://127.0.0.1:9000/v1` and use `adaptive` as the model.

## Security

- Provider keys are read from env (or `.env`), **never** committed.
- `.gitignore` covers `.env`, `.venv/`, `logs/`, `router.log`.
- `yaml.safe_load` (no YAML RCE).
- Default bind on `127.0.0.1` (not exposed to the network).
- Optional auth via `ROUTER_API_KEY` (Bearer).
- Each provider's key lives in its own env var (e.g. `OLLAMA_API_KEY`,
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) — set them in `.env`, which is git-ignored.

## Tests / verification

- 49 unit tests (`classify`, `config`, `proxy`, `sync-opencode`) with MockTransport.
- Real smoke test against Ollama Cloud validated 2026-08-25.
