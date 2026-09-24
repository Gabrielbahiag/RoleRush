from pathlib import Path

import pytest

from monitor.curriculo.guardrail import contexto_do_mestre, validar_reescrita
from monitor.curriculo.mestre import (
    Bullet,
    Certificacao,
    Contato,
    CurriculoMestre,
    Dados,
    Experiencia,
    Skill,
    TextoBilingue,
)
from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]

ORIGINAL_PT = "Reduzi em 40% o tempo de ingestão com Python."
ORIGINAL_EN = "Cut ingestion time by 40% with Python."


@pytest.fixture(scope="module")
def dicionario():
    return carregar_skills(RAIZ / "config" / "skills.yaml")


@pytest.fixture(scope="module")
def mestre():
    return CurriculoMestre(
        dados=Dados(nome="Alex Duarte", contato=Contato(email="alex@exemplo.com")),
        resumo=TextoBilingue(pt="resumo", en="summary"),
        experiencias=[
            Experiencia(
                cargo="Dev",
                empresa="Constelação Tech",
                periodo="2023 - atual",
                bullets=[
                    Bullet(
                        id="b1",
                        texto=TextoBilingue(pt=ORIGINAL_PT, en=ORIGINAL_EN),
                        tags=["Python"],
                    )
                ],
            )
        ],
        skills=[Skill(nome="Python"), Skill(nome="SQL")],
        certificacoes=[Certificacao(nome="Fundamentos de Dados", emissor="Instituto Exemplo")],
    )


@pytest.fixture(scope="module")
def contexto(mestre, dicionario):
    return contexto_do_mestre(mestre, dicionario)


def _validar(texto, contexto, dicionario, mestre, bullet_id="b1"):
    original = next((b for b in mestre.todos_bullets() if b.id == bullet_id), None)
    return validar_reescrita(bullet_id, texto, original, contexto, dicionario)


def test_reescrita_fiel_e_aceita(contexto, dicionario, mestre):
    texto = "Cortei 40% do tempo de ingestão usando Python."

    assert _validar(texto, contexto, dicionario, mestre) is None


def test_bullet_com_id_desconhecido_e_rejeitado(contexto, dicionario, mestre):
    motivo = _validar("Qualquer texto.", contexto, dicionario, mestre, bullet_id="nao-existe")

    assert motivo is not None
    assert "nao-existe" in motivo


def test_skill_ausente_do_mestre_e_rejeitada(contexto, dicionario, mestre):
    texto = "Reduzi em 40% o tempo de ingestão usando Kubernetes."

    motivo = _validar(texto, contexto, dicionario, mestre)

    assert motivo is not None
    assert "Kubernetes" in motivo


def test_skill_presente_no_mestre_e_aceita(contexto, dicionario, mestre):
    texto = "Reduzi em 40% o tempo de ingestão com Python e SQL."

    assert _validar(texto, contexto, dicionario, mestre) is None


def test_metrica_inventada_e_rejeitada(contexto, dicionario, mestre):
    # o número não existe no bullet original: é invenção, não reformulação.
    texto = "Reduzi em 65% o tempo de ingestão com Python."

    motivo = _validar(texto, contexto, dicionario, mestre)

    assert motivo is not None
    assert "65" in motivo


def test_metrica_do_original_pode_ser_mantida(contexto, dicionario, mestre):
    assert _validar("40% menos tempo de ingestão com Python.", contexto, dicionario, mestre) is None


def test_empresa_inexistente_e_rejeitada(contexto, dicionario, mestre):
    texto = "Reduzi em 40% o tempo de ingestão com Python na Google."

    motivo = _validar(texto, contexto, dicionario, mestre)

    assert motivo is not None
    assert "Google" in motivo


def test_empresa_do_mestre_e_aceita(contexto, dicionario, mestre):
    texto = "Reduzi em 40% o tempo de ingestão com Python na Constelação Tech."

    assert _validar(texto, contexto, dicionario, mestre) is None


def test_certificacao_inexistente_e_rejeitada(contexto, dicionario, mestre):
    texto = "Reduzi em 40% o tempo de ingestão com Python, certificado pela Fundação Bradesco."

    motivo = _validar(texto, contexto, dicionario, mestre)

    assert motivo is not None


def test_primeira_palavra_da_frase_nao_e_tratada_como_nome_proprio(contexto, dicionario, mestre):
    # "Desenvolvi" começa a frase e é só maiúscula de pontuação — reformular o
    # verbo inicial é exatamente o que uma reescrita legítima faz.
    texto = "Desenvolvi a ingestão com Python, cortando 40% do tempo."

    assert _validar(texto, contexto, dicionario, mestre) is None
