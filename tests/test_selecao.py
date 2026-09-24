from pathlib import Path

import pytest

from monitor.curriculo.extracao import RequisitosVaga
from monitor.curriculo.mestre import (
    Bullet,
    Contato,
    CurriculoMestre,
    Dados,
    Experiencia,
    Projeto,
    Skill,
    TextoBilingue,
    carregar_curriculo,
)
from monitor.curriculo.selecao import LimitesSelecao, selecionar
from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dicionario():
    return carregar_skills(RAIZ / "config" / "skills.yaml")


def _bullet(id_: str, tags: list[str]) -> Bullet:
    return Bullet(id=id_, texto=TextoBilingue(pt=f"{id_} pt", en=f"{id_} en"), tags=tags)


def _mestre() -> CurriculoMestre:
    return CurriculoMestre(
        dados=Dados(nome="Alex", contato=Contato(email="alex@exemplo.com")),
        resumo=TextoBilingue(pt="resumo pt", en="resumo en"),
        experiencias=[
            Experiencia(
                cargo="Dev",
                empresa="Acme",
                periodo="2023 - atual",
                bullets=[
                    _bullet("e1", ["Docker"]),
                    _bullet("e2", ["Python", "SQL"]),
                    _bullet("e3", []),
                    _bullet("e4", ["Pandas"]),
                    _bullet("e5", ["Python"]),
                ],
            ),
            Experiencia(
                cargo="Estagiário",
                empresa="Orvalho",
                periodo="2022 - 2023",
                bullets=[_bullet("o1", ["SQL"])],
            ),
        ],
        projetos=[
            Projeto(nome="P1", descricao=TextoBilingue(pt="d", en="d"), stack=["Docker"], bullets=[_bullet("p1", ["Docker"])]),
            Projeto(nome="P2", descricao=TextoBilingue(pt="d", en="d"), stack=["Python"], bullets=[_bullet("p2", ["Python"])]),
            Projeto(nome="P3", descricao=TextoBilingue(pt="d", en="d"), bullets=[_bullet("p3", [])]),
        ],
        skills=[Skill(nome="Docker"), Skill(nome="Python"), Skill(nome="SQL"), Skill(nome="Pandas")],
    )


def _requisitos() -> RequisitosVaga:
    return RequisitosVaga(obrigatorios=["Python"], desejaveis=["SQL"], idioma="pt")


def test_bullets_mais_relevantes_vem_primeiro(dicionario):
    adaptado = selecionar(_mestre(), _requisitos(), dicionario)

    primeira = adaptado.experiencias[0]
    # e2 tem Python (obrigatório) + SQL (desejável); e5 só Python.
    assert [bullet.id for bullet in primeira.bullets][:2] == ["e2", "e5"]


def test_empate_preserva_a_ordem_original_do_mestre(dicionario):
    adaptado = selecionar(_mestre(), _requisitos(), dicionario)

    irrelevantes = [b.id for b in adaptado.experiencias[0].bullets if b.id not in {"e2", "e5"}]

    assert irrelevantes == sorted(irrelevantes, key=["e1", "e3", "e4"].index)


def test_limite_de_bullets_por_experiencia_e_respeitado(dicionario):
    limites = LimitesSelecao(bullets_por_experiencia=2)

    adaptado = selecionar(_mestre(), _requisitos(), dicionario, limites=limites)

    assert [bullet.id for bullet in adaptado.experiencias[0].bullets] == ["e2", "e5"]


def test_limite_de_projetos_e_respeitado_e_o_mais_aderente_vem_primeiro(dicionario):
    limites = LimitesSelecao(projetos=2)

    adaptado = selecionar(_mestre(), _requisitos(), dicionario, limites=limites)

    assert [selecionado.projeto.nome for selecionado in adaptado.projetos] == ["P2", "P1"]


def test_todas_as_experiencias_sao_mantidas(dicionario):
    # cronologia é parte do currículo: corta-se bullet, não emprego.
    adaptado = selecionar(_mestre(), _requisitos(), dicionario)

    assert [s.experiencia.empresa for s in adaptado.experiencias] == ["Acme", "Orvalho"]


def test_skills_pedidas_pela_vaga_vem_primeiro(dicionario):
    adaptado = selecionar(_mestre(), _requisitos(), dicionario)

    assert adaptado.skills[:2] == ["Python", "SQL"]


def test_limite_de_skills_e_respeitado(dicionario):
    adaptado = selecionar(_mestre(), _requisitos(), dicionario, limites=LimitesSelecao(skills=2))

    assert adaptado.skills == ["Python", "SQL"]


def test_selecao_e_deterministica(dicionario):
    primeira = selecionar(_mestre(), _requisitos(), dicionario)
    segunda = selecionar(_mestre(), _requisitos(), dicionario)

    assert primeira == segunda


def test_idioma_segue_a_vaga_quando_nao_forcado(dicionario):
    requisitos = RequisitosVaga(obrigatorios=["Python"], idioma="en")

    assert selecionar(_mestre(), requisitos, dicionario).idioma == "en"


def test_idioma_pode_ser_forcado(dicionario):
    requisitos = RequisitosVaga(obrigatorios=["Python"], idioma="en")

    assert selecionar(_mestre(), requisitos, dicionario, idioma="pt").idioma == "pt"


def test_nunca_devolve_bullet_fora_do_mestre(dicionario):
    mestre = carregar_curriculo(RAIZ / "curriculo_mestre.example.yaml")
    ids_do_mestre = {bullet.id for bullet in mestre.todos_bullets()}

    adaptado = selecionar(mestre, _requisitos(), dicionario)

    selecionados = [
        bullet.id
        for grupo in (*adaptado.experiencias, *adaptado.projetos)
        for bullet in grupo.bullets
    ]
    assert selecionados
    assert set(selecionados) <= ids_do_mestre


def test_nunca_devolve_skill_fora_do_mestre(dicionario):
    mestre = carregar_curriculo(RAIZ / "curriculo_mestre.example.yaml")
    # a vaga pede Docker, que o currículo não tem: não pode aparecer na saída.
    requisitos = RequisitosVaga(obrigatorios=["Docker", "Python"], idioma="pt")

    adaptado = selecionar(mestre, requisitos, dicionario)

    assert set(adaptado.skills) <= {skill.nome for skill in mestre.skills}
    assert "Docker" not in adaptado.skills
