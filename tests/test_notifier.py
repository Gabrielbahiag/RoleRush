import httpx
import pytest
import respx
from httpx import Response

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
    linhas = texto.split("\n")

    # só titulo, url e "fonte: ..." — sem linha em branco pra empresa/local.
    assert len(linhas) == 3


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
    payload = rota.calls.last.request
    import json

    corpo = json.loads(payload.content)
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
