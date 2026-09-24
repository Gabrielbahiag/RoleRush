from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from monitor.curriculo.guardrail import contexto_do_mestre, validar_reescrita
from monitor.curriculo.llm import LLMProvider
from monitor.curriculo.mestre import Bullet, CurriculoMestre
from monitor.curriculo.selecao import CurriculoAdaptado
from monitor.curriculo.skills import DicionarioSkills

logger = logging.getLogger("monitor")

_INSTRUCAO = """Você reescreve bullets de currículo para ficarem mais diretos e
orientados a resultado. Regras absolutas:

- NÃO invente nada. Não acrescente tecnologia, empresa, certificação, número
  ou métrica que não esteja no texto original do bullet.
- Mantenha o mesmo idioma do original.
- Reformule apenas a redação: os fatos são exatamente os mesmos.
- Devolva APENAS um array JSON, sem comentários, no formato:
  [{"id": "<id do bullet>", "texto": "<texto reescrito>"}]
- Use exatamente os mesmos ids recebidos.

Bullets:
"""


class Rejeicao(BaseModel):
    id: str
    motivo: str


class ResultadoReescrita(BaseModel):
    textos: dict[str, str] = Field(default_factory=dict)
    rejeicoes: list[Rejeicao] = Field(default_factory=list)


class _BulletReescrito(BaseModel):
    id: str
    texto: str


def reescrever(
    adaptado: CurriculoAdaptado,
    provedor: LLMProvider,
    mestre: CurriculoMestre,
    dicionario: DicionarioSkills,
) -> ResultadoReescrita:
    """Reescreve os bullets selecionados, validando cada saída da IA.

    Nunca altera o currículo-mestre: devolve um mapa `id -> texto` que o
    gerador usa no lugar do original. O que não for aprovado simplesmente
    não entra no mapa, e o texto original é usado.

    De propósito, o prompt **não** recebe os requisitos da vaga: a adaptação
    à vaga já aconteceu na seleção, e contar pro modelo o que a vaga quer
    ouvir só criaria incentivo pra ele torcer os fatos.
    """
    bullets = _bullets_selecionados(adaptado)
    if not bullets:
        return ResultadoReescrita()

    bruto = provedor.gerar(_montar_prompt(bullets, adaptado))
    if not bruto:
        return ResultadoReescrita()

    itens = _ler_json(bruto)
    if itens is None:
        logger.warning("Reescrita: resposta não veio em JSON válido; mantendo os originais")
        return ResultadoReescrita()

    contexto = contexto_do_mestre(mestre, dicionario)
    por_id = {bullet.id: bullet for bullet in bullets}

    resultado = ResultadoReescrita()
    for item in itens:
        motivo = validar_reescrita(item.id, item.texto, por_id.get(item.id), contexto, dicionario)
        if motivo:
            resultado.rejeicoes.append(Rejeicao(id=item.id, motivo=motivo))
            continue
        resultado.textos[item.id] = item.texto
    return resultado


def _bullets_selecionados(adaptado: CurriculoAdaptado) -> list[Bullet]:
    return [
        bullet
        for grupo in (*adaptado.experiencias, *adaptado.projetos)
        for bullet in grupo.bullets
    ]


def _montar_prompt(bullets: list[Bullet], adaptado: CurriculoAdaptado) -> str:
    linhas = [
        f'- id: {bullet.id}\n  texto: {bullet.texto_para(adaptado.idioma)}' for bullet in bullets
    ]
    return _INSTRUCAO + "\n".join(linhas)


def _ler_json(bruto: str) -> list[_BulletReescrito] | None:
    inicio = bruto.find("[")
    fim = bruto.rfind("]")
    if inicio == -1 or fim <= inicio:
        return None
    try:
        dados = json.loads(bruto[inicio : fim + 1])
        return [_BulletReescrito.model_validate(item) for item in dados]
    except (json.JSONDecodeError, ValidationError, TypeError):
        return None
