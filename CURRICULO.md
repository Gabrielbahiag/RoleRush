# Role Rush — Feature: Adaptação de Currículo

> Spec da feature. Metodologia **test-first**: os testes de cada fase são
> escritos e rodados (falhando) ANTES da implementação. Nenhuma fase avança
> sem a suíte verde.
>
> Guia de trabalho no dia a dia: [CLAUDE.md](CLAUDE.md). Aqui fica o detalhe
> completo — roadmap, banco de testes e decisões.

---

## 1. Objetivo

A partir de um **currículo-mestre** (tudo o que o Gabriel realmente fez) e da
**descrição de uma vaga**, o RoleRush:

1. extrai os requisitos da vaga;
2. calcula um **score de aderência** (0–100) com explicação;
3. seleciona e ordena as experiências, projetos e skills mais relevantes;
4. (opcional) reescreve os bullets com IA, **sem inventar nada**;
5. gera um currículo **.docx** pronto para ATS.

---

## 2. Premissas inegociáveis

1. **Custo zero.** Nada de API paga, hospedagem ou serviço pago. A feature tem
   que funcionar 100% sem IA; a IA é um incremento opcional.
2. **Nunca inventar.** A adaptação só reprioriza, seleciona e reescreve
   experiência real do currículo-mestre. Skill, métrica, empresa ou
   responsabilidade que não está no mestre não pode aparecer na saída. Isso é
   garantido por validação automática (seção 6), não por confiança no LLM.
3. **Geração local e sob demanda.** O currículo é gerado por um comando na
   máquina do Gabriel, só para as vagas que ele escolher. Nada de credencial de
   IA no GitHub Actions.
4. **Dados pessoais fora do git.** O repositório é público. O currículo-mestre
   real (`curriculo_mestre.yaml`) e os currículos gerados (`saida/`) são
   ignorados pelo `.gitignore`; só `curriculo_mestre.example.yaml`, fictício,
   é versionado.
5. **Sem Docker e sem permissão de administrador.** Tudo roda com Python +
   `uv` no nível do usuário. Nada de dependência de sistema (ex.: LibreOffice).
6. **LinkedIn só por entrada manual** (texto colado ou arquivo). Sem scraping.
7. **Núcleo puro e testável.** Extração, score, seleção e validação são funções
   puras, sem I/O, para permitir no futuro expor tudo numa API (ex.: FastAPI
   chamada pelo n8n) sem reescrever nada.

---

## 3. Decisões travadas

| Tema | Decisão | Motivo |
|---|---|---|
| Idioma | Mestre **bilíngue** (campos `pt` e `en`); o idioma do currículo segue o idioma da vaga, detectado automaticamente | Tradução por IA pode alterar sentido — texto humano nos dois idiomas é mais seguro |
| Detecção de idioma | **Heurística por stopwords, em puro Python** | `langdetect` é não-determinístico por padrão (mesma entrada, saídas diferentes), o que brigaria com o requisito de testes determinísticos. E evita dependência nova. |
| Formato de saída | **.docx** via `python-docx` (puro Python) | Conversão docx→pdf exigiria LibreOffice — barrado pela premissa 5. PDF puro Python (`fpdf2`) fica como evolução. |
| Score na notificação | **Sim** — o Telegram mostra o score de cada vaga | Roda sem IA, no Actions, de graça |
| Filtro por aderência | `aderencia_minima` opcional no config, **desligado por padrão** | Começar vendo tudo; ligar o corte depois de calibrar o score com dados reais |
| Escopo dos testes | **Todos** — essenciais, recomendados e opcionais da seção 7 | — |

---

## 4. Arquitetura

```
Vaga (id do banco | arquivo | texto colado)
        │
        ▼
Normalização do texto (HTML/Markdown → texto limpo, idioma detectado)
        │
        ▼
Extração de requisitos ──── modo sem IA: dicionário de skills + sinônimos
        │                    modo IA: JSON estruturado (validado por Pydantic)
        ▼
Score de aderência (puro) ── 0–100 + skills atendidas + lacunas
        │
        ▼
Seleção (pura) ──────────── ranqueia bullets/projetos do mestre por relevância
        │
        ▼
Reescrita (opcional, IA) ─── LLMProvider plugável
        │
        ▼
Validação anti-invenção ──── reprovou? volta para o bullet original
        │
        ▼
Gerador .docx (ATS) + relatório no terminal
```

Código em `src/monitor/curriculo/`, separado do pipeline de monitoramento. O
núcleo (extração, score, seleção, guardrail) é puro — sem rede, sem disco,
sem relógio — exatamente como `filters.py` já é hoje.

---

## 5. Componentes

### 5.1 Currículo-mestre (`curriculo_mestre.yaml`, fora do git)

Validado por Pydantic. Estrutura:

- `dados`: nome, contato, links (GitHub, LinkedIn, portfólio).
- `resumo`: pt/en.
- `experiencias[]`: cargo, empresa, período, `bullets[]`.
- `projetos[]`: nome, descrição, stack, link, `bullets[]` (os projetos do
  portfólio entram aqui).
- `formacao[]`: curso, instituição, status (ex.: em andamento).
- `skills[]`: nome, categoria, nível.
- `idiomas[]`, `certificacoes[]`.

Cada **bullet** tem: `id` único e estável, texto pt/en e `tags` (skills que ele
comprova). O `id` é o que permite rastrear qualquer reescrita até a origem —
é a âncora do guardrail da seção 6, então tem que ser único no currículo
inteiro (validado na carga).

`curriculo_mestre.example.yaml` (fictício) fica versionado para documentar o
formato e alimentar os testes.

### 5.2 Dicionário de skills (`config/skills.yaml`, versionado)

Skill canônica + sinônimos e grafias (`postgres`, `postgresql`, `psql` →
PostgreSQL). Base do modo sem IA e da validação anti-invenção. Um mesmo
sinônimo não pode apontar para duas skills canônicas — ambiguidade quebraria
a extração em silêncio, então é erro na carga.

### 5.3 Extração de requisitos

- **Sem IA:** casamento por fronteira de palavra (mesmo espírito do
  `filters.py`) contra o dicionário; heurística para separar obrigatório de
  desejável (seções como "Requirements" vs "Nice to have" /
  "Requisitos" vs "Diferenciais"); senioridade e idioma.

  Implementado em `extracao.py`, com três detalhes que não são óbvios:

  1. A fronteira usa lookaround `(?<!\w)...(?!\w)`, não `\b`. Termos como
     `C++` e `Node.js` terminam em caractere não-palavra, e aí o `\b` final
     nunca casaria.
  2. Os termos entram na alternância **do mais longo para o mais curto**,
     senão "Google Cloud Platform" seria engolido por "Google Cloud".
  3. Termo que também é **palavra corrente** (`go`, `ia`, `spark`, `lead`…)
     só conta com **corroboração**: grafia de nome próprio/sigla (maiúscula
     ou dígito) *ou* uma frase que introduz skill logo antes
     ("experiência com go", "knowledge of spark"). A lista está em
     `_TERMOS_AMBIGUOS`; skill nova que colida com linguagem corrente entra
     lá.

     O critério é colisão, **não tamanho**. Uma regra por tamanho erra nos
     dois sentidos: deixa passar "spark innovation" (5 letras) e barra
     "experiência com go", que é obviamente a linguagem. É a mesma armadilha
     que já mordeu o projeto no filtro de palavras-chave do monitor, só que
     um nível acima.

  O marcador de seção vale a partir da linha em que aparece, inclusive quando
  vem junto do conteúdo (`Desejável: conhecimento em Power BI.`). Sem marcador
  nenhum, tudo é tratado como obrigatório. Skill que aparece nos dois blocos
  continua obrigatória.
- **Com IA:** o LLM devolve JSON `{obrigatorios, desejaveis, senioridade,
  idioma}`; saída inválida → cai para o modo sem IA.

### 5.4 Score de aderência

Puro e determinístico: cobertura ponderada (obrigatórios pesam mais que
desejáveis) → 0–100. Sempre acompanhado de explicação: o que bateu e o que
falta. As **lacunas** viram uma lista útil de "o que estudar" para vagas que
se repetem.

Implementado em `score.py`: peso 3 para obrigatório, 1 para desejável
(`PESO_OBRIGATORIO`/`PESO_DESEJAVEL`). Vaga em que **nenhum** requisito foi
detectado dá score **0**, não 100 — não houve cobertura verificada, e 100
sugeriria uma aderência que ninguém checou. A comparação ignora caixa;
`skills_canonicas_do_curriculo()` junta as skills declaradas com as `tags`
de todos os bullets, então experiência comprovada em bullet conta mesmo sem
estar na lista de skills.

### 5.5 Seleção

Ranqueia bullets e projetos pela sobreposição de tags com os requisitos,
respeitando limites (ex.: até N bullets por experiência, até M projetos, 1–2
páginas). Ordem estável em caso de empate (resultado reproduzível).

### 5.6 LLMProvider plugável

Interface única, escolhida no `config.yaml`:

- `nenhum` — padrão; a feature funciona inteira sem IA.
- `claude-cli` — chama o Claude Code em modo não interativo (`claude -p`)
  via subprocess, usando a assinatura já existente. Com timeout; qualquer erro
  cai para o modo sem IA.
- espaço para um provedor com camada gratuita no futuro.

### 5.7 Gerador .docx (ATS-friendly)

Uma coluna, sem tabelas, imagens ou caixas de texto, títulos de seção padrão,
fonte comum. Nome do arquivo: `empresa-cargo-AAAA-MM-DD.docx` em `saida/`
(fora do git).

### 5.8 CLI

```
uv run rolerush curriculo --vaga <id>        # vaga já coletada pelo RoleRush
uv run rolerush curriculo --arquivo vaga.txt # entrada manual (LinkedIn etc.)
uv run rolerush curriculo --texto "..."      # entrada manual colada
uv run rolerush aderencia --vaga <id>        # só o score + lacunas, sem gerar
```

Flags: `--sem-ia` (força o modo determinístico), `--idioma pt|en`.

### 5.9 Mudanças no pipeline existente

- **Storage:** hoje só guarda o id da vaga vista. Para `--vaga <id>` funcionar,
  passa a guardar os detalhes das vagas notificadas (título, empresa, URL,
  descrição, fonte) numa tabela própria, com migração segura e sujeita à mesma
  política de retenção. O padrão de migração já existe (`_migrar_ultimo_visto`
  + `test_migracao_...`) — é repetir a receita, não inventar uma nova.
- **Notifier:** mensagem ganha o score de aderência e o id da vaga (para o
  comando local).
- **Config:** novos blocos `curriculo` (caminho do mestre, provedor, limites) e
  `aderencia_minima` opcional.

Como ficou implementado:

- `vagas_detalhes` é **tabela nova**, então `CREATE TABLE IF NOT EXISTS` já é a
  migração segura — não toca em nada do banco antigo. A poda por retenção
  remove junto (`DELETE ... WHERE id NOT IN (SELECT id FROM vagas_vistas)`),
  o que também limpa órfão.
- O snapshot é salvo **só do que foi notificado**, mas o dedup
  (`marcar_todas`) vale pra **toda** vaga nova, inclusive a barrada pela
  aderência — senão ela voltaria a cada execução. O efeito colateral aceito:
  baixar `aderencia_minima` depois não traz de volta o que já foi barrado.
- **A tensão do Actions:** o currículo-mestre é dado pessoal e está no
  `.gitignore`, então ele **não existe** no runner — o score no Telegram não
  teria como ser calculado lá. A saída é `curriculo.skills_perfil` no
  `config.yaml`: só a lista de skills canônicas, sem nome, contato ou
  histórico. Vazio (padrão) = pontuação só local, e o pipeline segue normal.
  Sem fonte de pontuação, `aderencia_minima` é **ignorado** de propósito:
  melhor notificar do que engolir vaga por falta de dado.

---

## 6. Guardrail anti-invenção (o coração da feature)

Toda saída do LLM passa por validação automática antes de entrar no currículo.
Cada bullet reescrito precisa:

1. **referenciar o `id` de um bullet real** do mestre;
2. **não citar skill/tecnologia ausente** do mestre (checado contra o
   dicionário de skills);
3. **não conter número/métrica** (%, valores, quantidades) que não exista no
   bullet de origem;
4. **não mencionar empresa, cargo ou certificação** fora do mestre.

Reprovou em qualquer regra → o bullet original é usado no lugar, e o relatório
registra o motivo. A IA nunca consegue quebrar a premissa 2, mesmo que tente.

---

## 7. Banco de testes (test-first)

Escopo travado: **todos** entram — essenciais **[E]**, recomendados **[R]** e
opcionais **[O]**.

### Currículo-mestre
- [E] exemplo fictício carrega e valida
- [E] erro claro quando falta campo obrigatório ou há `id` duplicado
- [R] bullet com texto só em pt, em currículo pedido em en → erro explicativo

### Normalização da vaga
- [E] HTML e Markdown viram texto limpo (tags, entidades, listas)
- [R] detecção de idioma pt/en em descrições reais das fontes (fixtures)

### Extração sem IA
- [E] detecta skills do dicionário, inclusive por sinônimo
- [E] fronteira de palavra: "Java" não casa com "JavaScript"
- [R] separa obrigatórios de desejáveis por seção (pt e en)
- [O] detecta senioridade

### Score
- [E] 100 quando cobre tudo; 0 quando não cobre nada
- [E] obrigatórios pesam mais que desejáveis
- [E] vaga sem nenhum requisito detectado → comportamento definido (não divide por zero)
- [E] explicação lista exatamente o que bateu e o que falta

### Seleção
- [E] bullets mais relevantes primeiro; limites de quantidade respeitados
- [E] determinística (mesma entrada → mesma saída, inclusive em empates)
- [R] nunca devolve nada fora do mestre

### Guardrail anti-invenção
- [E] bullet sem `id` válido → rejeitado, original usado
- [E] skill ausente do mestre → rejeitado
- [E] métrica inventada ("aumentou vendas em 40%" sem o número no original) → rejeitado
- [E] empresa/certificação inexistente → rejeitado
- [E] reescrita fiel (só reformulação) → aceita

### LLMProvider
- [E] provedor `nenhum` produz currículo completo
- [E] provedor falso (fake) retornando JSON inválido → fallback sem IA
- [E] `claude-cli` com subprocess mockado: timeout e código de erro → fallback
- [R] nenhum teste chama IA real nem depende de rede

### Gerador .docx
- [E] arquivo gerado abre e contém as seções esperadas na ordem
- [R] estrutura ATS: sem tabelas nem imagens
- [O] nome do arquivo sanitizado (acentos, barras, espaços)

### Integração com o pipeline
- [E] migração do storage preserva dados existentes
- [E] detalhes da vaga salvos só para vagas notificadas; retenção também os remove
- [R] notificação inclui score e id da vaga
- [O] `aderencia_minima` filtra notificações abaixo do limite

### CLI
- [E] `--vaga`, `--arquivo`, `--texto` produzem o mesmo resultado para a mesma vaga
- [R] `--vaga` inexistente → mensagem clara, código de saída ≠ 0

**Fora do escopo de teste:** a qualidade do texto gerado pela IA (não
determinística). Testa-se o **tratamento** da saída: parse, validação e
fallback.

---

## 8. Roadmap em fases

### Fase 1 — Currículo-mestre — concluída
- [x] Schema Pydantic + `curriculo_mestre.example.yaml` + `.gitignore`
- [x] `config/skills.yaml` inicial

### Fase 2 — Extração + score (sem IA) — concluída
- [x] Normalização do texto da vaga (`normalizacao.py`)
- [x] Extração por dicionário (`extracao.py`)
- [x] Score com explicação e lacunas (`score.py`)

### Fase 3 — Integração com o pipeline — concluída
- [x] Storage guarda detalhes das vagas notificadas (migração + retenção)
- [x] Score e id da vaga na notificação do Telegram
- [x] `aderencia_minima`

### Fase 4 — MVP do currículo, sem IA — concluída
- [x] Seleção (`selecao.py`)
- [x] Gerador .docx (`documento.py`)
- [x] CLI `curriculo` e `aderencia` (`cli.py`, entry point `rolerush`)
- [x] **Entrega de valor a custo zero: currículo adaptado já funcionando**

Fica para a Fase 5: a flag `--sem-ia` ainda não existe, porque hoje **tudo** é
determinístico — ela só faz sentido quando houver um provedor de IA pra
desligar.

### Fase 5 — IA opcional — concluída
- [x] Interface `LLMProvider` + `nenhum` + `claude-cli` (`llm.py`)
- [x] Reescrita com IA (`reescrita.py`) + flag `--sem-ia`
- [x] Guardrail anti-invenção (`guardrail.py`)

Duas decisões de implementação que valem registro:

1. **O prompt de reescrita não recebe os requisitos da vaga.** A adaptação à
   vaga já aconteceu na seleção; contar pro modelo o que a vaga quer ouvir só
   criaria incentivo pra ele torcer os fatos. Ele só reformula a redação.
2. **A extração de requisitos continua 100% determinística.** A spec previa
   extração por IA como opção, mas ela não foi implementada: o ganho sobre o
   dicionário é incerto e cada chamada a mais é uma superfície a mais de
   falha e de não-determinismo. A IA entra só onde o texto é de fato
   subjetivo — a redação dos bullets.

E um furo que só apareceu no teste: a whitelist de nomes próprios do guardrail
não pode conter o dicionário inteiro. "Google Cloud" é skill conhecida, e o
token "google" acabava autorizando a **empresa** Google numa reescrita
inventada. A whitelist usa só os termos das skills que o mestre realmente tem.

### Evoluções
- [ ] PDF em puro Python (fpdf2)
- [ ] Comando no Telegram via polling agendado no Actions, devolvendo score e
      lacunas de uma vaga (a geração do .docx continua local)
- [ ] Relatório de lacunas recorrentes ("skills mais pedidas que você ainda não tem")
- [ ] Envelopar o núcleo em API (FastAPI) para integração futura com n8n

---

## 9. O que o Gabriel precisa preencher no final

Nada disso bloqueia o desenvolvimento — tudo tem default seguro e o código
funciona sem. É a lista do que falta pra feature render de verdade **na sua
máquina**, a ser feita quando as fases terminarem.

> ⚠️ **O guardrail não valida o mestre, só a IA.** Ele garante que a reescrita
> não invente nada *em relação ao mestre* — a veracidade do mestre é premissa,
> não é verificada. Um mestre com conteúdo de exemplo gera um currículo
> fabricado que passa em todas as checagens, com o seu nome real em cima.

### Obrigatório pra feature funcionar
- [ ] **`curriculo_mestre.yaml`** — o currículo real, no formato de
      [`curriculo_mestre.example.yaml`](curriculo_mestre.example.yaml). É o
      único item sem o qual nada é gerado. Fica fora do git (`.gitignore`).
      Atenção ao preencher:
      - todo bullet precisa de `id` único no currículo inteiro;
      - textos em `pt` **e** `en` (o currículo sai no idioma da vaga);
      - `tags` de cada bullet com as skills que ele comprova — é por elas que
        a seleção decide o que entra no currículo adaptado.

### Opcional, melhora o resultado
- [ ] **`config/skills.yaml`** — acrescentar skills suas que não estão no
      dicionário inicial (e sinônimos/grafias que as vagas usam). Skill que
      não está aqui não é detectada na vaga nem pontuada.
- [ ] **`config.yaml` → `aderencia_minima`** — hoje `null` (notifica tudo).
      Vale calibrar depois de ver os scores reais chegando no Telegram.
      Lembre: vaga barrada pelo corte já conta como vista, e baixar o corte
      depois não a traz de volta.
- [ ] **`config.yaml` → `curriculo.skills_perfil`** — só se você quiser score
      no Telegram **também pelo GitHub Actions**. O currículo-mestre não
      existe no runner (é dado pessoal, fora do git), então sem essa lista a
      pontuação só acontece localmente. Vazio é uma escolha legítima: publicar
      a lista de skills num repo público é decisão sua.

### Pendências herdadas de fases anteriores
- [ ] **`config.yaml` → `fontes.greenhouse.empresas` / `lever.empresas` /
      `ashby.empresas`** — as três estão `ativo: false` com lista vazia. São
      ATS por empresa, não agregadores: sem a lista curada por você, não
      produzem vaga nenhuma. O slug é o que aparece na URL da vaga na página
      de carreira da empresa.
- [ ] **`.env` → `THEMUSE_API_KEY`** — opcional; sem ela a API do The Muse
      funciona igual, só com limite menor (500 req/h em vez de 3.600).

---

## 10. Definição de pronto

Com um comando local, o Gabriel gera um **.docx adaptado** para qualquer vaga
coletada ou colada manualmente, vê o **score de aderência e as lacunas**, e
recebe o score já na notificação do Telegram. Tudo funciona **sem IA e sem
custo**; com o `claude-cli` ligado, os bullets são reescritos e **nenhuma
informação inventada passa pela validação**. Suíte inteira verde no CI, sem
rede e sem dados pessoais no repositório.
