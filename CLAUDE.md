# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Role Rush ("monitor de vagas"): a free job-posting monitor that runs on GitHub Actions. It pulls new job postings from configurable sources, filters them against a personal profile (keywords, seniority, remote/location), deduplicates against previously-seen postings (SQLite), and notifies via Telegram. All code, comments, and commit messages are in Portuguese (pt-BR) — match that when editing this repo.

## Commands

Dependency manager is [uv](https://docs.astral.sh/uv/) (not pip/poetry).

```bash
uv sync                        # create venv, install deps (use --frozen in CI)
cp .env.example .env           # then fill in TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / etc.
uv sync --extra dev            # pytest/respx live in optional-dependencies, NOT installed by a plain sync
uv run python -m monitor.main  # run the pipeline once: collect -> filter -> dedup -> notify
uv run pytest                  # run the full test suite
uv run pytest tests/test_filters.py::test_palavra_curta_nao_da_falso_positivo_em_substring  # single test

# résumé adaptation (local only — needs curriculo_mestre.yaml, which is gitignored)
uv run rolerush aderencia --vaga <id>        # score + gaps for a job already notified
uv run rolerush curriculo --arquivo vaga.txt # generate the adapted .docx into saida/
uv run rolerush curriculo --texto "..." --idioma en
```

`rolerush` is the résumé CLI, not the monitor — the monitor stays on `python -m monitor.main`, which is what the workflow calls.

**`uv sync` without `--extra dev` uninstalls pytest**, so both workflows use `uv sync --frozen --extra dev`; a plain `--frozen` makes `uv run pytest` fail with "program not found" and, in `monitor.yml`, that aborts the job before the monitor ever runs.

Without a configured Telegram token, the monitor still runs fully and just prints new postings to the terminal instead of sending them (skipped with a log warning) — this is the normal way to test locally without spamming Telegram.

Adjust active sources and filters in [config.yaml](config.yaml), never by editing code.

**The test suite must never depend on the network or on real secrets.** Every test that touches HTTP mocks it with `respx`; nothing calls a real API, not even for sources that in principle work without a key. This is enforced by CI (see below), not just convention — a new source or notifier change needs a mocked test, not a live smoke test.

## Architecture

Four-stage pipeline in `run()` in [src/monitor/main.py](src/monitor/main.py):

```
collect (network I/O) -> filter (pure) -> dedup (disk I/O) -> notify (network I/O)
```

### Plugin sources (Strategy pattern)

Every source implements the one-method interface in [src/monitor/sources/base.py](src/monitor/sources/base.py): `Source.fetch() -> list[Vaga]`. `main.py` never branches on which source it's talking to — it just calls `.fetch()` on whatever is in the list built by `montar_fontes()`. **Adding a new source means creating one file in `src/monitor/sources/` and registering it in `montar_fontes()` — zero changes to `filters.py`, `storage.py`, or `notifier.py`.**

Current sources: `remotive.py`, `remoteok.py`, `arbeitnow.py`, `himalayas.py`, `jobicy.py` (aggregators), `adzuna.py` (the only aggregator with real location-based filtering, e.g. by city), `themuse.py` (paginated, optional `THEMUSE_API_KEY` for a higher rate limit), and three **per-company ATS sources** — `github_repo.py`, `greenhouse.py`, `lever.py`, `ashby.py` — where each hits a public per-company JSON endpoint (the same one a company's own careers page uses) and `montar_fontes()` creates one `Source` instance per configured company/repo (see `config.fontes.greenhouse.empresas` etc. in `config.yaml`). There is no bulk search across companies for these three — the list is curated by hand.

Each source is responsible for translating its own API's shape into the single internal model in a private `_mapear()` method (Adapter pattern) — downstream code never needs to know which source a `Vaga` came from.

### `Vaga` model and dedup id ([src/monitor/models.py](src/monitor/models.py))

Single internal representation all sources normalize into. **`id` is namespaced per source** (`f"remotive:{item['id']}"`, `f"adzuna:{item['id']}"`, `f"github:{repo}:{issue_number}"`) — never derived from title. Two reasons, both load-bearing: ids from different sources can collide numerically, and job titles are neither unique nor stable, so using them as a dedup key produces both false duplicates and false negatives.

### Config ([src/monitor/config.py](src/monitor/config.py))

`config.yaml` is parsed once through Pydantic models into a fully-typed `Config` at startup ("parse, don't validate") — the rest of the codebase trusts the shape without re-checking it. Secrets (Telegram token, Adzuna keys, GitHub token, The Muse key) are **never** in `config.yaml`; they come from environment variables / GitHub Secrets, documented in [.env.example](.env.example).

### Filters ([src/monitor/filters.py](src/monitor/filters.py))

`aplicar_filtros()` is a pure function (no I/O) — this is why its tests need no mocks. Keyword/exclusion/seniority matching uses regex word-boundaries (`\b{term}\b`), not substring `in` — a short keyword like `"ia"` must match "Especialista em IA" but not "engenharia". Location filtering: remote postings always pass; on-site/hybrid postings only pass if they match a configured location term.

### Storage / dedup ([src/monitor/storage.py](src/monitor/storage.py))

SQLite table `vagas_vistas` has two timestamp columns, both UTC (SQLite's `datetime('now')` is UTC by default, so no explicit timezone handling needed): `visto_em` (first time the id was ever seen, set once) and `ultimo_visto` (bumped every time the id reappears). `marcar_como_vista()`/`marcar_todas()` use an `INSERT ... ON CONFLICT(id) DO UPDATE SET ultimo_visto = ...` upsert — inserting a new id still only writes once (`visto_em` and `ultimo_visto` start equal via the column `DEFAULT`), and re-marking an existing id never touches `visto_em`, only bumps `ultimo_visto`. This keeps dedup/idempotency identical to before (`ja_vista`/`filtrar_novas` still just check id existence) while fixing a real bug: retention pruning.

`retencao_dias` in `config.yaml` (default `90`, `null` disables it) bounds the table's growth: `run()` calls `storage.remover_vistas_antigas(dias)` right after opening `Storage`, before dedup. **The prune is keyed on `ultimo_visto`, never on `visto_em`.** Pruning by first-seen date was the original (buggy) implementation — a posting a source keeps returning on every run would still get deleted once `visto_em` crossed the retention window, and then get treated as "new" and re-notified on the very next run, even though it never actually left the dedup table's blind spot. Keying on `ultimo_visto` means a continuously-seen posting is never pruned, no matter how old `visto_em` is; only postings nobody has reported back in `retencao_dias` actually get removed (and *those* can legitimately cause a re-notification if a source returns them again later — that part's still an accepted trade-off, not a bug).

`Storage.__init__` migrates old `vagas_vistas` tables that predate the `ultimo_visto` column (`ALTER TABLE ... ADD COLUMN` + backfill) automatically and safely — existing rows are backfilled with `ultimo_visto = datetime('now')` (not copied from `visto_em`), so a freshly-migrated `vagas.db` doesn't get its entire history mass-pruned on the very next run.

A second table, `vagas_detalhes`, snapshots the postings that were actually **notified** (title, company, url, source, location, description) so `rolerush curriculo --vaga <id>` can find the description later. Being a new table, `CREATE TABLE IF NOT EXISTS` is itself the safe migration. Retention cascades into it (`DELETE ... WHERE id NOT IN (SELECT id FROM vagas_vistas)`). Note the asymmetry in `run()`, and keep it: details are saved only for notified postings, but `marcar_todas()` marks **every** new posting as seen, including ones `aderencia_minima` filtered out — otherwise they'd resurface on every run. The accepted cost is that lowering `aderencia_minima` later does not bring back postings already filtered.

### Fault isolation

In `coletar_vagas()` ([src/monitor/main.py](src/monitor/main.py)), each source's `fetch()` is wrapped in its own try/except that logs and `continue`s — one broken or misconfigured source (e.g. Adzuna without credentials, a 404'd repo) must not take down the whole run. Preserve this per-source isolation when adding sources.

### Logging and the token-leak lesson

`httpx`/`httpcore` loggers are explicitly set to `WARNING` in `main.py`. This is not generic hygiene — it fixed a real incident: `logging.basicConfig(level=INFO)` elevates every logger process-wide, including `httpx`'s, which logs full request URLs; the Telegram API embeds the bot token directly in the URL path (`/bot<TOKEN>/sendMessage`), so INFO-level httpx logging leaked the token. If you touch logging config in `main.py`, keep those two loggers suppressed.

### GitHub Actions automation

Two workflows:

- [.github/workflows/tests.yml](.github/workflows/tests.yml) — `uv sync --frozen --extra dev` + `uv run pytest` on every push and pull request. No secrets, no network calls (see the testing-conventions note above), so it runs the same for anyone forking the repo.
- [.github/workflows/monitor.yml](.github/workflows/monitor.yml) — runs every 6 hours via `cron` (plus manual `workflow_dispatch`). Runs `uv run pytest` **before** `python -m monitor.main`; since GitHub Actions stops a job at the first failing step by default, a broken test aborts the run before it ever collects or notifies anything real. Because the runner is ephemeral, `vagas.db` is committed back to the repo at the end of each run — that's how dedup state survives between runs without paid infrastructure. Required secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`. `GITHUB_TOKEN` does *not* need to be registered — Actions injects it automatically, scoped by the workflow's `permissions:` block; it's only relevant as an optional local env var to avoid the public GitHub API's 60 req/h rate limit.

### Resume adaptation ([src/monitor/curriculo/](src/monitor/curriculo/))

Separate feature from the monitoring pipeline: takes a master résumé plus a job description and produces an ATS-ready `.docx`, an adherence score (0–100) and a gap list. Full spec, roadmap and test bank in **[CURRICULO.md](CURRICULO.md)** — read it before touching this package. The invariants that must never be traded away:

- **It has to work with zero AI and zero cost.** AI (`LLMProvider`) is an optional increment; `nenhum` is the default provider and must always produce a complete résumé on its own. No paid API, no hosting, no system dependency (no LibreOffice, no Docker, no admin rights).
- **Never invent anything.** Adaptation may only reprioritize, select and rephrase what's already in the master résumé. Any skill, metric, company or certification absent from the master is rejected by the anti-fabrication guardrail (CURRICULO.md §6) and the original bullet is used instead. This is enforced by automated validation, never by trusting the LLM. Every bullet carries a stable unique `id` — that id is the anchor that makes a rewrite traceable back to real experience, so bullet ids must stay unique across the whole résumé (validated at load).
- **Personal data never enters git.** This repo is public: `curriculo_mestre.yaml` and `saida/` are gitignored; only the fictional `curriculo_mestre.example.yaml` is versioned, and it's what the tests run against.
- **The core is pure.** Extraction, scoring, selection and guardrail validation are pure functions — no network, no disk, no clock — the same property that makes `filters.py` trivially testable. AI generation runs locally on demand, never in GitHub Actions (no AI credentials there).
- **Determinism over convenience.** Language detection uses a stopword heuristic in pure Python rather than `langdetect`, which is non-deterministic by default and would make tests flaky. Tie-breaking in selection is stable for the same reason.
- **Skill matching has three non-obvious rules** (`extracao.py`), all load-bearing: boundaries use `(?<!\w)...(?!\w)` rather than `\b` (terms like `C++`/`Node.js` end in a non-word char, where a trailing `\b` can never match); dictionary terms enter the alternation longest-first (otherwise "Google Cloud Platform" gets eaten by "Google Cloud"); and terms listed in `_TERMOS_AMBIGUOS` — dictionary entries that are also ordinary words (`go`, `ia`, `spark`, `lead`) — only count with corroboration: proper-name casing, or a skill-introducing phrase right before them ("experiência com go"). The gate is **word collision, not term length**: a length rule lets "spark innovation" through at 5 chars while rejecting an obvious "experiência com go". Same family of bug as the `\b` lesson in `filters.py`, one level up.
- Tests never call a real LLM or the network. What's tested is the *handling* of model output — parse, validation, fallback — not the quality of generated prose.
- **The guardrail's ground truth is `curriculo_mestre.yaml` itself.** It verifies that a rewrite invents nothing *relative to the master* — it cannot tell whether the master is true. A master filled with placeholder or fictional experience produces a fabricated résumé that passes every check. Say so plainly if a user is about to generate from an unfilled master.
- `guardrail.py`'s proper-noun whitelist must be built from **only the skills the master actually has** (canonical + their dictionary synonyms), never the whole dictionary. "Google Cloud" is a known skill, so whitelisting all dictionary terms leaks the token "google" and lets an invented "at Google" slip through rule 4. A test covers exactly this.
- `LLMProvider.gerar()` returns `None` on *every* failure (timeout, missing binary, non-zero exit, empty output), and every caller treats `None` as "carry on without AI". The rewrite prompt also deliberately omits the job requirements: tailoring already happened during selection, and telling the model what the job wants to hear is an incentive to bend facts.
- **Scoring must degrade to off, never to wrong.** `run()` scores each new posting and puts the adherence in the Telegram message, but the master résumé is gitignored and therefore absent in GitHub Actions. `_fonte_de_aderencia()` resolves the skill set from the master résumé, else from `curriculo.skills_perfil` in `config.yaml` (a plain canonical-skill list, safe to version), else returns `None` and scoring switches off. When it's off, `aderencia_minima` is deliberately **ignored** rather than applied — filtering on a score that couldn't be computed would silently swallow jobs.

## Testing conventions

- `tests/test_filters.py` — pure function tests, no mocking needed.
- `tests/test_storage.py` — SQLite against `tmp_path`. The `_inserir_com_data` helper seeds a row with explicit `visto_em`/`ultimo_visto` values via a raw `sqlite3.connect` (bypassing the `Storage` API) so retention tests can set up scenarios `marcar_*` can't reach directly — e.g. "first seen 120 days ago, last seen yesterday" to prove pruning follows `ultimo_visto`. `test_migracao_adiciona_coluna_ultimo_visto_em_banco_existente` hand-builds the pre-migration schema the same way, then asserts `Storage(caminho)` upgrades it safely.
- `tests/test_sources.py` — HTTP mocked with `respx` (`@respx.mock` + `respx.get(url).mock(return_value=Response(...))`).
- `tests/test_notifier.py` — HTTP mocked with `respx` the same way; covers message formatting/escaping, the unconfigured-credentials error path, and a mocked Telegram HTTP error. Never hits the real Telegram API.
- `tests/test_main.py` — `coletar_vagas()` tested directly with fake `Source` doubles (one raises, to check fault isolation + logging via `caplog`). `run()` tested end-to-end with `monkeypatch.setattr("monitor.main.carregar_config", ...)` and `"monitor.main.montar_fontes", ...` swapped for fakes, plus `respx` for the Telegram call — this is what proves notify-only-new and idempotency (second `run()` on the same data notifies nothing) without touching any real source or config.yaml.

## Further reading

[ARQUITETURA.md](ARQUITETURA.md) has a detailed, pedagogical walkthrough of these design decisions (Portuguese) — consult it for the *why* behind a pattern before changing it. [PROJECT_PLAN.md](PROJECT_PLAN.md) has the original phased roadmap and locked-in architecture decisions. [CURRICULO.md](CURRICULO.md) is the full spec for the résumé-adaptation feature: premises, architecture, anti-fabrication guardrail, the per-phase test bank and the roadmap.
