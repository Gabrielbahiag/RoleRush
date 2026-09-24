import json

import httpx
import pytest
import respx
from httpx import Response

from monitor.curriculo.score import Aderencia
from monitor.models import Vaga
from monitor.notifier import TelegramNotifier, _formatar_vaga


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
def test_enviar_mensagem_propaga_erro_http_do_telegram():
    respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(400, json={"ok": False, "description": "Bad Request"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        TelegramNotifier(token="token-teste", chat_id="123").enviar_mensagem("Olá")


@respx.mock
def test_notificar_vagas_envia_uma_mensagem_por_vaga():
    rota = respx.post("https://api.telegram.org/bottoken-teste/sendMessage").mock(
        return_value=Response(200, json={"ok": True})
    )

    notifier = TelegramNotifier(token="token-teste", chat_id="123")
    notifier.notificar_vagas([_vaga(id="a:1"), _vaga(id="a:2")])

    assert rota.call_count == 2
