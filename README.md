# Role Rush

Monitor de vagas que roda de graça no GitHub Actions: busca vagas novas em
fontes configuráveis, filtra pelo meu perfil (palavras-chave, senioridade,
remoto), ignora o que eu já vi e me avisa no Telegram.

## Por quê

Procurar vaga é repetitivo: abrir os mesmos sites, escanear os mesmos
títulos, ignorar o que não serve. Este projeto automatiza essa varredura e
só me interrompe quando aparece algo relevante e novo.

## Como funciona

```
fontes (Remotive, issues do GitHub, Adzuna) -> filtros -> dedup (SQLite) -> Telegram
```

Cada fonte implementa a mesma interface (`Source.fetch() -> list[Vaga]`), então
adicionar uma fonte nova é criar um arquivo em `src/monitor/sources/`, sem
tocar no resto do pipeline. Veja [`src/monitor/sources/base.py`](src/monitor/sources/base.py).

```
src/monitor/
├── models.py        # dataclass Vaga
├── config.py         # carrega e valida config.yaml (pydantic)
├── storage.py         # SQLite: já vi essa vaga?
├── filters.py          # palavras-chave / exclusão / remoto / senioridade / localização
├── notifier.py          # envia mensagem no Telegram
├── sources/
│   ├── base.py            # interface Source
│   ├── remotive.py          # API pública do Remotive (vagas remotas globais)
│   ├── github_repo.py         # issues de repos tipo backend-br/vagas
│   └── adzuna.py               # agregador com filtro real de localização (ex: Brasília)
└── main.py                      # orquestra: coleta -> filtra -> dedup -> notifica
```

## Rodando localmente

Pré-requisito: [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # cria o venv e instala as dependências
cp .env.example .env          # preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID
uv run python -m monitor.main # roda uma vez: coleta, filtra, dedup, notifica
```

Sem token do Telegram configurado, o monitor roda normalmente e só imprime as
vagas novas no terminal (a notificação é pulada com um aviso no log).

Ajuste os filtros e as fontes ativas em [`config.yaml`](config.yaml).

## Testes

```bash
uv run pytest
```

## Automação (GitHub Actions)

O workflow em [`.github/workflows/monitor.yml`](.github/workflows/monitor.yml)
roda a cada 6 horas (`cron`) e também pode ser disparado manualmente pela aba
*Actions*. Como o runner é efêmero, o `vagas.db` (SQLite com o histórico de
dedup) é commitado de volta no repositório ao final de cada execução — é
assim que o dedup sobrevive entre runs sem precisar de infra paga.

Segredos necessários (em *Settings → Secrets and variables → Actions*):

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`

`GITHUB_TOKEN` **não precisa ser cadastrado** — é um nome reservado que o
próprio GitHub Actions injeta automaticamente em toda execução, escopado
pelo bloco `permissions:` do workflow. Ele só existe como variável opcional
no `.env` local (veja [`.env.example`](.env.example)) para quem quiser rodar
o monitor fora do Actions e evitar o rate limit de 60 req/h da API pública do
GitHub.

## Criando o bot do Telegram

1. Fale com [@BotFather](https://t.me/BotFather), rode `/newbot` e guarde o
   token.
2. Mande uma mensagem para o seu bot recém-criado.
3. Pegue o `chat_id` acessando
   `https://api.telegram.org/bot<TOKEN>/getUpdates` e lendo `message.chat.id`
   na resposta.

## Credenciais do Adzuna

Crie uma conta grátis em [developer.adzuna.com](https://developer.adzuna.com)
e pegue o `Application ID` e a `Application Key` no seu dashboard — são duas
chaves separadas (`ADZUNA_APP_ID` e `ADZUNA_APP_KEY`), não uma só.

## Roadmap

- [ ] Score de aderência da vaga ao perfil (por palavras, sem ML)
- [ ] Histórico/estatística de vagas por semana
- [ ] Suporte a múltiplos perfis de busca

Decisões de arquitetura e o plano de fases completo estão em
[`PROJECT_PLAN.md`](PROJECT_PLAN.md).
