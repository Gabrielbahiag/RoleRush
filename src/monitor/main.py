from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

from monitor.config import Config, carregar_config
from monitor.curriculo.extracao import extrair_requisitos
from monitor.curriculo.perfil import fonte_de_aderencia
from monitor.curriculo.score import Aderencia, calcular_aderencia
from monitor.filters import aplicar_filtros
from monitor.models import Vaga
from monitor.notifier import TelegramNotifier
from monitor.saude import RegistroFonte, descrever_erro, formatar_alerta_falhas, formatar_resumo
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


def coletar_vagas(fontes: list[Source]) -> tuple[list[Vaga], dict[str, str]]:
    """Vagas de todas as fontes + {fonte: erro} das que falharam.

    Uma fonte quebrada não derruba as outras — e, justamente por isso, a
    falha precisa ser devolvida para virar aviso; só logar a deixava
    invisível num job que termina verde.
    """
    vagas: list[Vaga] = []
    falhas: dict[str, str] = {}
    for fonte in fontes:
        try:
            encontradas = fonte.fetch()
        except Exception as erro:
            # sem traceback: a mensagem de erro do httpx traz a URL completa,
            # com token/app_key. descrever_erro só expõe status e tipo.
            falhas[fonte.nome] = descrever_erro(erro)
            logger.error("Falha ao buscar vagas em %s: %s", fonte.nome, falhas[fonte.nome])
            continue
        if not encontradas:
            logger.warning("%s: nenhuma vaga devolvida", fonte.nome)
        logger.info("%s: %d vaga(s) encontrada(s)", fonte.nome, len(encontradas))
        vagas.extend(encontradas)
    return vagas, falhas


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


def run(config_path: str = "config.yaml", db_path: str = "vagas.db", simular: bool = False) -> list[Vaga]:
    """Uma execução completa: coleta -> filtro -> dedup -> notificação.

    `simular=True` roda tudo contra uma cópia descartável do banco e não
    envia nada: dá pra testar filtro e fontes localmente sem mexer no
    vagas.db versionado nem no Telegram.
    """
    config = carregar_config(config_path)
    fontes = montar_fontes(config)
    if not fontes:
        logger.warning("Nenhuma fonte ativa em %s", config_path)
        return []

    if not simular:
        return _executar(config, fontes, db_path, enviar=True)

    with tempfile.TemporaryDirectory() as temporario:
        copia = Path(temporario) / "vagas.db"
        if Path(db_path).exists():
            shutil.copyfile(db_path, copia)
        return _executar(config, fontes, copia, enviar=False)


def _executar(config: Config, fontes: list[Source], db_path: str | Path, enviar: bool) -> list[Vaga]:
    coletadas, falhas = coletar_vagas(fontes)
    vagas = aplicar_filtros(coletadas, config.filtros)

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

    notificaveis = sorted(notificaveis, key=_instante_de_publicacao, reverse=True)
    lote = notificaveis[: config.notificacao.max_por_execucao]
    if len(lote) < len(notificaveis):
        logger.warning(
            "%d vaga(s) acima do teto de %d por execução ficam para a próxima",
            len(notificaveis) - len(lote),
            config.notificacao.max_por_execucao,
        )

    # Só é marcada como vista, aqui, a vaga que não está esperando entrega:
    # as já vistas que reapareceram (avança o ultimo_visto, que é o que a
    # retenção olha) e as novas barradas pela aderência (senão voltariam a
    # cada execução). As notificáveis só são marcadas depois de entregues.
    pendentes = {vaga.id for vaga in notificaveis}
    storage.marcar_todas([vaga for vaga in vagas if vaga.id not in pendentes])

    notificadas: Counter[str] = Counter()

    def entregue(vaga: Vaga) -> None:
        storage.salvar_detalhes([vaga])
        storage.marcar_todas([vaga])
        notificadas[vaga.fonte] += 1

    notifier = TelegramNotifier() if enviar and config.notificacao.telegram else None
    if lote:
        if notifier is not None:
            _notificar(notifier, lote, aderencias, entregue)
        else:
            # Telegram desligado no config (ou simulação): imprimir é a entrega.
            for vaga in lote:
                entregue(vaga)

    for vaga in lote:
        aderencia = aderencias.get(vaga.id)
        score = f" [{aderencia.score}%]" if aderencia else ""
        print(f"- [{vaga.fonte}]{score} {vaga.titulo} @ {vaga.empresa} — {vaga.url}")

    if notifier is not None and notifier.configurado:
        _avisar_saude(notifier, storage, falhas)

    # depois dos avisos: se o envio de um deles falhar, a execução não fica
    # registrada e o aviso é tentado de novo na próxima.
    por_fonte_coletadas = Counter(vaga.fonte for vaga in coletadas)
    por_fonte_aprovadas = Counter(vaga.fonte for vaga in vagas)
    storage.registrar_execucao(
        [
            RegistroFonte(
                fonte=fonte.nome,
                coletadas=por_fonte_coletadas[fonte.nome],
                aprovadas=por_fonte_aprovadas[fonte.nome],
                notificadas=notificadas[fonte.nome],
                erro=falhas.get(fonte.nome),
            )
            for fonte in fontes
        ]
    )
    return novas


_DIAS_DO_RESUMO = 7


def _avisar_saude(notifier: TelegramNotifier, storage: Storage, falhas: dict[str, str]) -> None:
    # só a transição ok -> falha vira aviso; falha que persiste aparece no
    # resumo semanal, em vez de repetir o alerta a cada 6 horas.
    ja_falhavam = storage.falharam_na_execucao_anterior()
    novas_falhas = {fonte: erro for fonte, erro in falhas.items() if fonte not in ja_falhavam}
    if novas_falhas:
        notifier.enviar_mensagem(formatar_alerta_falhas(novas_falhas))

    dias = storage.dias_desde_meta("ultimo_resumo")
    if dias is None:
        # primeira execução com esta versão: começa a contar a semana agora,
        # em vez de mandar um "resumo semanal" com uma execução só.
        storage.marcar_meta_agora("ultimo_resumo")
    elif dias >= _DIAS_DO_RESUMO:
        resumos = storage.resumo_fontes(_DIAS_DO_RESUMO)
        if resumos:
            notifier.enviar_mensagem(formatar_resumo(resumos, _DIAS_DO_RESUMO))
        storage.marcar_meta_agora("ultimo_resumo")


def _notificar(
    notifier: TelegramNotifier, lote: list[Vaga], aderencias: dict[str, Aderencia], entregue
) -> None:
    if not notifier.configurado:
        if _em_ci():
            # no Actions, credencial ausente é erro de configuração: falhar
            # alto é o que dispara o e-mail de falha do GitHub. Seguir em
            # frente marcaria tudo como visto sem nada ter chegado.
            raise RuntimeError(
                "Telegram habilitado, mas TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID estão vazios. "
                "Nenhuma vaga foi marcada como vista."
            )
        logger.warning("Telegram sem credenciais: só imprimindo, sem marcar as vagas como vistas")
        return
    notifier.notificar_vagas(lote, aderencias, ao_enviar=entregue)


def _em_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _instante_de_publicacao(vaga: Vaga) -> float:
    # mais recente primeiro; sem data vai pro fim. timestamp() resolve a
    # mistura de datas com e sem fuso que as fontes devolvem.
    if vaga.publicada_em is None:
        return float("-inf")
    try:
        return vaga.publicada_em.timestamp()
    except (OverflowError, OSError, ValueError):
        return float("-inf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m monitor.main",
        description="Coleta vagas, filtra pelo perfil, deduplica e notifica no Telegram.",
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="vagas.db")
    parser.add_argument(
        "--simular",
        action="store_true",
        help="coleta e filtra de verdade, mas não envia nada nem grava no banco",
    )
    args = parser.parse_args(argv)
    run(config_path=args.config, db_path=args.db, simular=args.simular)
    return 0


if __name__ == "__main__":
    sys.exit(main())
