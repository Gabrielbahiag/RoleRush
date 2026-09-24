from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from monitor.curriculo.skills import carregar_skills

RAIZ = Path(__file__).resolve().parents[1]
DICIONARIO = RAIZ / "config" / "skills.yaml"


def test_dicionario_versionado_carrega():
    dicionario = carregar_skills(DICIONARIO)

    assert dicionario.skills


def test_canonizar_reconhece_o_proprio_nome_canonico():
    dicionario = carregar_skills(DICIONARIO)

    assert dicionario.canonizar("Python") == "Python"


def test_canonizar_reconhece_sinonimo_ignorando_caixa_e_espaco():
    dicionario = carregar_skills(DICIONARIO)

    assert dicionario.canonizar("  POSTGRES ") == "PostgreSQL"


def test_canonizar_devolve_none_para_termo_desconhecido():
    dicionario = carregar_skills(DICIONARIO)

    assert dicionario.canonizar("cobol") is None


def test_termos_mapeia_canonicas_e_sinonimos_para_a_forma_canonica():
    termos = carregar_skills(DICIONARIO).termos()

    assert termos["python"] == "Python"
    assert termos["postgres"] == "PostgreSQL"


def test_sinonimo_apontando_para_duas_skills_da_erro(tmp_path):
    # ambiguidade silenciosa quebraria a extração da vaga: "golang" não pode
    # resolver ora pra Go, ora pra Google Cloud.
    caminho = tmp_path / "skills.yaml"
    caminho.write_text(
        yaml.safe_dump(
            {
                "skills": [
                    {"canonica": "Go", "sinonimos": ["golang"]},
                    {"canonica": "Google Cloud", "sinonimos": ["golang"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError) as excinfo:
        carregar_skills(caminho)

    assert "golang" in str(excinfo.value)


def test_arquivo_de_skills_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="nao-existe"):
        carregar_skills(tmp_path / "nao-existe.yaml")
