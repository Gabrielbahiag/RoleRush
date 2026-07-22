from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://remoteok.com/api"


class RemoteOKSource(Source):
    """API pública do RemoteOK — todas as vagas do site são remotas."""

    nome = "remoteok"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(API_URL)
            resposta.raise_for_status()
            itens = resposta.json()

        # o primeiro item é um aviso legal da API, não uma vaga.
        return [self._mapear(item) for item in itens if "id" in item]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        return Vaga(
            id=f"remoteok:{item['id']}",
            titulo=item.get("position", ""),
            empresa=item.get("company", ""),
            url=item.get("url") or item.get("apply_url", ""),
            fonte=self.nome,
            localizacao=item.get("location") or None,
            remoto=True,
            publicada_em=_parse_data(item.get("date")),
            descricao=item.get("description", ""),
        )


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
