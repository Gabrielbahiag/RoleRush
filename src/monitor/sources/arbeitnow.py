from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from monitor.models import Vaga
from monitor.sources.base import Source

API_URL = "https://arbeitnow.com/api/job-board-api"


class ArbeitnowSource(Source):
    """API pública do Arbeitnow — cobertura forte em Europa/DACH."""

    nome = "arbeitnow"

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch(self) -> list[Vaga]:
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resposta = client.get(API_URL)
            resposta.raise_for_status()
            dados = resposta.json()

        return [self._mapear(item) for item in dados.get("data", [])]

    def _mapear(self, item: dict[str, Any]) -> Vaga:
        return Vaga(
            id=f"arbeitnow:{item['slug']}",
            titulo=item.get("title", ""),
            empresa=item.get("company_name", ""),
            url=item.get("url", ""),
            fonte=self.nome,
            localizacao=item.get("location") or None,
            remoto=item.get("remote"),
            publicada_em=_parse_epoch(item.get("created_at")),
            descricao=item.get("description", ""),
        )


def _parse_epoch(valor: int | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromtimestamp(valor)
    except (ValueError, OSError):
        return None
