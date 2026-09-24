from pathlib import Path

import pytest
import yaml

from monitor.cli import main
from monitor.models import Vaga
from monitor.storage import Storage

RAIZ = Path(__file__).resolve().parents[1]
EXEMPLO = str(RAIZ / "curriculo_mestre.example.yaml")
SKILLS = str(RAIZ / "config" / "skills.yaml")

DESCRICAO = "Requisitos: Python, SQL e PostgreSQL.\nDiferenciais: Docker."


def _config(tmp_path, mestre: str = EXEMPLO) -> str:
    caminho = tmp_path / "config.yaml"
    caminho.write_text(
        yaml.safe_dump({"curriculo": {"mestre": mestre, "skills": SKILLS}}),
        encoding="utf-8",
    )
    return str(caminho)


def _db_com_vaga(tmp_path) -> str:
    caminho = tmp_path / "vagas.db"
    storage = Storage(caminho)
    storage.salvar_detalhes(
        [
            Vaga(
                id="remotive:1",
                titulo="Pessoa Desenvolvedora Python",
                empresa="Acme",
                url="https://exemplo.com/1",
                fonte="remotive",
                descricao=DESCRICAO,
            )
        ]
    )
    return str(caminho)


def test_aderencia_por_texto_imprime_score_e_lacunas(tmp_path, capsys):
    codigo = main(["aderencia", "--texto", DESCRICAO, "--config", _config(tmp_path)])

    saida = capsys.readouterr().out
    assert codigo == 0
    assert "%" in saida
    assert "Docker" in saida  # lacuna: o currículo de exemplo não tem


def test_tres_modos_de_entrada_dao_o_mesmo_resultado(tmp_path, capsys):
    config = _config(tmp_path)
    db = _db_com_vaga(tmp_path)
    arquivo = tmp_path / "vaga.txt"
    texto_da_vaga = f"Pessoa Desenvolvedora Python\n{DESCRICAO}"
    arquivo.write_text(texto_da_vaga, encoding="utf-8")

    main(["aderencia", "--vaga", "remotive:1", "--config", config, "--db", db])
    por_vaga = capsys.readouterr().out
    main(["aderencia", "--arquivo", str(arquivo), "--config", config])
    por_arquivo = capsys.readouterr().out
    main(["aderencia", "--texto", texto_da_vaga, "--config", config])
    por_texto = capsys.readouterr().out

    assert por_vaga == por_arquivo == por_texto


def test_vaga_inexistente_da_mensagem_clara_e_codigo_diferente_de_zero(tmp_path, capsys):
    codigo = main(
        ["aderencia", "--vaga", "nao-existe:1", "--config", _config(tmp_path), "--db", _db_com_vaga(tmp_path)]
    )

    saida = capsys.readouterr()
    assert codigo != 0
    assert "nao-existe:1" in (saida.out + saida.err)


def test_arquivo_inexistente_da_mensagem_clara_e_codigo_diferente_de_zero(tmp_path, capsys):
    codigo = main(["aderencia", "--arquivo", str(tmp_path / "sumiu.txt"), "--config", _config(tmp_path)])

    saida = capsys.readouterr()
    assert codigo != 0
    assert "sumiu.txt" in (saida.out + saida.err)


def test_curriculo_gera_o_docx_e_informa_o_caminho(tmp_path, capsys):
    destino = tmp_path / "saida"

    codigo = main(
        ["curriculo", "--texto", DESCRICAO, "--config", _config(tmp_path), "--saida", str(destino)]
    )

    saida = capsys.readouterr().out
    gerados = list(destino.glob("*.docx"))
    assert codigo == 0
    assert len(gerados) == 1
    assert gerados[0].name in saida


def test_curriculo_sem_mestre_da_mensagem_clara_e_codigo_diferente_de_zero(tmp_path, capsys):
    config = _config(tmp_path, mestre=str(tmp_path / "nao-existe.yaml"))

    codigo = main(["curriculo", "--texto", DESCRICAO, "--config", config, "--saida", str(tmp_path)])

    saida = capsys.readouterr()
    assert codigo != 0
    assert "nao-existe.yaml" in (saida.out + saida.err)


def test_idioma_pode_ser_forcado_pela_flag(tmp_path):
    from docx import Document

    destino = tmp_path / "saida"

    main(
        [
            "curriculo",
            "--texto",
            DESCRICAO,  # descrição em português
            "--idioma",
            "en",
            "--config",
            _config(tmp_path),
            "--saida",
            str(destino),
        ]
    )

    gerado = next(destino.glob("*.docx"))
    textos = [p.text.strip() for p in Document(str(gerado)).paragraphs]
    assert "Professional Experience" in textos


def test_sem_subcomando_nao_explode(capsys):
    with pytest.raises(SystemExit):
        main([])
