from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


def _normalizar(termo: str) -> str:
    return termo.strip().lower()


class SkillCanonica(BaseModel):
    canonica: str
    categoria: str | None = None
    sinonimos: list[str] = Field(default_factory=list)

    def todos_os_termos(self) -> list[str]:
        return [self.canonica, *self.sinonimos]


def _mapear_termos(skills: list[SkillCanonica]) -> tuple[dict[str, str], list[str]]:
    mapa: dict[str, str] = {}
    conflitos: list[str] = []
    for skill in skills:
        for termo in skill.todos_os_termos():
            chave = _normalizar(termo)
            anterior = mapa.get(chave)
            if anterior is not None and anterior != skill.canonica:
                conflitos.append(f"'{termo}' ({anterior} vs {skill.canonica})")
            mapa[chave] = skill.canonica
    return mapa, conflitos


class DicionarioSkills(BaseModel):
    """Skills canônicas + sinônimos e grafias.

    Base do modo sem IA (extração de requisitos da vaga) e do guardrail
    anti-invenção, que usa este dicionário pra decidir se uma tecnologia
    citada por um bullet reescrito existe mesmo no currículo-mestre.
    """

    skills: list[SkillCanonica] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sem_termo_ambiguo(self) -> DicionarioSkills:
        _, conflitos = _mapear_termos(self.skills)
        if conflitos:
            # ambiguidade silenciosa quebraria a extração: o mesmo termo não
            # pode resolver ora pra uma skill, ora pra outra.
            raise ValueError(
                "termo apontando para mais de uma skill canônica: " + "; ".join(conflitos)
            )
        return self

    def termos(self) -> dict[str, str]:
        """Todo termo reconhecido (normalizado) -> forma canônica."""
        mapa, _ = _mapear_termos(self.skills)
        return mapa

    def canonizar(self, termo: str) -> str | None:
        return self.termos().get(_normalizar(termo))


def carregar_skills(caminho: str | Path = "config/skills.yaml") -> DicionarioSkills:
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Dicionário de skills não encontrado: {caminho}")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    return DicionarioSkills.model_validate(dados)
