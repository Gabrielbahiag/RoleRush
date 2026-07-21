from __future__ import annotations

import re

from monitor.config import FiltrosConfig
from monitor.models import Vaga


def vaga_passa_filtro(vaga: Vaga, filtros: FiltrosConfig) -> bool:
    texto = vaga.texto_busca()

    if filtros.remoto is True and vaga.remoto is False:
        return False

    if filtros.excluir and _contem_alguma(texto, filtros.excluir):
        return False

    if filtros.palavras_chave and not _contem_alguma(texto, filtros.palavras_chave):
        return False

    if filtros.senioridade and not _contem_alguma(texto, filtros.senioridade):
        return False

    if filtros.localizacao and not _bate_localizacao(vaga, filtros.localizacao):
        return False

    return True


def aplicar_filtros(vagas: list[Vaga], filtros: FiltrosConfig) -> list[Vaga]:
    return [vaga for vaga in vagas if vaga_passa_filtro(vaga, filtros)]


def _bate_localizacao(vaga: Vaga, termos: list[str]) -> bool:
    # remota serve pra qualquer localização; presencial/híbrida só se bater
    # com um dos termos configurados (ex: "brasília").
    if vaga.remoto is True:
        return True
    texto = f"{vaga.texto_busca()}\n{(vaga.localizacao or '').lower()}"
    return _contem_alguma(texto, termos)


def _contem_alguma(texto: str, termos: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(termo.lower())}\b", texto) for termo in termos)
