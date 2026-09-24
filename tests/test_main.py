import logging
from pathlib import Path

import respx
from httpx import Response

from monitor.config import Config, CurriculoConfig, NotificacaoConfig
from monitor.main import coletar_vagas, run
from monitor.models import Vaga
from monitor.sources.base import Source
from monitor.storage import Storage

RAIZ = Path(__file__).resolve().parents[1]
CURRICULO_EXEMPLO = str(RAIZ / "curriculo_mestre.example.yaml")
SKILLS = str(RAIZ / "config" / "skills.yaml")

# o currículo-mestre real é gitignored: apontar explicitamente pra um caminho
# inexistente mantém o teste igual em qualquer máquina, exista ele ou não.
SEM_CURRICULO = CurriculoConfig(mestre="nao-existe.yaml", skills="nao-existe.yaml")
COM_CURRICULO = CurriculoConfig(mestre=CURRICULO_EXEMPLO, skills=SKILLS)


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
    config = Config(notificacao=NotificacaoConfig(telegram=True), curriculo=SEM_CURRICULO)
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
    config = Config(notificacao=NotificacaoConfig(telegram=True), curriculo=SEM_CURRICULO)
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


def _rodar(monkeypatch, tmp_path, config, vagas):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-teste")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("monitor.main.carregar_config", lambda caminho: config)
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [_FonteFixa("teste", vagas)])
    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    db_path = tmp_path / "vagas.db"
    novas = run(config_path="ignorado.yaml", db_path=str(db_path))
    return novas, rota, Storage(str(db_path))


def _vaga_com_descricao(id_: str, descricao: str) -> Vaga:
    return Vaga(
        id=id_,
        titulo="Pessoa Desenvolvedora",
        empresa="Acme",
        url=f"https://exemplo.com/{id_}",
        fonte="teste",
        descricao=descricao,
    )


@respx.mock
def test_run_salva_detalhes_apenas_das_vagas_notificadas(tmp_path, monkeypatch):
    # aderência mínima alta derruba a vaga fraca: ela conta pro dedup, mas não
    # vira detalhe salvo nem notificação.
    forte = _vaga_com_descricao("forte:1", "Requisitos: Python, SQL e PostgreSQL.")
    fraca = _vaga_com_descricao("fraca:1", "Requisitos: Kubernetes, Terraform e AWS.")
    config = Config(
        notificacao=NotificacaoConfig(telegram=True),
        curriculo=COM_CURRICULO,
        aderencia_minima=70,
    )

    novas, rota, storage = _rodar(monkeypatch, tmp_path, config, [forte, fraca])

    assert {vaga.id for vaga in novas} == {"forte:1", "fraca:1"}
    assert rota.call_count == 1
    assert storage.buscar_detalhes("forte:1") is not None
    assert storage.buscar_detalhes("fraca:1") is None


@respx.mock
def test_run_marca_como_vista_mesmo_a_vaga_barrada_pela_aderencia(tmp_path, monkeypatch):
    fraca = _vaga_com_descricao("fraca:1", "Requisitos: Kubernetes e Terraform.")
    config = Config(
        notificacao=NotificacaoConfig(telegram=True),
        curriculo=COM_CURRICULO,
        aderencia_minima=70,
    )

    _, rota, storage = _rodar(monkeypatch, tmp_path, config, [fraca])

    assert rota.call_count == 0
    assert storage.ja_vista("fraca:1") is True


@respx.mock
def test_run_sem_aderencia_minima_notifica_tudo(tmp_path, monkeypatch):
    fraca = _vaga_com_descricao("fraca:1", "Requisitos: Kubernetes e Terraform.")
    config = Config(notificacao=NotificacaoConfig(telegram=True), curriculo=COM_CURRICULO)

    _, rota, _ = _rodar(monkeypatch, tmp_path, config, [fraca])

    assert rota.call_count == 1


@respx.mock
def test_run_sem_curriculo_mestre_nao_pontua_e_notifica_tudo(tmp_path, monkeypatch):
    # no GitHub Actions o currículo-mestre não existe (é dado pessoal, fora do
    # git): a aderência simplesmente desliga, sem derrubar o pipeline nem
    # engolir notificação.
    vaga = _vaga_com_descricao("x:1", "Requisitos: Kubernetes e Terraform.")
    config = Config(
        notificacao=NotificacaoConfig(telegram=True),
        curriculo=SEM_CURRICULO,
        aderencia_minima=90,
    )

    _, rota, _ = _rodar(monkeypatch, tmp_path, config, [vaga])

    assert rota.call_count == 1


@respx.mock
def test_run_inclui_o_score_na_mensagem_quando_ha_curriculo(tmp_path, monkeypatch):
    import json

    vaga = _vaga_com_descricao("x:1", "Requisitos: Python, SQL e PostgreSQL.")
    config = Config(notificacao=NotificacaoConfig(telegram=True), curriculo=COM_CURRICULO)

    _, rota, _ = _rodar(monkeypatch, tmp_path, config, [vaga])

    texto = json.loads(rota.calls.last.request.content)["text"]
    assert "100" in texto
    assert "x:1" in texto
