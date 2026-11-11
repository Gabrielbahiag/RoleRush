import httpx

from monitor.saude import ResumoFonte, descrever_erro, formatar_alerta_falhas, formatar_resumo


def test_descrever_erro_http_mostra_so_o_status():
    requisicao = httpx.Request("GET", "https://api.telegram.org/botSEGREDO/sendMessage")
    erro = httpx.HTTPStatusError("falhou em https://api.telegram.org/botSEGREDO", request=requisicao,
                                 response=httpx.Response(502, request=requisicao))

    assert descrever_erro(erro) == "HTTP 502"


def test_descrever_erro_de_rede_mostra_so_o_tipo():
    assert descrever_erro(httpx.ConnectTimeout("https://x/botSEGREDO")) == "ConnectTimeout"


def test_alerta_lista_as_fontes_e_escapa_html():
    texto = formatar_alerta_falhas({"github:a/<b>": "HTTP 404"})

    assert "github:a/&lt;b&gt;: HTTP 404" in texto


def test_resumo_destaca_fonte_muda_quebrada_ou_sem_aprovadas():
    resumos = [
        ResumoFonte("boa", 28, 0, 400, 12, 10, None),
        ResumoFonte("muda", 28, 0, 0, 0, 0, None),
        ResumoFonte("filtrada", 28, 0, 300, 0, 0, None),
        ResumoFonte("quebrada", 28, 28, 0, 0, 0, "HTTP 401"),
    ]

    linhas = formatar_resumo(resumos, 7).splitlines()

    assert "boa: 400 → 12 → 10" in linhas
    assert any(l.startswith("muda") and "não devolveu nada" in l for l in linhas)
    assert any(l.startswith("filtrada") and "nada passou no filtro" in l for l in linhas)
    assert any(l.startswith("quebrada") and "falhou em 28/28" in l and "HTTP 401" in l for l in linhas)
    assert linhas[-1] == "total notificado: 10"
