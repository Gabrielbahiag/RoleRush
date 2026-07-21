# Role Rush (Monitor de Vagas) — Plano de Ação

> Spec do projeto. Feito para servir de contexto ao Claude Code na IDE.
> Objetivo: coletar vagas de fontes configuráveis, filtrar pelo meu perfil,
> deduplicar e me avisar no Telegram — rodando de graça via GitHub Actions.

---

## 1. Visão geral

Um serviço que roda periodicamente, busca vagas novas em uma ou mais fontes,
aplica filtros que eu defino (palavras-chave, senioridade, localização/remoto),
ignora vagas que já vi antes e me manda as novidades no Telegram.

**Não-objetivos do MVP** (deixar para depois): interface web, machine learning,
múltiplos usuários, banco de dados hospedado. Começar simples e funcionando.

---

## 2. Decisões de arquitetura (já travadas)

| Decisão | Escolha | Motivo |
|---|---|---|
| Fontes iniciais | API do Remotive + repos de vagas do GitHub (ex: `backend-br/vagas` via API oficial do GitHub) | Amigáveis a acesso programático, sem guerra com anti-bot |
| Notificação | Bot do Telegram | API gratuita, simples, push no celular |
| Persistência | SQLite (arquivo commitado ou artifact do Actions) | Zero infra, suficiente para dedup |
| Agendamento | GitHub Actions com `cron` | Roda de graça, e vira vitrine de CI/CD no portfólio |
| Config | Arquivo `config.yaml` | Editar filtros sem mexer no código |
| HTTP | `httpx` | Moderno, suporta sync e async |

**A ideia de fonte é plugável:** cada fonte é um módulo que implementa a mesma
interface (`fetch() -> list[Vaga]`). Adicionar uma fonte nova = criar um arquivo,
sem tocar no resto. Isso mostra bom design em entrevista.

---

## 3. Estrutura de pastas sugerida

```
monitor-vagas/
├── README.md
├── PROJECT_PLAN.md          # este arquivo
├── pyproject.toml           # deps + config do projeto
├── config.yaml              # meus filtros (versionado)
├── .env.example             # nomes das variáveis de ambiente (sem segredos)
├── .github/
│   └── workflows/
│       └── monitor.yml      # cron do GitHub Actions
├── src/
│   └── monitor/
│       ├── __init__.py
│       ├── models.py        # dataclass Vaga (id, titulo, empresa, url, ...)
│       ├── config.py        # carrega e valida o config.yaml
│       ├── storage.py       # SQLite: já_vi? / marcar_como_vista()
│       ├── filters.py       # aplica filtros e (opcional) score de aderência
│       ├── notifier.py      # envia mensagem no Telegram
│       ├── sources/
│       │   ├── __init__.py
│       │   ├── base.py      # interface Source (abstract)
│       │   ├── remotive.py
│       │   └── github_repo.py
│       └── main.py          # orquestra: coleta -> filtra -> dedup -> notifica
└── tests/
    ├── test_filters.py
    ├── test_storage.py
    └── test_sources.py
```

---

## 4. Modelo de dados (a `Vaga`)

Campos mínimos para funcionar e deduplicar bem:

- `id` — identificador estável e único (idealmente derivado da URL ou id da fonte)
- `titulo`
- `empresa`
- `localizacao` / `remoto` (bool)
- `url`
- `fonte` — de onde veio (ex: "remotive")
- `publicada_em` — data, quando disponível
- `descricao` — texto para os filtros baterem em cima

> A chave de dedup deve ser o `id` estável. Cuidado: usar o título como chave
> gera falsos duplicados/faltantes. Preferir URL canônica ou id nativo da fonte.

---

## 5. Config (exemplo de `config.yaml`)

```yaml
filtros:
  palavras_chave:        # bate no título + descrição
    - python
    - backend
  excluir:               # descarta se aparecer
    - senior
    - pleno/senior
  senioridade:
    - junior
    - estagio
  remoto: true           # só remotas; ou false para qualquer

fontes:
  remotive:
    ativo: true
    categoria: software-dev
  github_repo:
    ativo: true
    repos:
      - backend-br/vagas
      - frontend-br/vagas

notificacao:
  telegram: true
```

Segredos (token do bot, chat_id) **nunca** no YAML — vão por variável de
ambiente / GitHub Secrets. O `.env.example` documenta os nomes.

---

## 6. Roadmap em fases (checklist)

### Fase 0 — Fundação (30–60 min)
- [ ] Criar repo, `pyproject.toml`, venv, instalar deps
- [ ] `models.py` com a dataclass `Vaga`
- [ ] `config.py` que carrega e valida `config.yaml`
- [ ] Esqueleto de testes rodando (pytest)

### Fase 1 — Uma fonte funcionando end-to-end
- [ ] `sources/base.py` com a interface `Source`
- [ ] `sources/remotive.py` buscando e mapeando para `Vaga`
- [ ] Rodar via `main.py` e printar as vagas no terminal (sem notificar ainda)

### Fase 2 — Filtros + dedup
- [ ] `filters.py` aplicando palavras-chave / exclusão / remoto
- [ ] Testes de `filters.py` cobrindo casos de borda
- [ ] `storage.py` com SQLite: marcar vistas e ignorar repetidas

### Fase 3 — Notificação
- [ ] Criar o bot no Telegram (BotFather) e pegar token + chat_id
- [ ] `notifier.py` enviando mensagem formatada (título, empresa, link)
- [ ] Fluxo completo local: coleta → filtra → dedup → Telegram

### Fase 4 — Automação (o diferencial de portfólio)
- [ ] `.github/workflows/monitor.yml` com `cron` (ex: a cada 6h)
- [ ] Configurar GitHub Secrets (token, chat_id)
- [ ] Resolver persistência do SQLite entre execuções
      (commit do arquivo, cache, ou artifact — decidir na hora)

### Fase 5 — Segunda fonte + polimento
- [ ] `sources/github_repo.py` lendo issues via API do GitHub
- [ ] README caprichado: problema, solução, print/GIF, como rodar
- [ ] Cobertura de testes decente + badge de CI

### Evoluções futuras (contar como "roadmap" na entrevista)
- [ ] Score de aderência da vaga ao meu perfil (por palavras, sem ML)
- [ ] Histórico/estatística de vagas por semana
- [ ] Suporte a múltiplos perfis de busca

---

## 7. Gotchas para não tropeçar

- **Rate limiting e robots.txt:** respeitar. Começar pelas fontes de API
  (Remotive, GitHub) evita dor de cabeça. Mencionar esse cuidado no README
  mostra maturidade.
- **Segredos:** nada de token no código ou no YAML. `.env` local no
  `.gitignore`; em produção, GitHub Secrets.
- **Persistência no Actions:** o runner é efêmero — o SQLite some entre runs se
  nada for feito. Definir a estratégia na Fase 4 (é uma decisão consciente).
- **Idempotência:** rodar duas vezes seguidas não pode gerar notificação
  duplicada. O dedup resolve, mas testar isso.
- **Fuso/formatação de datas:** fontes retornam formatos diferentes; normalizar
  ao mapear para `Vaga`.

---

## 8. Stack final

`httpx` · `pydantic` ou `dataclasses` · `PyYAML` · `sqlite3` (stdlib) ·
`python-telegram-bot` (ou chamada HTTP direta à API do Telegram) · `pytest` ·
GitHub Actions.

Lembrete: sempre pergunte o usuario oque ja foi configurado em sua maquina e auxilio em alguns casos necessarios.