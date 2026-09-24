import subprocess

import pytest
from pydantic import ValidationError

from monitor.config import Config, CurriculoConfig
from monitor.curriculo.llm import ProvedorClaudeCLI, ProvedorNenhum, montar_provedor


def _fake_run(retorno=None, erro=None, registro=None):
    def executar(comando, **kwargs):
        if registro is not None:
            registro["comando"] = comando
            registro["kwargs"] = kwargs
        if erro is not None:
            raise erro
        return retorno

    return executar


def test_provedor_nenhum_nunca_gera():
    assert ProvedorNenhum().gerar("qualquer prompt") is None


def test_montar_provedor_padrao_e_nenhum():
    assert montar_provedor(Config()).nome == "nenhum"


def test_montar_provedor_claude_cli():
    config = Config(curriculo=CurriculoConfig(provedor="claude-cli"))

    assert montar_provedor(config).nome == "claude-cli"


def test_provedor_desconhecido_e_rejeitado_na_carga_do_config():
    # "parse, don't validate": nome errado explode na carga, não no meio da
    # geração do currículo.
    with pytest.raises(ValidationError):
        CurriculoConfig(provedor="modelo-inventado")


def test_claude_cli_devolve_a_saida_do_processo(monkeypatch):
    concluido = subprocess.CompletedProcess(["claude"], 0, stdout="resposta do modelo", stderr="")
    monkeypatch.setattr("monitor.curriculo.llm.subprocess.run", _fake_run(retorno=concluido))

    assert ProvedorClaudeCLI().gerar("prompt") == "resposta do modelo"


def test_claude_cli_passa_o_prompt_e_o_timeout_configurado(monkeypatch):
    registro: dict = {}
    concluido = subprocess.CompletedProcess(["claude"], 0, stdout="ok", stderr="")
    monkeypatch.setattr(
        "monitor.curriculo.llm.subprocess.run", _fake_run(retorno=concluido, registro=registro)
    )

    ProvedorClaudeCLI(timeout=12.0).gerar("meu prompt")

    assert "meu prompt" in registro["comando"]
    assert registro["kwargs"]["timeout"] == 12.0


@pytest.mark.parametrize(
    "retorno,erro",
    [
        (None, subprocess.TimeoutExpired(cmd="claude", timeout=1)),
        (None, FileNotFoundError("claude não instalado")),
        (subprocess.CompletedProcess(["claude"], 1, stdout="", stderr="falhou"), None),
        (subprocess.CompletedProcess(["claude"], 0, stdout="", stderr=""), None),
    ],
    ids=["timeout", "sem executavel", "codigo de erro", "saida vazia"],
)
def test_qualquer_falha_do_claude_cli_vira_none_para_cair_no_fallback(monkeypatch, retorno, erro):
    monkeypatch.setattr(
        "monitor.curriculo.llm.subprocess.run", _fake_run(retorno=retorno, erro=erro)
    )

    assert ProvedorClaudeCLI().gerar("prompt") is None
