from pathlib import Path

import pytest

from monitor.curriculo.extracao import extrair_requisitos
from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vagas"


@pytest.fixture(scope="module")
def dicionario():
    return carregar_skills(RAIZ / "config" / "skills.yaml")


def test_detecta_skill_do_dicionario(dicionario):
    requisitos = extrair_requisitos("Requisitos: experiência com Python e PostgreSQL.", dicionario)

    assert "Python" in requisitos.obrigatorios
    assert "PostgreSQL" in requisitos.obrigatorios


def test_detecta_skill_por_sinonimo_normalizando_para_a_forma_canonica(dicionario):
    requisitos = extrair_requisitos("Requisitos: postgres e k8s.", dicionario)

    assert "PostgreSQL" in requisitos.obrigatorios
    assert "Kubernetes" in requisitos.obrigatorios


def test_fronteira_de_palavra_java_nao_casa_com_javascript(dicionario):
    requisitos = extrair_requisitos("Requisitos: JavaScript avançado.", dicionario)

    assert "JavaScript" in requisitos.obrigatorios
    assert "Java" not in requisitos.obrigatorios


def test_fronteira_de_palavra_reconhece_java_isolado(dicionario):
    assert "Java" in extrair_requisitos("Requisitos: Java 17.", dicionario).obrigatorios


def test_termo_composto_nao_e_engolido_pelo_mais_curto(dicionario):
    requisitos = extrair_requisitos("Requisitos: Google Cloud Platform.", dicionario)

    assert "Google Cloud" in requisitos.obrigatorios
    assert "Go" not in requisitos.obrigatorios


def test_sigla_curta_em_minuscula_no_meio_da_frase_nao_vira_skill(dicionario):
    # mesma lição do filtro de palavras-chave do monitor: "go" (verbo) e "ia"
    # (verbo) não podem virar Go / Inteligência Artificial.
    texto = "Requisitos: você vai go to market, e ele ia atender o time."

    requisitos = extrair_requisitos(texto, dicionario)

    assert "Go" not in requisitos.obrigatorios
    assert "Inteligência Artificial" not in requisitos.obrigatorios


def test_sigla_curta_em_maiuscula_vira_skill(dicionario):
    requisitos = extrair_requisitos("Requisitos: Go e IA aplicada.", dicionario)

    assert "Go" in requisitos.obrigatorios
    assert "Inteligência Artificial" in requisitos.obrigatorios


def test_palavra_comum_mais_longa_tambem_precisa_de_corroboracao(dicionario):
    # "spark" tem 5 letras: uma regra por tamanho não pegaria isso, mas
    # "spark innovation" é inglês corrente, não Apache Spark.
    texto = "We want people who spark innovation and lead change."

    requisitos = extrair_requisitos(texto, dicionario)

    assert "Apache Spark" not in requisitos.obrigatorios


def test_palavra_comum_escrita_como_nome_proprio_vira_skill(dicionario):
    requisitos = extrair_requisitos("Requirements: Apache Spark and Airflow.", dicionario)

    assert "Apache Spark" in requisitos.obrigatorios


@pytest.mark.parametrize(
    "texto,esperada",
    [
        ("Requisitos: experiência com go e kubernetes.", "Go"),
        ("Requisitos: conhecimento em ia aplicada a produtos.", "Inteligência Artificial"),
        ("Requirements: experience with go in production.", "Go"),
        ("Requirements: knowledge of spark and airflow.", "Apache Spark"),
    ],
)
def test_termo_ambiguo_em_minuscula_conta_quando_o_contexto_corrobora(dicionario, texto, esperada):
    # "experiência com go" é claramente a linguagem, mesmo em minúscula: a
    # frase que introduz skill é a corroboração que faltava.
    assert esperada in extrair_requisitos(texto, dicionario).obrigatorios


def test_termo_nao_ambiguo_em_minuscula_continua_valendo(dicionario):
    # "git" e "k8s" não são palavra comum: não precisam de corroboração
    # nenhuma, mesmo com 3 caracteres.
    requisitos = extrair_requisitos("Requisitos: versionamento com git e deploy em k8s.", dicionario)

    assert "Git" in requisitos.obrigatorios
    assert "Kubernetes" in requisitos.obrigatorios


def test_separa_obrigatorios_de_desejaveis_em_portugues(dicionario):
    texto = "Requisitos\n- Python\n- SQL\n\nDiferenciais\n- Docker\n"

    requisitos = extrair_requisitos(texto, dicionario)

    assert requisitos.obrigatorios == ["Python", "SQL"]
    assert requisitos.desejaveis == ["Docker"]


def test_separa_obrigatorios_de_desejaveis_em_ingles(dicionario):
    texto = "Requirements\n- Python\n- SQL\n\nNice to have\n- Kubernetes\n"

    requisitos = extrair_requisitos(texto, dicionario)

    assert requisitos.obrigatorios == ["Python", "SQL"]
    assert requisitos.desejaveis == ["Kubernetes"]


def test_marcador_de_desejavel_na_mesma_linha_do_conteudo(dicionario):
    texto = "Requisitos: Python\nDesejável: conhecimento em Docker.\n"

    requisitos = extrair_requisitos(texto, dicionario)

    assert requisitos.obrigatorios == ["Python"]
    assert requisitos.desejaveis == ["Docker"]


def test_sem_secao_reconhecida_tudo_vira_obrigatorio(dicionario):
    texto = "Vaga para pessoa desenvolvedora Python com Docker."

    requisitos = extrair_requisitos(texto, dicionario)

    assert set(requisitos.obrigatorios) == {"Python", "Docker"}
    assert requisitos.desejaveis == []


def test_skill_repetida_nos_dois_blocos_fica_so_em_obrigatorios(dicionario):
    texto = "Requisitos\n- Python\n\nDiferenciais\n- Python\n"

    requisitos = extrair_requisitos(texto, dicionario)

    assert requisitos.obrigatorios == ["Python"]
    assert requisitos.desejaveis == []


def test_ordem_e_de_primeira_aparicao_e_sem_repeticao(dicionario):
    requisitos = extrair_requisitos("Requisitos: SQL, Python, Docker e Python.", dicionario)

    assert requisitos.obrigatorios == ["SQL", "Python", "Docker"]


def test_extracao_e_deterministica(dicionario):
    texto = "Requisitos: Python, SQL, Docker\nDiferenciais: AWS\n"

    primeira = extrair_requisitos(texto, dicionario)
    segunda = extrair_requisitos(texto, dicionario)

    assert primeira == segunda


def test_idioma_da_vaga_e_detectado(dicionario):
    texto = "We are looking for a Python developer to join our team."

    assert extrair_requisitos(texto, dicionario).idioma == "en"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Vaga para desenvolvedor júnior", "junior"),
        ("Desenvolvedor Pleno em Brasília", "pleno"),
        ("Senior Software Engineer", "senior"),
        ("Programa de estágio em tecnologia", "estagio"),
        ("Pessoa desenvolvedora de software", None),
    ],
)
def test_detecta_senioridade(dicionario, texto, esperado):
    assert extrair_requisitos(texto, dicionario).senioridade == esperado


def test_extrai_de_html_e_markdown_reais_das_fontes(dicionario):
    remotive = extrair_requisitos((FIXTURES / "remotive_en.html").read_text(encoding="utf-8"), dicionario)
    github = extrair_requisitos((FIXTURES / "github_pt.md").read_text(encoding="utf-8"), dicionario)

    assert remotive.idioma == "en"
    assert {"Python", "SQL", "PostgreSQL"} <= set(remotive.obrigatorios)
    assert {"Docker", "Kubernetes", "AWS"} <= set(remotive.desejaveis)

    assert github.idioma == "pt"
    assert {"Python", "SQL", "PostgreSQL", "Git"} <= set(github.obrigatorios)
    assert {"Docker", "Apache Airflow"} <= set(github.desejaveis)
