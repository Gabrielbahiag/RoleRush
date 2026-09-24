from __future__ import annotations

from pathlib import Path

from monitor.config import Config
from monitor.curriculo.mestre import carregar_curriculo
from monitor.curriculo.score import skills_canonicas_do_curriculo
from monitor.curriculo.skills import DicionarioSkills, carregar_skills


def fonte_de_aderencia(config: Config) -> tuple[DicionarioSkills, set[str]] | None:
    """Dicionário + skills do perfil, ou None se não dá pra pontuar.

    O currículo-mestre é dado pessoal e fica fora do git, então no runner do
    GitHub Actions ele não existe: nesse caso cai pro `skills_perfil` do
    config (versionável, só nomes de skill) e, sem ele, a pontuação
    simplesmente desliga — melhor não pontuar do que pontuar errado.
    """
    caminho_skills = Path(config.curriculo.skills)
    if not caminho_skills.exists():
        return None
    dicionario = carregar_skills(caminho_skills)

    mestre = Path(config.curriculo.mestre)
    if mestre.exists():
        return dicionario, skills_canonicas_do_curriculo(carregar_curriculo(mestre), dicionario)
    if config.curriculo.skills_perfil:
        return dicionario, {
            dicionario.canonizar(skill) or skill for skill in config.curriculo.skills_perfil
        }
    return None
