from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    nome = "remotive"

    def __init__(self, categoria: str | None = None, timeout: float = 15.0) -> None:
        self.categoria = categoria
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        params = {"category": self.categoria} if self.categoria else {}
        with httpx.Client(timeout=self.timeout) as client:
            resposta = client.get(API_URL, params=params)
            resposta.raise_for_status()
            dados = resposta.json()
        return [self._mapear(item) for item in dados.get("jobs", [])]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        return Vaga(
            id=f"remotive:{item['id']}",
            titulo=item.get("title", ""),
            empresa=item.get("company_name", ""),
            url=item.get("url", ""),
            fonte=self.nome,
            localizacao=item.get("candidate_required_location"),
            remoto=True,
            publicada_em=_parse_data(item.get("publication_date")),
            descricao=item.get("description", ""),
        )


def _parse_data(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
