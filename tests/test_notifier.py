import json

import httpx
import pytest
import respx
from httpx import Response

from monitor.curriculo.score import Aderencia
from monitor.models import Vaga
from monitor.notifier import ErroTelegram, TelegramNotifier, _formatar_vaga


def _vaga(**overrides) -> Vaga:
    base = dict(
        id="teste:1",
        titulo="Dev Python",
        empresa="Acme",
        url="https://exemplo.com/vaga/1",
        fonte="remotive",
        localizacao="Remoto",
    )
    base.update(overrides)
    return Vaga(**base)


def test_formatar_vaga_inclui_titulo_empresa_localizacao_url_e_fonte():
    texto = _formatar_vaga(_vaga())

    assert "<b>Dev Python</b>" in texto
    assert "Acme" in texto
    assert "Remoto" in texto
    assert "https://exemplo.com/vaga/1" in texto
    assert "fonte: remotive" in texto


def test_formatar_vaga_escapa_caracteres_html_especiais_no_titulo_e_empresa():
    vaga = _vaga(titulo="Dev C++ & <Backend>", empresa="A & B <Ltda>")

    texto = _formatar_vaga(vaga)

    assert "Dev C++ &amp; &lt;Backend&gt;" in texto
    assert "A &amp; B &lt;Ltda&gt;" in texto
    assert "<Backend>" not in texto
    assert "<Ltda>" not in texto


def test_formatar_vaga_omite_empresa_e_localizacao_quando_vazios():
    vaga = _vaga(empresa="", localizacao=None)

    texto = _formatar_vaga(vaga)

    # sem linha em branco no lugar da empresa/localização ausentes...
    assert "\n\n" not in texto
    assert "Acme" not in texto
    # ...mas o resto continua lá.
    assert "<b>Dev Python</b>" in texto
    assert vaga.url in texto
    assert "remotive" in texto


def test_mensagem_inclui_o_id_da_vaga():
    # é por esse id que o comando local gera o currículo adaptado
    # (`rolerush curriculo --vaga <id>`).
    assert "teste:1" in _formatar_vaga(_vaga())


def test_mensagem_inclui_score_e_lacunas_quando_ha_aderencia():
    aderencia = Aderencia(
        score=72,
        obrigatorios_atendidos=["Python"],
        obrigatorios_faltantes=["Docker"],
        desejaveis_faltantes=["AWS"],
    )

    texto = _formatar_vaga(_vaga(), aderencia)

    assert "72" in texto
    assert "Docker" in texto
    assert "AWS" in texto


def test_mensagem_sem_aderencia_nao_menciona_score():
    texto = _formatar_vaga(_vaga(), None)

    assert "aderência" not in texto.lower()


@respx.mock
def test_notificar_vagas_usa_a_aderencia_da_vaga_certa():
    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )
    vagas = [_vaga(id="a:1"), _vaga(id="a:2")]
    aderencias = {"a:1": Aderencia(score=90), "a:2": Aderencia(score=10)}

    TelegramNotifier(token="token-teste", chat_id="123").notificar_vagas(vagas, aderencias)

    enviadas = [json.loads(chamada.request.content)["text"] for chamada in rota.calls]
    assert "90" in enviadas[0]
    assert "10" in enviadas[1]


def test_configurado_false_sem_token_ou_chat_id(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    assert TelegramNotifier().configurado is False


def test_configurado_true_com_token_e_chat_id():
    assert TelegramNotifier(token="t", chat_id="c").configurado is True


def test_enviar_mensagem_sem_configuracao_da_erro_claro(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        TelegramNotifier().enviar_mensagem("teste")


@respx.mock
def test_enviar_mensagem_manda_payload_correto_pra_api_do_telegram():
    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )

    TelegramNotifier(token="token-teste", chat_id="123").enviar_mensagem("Olá")

    assert rota.called
    corpo = json.loads(rota.calls.last.request.content)
    assert corpo["chat_id"] == "123"
    assert corpo["text"] == "Olá"
    assert corpo["parse_mode"] == "HTML"


@respx.mock
def test_enviar_mensagem_propaga_erro_http_do_telegram_sem_vazar_o_token():
    respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(400, json={"ok": False, "description": "Bad Request"})
    )

    with pytest.raises(ErroTelegram) as erro:
        TelegramNotifier(token="token-teste", chat_id="123").enviar_mensagem("Olá")

    assert erro.value.status == 400
    assert "Bad Request" in str(erro.value)
    # a URL da API contém o token: o erro (que vai pro log) não pode citá-la.
    assert "token-teste" not in str(erro.value)


@respx.mock
def test_notificar_vagas_envia_uma_mensagem_por_vaga():
    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )

    notifier = TelegramNotifier(token="token-teste", chat_id="123")
    notifier.notificar_vagas([_vaga(id="a:1"), _vaga(id="a:2")])

    assert rota.call_count == 2


URL_API = "https://api.telegram.org/bottoken-teste/sendMessage"
OK = Response(200, json={"ok": True})


def _notifier() -> TelegramNotifier:
    return TelegramNotifier(token="token-teste", chat_id="123")


@pytest.fixture
def pausas(monkeypatch):
    registradas: list[float] = []
    monkeypatch.setattr("monitor.notifier._dormir", registradas.append)
    return registradas


def test_formatar_vaga_escapa_a_url():
    texto = _formatar_vaga(_vaga(url="https://x.com/vaga?a=1&b=<2>"))

    assert "https://x.com/vaga?a=1&amp;b=&lt;2&gt;" in texto


@respx.mock
def test_429_espera_o_retry_after_e_tenta_de_novo(pausas):
    limite = Response(429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}})
    rota = respx.post(URL_API).mock(side_effect=[limite, OK])

    _notifier().enviar_mensagem("Olá")

    assert rota.call_count == 2
    assert pausas == [8]


@respx.mock
def test_erro_5xx_persistente_esgota_as_tentativas_e_propaga(pausas):
    rota = respx.post(URL_API).mock(return_value=Response(502, json={"ok": False, "description": "Bad Gateway"}))

    with pytest.raises(ErroTelegram) as erro:
        _notifier().enviar_mensagem("Olá")

    assert erro.value.status == 502
    assert rota.call_count == 4
    assert pausas == [2, 4, 8]


@respx.mock
def test_falha_de_rede_e_retentada_e_o_erro_nao_cita_a_url():
    rota = respx.post(URL_API).mock(
        side_effect=[httpx.ConnectTimeout("timeout em https://api.telegram.org/bottoken-teste"), OK]
    )
    _notifier().enviar_mensagem("Olá")
    assert rota.call_count == 2

    respx.post(URL_API).mock(side_effect=httpx.ConnectError("falhou em https://api.telegram.org/bottoken-teste"))
    with pytest.raises(ErroTelegram) as erro:
        _notifier().enviar_mensagem("Olá")
    assert "token-teste" not in str(erro.value)


@respx.mock
def test_401_nao_e_retentado():
    rota = respx.post(URL_API).mock(return_value=Response(401, json={"ok": False, "description": "Unauthorized"}))

    with pytest.raises(ErroTelegram):
        _notifier().enviar_mensagem("Olá")

    assert rota.call_count == 1


@respx.mock
def test_mensagem_rejeitada_com_400_e_reenviada_sem_formatacao():
    # sem isso, uma vaga cujo texto o Telegram recusa trava a fila pra sempre.
    recusa = Response(400, json={"ok": False, "description": "can not parse entities"})
    rota = respx.post(URL_API).mock(side_effect=[recusa, OK])
    entregues = []

    _notifier().notificar_vagas([_vaga(id="a:1")], ao_enviar=entregues.append)

    segunda = json.loads(rota.calls[1].request.content)
    assert "parse_mode" not in segunda
    assert "Dev Python" in segunda["text"]
    assert [vaga.id for vaga in entregues] == ["a:1"]


@respx.mock
def test_falha_no_meio_para_o_envio_e_so_as_entregues_sao_reportadas():
    respx.post(URL_API).mock(side_effect=[OK, Response(401, json={"ok": False, "description": "Unauthorized"})])
    entregues = []

    with pytest.raises(ErroTelegram):
        _notifier().notificar_vagas(
            [_vaga(id="a:1"), _vaga(id="a:2"), _vaga(id="a:3")], ao_enviar=entregues.append
        )

    assert [vaga.id for vaga in entregues] == ["a:1"]


@respx.mock
def test_pausa_entre_mensagens_respeita_o_limite_do_chat(pausas):
    respx.post(URL_API).mock(return_value=OK)

    _notifier().notificar_vagas([_vaga(id="a:1"), _vaga(id="a:2"), _vaga(id="a:3")])

    assert pausas == [1.1, 1.1]


@respx.mock
def test_texto_acima_do_limite_do_telegram_e_cortado():
    rota = respx.post(URL_API).mock(return_value=OK)

    _notifier().enviar_mensagem("x" * 5000)

    assert len(json.loads(rota.calls.last.request.content)["text"]) == 4096
