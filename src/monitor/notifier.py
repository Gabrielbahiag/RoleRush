from __future__ import annotations

import os

import httpx

from monitor.curriculo.score import Aderencia
from monitor.models import Vaga

API_BASE = "https://api.telegram.org"

# a mensagem é pra bater o olho no celular; lacuna demais vira parede de texto.
_MAX_LACUNAS_NA_MENSAGEM = 4


class TelegramNotifier:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.timeout = timeout

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat_id)

    def notificar_vaga(self, vaga: Vaga, aderencia: Aderencia | None = None) -> None:
        self.enviar_mensagem(_formatar_vaga(vaga, aderencia))

    def notificar_vagas(
        self, vagas: list[Vaga], aderencias: dict[str, Aderencia] | None = None
    ) -> None:
        aderencias = aderencias or {}
        for vaga in vagas:
            self.notificar_vaga(vaga, aderencias.get(vaga.id))

    def enviar_mensagem(self, texto: str) -> None:
        if not self.configurado:
            raise RuntimeError(
                "Telegram não configurado: defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID."
            )
        url = f"{API_BASE}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.post(url, json=payload)
            resposta.raise_for_status()


def _formatar_vaga(vaga: Vaga, aderencia: Aderencia | None = None) -> str:
    partes = [f"<b>{_escapar(vaga.titulo)}</b>"]
    if vaga.empresa:
        partes.append(_escapar(vaga.empresa))
    if vaga.localizacao:
        partes.append(_escapar(vaga.localizacao))
    partes.append(vaga.url)
    if aderencia is not None:
        partes.append(_formatar_aderencia(aderencia))
    # o id vai na mensagem porque é o argumento de
    # `rolerush curriculo --vaga <id>` na máquina local.
    partes.append(f"fonte: {vaga.fonte} · id: {_escapar(vaga.id)}")
    return "\n".join(partes)


def _formatar_aderencia(aderencia: Aderencia) -> str:
    linha = f"aderência: {aderencia.score}%"
    if aderencia.lacunas:
        faltando = ", ".join(aderencia.lacunas[:_MAX_LACUNAS_NA_MENSAGEM])
        linha += f" · faltam: {_escapar(faltando)}"
    return linha


def _escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
