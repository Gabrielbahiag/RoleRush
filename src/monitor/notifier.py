from __future__ import annotations

import os

import httpx

from monitor.models import Vaga

API_BASE = "https://api.telegram.org"


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

    def notificar_vaga(self, vaga: Vaga) -> None:
        self.enviar_mensagem(_formatar_vaga(vaga))

    def notificar_vagas(self, vagas: list[Vaga]) -> None:
        for vaga in vagas:
            self.notificar_vaga(vaga)

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


def _formatar_vaga(vaga: Vaga) -> str:
    partes = [f"<b>{_escapar(vaga.titulo)}</b>"]
    if vaga.empresa:
        partes.append(_escapar(vaga.empresa))
    if vaga.localizacao:
        partes.append(_escapar(vaga.localizacao))
    partes.append(vaga.url)
    partes.append(f"fonte: {vaga.fonte}")
    return "\n".join(partes)


def _escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
