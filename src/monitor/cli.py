from __future__ import annotations

import argparse
import sys
from pathlib import Path

from monitor.config import Config, carregar_config
from monitor.curriculo.documento import gerar_docx, nome_de_arquivo
from monitor.curriculo.extracao import RequisitosVaga, extrair_requisitos
from monitor.curriculo.mestre import carregar_curriculo
from monitor.curriculo.perfil import fonte_de_aderencia
from monitor.curriculo.score import Aderencia, calcular_aderencia, skills_canonicas_do_curriculo
from monitor.curriculo.selecao import selecionar
from monitor.curriculo.skills import DicionarioSkills, carregar_skills
from monitor.models import Vaga
from monitor.storage import Storage

ERRO = 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = carregar_config(args.config)

    entrada = _resolver_entrada(args)
    if entrada is None:
        return ERRO
    texto, vaga = entrada

    dicionario = carregar_skills(config.curriculo.skills)
    requisitos = extrair_requisitos(texto, dicionario)

    if args.comando == "aderencia":
        return _comando_aderencia(config, requisitos)
    return _comando_curriculo(args, config, requisitos, dicionario, vaga)


def _resolver_entrada(args) -> tuple[str, Vaga | None] | None:
    if args.texto:
        return args.texto, None

    if args.arquivo:
        caminho = Path(args.arquivo)
        if not caminho.exists():
            print(f"Arquivo não encontrado: {caminho}", file=sys.stderr)
            return None
        return caminho.read_text(encoding="utf-8"), None

    vaga = Storage(args.db).buscar_detalhes(args.vaga)
    if vaga is None:
        print(f"Vaga não encontrada no banco: {args.vaga}", file=sys.stderr)
        print(
            "Só ficam salvas as vagas que chegaram a ser notificadas. "
            "Use --arquivo ou --texto pra colar a descrição.",
            file=sys.stderr,
        )
        return None
    return f"{vaga.titulo}\n{vaga.descricao}", vaga


def _comando_aderencia(config: Config, requisitos: RequisitosVaga) -> int:
    fonte = fonte_de_aderencia(config)
    if fonte is None:
        print(f"Currículo-mestre não encontrado: {config.curriculo.mestre}", file=sys.stderr)
        return ERRO

    _, minhas_skills = fonte
    _imprimir_aderencia(calcular_aderencia(requisitos, minhas_skills))
    return 0


def _comando_curriculo(
    args, config: Config, requisitos: RequisitosVaga, dicionario: DicionarioSkills, vaga: Vaga | None
) -> int:
    caminho_mestre = Path(config.curriculo.mestre)
    if not caminho_mestre.exists():
        print(f"Currículo-mestre não encontrado: {caminho_mestre}", file=sys.stderr)
        print("Crie o seu a partir de curriculo_mestre.example.yaml.", file=sys.stderr)
        return ERRO

    mestre = carregar_curriculo(caminho_mestre)
    adaptado = selecionar(mestre, requisitos, dicionario, idioma=args.idioma)

    destino = Path(args.saida) / nome_de_arquivo(
        vaga.empresa if vaga else "", vaga.titulo if vaga else ""
    )
    gerar_docx(adaptado, destino)

    print(f"currículo gerado: {destino}")
    _imprimir_aderencia(calcular_aderencia(requisitos, skills_canonicas_do_curriculo(mestre, dicionario)))
    return 0


def _imprimir_aderencia(aderencia: Aderencia) -> None:
    print(f"aderência: {aderencia.score}%")
    _linha("obrigatórios atendidos", aderencia.obrigatorios_atendidos)
    _linha("obrigatórios faltantes", aderencia.obrigatorios_faltantes)
    _linha("desejáveis atendidos", aderencia.desejaveis_atendidos)
    _linha("desejáveis faltantes", aderencia.desejaveis_faltantes)


def _linha(rotulo: str, skills: list[str]) -> None:
    if skills:
        print(f"{rotulo}: {', '.join(skills)}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolerush",
        description="Adapta o currículo-mestre para uma vaga e calcula a aderência.",
    )
    subcomandos = parser.add_subparsers(dest="comando", required=True)

    for nome, ajuda in (
        ("curriculo", "gera o .docx adaptado para a vaga"),
        ("aderencia", "mostra só o score e as lacunas, sem gerar arquivo"),
    ):
        sub = subcomandos.add_parser(nome, help=ajuda)
        entrada = sub.add_mutually_exclusive_group(required=True)
        entrada.add_argument("--vaga", help="id de uma vaga já notificada pelo monitor")
        entrada.add_argument("--arquivo", help="arquivo com a descrição da vaga")
        entrada.add_argument("--texto", help="descrição da vaga colada direto")
        sub.add_argument("--idioma", choices=("pt", "en"), help="padrão: o idioma da vaga")
        sub.add_argument("--config", default="config.yaml")
        sub.add_argument("--db", default="vagas.db")
        sub.add_argument("--saida", default="saida", help="diretório do .docx gerado")

    return parser


if __name__ == "__main__":
    sys.exit(main())
