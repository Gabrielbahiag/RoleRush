from __future__ import annotations

from pydantic import BaseModel, Field

from monitor.curriculo.extracao import RequisitosVaga
from monitor.curriculo.mestre import Bullet, CurriculoMestre, Experiencia, Projeto
from monitor.curriculo.normalizacao import Idioma
from monitor.curriculo.score import PESO_DESEJAVEL, PESO_OBRIGATORIO
from monitor.curriculo.skills import DicionarioSkills


class LimitesSelecao(BaseModel):
    """Quanto cabe num currículo de 1–2 páginas."""

    bullets_por_experiencia: int = 4
    projetos: int = 3
    bullets_por_projeto: int = 3
    skills: int = 12


class ExperienciaSelecionada(BaseModel):
    experiencia: Experiencia
    bullets: list[Bullet]


class ProjetoSelecionado(BaseModel):
    projeto: Projeto
    bullets: list[Bullet]


class CurriculoAdaptado(BaseModel):
    """Recorte do mestre para uma vaga — nada aqui vem de fora dele."""

    mestre: CurriculoMestre
    idioma: Idioma
    experiencias: list[ExperienciaSelecionada] = Field(default_factory=list)
    projetos: list[ProjetoSelecionado] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


def selecionar(
    curriculo: CurriculoMestre,
    requisitos: RequisitosVaga,
    dicionario: DicionarioSkills,
    idioma: Idioma | None = None,
    limites: LimitesSelecao | None = None,
) -> CurriculoAdaptado:
    """Reordena e recorta o mestre pela aderência à vaga.

    Função pura: só reprioriza o que já existe. Nenhuma experiência é
    inventada, reescrita ou removida — o que se corta é bullet, nunca
    emprego, porque a cronologia faz parte do currículo.
    """
    limites = limites or LimitesSelecao()
    pesos = _pesos_dos_requisitos(requisitos, dicionario)

    experiencias = [
        ExperienciaSelecionada(
            experiencia=experiencia,
            bullets=_melhores_bullets(
                experiencia.bullets, pesos, dicionario, limites.bullets_por_experiencia
            ),
        )
        for experiencia in curriculo.experiencias
    ]

    projetos = [
        ProjetoSelecionado(
            projeto=projeto,
            bullets=_melhores_bullets(
                projeto.bullets, pesos, dicionario, limites.bullets_por_projeto
            ),
        )
        for projeto in _melhores_projetos(curriculo.projetos, pesos, dicionario, limites.projetos)
    ]

    return CurriculoAdaptado(
        mestre=curriculo,
        idioma=idioma or requisitos.idioma,
        experiencias=experiencias,
        projetos=projetos,
        skills=_melhores_skills(curriculo, pesos, dicionario, limites.skills),
    )


def _pesos_dos_requisitos(
    requisitos: RequisitosVaga, dicionario: DicionarioSkills
) -> dict[str, int]:
    pesos: dict[str, int] = {}
    for skill in requisitos.desejaveis:
        pesos[_canonizar(skill, dicionario)] = PESO_DESEJAVEL
    # obrigatório sobrescreve: se a vaga cita nos dois blocos, vale o maior.
    for skill in requisitos.obrigatorios:
        pesos[_canonizar(skill, dicionario)] = PESO_OBRIGATORIO
    return pesos


def _canonizar(termo: str, dicionario: DicionarioSkills) -> str:
    return dicionario.canonizar(termo) or termo.strip().lower()


def _relevancia(tags: list[str], pesos: dict[str, int], dicionario: DicionarioSkills) -> int:
    return sum(pesos.get(_canonizar(tag, dicionario), 0) for tag in tags)


def _melhores_bullets(
    bullets: list[Bullet], pesos: dict[str, int], dicionario: DicionarioSkills, limite: int
) -> list[Bullet]:
    # `sorted` é estável: em empate vale a ordem do mestre, e a saída não muda
    # entre execuções.
    ordenados = sorted(bullets, key=lambda bullet: -_relevancia(bullet.tags, pesos, dicionario))
    return ordenados[:limite]


def _melhores_projetos(
    projetos: list[Projeto], pesos: dict[str, int], dicionario: DicionarioSkills, limite: int
) -> list[Projeto]:
    def peso(projeto: Projeto) -> int:
        das_tags = sum(_relevancia(bullet.tags, pesos, dicionario) for bullet in projeto.bullets)
        return das_tags + _relevancia(projeto.stack, pesos, dicionario)

    return sorted(projetos, key=lambda projeto: -peso(projeto))[:limite]


def _melhores_skills(
    curriculo: CurriculoMestre, pesos: dict[str, int], dicionario: DicionarioSkills, limite: int
) -> list[str]:
    ordenadas = sorted(
        curriculo.skills,
        key=lambda skill: -pesos.get(_canonizar(skill.nome, dicionario), 0),
    )
    # devolve o nome como está no mestre: skill que a vaga pede mas o
    # currículo não tem simplesmente não aparece.
    return [skill.nome for skill in ordenadas[:limite]]
