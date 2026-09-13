# Polvo: setups e comparativo de modelos

Este documento consolida tres propostas de configuracao para o Polvo e uma comparacao entre modelos open weights e proprietarios para desenvolvimento de software.

A recomendacao assume que o Polvo deve servir usuarios diferentes, com providers e modelos substituiveis. Portanto, os nomes `mini`, `air`, `pro` e `ultra` representam requisitos de tarefa, nao marcas fixas.

## Como ler os dados

- Precos da Ollama Cloud sao os valores informados durante a analise e representam USD por 1 milhao de tokens.
- Precos do OpenRouter sao referencias observadas na API publica de modelos em 2026-09-07. Podem variar por snapshot, provider, batch, contexto longo e tokens internos de reasoning.
- Os indices de benchmark abaixo sao metadados agregados exibidos pelo OpenRouter, incluindo `coding_index`, `agentic_index` e `intelligence_index` quando disponiveis.
- Esses indices nao sao uma medicao do Polvo. Para producao, a metrica mais importante e taxa de sucesso da tarefa: testes passando, lint limpo, patch aplicavel e ausencia de regressao.
- Comparacoes de custo por 1M input + 1M output sao uma normalizacao. O custo real depende da proporcao de entrada, saida, cache, reasoning e retries.

## Os quatro tiers

| Tier | Requisito da tarefa | Politica geral |
|---|---|---|
| `mini` | conversa, transformacao mecanica e mudanca obvia | maximizar volume barato |
| `air` | implementacao cotidiana com caminho claro | modelo padrao de desenvolvimento |
| `pro` | debugging, arquitetura e descoberta da solucao | engenharia complexa e multi-arquivo |
| `ultra` | sintese de sistema e alto risco | poucas tarefas, alta exigencia |

O erro mais comum e usar o comprimento do prompt como proxy de dificuldade. O classificador deve perguntar: "o que executar esta tarefa exige?" Um prompt longo pode ser mecanico; um prompt curto pode esconder uma decisao de seguranca ou concorrencia.

---

## Setup 1: full open weights

Este setup evita modelos proprietarios e pode ser executado com Ollama Cloud, OpenRouter ou outro provider compativel.

| Tier | Modelo recomendado | Alternativa | Custo informado Ollama, input | Output | Soma normalizada |
|---|---|---|---:|---:|---:|
| `mini` | Gemma 4 31B | Gemma 4 26B | US$ 0,14 | US$ 0,40 | **US$ 0,54** |
| `air` | GLM-5.3-Flash | DeepSeek-V4-Flash | US$ 0,15 | US$ 0,50 | **US$ 0,65** |
| `pro` | DeepSeek-V4-Pro | GLM-5.3 | US$ 0,66 | US$ 1,98 | **US$ 2,64** |
| `ultra` | GLM-5.3 | Kimi K3 | US$ 1,40 | US$ 4,40 | **US$ 5,80** |

Configuracao de referencia:

```yaml
providers:
  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY

adaptive:
  mini:
    model: google/gemma-4-31b-it
    provider: openrouter
    description: "tarefas triviais e alteracoes mecanicas"
  air:
    model: z-ai/glm-5.3-flash
    provider: openrouter
    description: "codigo cotidiano, testes e features com caminho claro"
  pro:
    model: deepseek/deepseek-v4-pro-0813
    provider: openrouter
    description: "debugging profundo, arquitetura e multiplos modulos"
  ultra:
    model: z-ai/glm-5.3
    provider: openrouter
    description: "sintese de sistema, refactors amplos e tarefas de alto risco"
```

### Onde entram MiniMax e Qwen

O MiniMax-M3 e um candidato real a `pro` ou `ultra` economico. No catalogo do OpenRouter, ele aparece com contexto de 1M e descricao orientada a coding e tarefas agentic, mas os indices agregados observados ficam abaixo dos melhores modelos desta lista: coding 58,6 e agentic 31,0. Isso nao o invalida; indica que ele deve ser validado em tarefas reais antes de substituir DeepSeek-Pro ou GLM.

O Qwen merece uma familia de candidatos, nao um unico slot:

- `qwen/qwen3.8-flash`: candidato a `air`, com foco em coding, agentes e contexto de 1M.
- `qwen/qwen3.8-27b`: open weight multimodal, candidato a `air` ou `pro` leve.
- `qwen/qwen3.8-max-0902`: modelo proprietario da familia Qwen, nao deve ser classificado como open weight apenas por ser da Alibaba.
- `qwen/qwen3-coder-plus` e `qwen/qwen3-coder-flash`: candidatos especializados para coding agentic.
- `qwen/qwen3-coder-480b-a35b`: open weight especializado em codigo, mas com sinais de benchmark menos conclusivos que os modelos mais recentes.

A distincao entre open weights, open source e modelo proprietario precisa permanecer explicita. "Disponivel no OpenRouter" nao significa "open weights".

---

## Setup 2: misto

Este setup usa open weights para volume e modelos proprietarios nos pontos onde consistencia, ferramentas e manutencao de contexto pagam o custo adicional.

| Tier | Modelo | Papel |
|---|---|---|
| `mini` | GLM-5.3-Flash ou Gemma 4 31B | volume, classificacao e mecanica |
| `air` | Gemini 3.8 Flash | codigo cotidiano e contexto grande |
| `pro` | Claude Sonnet 5 ou GPT-5.3-Codex | debugging, refactor e engenharia multi-arquivo |
| `ultra` | Claude Opus 5 ou GPT-6 Astra | sintese e tarefas de risco alto |

Uma variante OpenAI-first e:

```text
mini  = GPT-5.4 mini ou GLM-5.3-Flash
air   = GPT-5.4 ou Gemini 3.8 Flash
pro   = GPT-5.3-Codex
ultra = GPT-5.5 ou GPT-6 Astra
```

Uma variante Anthropic-first e:

```text
mini  = GLM-5.3-Flash
air   = Gemini 3.8 Flash
pro   = Claude Sonnet 5
ultra = Claude Opus 5
```

### Quando o setup misto vence

Ele tende a vencer quando o custo humano domina o custo de inferencia. Exemplos:

- o modelo precisa navegar uma base de codigo desconhecida;
- a tarefa envolve ferramentas em varias etapas;
- uma resposta quase correta gera uma regressao cara;
- o agente precisa preservar convencoes existentes;
- e necessario revisar e corrigir a propria mudanca.

O modelo proprietario nao compra automaticamente codigo correto. Ele compra, em media, maior previsibilidade operacional: melhor aderencia a instrucoes, tool calling, edicoes iterativas e continuidade em tarefas longas.

---

## Setup 3: recomendado

Minha recomendacao e um setup misto com um nucleo open weight e escalada seletiva para modelos proprietarios.

```text
mini  = GLM-5.3-Flash
air   = Gemini 3.8 Flash
pro   = DeepSeek-V4-Pro
pro+  = Claude Sonnet 5 ou GLM-5.3
ultra = Claude Opus 5 ou GPT-6 Astra
```

Como o eixo adaptativo do Polvo possui quatro nomes, `pro+` pode ser implementado inicialmente como:

- modelo customizado acionado por override;
- fallback depois de falha de teste ou lint;
- alias de um segundo provider;
- ou uma futura politica de roteamento interno dentro do tier `pro`.

### Distribuicao inicial recomendada

| Tier | Faixa |
|---|---:|
| `mini` | 55% a 65% |
| `air` | 20% a 30% |
| `pro` | 10% a 15% |
| `ultra` | 1% a 3% |

Ponto inicial pratico: 60% `mini`, 25% `air`, 13% `pro`, 2% `ultra`.

A promocao de `pro` para `pro+` deve ocorrer quando houver falha verificavel, nao apenas quando o prompt for grande:

- testes ou lint falharam;
- causa do bug ainda nao foi encontrada;
- alteracao cruza varios subsistemas;
- problema envolve seguranca, concorrencia, migracao ou autenticacao;
- a primeira solucao exige uma revisao arquitetural.

A promocao para `ultra` fica reservada para refactors sistemicos, migracoes de grande impacto, sintese de requisitos conflitantes e problemas sem caminho conhecido.

---

## Open weights contra modelos proprietarios

A resposta curta e: **a fronteira open weight ja compete em capacidade bruta, mas ainda nao compete de forma uniforme em todo o produto de engenharia**.

### Onde os open weights competem bem

- custo por token;
- contexto longo;
- raciocinio matematico e tecnico;
- coding em tarefas bem especificadas;
- multimodalidade em familias como Qwen, Kimi e Gemini open-weight;
- possibilidade de trocar provider ou hospedar a inferencia;
- ausencia de dependencia de um contrato de API fechado.

DeepSeek-V4-Pro, GLM-5.3, Kimi K3, Qwen3.8 Max e alguns modelos Qwen Coder ja aparecem proximos em indices de codigo e agentes. O Kimi K3, por exemplo, aparece com coding index 76,2 e agentic index 50,9 no catalogo observado do OpenRouter. Isso o coloca como um candidato serio a `ultra`, apesar do preco.

### Onde os proprietarios ainda tendem a vencer

- tool calling consistente em sequencias longas;
- seguir instrucoes com muitas restricoes simultaneas;
- editar uma base existente sem espalhar mudancas desnecessarias;
- perceber quando devem pedir esclarecimento;
- manter uma politica de seguranca e estilo mais estavel;
- variacao menor entre providers e snapshots;
- melhor integracao com ambientes agentic e produtos de desenvolvimento.

Essa diferenca e particularmente importante no Polvo. Um modelo pode ter coding index alto e ainda produzir patches menos confiaveis no fluxo especifico de uma equipe.

---

## Benchmarks observados

Os numeros abaixo sao indices do catalogo OpenRouter/Artificial Analysis observados em 2026-09-07. Eles sao uteis para ordenar candidatos, mas nao substituem um benchmark proprio.

| Modelo | Tipo | Intelligence | Coding | Agentic |
|---|---|---:|---:|---:|
| Claude Fable 5.1 | proprietario | 56,8 | **81,6** | **58,2** |
| Claude Opus 5 | proprietario | 54,1 | 78,0 | 56,4 |
| Gemini 3.8 Flash | proprietario | 47,1 | 76,3 | 41,2 |
| GPT-6 Astra | proprietario | 54,7 | 76,9 | 51,6 |
| GPT-5.6 Sol | proprietario | 51,3 | 77,4 | 50,7 |
| Kimi K3 | open weight | 50,2 | **76,2** | **50,9** |
| GLM-5.3 | open weight | 48,6 | 74,3 | 53,6 |
| GLM-5.3-Flash | open weight | 46,2 | 71,5 | 51,5 |
| DeepSeek-V4-Pro 0813 | open weight | 42,1 | 68,8 | 42,5 |
| DeepSeek-V4-Flash 0731 | open weight | 40,8 | 69,1 | 41,9 |
| Qwen3.8 Max | proprietario | 49,9 | 71,8 | 49,9 |
| Qwen3.8 2.4T A95B | open weight | 46,7 | 71,9 | 50,7 |
| Qwen3.8 27B | open weight | 41,4 | 68,1 | 46,8 |
| MiniMax-M3 | open weight | 35,7 | 58,6 | 31,0 |
| Gemma 4 31B | open weight | sem indice | 43,4 | 6,8 |

### Como interpretar a tabela

1. Kimi K3 e o caso mais forte contra a ideia de que open weights estao muito atrasados: seus indices de coding e agentic ficam proximos dos modelos proprietarios mais fortes.
2. Gemini 3.8 Flash e um proprietario particularmente competitivo em coding, com custo e latencia de uma familia Flash.
3. GLM-5.3 aparece como um open weight muito forte para engenharia longa, especialmente no indice agentic.
4. DeepSeek-V4-Pro tem bom custo e capacidade, mas os indices agregados observados nao o colocam no topo da tabela. Isso pode refletir diferencas de benchmark, prompt ou foco do modelo.
5. MiniMax-M3 tem bons resultados qualitativos e contexto grande, mas os indices observados nao justificam automaticamente coloca-lo acima de DeepSeek-Pro ou GLM-5.3.
6. Gemma 4 31B continua adequado ao `mini`, mas o indice agentic baixo reforca que ele nao deve receber tarefas autonomas complexas.

### Limites dos benchmarks

Um ranking de arena mede preferencia ou vitoria em conjuntos de prompts. Ele nao mede diretamente:

- se o patch compila no repositorio do usuario;
- se os testes passam;
- quantos arquivos desnecessarios foram modificados;
- custo total depois de retries;
- latencia sob carga;
- estabilidade de tool calling;
- vazamento de contexto;
- comportamento em portugues e nos frameworks da equipe.

O benchmark mais valioso para o Polvo deve ser um conjunto versionado de tarefas reais, com avaliacao automatica:

```text
score = testes_passando
      + lint_passando
      + patch_aplicavel
      + aderencia_ao_escopo
      - regressao
      - custo
      - latencia
```

A metrica de custo-beneficio deve usar custo por tarefa resolvida, nao apenas custo por token:

$$
C_{resolvida} =
\frac{C_{tokens} + C_{retries} + C_{revisao}}{P(\text{tarefa resolvida})}
$$

---

## Open weights adicionais para acompanhar

### MiniMax-M3

Candidato a `pro` barato ou `ultra` alternativo. Tem contexto de 1M, multimodalidade e foco em coding/agents, mas os indices agregados observados sao inferiores aos de Kimi K3, GLM-5.3 e Gemini 3.8 Flash. Vale testar especialmente em tarefas longas e autonomia de agente, onde sua arquitetura pode se comportar melhor que a media do benchmark.

### Qwen

Qwen e uma familia, nao uma unica alternativa:

| Modelo | Possivel tier | Observacao |
|---|---|---|
| Qwen3.8 Flash | `air` | veloz, multimodal, contexto de 1M |
| Qwen3.8 27B | `air`/`pro` leve | open weight, bom custo e contexto |
| Qwen3.8 2.4T A95B | `pro`/`ultra` open weight | raciocinio e agentic fortes, caro |
| Qwen3 Coder Flash | `air`/`pro` coding | especializado em coding agentic |
| Qwen3 Coder Plus | `pro` | coding agentic e tool calling |
| Qwen3 Coder 480B A35B | `pro` | open weight especializado, snapshot mais antigo |

A melhor hipotese para um experimento novo seria comparar `GLM-5.3-Flash`, `Qwen3.8-Flash` e `Qwen3 Coder Flash` no `air`, com as mesmas tarefas e o mesmo limite de output.

### Outros candidatos

- **Kimi K3**: candidato serio a `ultra` open weight; forte em coding e agentes, mas caro.
- **Kimi K2.7 Code**: especializado em coding, pode ser um `pro` alternativo.
- **Qwen3.8 2.4T A95B**: interessante quando contexto e raciocinio importam mais que custo.
- **MiMo-V2.5-Pro**: candidato de custo-beneficio para engenharia, com resultados competitivos em coding.
- **GLM-5.3-Flash**: continua sendo um dos melhores candidatos a `air` pela combinacao de preco, coding e agentic.
- **Devstral 2**: especializado em coding agentic, mas os dados agregados observados sao mais fracos que sua proposta de produto; merece teste proprio, nao suposicao.
- **KAT-Coder-Pro**: candidato especializado para tarefas de repositorio, com custo que pode ser interessante no `pro`.
- **Mistral Small 4**: candidato de volume, mas os indices observados de coding sao inferiores aos lideres desta lista.

---

## Conclusao para o Polvo

A fronteira nao esta dividida simplesmente entre "proprietario bom" e "open weight ruim". O quadro atual e mais interessante:

- open weights ja entregam candidatos muito fortes em coding, contexto e agentes;
- proprietarios ainda tendem a oferecer maior previsibilidade de produto e integracao;
- o melhor custo-beneficio depende da taxa de sucesso na tarefa, nao do preco unitario;
- Kimi K3, GLM-5.3 e Qwen3.8 A95B merecem tratamento como candidatos de alta capacidade;
- MiniMax-M3 e Qwen Coder merecem uma bateria real no Polvo antes de serem promovidos ou descartados;
- o tier `air` e o ponto de maior impacto economico, porque concentra volume;
- `pro+` ou fallback por validacao permite usar modelos fortes sem transformar cada request em custo de fronteira.

Minha configuracao recomendada permanece:

```text
mini  = GLM-5.3-Flash
air   = Gemini 3.8 Flash ou Qwen3.8 Flash
pro   = DeepSeek-V4-Pro
pro+  = Claude Sonnet 5 ou GLM-5.3
ultra = Claude Opus 5, GPT-6 Astra ou Kimi K3
```

Para decidir entre eles, o proximo passo nao deve ser outro ranking generico. Deve ser um benchmark do Polvo com tarefas reais, medindo primeira tentativa, testes, regressao, latencia e custo total.

## Fontes

- [OpenRouter Models API](https://openrouter.ai/api/v1/models)
- [OpenRouter model documentation](https://openrouter.ai/docs/models)
- [OpenRouter model catalog](https://openrouter.ai/models)
- Precos da Ollama Cloud fornecidos pelo usuario nesta analise
