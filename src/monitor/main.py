from __future__ import annotations

import logging
import sys

from monitor.config import Config, carregar_config
from monitor.filters import aplicar_filtros
from monitor.models import Vaga
from monitor.notifier import TelegramNotifier
from monitor.sources.adzuna import AdzunaSource
from monitor.sources.base import Source
from monitor.sources.github_repo import GithubRepoSource
from monitor.sources.remotive import RemotiveSource
from monitor.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor")

# httpx loga a URL completa de cada request em INFO, e a API do Telegram
# embute o bot token na própria URL (/bot<TOKEN>/sendMessage) — sem isso,
# o token vaza em qualquer log local ou do GitHub Actions.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def montar_fontes(config: Config) -> list[Source]:
    fontes: list[Source] = []

    if config.fontes.remotive.ativo:
        fontes.append(RemotiveSource(categoria=config.fontes.remotive.categoria))

    if config.fontes.github_repo.ativo:
        for repo in config.fontes.github_repo.repos:
            fontes.append(GithubRepoSource(repo=repo))

    if config.fontes.adzuna.ativo:
        fontes.append(
            AdzunaSource(
                pais=config.fontes.adzuna.pais,
                what=config.fontes.adzuna.what,
                where=config.fontes.adzuna.where,
            )
        )

    return fontes


def coletar_vagas(fontes: list[Source]) -> list[Vaga]:
    vagas: list[Vaga] = []
    for fonte in fontes:
        try:
            encontradas = fonte.fetch()
        except Exception:
            logger.exception("Falha ao buscar vagas em %s", fonte.nome)
            continue
        logger.info("%s: %d vaga(s) encontrada(s)", fonte.nome, len(encontradas))
        vagas.extend(encontradas)
    return vagas


def run(config_path: str = "config.yaml", db_path: str = "vagas.db", enviar: bool = True) -> list[Vaga]:
    config = carregar_config(config_path)
    fontes = montar_fontes(config)
    if not fontes:
        logger.warning("Nenhuma fonte ativa em %s", config_path)
        return []

    vagas = coletar_vagas(fontes)
    vagas = aplicar_filtros(vagas, config.filtros)

    storage = Storage(db_path)
    novas = storage.filtrar_novas(vagas)
    logger.info("%d vaga(s) nova(s) após filtro e dedup", len(novas))

    if novas and enviar and config.notificacao.telegram:
        notifier = TelegramNotifier()
        if notifier.configurado:
            notifier.notificar_vagas(novas)
        else:
            logger.warning("Notificação Telegram habilitada, mas token/chat_id ausentes")

    for vaga in novas:
        print(f"- [{vaga.fonte}] {vaga.titulo} @ {vaga.empresa} — {vaga.url}")

    storage.marcar_todas(novas)
    return novas


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
