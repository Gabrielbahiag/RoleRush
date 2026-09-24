from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

from monitor.curriculo.extracao import RequisitosVaga
from monitor.curriculo.mestre import CurriculoMestre
from monitor.curriculo.skills import DicionarioSkills

PESO_OBRIGATORIO = 3
PESO_DESEJAVEL = 1


class Aderencia(BaseModel):
    """Score 0–100 mais a explicação: o que bateu e o que falta."""

    score: int
    obrigatorios_atendidos: list[str] = Field(default_factory=list)
    obrigatorios_faltantes: list[str] = Field(default_factory=list)
    desejaveis_atendidos: list[str] = Field(default_factory=list)
    desejaveis_faltantes: list[str] = Field(default_factory=list)

    @property
    def lacunas(self) -> list[str]:
        """O que estudar: tudo que a vaga pediu e o currículo não tem."""
        return [*self.obrigatorios_faltantes, *self.desejaveis_faltantes]


def calcular_aderencia(
    requisitos: RequisitosVaga, skills_do_curriculo: Iterable[str]
) -> Aderencia:
    possuidas = {skill.strip().lower() for skill in skills_do_curriculo}

    obrigatorios_atendidos = [s for s in requisitos.obrigatorios if s.lower() in possuidas]
    obrigatorios_faltantes = [s for s in requisitos.obrigatorios if s.lower() not in possuidas]
    desejaveis_atendidos = [s for s in requisitos.desejaveis if s.lower() in possuidas]
    desejaveis_faltantes = [s for s in requisitos.desejaveis if s.lower() not in possuidas]

    total = (
        PESO_OBRIGATORIO * len(requisitos.obrigatorios)
        + PESO_DESEJAVEL * len(requisitos.desejaveis)
    )
    if total == 0:
        # nenhum requisito detectado: não houve cobertura verificada, então o
        # score é 0. Dizer 100 sugeriria uma aderência que ninguém checou.
        score = 0
    else:
        atendido = (
            PESO_OBRIGATORIO * len(obrigatorios_atendidos)
            + PESO_DESEJAVEL * len(desejaveis_atendidos)
        )
        score = round(100 * atendido / total)

    return Aderencia(
        score=score,
        obrigatorios_atendidos=obrigatorios_atendidos,
        obrigatorios_faltantes=obrigatorios_faltantes,
        desejaveis_atendidos=desejaveis_atendidos,
        desejaveis_faltantes=desejaveis_faltantes,
    )


def skills_canonicas_do_curriculo(
    curriculo: CurriculoMestre, dicionario: DicionarioSkills
) -> set[str]:
    """O que o currículo comprova: skills declaradas + tags dos bullets.

    Termo fora do dicionário é mantido como veio — não casa com nada da
    extração (que só produz forma canônica), mas também não some.
    """
    brutas = [skill.nome for skill in curriculo.skills]
    for bullet in curriculo.todos_bullets():
        brutas.extend(bullet.tags)
    return {dicionario.canonizar(termo) or termo for termo in brutas}
