from pathlib import Path

import pytest

from monitor.curriculo.extracao import RequisitosVaga
from monitor.curriculo.mestre import carregar_curriculo
from monitor.curriculo.score import calcular_aderencia, skills_canonicas_do_curriculo
from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dicionario():
    return carregar_skills(RAIZ / "config" / "skills.yaml")


@pytest.fixture(scope="module")
def curriculo():
    return carregar_curriculo(RAIZ / "curriculo_mestre.example.yaml")


def _requisitos(obrigatorios=(), desejaveis=()) -> RequisitosVaga:
    return RequisitosVaga(obrigatorios=list(obrigatorios), desejaveis=list(desejaveis))


def test_score_100_quando_cobre_tudo():
    aderencia = calcular_aderencia(_requisitos(["Python", "SQL"], ["Docker"]), ["Python", "SQL", "Docker"])

    assert aderencia.score == 100
    assert aderencia.obrigatorios_faltantes == []
    assert aderencia.desejaveis_faltantes == []


def test_score_0_quando_nao_cobre_nada():
    aderencia = calcular_aderencia(_requisitos(["Python", "SQL"], ["Docker"]), ["Java"])

    assert aderencia.score == 0
    assert aderencia.obrigatorios_atendidos == []


def test_obrigatorio_pesa_mais_que_desejavel():
    requisitos = _requisitos(["Python"], ["Docker"])

    so_obrigatorio = calcular_aderencia(requisitos, ["Python"]).score
    so_desejavel = calcular_aderencia(requisitos, ["Docker"]).score

    assert so_obrigatorio > so_desejavel


def test_vaga_sem_requisitos_detectados_nao_divide_por_zero():
    # comportamento definido: sem requisito detectado não há cobertura
    # verificada, então o score é 0 — não 100.
    aderencia = calcular_aderencia(_requisitos(), ["Python"])

    assert aderencia.score == 0
    assert aderencia.lacunas == []


def test_explicacao_lista_exatamente_o_que_bateu_e_o_que_falta():
    requisitos = _requisitos(["Python", "SQL"], ["Docker", "AWS"])

    aderencia = calcular_aderencia(requisitos, ["Python", "Docker"])

    assert aderencia.obrigatorios_atendidos == ["Python"]
    assert aderencia.obrigatorios_faltantes == ["SQL"]
    assert aderencia.desejaveis_atendidos == ["Docker"]
    assert aderencia.desejaveis_faltantes == ["AWS"]


def test_lacunas_juntam_faltantes_obrigatorios_e_desejaveis():
    aderencia = calcular_aderencia(_requisitos(["SQL"], ["AWS"]), [])

    assert aderencia.lacunas == ["SQL", "AWS"]


def test_comparacao_ignora_caixa_do_nome_da_skill():
    assert calcular_aderencia(_requisitos(["Python"]), ["python"]).score == 100


def test_score_fica_entre_0_e_100():
    aderencia = calcular_aderencia(_requisitos(["Python", "SQL", "AWS"], ["Docker"]), ["Python"])

    assert 0 < aderencia.score < 100


def test_calculo_e_deterministico():
    requisitos = _requisitos(["Python", "SQL"], ["Docker"])

    assert calcular_aderencia(requisitos, ["Python"]) == calcular_aderencia(requisitos, ["Python"])


def test_skills_do_curriculo_juntam_a_lista_de_skills_e_as_tags_dos_bullets(curriculo, dicionario):
    skills = skills_canonicas_do_curriculo(curriculo, dicionario)

    assert "Python" in skills  # declarada em skills[]
    assert "ETL" in skills  # só aparece como tag de bullet
    assert "REST API" in skills  # idem


def test_curriculo_de_exemplo_tem_aderencia_alta_em_vaga_de_python_e_dados(curriculo, dicionario):
    requisitos = _requisitos(["Python", "SQL", "PostgreSQL"], ["Pandas"])

    aderencia = calcular_aderencia(requisitos, skills_canonicas_do_curriculo(curriculo, dicionario))

    assert aderencia.score == 100
    assert aderencia.lacunas == []
