import json
import logging
from pathlib import Path

import pytest
import respx
from httpx import Response

from monitor.config import Config, CurriculoConfig, NotificacaoConfig
from monitor.main import coletar_vagas, main, run
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
    # título distinto por id: mesma empresa + mesmo título é tratado como a
    # mesma vaga (impressão digital) e só notifica uma vez.
    return Vaga(id=id_, titulo=f"Dev Python {id_}", empresa="Acme", url=f"https://exemplo.com/{id_}", fonte="teste")


def test_coletar_vagas_isola_fonte_que_lanca_excecao_e_segue_as_demais(caplog):
    vaga_ok = _vaga("ok:1")
    fontes = [_FonteQuebrada(), _FonteFixa("ok", [vaga_ok])]

    with caplog.at_level(logging.ERROR, logger="monitor"):
        vagas, falhas = coletar_vagas(fontes)

    assert vagas == [vaga_ok]
    assert falhas == {"quebrada": "RuntimeError: falha simulada"}
    assert "quebrada" in caplog.text


class _FonteHttp(Source):
    nome = "adzuna"

    def fetch(self) -> list[Vaga]:
        import httpx

        requisicao = httpx.Request("GET", "https://api.adzuna.com/v1/api/jobs/br/search/1?app_key=SEGREDO")
        resposta = httpx.Response(401, request=requisicao)
        resposta.raise_for_status()
        return []


def test_coletar_vagas_nao_vaza_a_url_da_fonte_no_log(caplog):
    # a mensagem do HTTPStatusError traz a URL completa, com app_key/token.
    with caplog.at_level(logging.DEBUG):
        _, falhas = coletar_vagas([_FonteHttp()])

    assert falhas == {"adzuna": "HTTP 401"}
    assert "SEGREDO" not in caplog.text


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


@respx.mock
def test_run_atualiza_ultimo_visto_de_vaga_que_reaparece_e_a_retencao_nao_a_poda(tmp_path, monkeypatch):
    # regressão: run() só marcava as novas, então ultimo_visto nunca avançava
    # e uma vaga aberta há mais de `retencao_dias` era podada e renotificada.
    import sqlite3

    vaga = _vaga("teste:1")
    config = Config(notificacao=NotificacaoConfig(telegram=True), curriculo=SEM_CURRICULO, retencao_dias=90)
    _, rota, _ = _rodar(monkeypatch, tmp_path, config, [vaga])
    assert rota.call_count == 1

    db_path = tmp_path / "vagas.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE vagas_vistas SET visto_em = datetime('now', '-80 days'), "
            "ultimo_visto = datetime('now', '-80 days')"
        )

    # reaparece hoje: ultimo_visto precisa voltar pra agora...
    run(config_path="ignorado.yaml", db_path=str(db_path))
    with sqlite3.connect(db_path) as conn:
        visto_em, ultimo = conn.execute(
            "SELECT julianday('now') - julianday(visto_em), julianday('now') - julianday(ultimo_visto) "
            "FROM vagas_vistas"
        ).fetchone()
    assert visto_em > 79
    assert ultimo < 1

    # ...e 20 dias depois (100 desde o primeiro avistamento) não é renotificada.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE vagas_vistas SET ultimo_visto = datetime('now', '-20 days')")
    run(config_path="ignorado.yaml", db_path=str(db_path))
    assert rota.call_count == 1


URL_API = "https://api.telegram.org/bottoken-teste/sendMessage"


def _datada(id_: str, dia: int) -> Vaga:
    from datetime import datetime, timezone

    vaga = _vaga(id_)
    vaga.publicada_em = datetime(2026, 11, dia, tzinfo=timezone.utc)
    return vaga


def _config(**notificacao) -> Config:
    return Config(notificacao=NotificacaoConfig(telegram=True, **notificacao), curriculo=SEM_CURRICULO)


def _preparar(monkeypatch, config, vagas, credenciais=True):
    if credenciais:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-teste")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("monitor.main.carregar_config", lambda caminho: config)
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [_FonteFixa("teste", vagas)])


def _textos(rota) -> list[str]:
    return [json.loads(chamada.request.content)["text"] for chamada in rota.calls]


@respx.mock
def test_falha_no_meio_do_envio_grava_o_que_chegou_e_o_resto_vem_na_proxima(tmp_path, monkeypatch):
    vagas = [_datada("t:1", 3), _datada("t:2", 2), _datada("t:3", 1)]
    _preparar(monkeypatch, _config(), vagas)
    db_path = str(tmp_path / "vagas.db")
    ok = Response(200, json={"ok": True})
    rota = respx.post(URL_API).mock(
        side_effect=[ok, ok, Response(401, json={"ok": False, "description": "Unauthorized"})]
    )

    with pytest.raises(Exception):
        run(config_path="x", db_path=db_path)

    storage = Storage(db_path)
    assert storage.ja_vista("t:1") and storage.ja_vista("t:2")
    assert not storage.ja_vista("t:3")
    assert storage.buscar_detalhes("t:1") is not None

    rota.side_effect = None
    rota.return_value = ok
    run(config_path="x", db_path=db_path)

    # 3ª chamada = a tentativa recusada; a 2ª execução reenvia só a t:3.
    assert rota.call_count == 4
    assert "t:3" in _textos(rota)[3]
    assert Storage(db_path).ja_vista("t:3")


def test_sem_credenciais_localmente_imprime_e_nao_marca_nada(tmp_path, monkeypatch, capsys):
    _preparar(monkeypatch, _config(), [_vaga("t:1")], credenciais=False)
    db_path = str(tmp_path / "vagas.db")

    run(config_path="x", db_path=db_path)

    assert "exemplo.com/t:1" in capsys.readouterr().out
    assert not Storage(db_path).ja_vista("t:1")


def test_sem_credenciais_no_actions_falha_sem_marcar_nada(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _preparar(monkeypatch, _config(), [_vaga("t:1")], credenciais=False)
    db_path = str(tmp_path / "vagas.db")

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        run(config_path="x", db_path=db_path)

    assert not Storage(db_path).ja_vista("t:1")


def test_telegram_desligado_no_config_marca_como_vista(tmp_path, monkeypatch):
    config = Config(notificacao=NotificacaoConfig(telegram=False), curriculo=SEM_CURRICULO)
    _preparar(monkeypatch, config, [_vaga("t:1")], credenciais=False)
    db_path = str(tmp_path / "vagas.db")

    run(config_path="x", db_path=db_path)

    assert Storage(db_path).ja_vista("t:1")


@respx.mock
def test_teto_por_execucao_envia_as_mais_recentes_e_deixa_o_resto_pra_depois(tmp_path, monkeypatch):
    vagas = [_datada("t:antiga", 1), _datada("t:nova", 9), _vaga("t:sem-data"), _datada("t:media", 5)]
    _preparar(monkeypatch, _config(max_por_execucao=2), vagas)
    db_path = str(tmp_path / "vagas.db")
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    run(config_path="x", db_path=db_path)

    primeiros = _textos(rota)
    assert "t:nova" in primeiros[0] and "t:media" in primeiros[1]
    assert not Storage(db_path).ja_vista("t:antiga")

    run(config_path="x", db_path=db_path)
    assert rota.call_count == 4
    assert Storage(db_path).ja_vista("t:sem-data")


@respx.mock
def test_simular_nao_envia_nem_grava(tmp_path, monkeypatch, capsys):
    _preparar(monkeypatch, _config(), [_vaga("t:1")])
    db_path = tmp_path / "vagas.db"
    Storage(str(db_path)).marcar_todas([_vaga("t:velha")])
    antes = db_path.read_bytes()
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    main(["--simular", "--db", str(db_path), "--config", "x"])

    assert rota.call_count == 0
    assert db_path.read_bytes() == antes
    assert "exemplo.com/t:1" in capsys.readouterr().out


def test_simular_sem_banco_existente_nao_cria_arquivo(tmp_path, monkeypatch):
    _preparar(monkeypatch, _config(), [_vaga("t:1")])
    db_path = tmp_path / "vagas.db"

    run(config_path="x", db_path=str(db_path), simular=True)

    assert not db_path.exists()


class _FonteAlternavel(Source):
    nome = "instavel"

    def __init__(self) -> None:
        self.quebrada = True

    def fetch(self) -> list[Vaga]:
        if self.quebrada:
            raise RuntimeError("fora do ar")
        return []


@respx.mock
def test_fonte_que_quebra_gera_um_aviso_so_na_transicao(tmp_path, monkeypatch):
    instavel = _FonteAlternavel()
    _preparar(monkeypatch, _config(), [])
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [instavel, _FonteFixa("ok", [])])
    db_path = str(tmp_path / "vagas.db")
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    def avisos() -> int:
        return sum("com falha" in texto for texto in _textos(rota))

    run(config_path="x", db_path=db_path)
    assert avisos() == 1
    assert "instavel" in _textos(rota)[0]

    run(config_path="x", db_path=db_path)  # continua quebrada: sem novo aviso
    assert avisos() == 1

    instavel.quebrada = False
    run(config_path="x", db_path=db_path)  # voltou
    instavel.quebrada = True
    run(config_path="x", db_path=db_path)  # quebrou de novo: avisa
    assert avisos() == 2


@respx.mock
def test_resumo_semanal_sai_uma_vez_por_semana(tmp_path, monkeypatch):
    import sqlite3

    _preparar(monkeypatch, _config(), [_vaga("t:1")])
    db_path = str(tmp_path / "vagas.db")
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    def resumos() -> list[str]:
        return [texto for texto in _textos(rota) if "Resumo" in texto]

    run(config_path="x", db_path=db_path)
    assert resumos() == []  # primeira execução só começa a contar a semana

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE meta SET valor = datetime('now', '-8 days') WHERE chave = 'ultimo_resumo'")
    run(config_path="x", db_path=db_path)

    # o resumo cobre as execuções anteriores (a atual entra no próximo).
    assert len(resumos()) == 1
    assert "teste: 1 → 1 → 1" in resumos()[0]

    run(config_path="x", db_path=db_path)
    assert len(resumos()) == 1


def test_execucao_fica_registrada_por_fonte(tmp_path, monkeypatch):
    config = Config(
        notificacao=NotificacaoConfig(telegram=False),
        curriculo=SEM_CURRICULO,
    )
    _preparar(monkeypatch, config, [], credenciais=False)
    monkeypatch.setattr(
        "monitor.main.montar_fontes", lambda cfg: [_FonteQuebrada(), _FonteFixa("teste", [_vaga("t:1")])]
    )
    db_path = str(tmp_path / "vagas.db")

    run(config_path="x", db_path=db_path)

    resumos = {r.fonte: r for r in Storage(db_path).resumo_fontes(7)}
    assert resumos["quebrada"].falhas == 1
    assert resumos["quebrada"].ultimo_erro == "RuntimeError: falha simulada"
    assert (resumos["teste"].coletadas, resumos["teste"].aprovadas, resumos["teste"].notificadas) == (1, 1, 1)


@respx.mock
def test_mesma_vaga_em_duas_fontes_ou_dois_paises_notifica_uma_vez(tmp_path, monkeypatch):
    def vaga(id_, titulo, empresa="Acme"):
        return Vaga(id=id_, titulo=titulo, empresa=empresa, url=f"https://x/{id_}", fonte="teste")

    primeira = [vaga("jobicy:1", "Security Engineer (Remote - Denmark)"), vaga("jobicy:2", "Security Engineer (Remote - Spain)")]
    _preparar(monkeypatch, _config(), primeira)
    db_path = str(tmp_path / "vagas.db")
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    run(config_path="x", db_path=db_path)
    assert rota.call_count == 1
    assert Storage(db_path).ja_vista("jobicy:2")  # repetida: vista, não notificada

    # outra fonte, dias depois, mesma vaga: não renotifica; vaga diferente sim.
    segunda = [vaga("remotive:9", "Security Engineer"), vaga("remotive:10", "Data Engineer")]
    monkeypatch.setattr("monitor.main.montar_fontes", lambda cfg: [_FonteFixa("teste", segunda)])
    run(config_path="x", db_path=db_path)

    assert rota.call_count == 2
    assert "Data Engineer" in _textos(rota)[-1]


@respx.mock
def test_mesmo_id_duas_vezes_na_coleta_notifica_uma_vez(tmp_path, monkeypatch):
    _preparar(monkeypatch, _config(), [_vaga("t:1"), _vaga("t:1")])
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    run(config_path="x", db_path=str(tmp_path / "vagas.db"))

    assert rota.call_count == 1


@respx.mock
def test_no_actions_o_log_nao_lista_as_vagas(tmp_path, monkeypatch, capsys):
    # log de Actions em repo público é público: título/URL ficam só no Telegram.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _preparar(monkeypatch, _config(), [_vaga("t:1")])
    respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    run(config_path="x", db_path=str(tmp_path / "vagas.db"))

    assert "exemplo.com/t:1" not in capsys.readouterr().out


@respx.mock
def test_curriculo_mestre_invalido_desliga_a_aderencia_sem_derrubar_a_notificacao(tmp_path, monkeypatch, caplog):
    # achado ao rodar --simular de verdade: um bullet sem `texto` no mestre
    # local derrubava o monitor inteiro por causa de uma feature opcional.
    mestre = tmp_path / "mestre.yaml"
    mestre.write_text("experiencias:\n  - bullets:\n      - id: sem-texto\n", encoding="utf-8")
    config = Config(
        notificacao=NotificacaoConfig(telegram=True),
        curriculo=CurriculoConfig(mestre=str(mestre), skills=SKILLS),
        aderencia_minima=90,
    )
    _preparar(monkeypatch, config, [_vaga("t:1")])
    rota = respx.post(URL_API).mock(return_value=Response(200, json={"ok": True}))

    with caplog.at_level(logging.ERROR):
        run(config_path="x", db_path=str(tmp_path / "vagas.db"))

    assert rota.call_count == 1  # notificou, e sem corte por aderência
    assert "Aderência desligada" in caplog.text
    assert "sem-texto" not in caplog.text
