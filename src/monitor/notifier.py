from __future__ import annotations

import html
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from monitor.curriculo.score import Aderencia
from monitor.models import Vaga

API_BASE = "https://api.telegram.org"

logger = logging.getLogger("monitor.notifier")

# a mensagem é pra bater o olho no celular; lacuna demais vira parede de texto.
_MAX_LACUNAS_NA_MENSAGEM = 4
# limite do Telegram por mensagem (em caracteres, depois do parse do HTML).
_MAX_CARACTERES = 4096
# o Telegram tolera ~1 mensagem/s no mesmo chat; acima disso devolve 429.
_PAUSA_ENTRE_MENSAGENS = 1.1

# indireção pra os testes não dormirem de verdade.
_dormir = time.sleep


class ErroTelegram(Exception):
    """Falha ao enviar. A mensagem nunca leva a URL da API, que contém o token."""

    def __init__(self, status: int | None, descricao: str, retry_after: float | None = None) -> None:
        super().__init__(f"Telegram {status or 'sem resposta'}: {descricao}")
        self.status = status
        self.retry_after = retry_after


class TelegramNotifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        timeout: float = 10.0,
        tentativas: int = 4,
    ) -> None:
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.timeout = timeout
        self.tentativas = tentativas

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def notificar_vaga(self, vaga: Vaga, aderencia: Aderencia | None = None) -> None:
        self.enviar_mensagem(_formatar_vaga(vaga, aderencia))

    def notificar_vagas(
        self,
        vagas: list[Vaga],
        aderencias: dict[str, Aderencia] | None = None,
        ao_enviar: Callable[[Vaga], None] | None = None,
        agrupar_acima: int | None = None,
        por_mensagem: int = 8,
    ) -> None:
        """Envia as vagas, chamando `ao_enviar` para cada uma assim que chega.

        É o `ao_enviar` que marca a vaga como vista: se o envio parar no meio,
        o que já chegou fica gravado e o resto volta na próxima execução — sem
        reenviar o que já foi e sem perder o que faltou.

        Com mais de `agrupar_acima` vagas, junta até `por_mensagem` vagas por
        mensagem: numa rajada, 60 notificações seguidas viram 8 mensagens.
        """
        aderencias = aderencias or {}
        if agrupar_acima is not None and len(vagas) > agrupar_acima:
            envios = _envios_agrupados(vagas, aderencias, por_mensagem)
        else:
            envios = [
                _Envio(_formatar_vaga(vaga, aderencias.get(vaga.id)), _formatar_texto_puro(vaga), [vaga])
                for vaga in vagas
            ]

        for indice, envio in enumerate(envios):
            if indice:
                _dormir(_PAUSA_ENTRE_MENSAGENS)
            try:
                self.enviar_mensagem(envio.html)
            except ErroTelegram as erro:
                if erro.status != 400:
                    # credencial errada, chat inexistente ou falha transitória
                    # que não passou com as novas tentativas: para aqui.
                    raise
                # 400 = o Telegram nunca vai aceitar ESTA mensagem. Reenviar
                # sem formatação evita que ela trave a fila pra sempre.
                logger.error("Mensagem rejeitada (%s); reenviando sem formatação", erro)
                self.enviar_mensagem(envio.texto_puro, parse_mode=None)
            if ao_enviar:
                for vaga in envio.vagas:
                    ao_enviar(vaga)

    def enviar_mensagem(self, texto: str, parse_mode: str | None = "HTML") -> None:
        if not self.configurado:
            raise RuntimeError(
                "Telegram não configurado: defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID."
            )
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        payload: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": texto[:_MAX_CARACTERES],
            "disable_web_page_preview": False,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        erro = ErroTelegram(None, "nenhuma tentativa feita")
        with httpx.Client(timeout=self.timeout) as client:
            for tentativa in range(self.tentativas):
                if tentativa:
                    _dormir(_espera(erro, tentativa))
                try:
                    resposta = client.post(url, json=payload)
                except httpx.TransportError as falha:
                    # str(falha) pode citar a URL; só o tipo é seguro de logar.
                    erro = ErroTelegram(None, type(falha).__name__)
                    continue
                if resposta.is_success:
                    return
                corpo = _json_ou_vazio(resposta)
                retry_after = (corpo.get("parameters") or {}).get("retry_after")
                erro = ErroTelegram(
                    resposta.status_code,
                    str(corpo.get("description", "")),
                    retry_after if isinstance(retry_after, (int, float)) else None,
                )
                if resposta.status_code != 429 and resposta.status_code < 500:
                    raise erro
        raise erro


@dataclass(slots=True)
class _Envio:
    html: str
    texto_puro: str
    vagas: list[Vaga]


def _envios_agrupados(
    vagas: list[Vaga], aderencias: dict[str, Aderencia], por_mensagem: int
) -> list[_Envio]:
    # folga pro cabeçalho; o tamanho do HTML é sempre >= ao texto renderizado
    # que o Telegram conta, então caber aqui garante caber lá.
    limite = _MAX_CARACTERES - 200
    grupos: list[list[tuple[Vaga, str]]] = []
    atual: list[tuple[Vaga, str]] = []
    tamanho = 0
    for vaga in vagas:
        bloco = _formatar_vaga(vaga, aderencias.get(vaga.id))
        if atual and (len(atual) >= por_mensagem or tamanho + len(bloco) + 2 > limite):
            grupos.append(atual)
            atual, tamanho = [], 0
        atual.append((vaga, bloco))
        tamanho += len(bloco) + 2
    if atual:
        grupos.append(atual)

    return [
        _Envio(
            html=f"📬 <b>{len(vagas)} vagas novas</b> ({numero}/{len(grupos)})\n\n"
            + "\n\n".join(bloco for _, bloco in grupo),
            texto_puro="\n\n".join(_formatar_texto_puro(vaga) for vaga, _ in grupo),
            vagas=[vaga for vaga, _ in grupo],
        )
        for numero, grupo in enumerate(grupos, start=1)
    ]


def _espera(erro: ErroTelegram, tentativa: int) -> float:
    # 429 diz quanto esperar; 5xx/rede: recuo exponencial (2s, 4s, 8s).
    if erro.retry_after is not None:
        return erro.retry_after + 1
    return float(2**tentativa)


def _json_ou_vazio(resposta: httpx.Response) -> dict:
    try:
        corpo = resposta.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _formatar_vaga(vaga: Vaga, aderencia: Aderencia | None = None) -> str:
    partes = [f"<b>{_escapar(vaga.titulo)}</b>"]
    if vaga.empresa:
        partes.append(_escapar(vaga.empresa))
    if vaga.localizacao:
        partes.append(_escapar(vaga.localizacao))
    partes.append(_escapar(vaga.url))
    if aderencia is not None:
        partes.append(_formatar_aderencia(aderencia))
    # o id vai na mensagem porque é o argumento de
    # `rolerush curriculo --vaga <id>` na máquina local.
    partes.append(f"fonte: {_escapar(vaga.fonte)} · id: {_escapar(vaga.id)}")
    return "\n".join(partes)


def _formatar_texto_puro(vaga: Vaga) -> str:
    return "\n".join(
        parte for parte in (vaga.titulo, vaga.empresa, vaga.url, f"id: {vaga.id}") if parte
    )


def _formatar_aderencia(aderencia: Aderencia) -> str:
    linha = f"aderência: {aderencia.score}%"
    if aderencia.lacunas:
        faltando = ", ".join(aderencia.lacunas[:_MAX_LACUNAS_NA_MENSAGEM])
        linha += f" · faltam: {_escapar(faltando)}"
    return linha


def _escapar(texto: str) -> str:
    return html.escape(texto, quote=False)
