from __future__ import annotations

import logging
import sys

from monitor.config import Config, carregar_config
from monitor.curriculo.extracao import extrair_requisitos
from monitor.curriculo.perfil import fonte_de_aderencia
from monitor.curriculo.score import Aderencia, calcular_aderencia
from monitor.filters import aplicar_filtros
from monitor.models import Vaga
from monitor.notifier import TelegramNotifier
from monitor.sources.adzuna import AdzunaSource
from monitor.sources.arbeitnow import ArbeitnowSource
from monitor.sources.ashby import AshbySource
from monitor.sources.base import Source
from monitor.sources.github_repo import GithubRepoSource
from monitor.sources.greenhouse import GreenhouseSource
from monitor.sources.himalayas import HimalayasSource
from monitor.sources.jobicy import JobicySource
from monitor.sources.lever import LeverSource
from monitor.sources.remoteok import RemoteOKSource
from monitor.sources.remotive import RemotiveSource
from monitor.sources.themuse import TheMuseSource
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

    if config.fontes.remoteok.ativo:
        fontes.append(RemoteOKSource())

    if config.fontes.arbeitnow.ativo:
        fontes.append(ArbeitnowSource())

    if config.fontes.himalayas.ativo:
        fontes.append(
            HimalayasSource(
                country=config.fontes.himalayas.country,
                q=config.fontes.himalayas.q,
            )
        )

    if config.fontes.jobicy.ativo:
        fontes.append(JobicySource())

    if config.fontes.themuse.ativo:
        fontes.append(
            TheMuseSource(
                categoria=config.fontes.themuse.categoria,
                localizacao=config.fontes.themuse.localizacao,
            )
        )

    if config.fontes.greenhouse.ativo:
        for empresa in config.fontes.greenhouse.empresas:
            fontes.append(GreenhouseSource(empresa=empresa))

    if config.fontes.lever.ativo:
        for empresa in config.fontes.lever.empresas:
            fontes.append(LeverSource(empresa=empresa))

    if config.fontes.ashby.ativo:
        for empresa in config.fontes.ashby.empresas:
            fontes.append(AshbySource(empresa=empresa))

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


def calcular_aderencias(vagas: list[Vaga], config: Config) -> dict[str, Aderencia]:
    fonte = fonte_de_aderencia(config)
    if fonte is None:
        logger.info("Aderência desligada: sem currículo-mestre nem skills_perfil no config")
        return {}

    dicionario, minhas_skills = fonte
    aderencias: dict[str, Aderencia] = {}
    for vaga in vagas:
        # o título costuma carregar stack que não se repete na descrição.
        requisitos = extrair_requisitos(f"{vaga.titulo}\n{vaga.descricao}", dicionario)
        aderencias[vaga.id] = calcular_aderencia(requisitos, minhas_skills)
    return aderencias


def _passa_aderencia(vaga: Vaga, aderencias: dict[str, Aderencia], minima: int | None) -> bool:
    if minima is None:
        return True
    aderencia = aderencias.get(vaga.id)
    # sem pontuação não dá pra julgar: melhor notificar do que engolir a vaga.
    return aderencia is None or aderencia.score >= minima


def run(config_path: str = "config.yaml", db_path: str = "vagas.db", enviar: bool = True) -> list[Vaga]:
    config = carregar_config(config_path)
    fontes = montar_fontes(config)
    if not fontes:
        logger.warning("Nenhuma fonte ativa em %s", config_path)
        return []

    vagas = coletar_vagas(fontes)
    vagas = aplicar_filtros(vagas, config.filtros)

    storage = Storage(db_path)
    if config.retencao_dias:
        removidas = storage.remover_vistas_antigas(config.retencao_dias)
        if removidas:
            logger.info("%d registro(s) antigo(s) removido(s) do histórico de dedup", removidas)

    novas = storage.filtrar_novas(vagas)
    logger.info("%d vaga(s) nova(s) após filtro e dedup", len(novas))

    aderencias = calcular_aderencias(novas, config)
    notificaveis = [
        vaga for vaga in novas if _passa_aderencia(vaga, aderencias, config.aderencia_minima)
    ]
    if len(notificaveis) != len(novas):
        logger.info(
            "%d vaga(s) abaixo da aderência mínima (%s)",
            len(novas) - len(notificaveis),
            config.aderencia_minima,
        )

    if notificaveis and enviar and config.notificacao.telegram:
        notifier = TelegramNotifier()
        if notifier.configurado:
            notifier.notificar_vagas(notificaveis, aderencias)
        else:
            logger.warning("Notificação Telegram habilitada, mas token/chat_id ausentes")

    for vaga in notificaveis:
        aderencia = aderencias.get(vaga.id)
        score = f" [{aderencia.score}%]" if aderencia else ""
        print(f"- [{vaga.fonte}]{score} {vaga.titulo} @ {vaga.empresa} — {vaga.url}")

    # snapshot só do que foi notificado; o dedup vale pra toda vaga nova,
    # inclusive a barrada pela aderência (senão ela volta a cada execução).
    storage.salvar_detalhes(notificaveis)
    storage.marcar_todas(novas)
    return novas


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
