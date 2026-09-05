# Polvo — Redesign de tiers + rebuild de CLI

> **Para Hermes:** plano de implementação. NÃO executar sem aprovação explícita do usuário.

**Goal:** Tornar o router flexível (tiers arbitrários, sem valores padrão) e reconstruir o CLI com UX estilo Hermes (setup por seções, providers/tiers separados, validação de provider-existente).

**Backup:** branch `backup/polvo-cli-2026-09-05` (commit `d3de485`).

---

## Decisões fechadas (com o usuário)

### Arquitetura do router
1. **Sem valores padrão de tier** — `_DEFAULT_TABLE` (gemma4/deepseek/kimi) deixa de ser fallback. Config é a única fonte de tiers.
2. **Tiers arbitrários** — cliente define quantos quiser. Os 4 nomes `mini/air/pro/ultra` são os únicos **adaptive** (o classifier só pode retorná-los). Qualquer outro nome é tier **extra**, roteado só por override explícito (model id/alias no request), nunca pelo classifier.
3. **default_tier** = menor tier adaptive configurado (ordem: mini < air < pro < ultra). Se nenhum adaptive configurado, erro.
4. **classifier model** = exigir config explícito (sem default `gemma4:31b`).
5. **Zero tiers** = erro claro no startup ("nenhum tier configurado").
6. **Menos de 4 adaptive** = classifier degrada e escolhe só entre os adaptive existentes.
7. **Sem default de provider** — `DEFAULT_PROVIDERS` (Ollama Cloud) é removido. Provider é 100% explícito; referência a provider não configurado = erro claro.

### CLI
7. **`-h` + `--help`** via `context_settings={"help_option_names": ["-h", "--help"]}`.
8. **`--install-completion`/`--show-completion`** desligados (`add_completion=False`).
9. **Setup estilo Hermes**: `polvo setup [provider|tier]` — wizard por seções, autosave imediato.
10. **Providers e tiers separados**; no fluxo de tier, só providers já existentes; sem provider → orienta criar primeiro.
11. **`polvo config list/set`** mantido como alias (delega a `tier`).
12. **`polvo models <provider>`** mantido.

---

## Modelo de dados novo

`Tier` (enum fixo de 4) é substituído por chaves de string + um conjunto fixo de nomes adaptive:

```python
# models.py
ADAPTIVE_TIERS = ("mini", "air", "pro", "ultra")  # eixo de escalação, ordem fixa

@dataclass(frozen=True)
class RouterModels:
    tiers: dict[str, ModelSpec]          # chave = nome do tier (adaptive ou extra)
    default_tier: str                    # menor adaptive configurado
    classifier_model: str                # obrigatório, sem default
    classifier_provider: str = "default"
    min_classify_len: int = 10
    providers: dict[str, ProviderSpec]
```

- `tier_for_alias(alias) -> str | None` — resolve model id/alias para chave de tier (adaptive OU extra).
- `adaptive_tiers()` — subconjunto de `tiers` cujas chaves estão em `ADAPTIVE_TIERS`, na ordem do eixo.
- `ModelSpec` ganha um campo `adaptive: bool` (derivado do nome) ou é inferido por `name in ADAPTIVE_TIERS`.

---

## Mudanças por arquivo

### 1. `src/model_router/models.py`
- Remover `class Tier(Enum)`; adicionar `ADAPTIVE_TIERS` (tuple ordenada).
- `RouterModels.tiers` vira `dict[str, ModelSpec]`.
- Remover `_DEFAULT_TABLE` como fallback (manter apenas como docstring/exemplo, se útil).
- `default_tier: str` (não mais `Tier`).
- `tier_for_alias` retorna `str | None`.
- Adicionar helper `adaptive_tiers()` e `is_adaptive(name)`.

### 2. `src/model_router/config.py`
- `load_models_yaml`:
  - Sem defaults de tier: tiers vêm só do YAML.
  - Exigir `classifier.model` (erro claro se ausente).
  - Exigir ≥1 tier (erro claro se zero).
  - Derivar `default_tier` = menor adaptive configurado; erro se nenhum adaptive.
  - Manter validação de provider desconhecido.
  - **Sem `DEFAULT_PROVIDERS`**: providers vêm só do YAML; referência a provider ausente = erro claro.

### 3. `src/model_router/classify.py`
- `build_llm_system` lista só os adaptive configurados (não `for tier in Tier`).
- `_parse_tier_response` valida contra adaptive configurados (não `Tier(candidate)`).
- `deterministic_tier` e `classify` retornam `str` (chave de tier).
- `_model_override` mapeia api_id/alias → chave de tier (inclui extras).

### 4. `src/model_router/proxy.py`
- `_model_list_payload` itera `tiers` (adaptive + extras), não `for tier in Tier`.
- `tier_for_alias` retorna `str`; roteamento por override cobre extras.
- `routed_tier` é `str`; `settings.models.tiers[routed_tier]` resolve spec.

### 5. CLI — `src/polvo_cli/`
- `main.py`: `add_completion=False`, `-h`/`--help`, subgrupos `provider` e `tier`, manter `config`/`models`/serviço/`version`/`banner`.
- `setup.py`: reescrever como wizard por seções (`run_setup(section)`), autosave, validação provider-existente.
- `provider_cmd.py` (novo): `add/list/remove` não-interativos.
- `tier_cmd.py` (novo): `set/list`; `set` valida provider existente; tier key arbitrária (adaptive se nome ∈ ADAPTIVE_TIERS).

### 6. `tests/`
- `test_models.py`, `test_config.py`: tiers dinâmicos, sem default, default_tier derivado, zero-tier erro, classifier obrigatório.
- `test_classify.py`: classifier só retorna adaptive; degrada com <4.
- `test_proxy.py`: extras roteados por override; adaptive por classifier.
- `test_setup.py`, `test_main.py`, novos `test_provider_cmd.py`/`test_tier_cmd.py`.

---

## Riscos / tradeoffs

- **Remover `Tier` enum** toca ~5 arquivos + testes. É a mudança certa (tiers dinâmicos), mas é a maior.
- **Sem default de tier** quebra qualquer config existente que dependia de `_DEFAULT_TABLE`. O config atual do usuário (`~/.config/polvo/config.yml`) já tem os 4 tiers, então migra limpo — mas vale validar.
- **classifier model obrigatório** pode quebrar quem sobe o router sem config. Mitigação: erro claro no startup apontando o que falta.
- **Sem default de provider** quebra quem dependia do fallback Ollama Cloud. O config atual já declara `Ollama Cloud` explicitamente, então migra limpo — mas o `Settings.from_env` (que lê `OLLAMA_API_KEY`/`OLLAMA_BASE_URL` do env) precisa ser reconciliado: esses env vars hoje alimentam o fallback. Decidir se viram provider explícito ou são removidos.

---

## Ordem de execução (TDD)

1. `models.py` — tiers dinâmicos + `ADAPTIVE_TIERS` + testes.
2. `config.py` — sem default, classifier obrigatório, default_tier derivado, zero-tier erro + testes.
3. `classify.py` — classifier só adaptive, degrada com <4 + testes.
4. `proxy.py` — extras por override, adaptive por classifier + testes.
5. CLI: `provider_cmd.py` → `tier_cmd.py` → `setup.py` → `main.py` + testes.
6. Reinstalar tool (`rsync` + `uv tool upgrade --reinstall polvo`) e smoke test manual.

---

## Verificação final

- `uv run pytest -q` → tudo verde.
- `polvo` → banner + help com `-h`/`--help`, sem `--install-completion`.
- `polvo setup provider` → cria provider, grava na hora.
- `polvo setup tier` → só providers existentes; sem provider, orienta criar primeiro.
- `polvo tier set air --model x --provider "Ollama Cloud"` → grava; provider inexistente → erro claro.
- `polvo tier set meu-tier --model y --provider "Ollama Cloud"` → tier extra, roteável só por override.
- Router: zero tiers → erro no startup; <4 adaptive → classifier degrada; extras → override.
