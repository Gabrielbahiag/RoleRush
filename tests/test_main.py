import logging

import respx
from httpx import Response

from monitor.config import Config, NotificacaoConfig
from monitor.main import coletar_vagas, run
from monitor.models import Vaga
from monitor.sources.base import Source


class _FonteQuebrada(Source):
    nome = "quebrada"

    def fetch(self) -> list[Vaga]:
        raise RuntimeError("falha simulada")


class _FonteFixa(Source):
    def __init__(self, nome: str, vagas: list[Vaga]) -> None:
        self.nome = nome
        self._vagas = vagas

    def fetch(self) -> list[Vaga]:
        return self._vagas


def _vaga(id_: str) -> Vaga:
    return Vaga(id=id_, titulo="Dev Python", empresa="Acme", url=f"https://exemplo.com/{id_}", fonte="teste")


def test_coletar_vagas_isola_fonte_que_lanca_excecao_e_segue_as_demais(caplog):
    vaga_ok = _vaga("ok:1")
    fontes = [_FonteQuebrada(), _FonteFixa("ok", [vaga_ok])]

    with caplog.at_level(logging.ERROR, logger="monitor"):
        vagas = coletar_vagas(fontes)

    assert vagas == [vaga_ok]
    assert "quebrada" in caplog.text


@respx.mock
def test_run_notifica_so_vagas_novas_e_marca_como_vistas(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-teste")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    vaga = _vaga("teste:1")
    config = Config(notificacao=NotificacaoConfig(telegram=True))
    monkeypatch.setattr("monitor.main.carregar_config", lambda caminho: config)
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [_FonteFixa("teste", [vaga])])

    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )

    db_path = tmp_path / "vagas.db"
    novas = run(config_path="ignorado.yaml", db_path=str(db_path))

    assert novas == [vaga]
    assert rota.call_count == 1


@respx.mock
def test_run_e_idempotente_segunda_execucao_com_mesmas_vagas_nao_notifica_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-teste")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    vaga = _vaga("teste:1")
    config = Config(notificacao=NotificacaoConfig(telegram=True))
    monkeypatch.setattr("monitor.main.carregar_config", lambda caminho: config)
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [_FonteFixa("teste", [vaga])])

    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )

    db_path = tmp_path / "vagas.db"
    primeira = run(config_path="ignorado.yaml", db_path=str(db_path))
    segunda = run(config_path="ignorado.yaml", db_path=str(db_path))

    assert primeira == [vaga]
    assert segunda == []
    assert rota.call_count == 1  # só a primeira execução notificou
